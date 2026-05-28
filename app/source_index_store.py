from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any

from app.co_case_store import declaration_refs, invoice_keys
from app.database import DATABASE_URL_ENV, apply_migrations, connect, database_url


CATALOG_KEY_FIELDS = {
    "material_catalog": "customs_code",
    "product_catalog": "product_code",
}
SOURCE_INDEX_MODULES = ("material_catalog", "product_catalog", "bcct")
SOURCE_HISTORY_FIELDS = (
    "customs_code",
    "product_code",
    "transaction_key",
    "direction",
    "declaration_no",
    "line_no",
    "declaration_type",
    "item_code",
    "hs_code",
    "invoice_ref",
)


class SourceIndexUnavailable(RuntimeError):
    pass


def get_source_index_store() -> "PostgresSourceIndexStore | None":
    url = database_url()
    return PostgresSourceIndexStore(url) if url else None


def rebuild_source_index_if_configured(client: dict) -> dict | None:
    store = get_source_index_store()
    if store is None:
        return None
    return store.rebuild_client_from_files(client)


def build_bcct_index_records(client_id: str, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    bcct_records = []
    invoice_records = []
    for row in rows:
        transaction_key = row["transaction_key"]
        bcct_records.append({
            "client_id": client_id,
            "transaction_key": transaction_key,
            "direction": row.get("direction", ""),
            "review_status": row.get("review_status", ""),
            "declaration_no": row.get("declaration_no", ""),
            "line_no": row.get("line_no", ""),
            "declaration_type": row.get("declaration_type", ""),
            "item_code": row.get("item_code", ""),
            "hs_code": row.get("hs_code", ""),
            "quantity": row.get("quantity", ""),
            "unit": row.get("unit", ""),
            "invoice_ref": row.get("invoice_ref", ""),
            "payload": dict(row),
        })
        for invoice_key in sorted(invoice_keys(row.get("invoice_ref", ""))):
            invoice_records.append({
                "client_id": client_id,
                "invoice_key": invoice_key,
                "transaction_key": transaction_key,
            })
    return bcct_records, invoice_records


def build_catalog_index_records(client_id: str, module: str, rows: list[dict]) -> list[dict]:
    key_field = CATALOG_KEY_FIELDS.get(module)
    if not key_field:
        raise ValueError(f"Unsupported catalog module: {module}")
    records = []
    for index, source_row in enumerate(rows, start=1):
        row = dict(source_row)
        row_key = row.get(key_field) or f"row-{index}"
        records.append({
            "client_id": client_id,
            "module": module,
            "row_key": row_key,
            "customs_code": row.get("customs_code", ""),
            "product_code": row.get("product_code", ""),
            "hs_code": row.get("hs_code", ""),
            "unit": row.get("unit", ""),
            "status": row.get("status", ""),
            "payload": row,
        })
    return records


def build_co_stock_index_records(client_id: str, rows: list[dict]) -> list[dict]:
    return [
        {
            "client_id": client_id,
            "source_row": row["source_row"],
            "transaction_key": row.get("source_transaction_key", ""),
            "import_declaration_no": row.get("import_declaration_no", ""),
            "line_no": row.get("line_no", ""),
            "declaration_type": row.get("declaration_type", ""),
            "customs_item_code": row.get("customs_item_code", ""),
            "allocation_code": row.get("allocation_code", ""),
            "eligibility_status": row.get("eligibility_status", ""),
            "remaining_qty": row.get("remaining_qty", ""),
            "payload": dict(row),
        }
        for row in rows
    ]


def build_correction_candidate_records(client_id: str, module: str, candidates: list[dict]) -> list[dict]:
    return [
        {
            "client_id": client_id,
            "module": module,
            "candidate_id": candidate.get("candidate_id", "") or f"{module}-candidate-{index}",
            "transaction_key": candidate.get("transaction_key", ""),
            "status": candidate.get("status", ""),
            "payload": dict(candidate),
        }
        for index, candidate in enumerate(candidates, start=1)
    ]


def build_source_state_records(client_id: str, module: str, state: dict) -> dict:
    latest = state.get("latest_version") or {}
    uploads = [source_upload_record(client_id, module, upload) for upload in state.get("uploads", [])]
    versions = [source_version_record(client_id, module, version) for version in state.get("versions", [])]
    snapshots = [source_snapshot_record(client_id, module, upload) for upload in uploads if upload.get("snapshot_id")]
    snapshot_rows = [
        row
        for upload in uploads
        if upload.get("snapshot_id")
        for row in source_snapshot_row_records(
            client_id,
            module,
            upload["snapshot_id"],
            source_snapshot_rows_from_state(client_id, module, state, upload["snapshot_id"]),
        )
    ]
    version_rows = [
        row
        for version in versions
        for row in source_version_row_records(
            client_id,
            module,
            version["version_id"],
            source_version_rows_from_state(client_id, module, state, version),
        )
    ]
    audit_events = [
        source_audit_event_record(client_id, module, event, index)
        for index, event in enumerate(state.get("audit_events", []), start=1)
    ]
    return {
        "module_state": {
            "client_id": client_id,
            "module": module,
            "schema_version": int(state.get("schema_version") or 1),
            "latest_version_id": latest.get("version_id", ""),
            "next_version_no": int(state.get("next_version_no") or (len(versions) + 1)),
            "published_row_count": len(state.get("published_rows", [])),
            "upload_count": len(uploads),
            "version_count": len(versions),
            "correction_candidate_count": len(state.get("correction_candidates", [])),
        },
        "uploads": uploads,
        "raw_files": [source_raw_file_record(upload) for upload in uploads if upload.get("stored_path")],
        "snapshots": snapshots,
        "snapshot_rows": snapshot_rows,
        "versions": versions,
        "version_rows": version_rows,
        "audit_events": audit_events,
    }


def source_state_from_workspace(client_id: str, module: str, workspace: dict) -> dict:
    versions = [dict(version) for version in workspace.get("versions", [])]
    max_version_no = max([int(version.get("version_no") or 0) for version in versions] or [0])
    return {
        "schema_version": int(workspace.get("schema_version") or 1),
        "client_id": client_id,
        "module": module,
        "published_rows": [dict(row) for row in workspace.get("published_rows", [])],
        "latest_version": dict(workspace.get("latest_version") or {}),
        "versions": versions,
        "uploads": [dict(upload) for upload in workspace.get("uploads", [])],
        "snapshot_rows": {
            snapshot_id: [dict(row) for row in rows]
            for snapshot_id, rows in (workspace.get("snapshot_rows") or {}).items()
        },
        "version_rows": {
            version_id: [dict(row) for row in rows]
            for version_id, rows in (workspace.get("version_rows") or {}).items()
        },
        "correction_candidates": [dict(candidate) for candidate in workspace.get("correction_candidates", [])],
        "audit_events": [dict(event) for event in workspace.get("audit_events", [])],
        "next_version_no": max_version_no + 1,
    }


def source_metadata_record_from_state(client_id: str, module: str, state: dict, config_hash: str = "") -> dict:
    latest = state.get("latest_version") or {}
    return {
        "client_id": client_id,
        "module": module,
        "version_id": latest.get("version_id", ""),
        "version_no": int(latest.get("version_no") or 0),
        "published_row_count": len(state.get("published_rows", [])),
        "reviewed_row_count": sum(1 for row in state.get("published_rows", []) if row.get("review_status") == "reviewed"),
        "correction_candidate_count": len(state.get("correction_candidates", [])),
        "state_mtime_ns": 0,
        "config_hash": config_hash,
    }


def empty_source_state(client_id: str, module: str) -> dict:
    return {
        "schema_version": 1,
        "client_id": client_id,
        "module": module,
        "published_rows": [],
        "latest_version": {},
        "versions": [],
        "uploads": [],
        "snapshot_rows": {},
        "version_rows": {},
        "correction_candidates": [],
        "audit_events": [],
        "next_version_no": 1,
    }


def source_upload_record(client_id: str, module: str, upload: dict) -> dict:
    original_filename = upload.get("original_filename") or upload.get("filename", "")
    stored_filename = upload.get("stored_filename") or original_filename
    stored_path = upload.get("stored_path") or legacy_stored_path(client_id, module, upload["upload_id"], stored_filename)
    size_bytes = int(upload.get("size_bytes") or stored_file_size(stored_path) or 0)
    mime_type = upload.get("mime_type") or upload.get("content_type") or mimetypes.guess_type(original_filename)[0] or ""
    return {
        "upload_id": upload["upload_id"],
        "client_id": client_id,
        "module": module,
        "metadata_schema_version": int(upload.get("metadata_schema_version") or 1),
        "original_filename": original_filename,
        "safe_filename": upload.get("safe_filename") or original_filename,
        "stored_filename": stored_filename,
        "stored_path": stored_path,
        "storage_backend": upload.get("storage_backend") or ("filesystem" if stored_path else ""),
        "content_sha256": upload.get("content_sha256", ""),
        "size_bytes": size_bytes,
        "file_ext": upload.get("file_ext") or Path(original_filename).suffix.lower(),
        "mime_type": mime_type,
        "upload_scope": upload.get("upload_scope", ""),
        "parse_status": upload.get("parse_status", ""),
        "parse_error": upload.get("parse_error", ""),
        "snapshot_id": upload.get("snapshot_id", ""),
        "snapshot_rows_hash": upload.get("snapshot_rows_hash", ""),
        "row_count": int(upload.get("row_count") or 0),
        "result": upload.get("result", ""),
        "created_version_id": upload.get("created_version_id", ""),
        "diff_summary": dict(upload.get("diff_summary") or {}),
        "payload": dict(upload),
        "created_at": upload.get("created_at"),
    }


def legacy_stored_path(client_id: str, module: str, upload_id: str, filename: str) -> str:
    if not upload_id or not filename:
        return ""
    return f"clients/{client_id}/{module.replace('_', '-')}/uploads/{upload_id}/raw/{filename}"


def stored_file_size(stored_path: str) -> int:
    if not stored_path:
        return 0
    try:
        from app.source_store import source_root

        return (source_root() / stored_path).stat().st_size
    except OSError:
        return 0


def source_raw_file_record(upload: dict) -> dict:
    return {
        "raw_file_id": f"{upload['upload_id']}:raw",
        "upload_id": upload["upload_id"],
        "client_id": upload["client_id"],
        "module": upload["module"],
        "storage_backend": upload.get("storage_backend", ""),
        "storage_key": upload.get("stored_path", ""),
        "filename": upload.get("stored_filename", ""),
        "content_sha256": upload.get("content_sha256", ""),
        "size_bytes": int(upload.get("size_bytes") or 0),
        "content_type": upload.get("mime_type", ""),
        "created_at": upload.get("created_at"),
    }


def source_snapshot_record(client_id: str, module: str, upload: dict) -> dict:
    rows_hash = upload.get("snapshot_rows_hash") or legacy_snapshot_rows_hash(client_id, module, upload["snapshot_id"])
    snapshot = {
        "snapshot_id": upload["snapshot_id"],
        "client_id": client_id,
        "module": module,
        "upload_id": upload["upload_id"],
        "row_count": int(upload.get("row_count") or 0),
        "rows_hash": rows_hash,
        "created_at": upload.get("created_at"),
    }
    return {**snapshot, "payload": snapshot}


def source_snapshot_row_records(client_id: str, module: str, snapshot_id: str, rows: list[dict]) -> list[dict]:
    return [
        {
            **source_history_row_record(client_id, module, row, index),
            "snapshot_id": snapshot_id,
        }
        for index, row in enumerate(rows, start=1)
    ]


def source_version_row_records(client_id: str, module: str, version_id: str, rows: list[dict]) -> list[dict]:
    return [
        {
            **source_history_row_record(client_id, module, row, index),
            "version_id": version_id,
        }
        for index, row in enumerate(rows, start=1)
    ]


def source_history_row_record(client_id: str, module: str, row: dict, index: int) -> dict:
    payload = dict(row)
    promoted = {field: str(payload.get(field, "") or "") for field in SOURCE_HISTORY_FIELDS}
    return {
        "client_id": client_id,
        "module": module,
        "row_index": index,
        "row_key": source_row_key(module, payload, index),
        **promoted,
        "payload": payload,
    }


def source_row_key(module: str, row: dict, index: int) -> str:
    key_field = CATALOG_KEY_FIELDS.get(module)
    if key_field:
        return str(row.get(key_field) or f"row-{index}")
    if module == "bcct":
        return str(row.get("transaction_key") or f"row-{index}")
    return f"row-{index}"


def source_snapshot_rows_from_state(client_id: str, module: str, state: dict, snapshot_id: str) -> list[dict]:
    rows_by_snapshot = state.get("snapshot_rows") or {}
    if snapshot_id in rows_by_snapshot:
        return [dict(row) for row in rows_by_snapshot[snapshot_id]]
    return legacy_snapshot_rows(client_id, module, snapshot_id)


def source_version_rows_from_state(client_id: str, module: str, state: dict, version: dict) -> list[dict]:
    version_id = version["version_id"]
    rows_by_version = state.get("version_rows") or {}
    if version_id in rows_by_version:
        return [dict(row) for row in rows_by_version[version_id]]
    rows = legacy_version_rows(client_id, module, int(version.get("version_no") or 0))
    if rows:
        return rows
    latest = state.get("latest_version") or {}
    published_rows = state.get("published_rows") or []
    if version_id == latest.get("version_id") and int(version.get("row_count") or 0) == len(published_rows):
        return [dict(row) for row in published_rows]
    return []


def legacy_snapshot_rows(client_id: str, module: str, snapshot_id: str) -> list[dict]:
    if not snapshot_id:
        return []
    try:
        from app.source_store import source_root

        rows_path = source_root() / "clients" / client_id / module.replace("_", "-") / "snapshots" / snapshot_id / "rows.json"
        return read_legacy_rows(rows_path)
    except OSError:
        return []


def legacy_version_rows(client_id: str, module: str, version_no: int) -> list[dict]:
    if not version_no:
        return []
    try:
        from app.source_store import source_root

        rows_path = source_root() / "clients" / client_id / module.replace("_", "-") / "versions" / f"v{version_no}" / "rows.json"
        return read_legacy_rows(rows_path)
    except OSError:
        return []


def read_legacy_rows(path: Path) -> list[dict]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def legacy_snapshot_rows_hash(client_id: str, module: str, snapshot_id: str) -> str:
    if not snapshot_id:
        return ""
    try:
        from app.source_store import normalized_rows_hash, source_root

        snapshot_dir = source_root() / "clients" / client_id / module.replace("_", "-") / "snapshots" / snapshot_id
        snapshot_path = snapshot_dir / "snapshot.json"
        rows_hash = json.loads(snapshot_path.read_text(encoding="utf-8")).get("rows_hash", "")
        if rows_hash:
            return rows_hash
        rows_path = snapshot_dir / "rows.json"
        return normalized_rows_hash(json.loads(rows_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return ""


def source_version_record(client_id: str, module: str, version: dict) -> dict:
    return {
        "version_id": version["version_id"],
        "client_id": client_id,
        "module": module,
        "version_no": int(version.get("version_no") or 0),
        "source_upload_id": version.get("source_upload_id", ""),
        "snapshot_id": version.get("snapshot_id", ""),
        "row_count": int(version.get("row_count") or 0),
        "rows_hash": version.get("rows_hash", ""),
        "summary": dict(version.get("summary") or {}),
        "payload": dict(version),
        "created_at": version.get("created_at"),
    }


def source_audit_event_record(client_id: str, module: str, event: dict, index: int) -> dict:
    details = dict(event.get("details") or {})
    event_id = event.get("audit_event_id") or stable_audit_event_id(client_id, module, event, index)
    return {
        "audit_event_id": event_id,
        "client_id": client_id,
        "module": module,
        "event": event.get("event", ""),
        "upload_id": details.get("upload_id", ""),
        "version_id": details.get("version_id", ""),
        "snapshot_id": details.get("snapshot_id", ""),
        "details": details,
        "payload": dict(event),
        "created_at": event.get("created_at"),
    }


def stable_audit_event_id(client_id: str, module: str, event: dict, index: int) -> str:
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha1(f"{client_id}|{module}|{index}|{payload}".encode("utf-8")).hexdigest()[:16]
    return f"audit-{digest}"


class PostgresSourceIndexStore:
    def __init__(self, url: str):
        self.url = url

    def ensure_schema(self) -> None:
        apply_migrations(self.url)

    def has_client(self, client_id: str) -> bool:
        try:
            self.ensure_client(client_id)
            return True
        except Exception:
            return False

    def ensure_client(self, client_id: str) -> None:
        self.ensure_schema()
        if self._client_index_exists(client_id):
            return
        states = {module: empty_source_state(client_id, module) for module in SOURCE_INDEX_MODULES}
        metadata = [
            source_metadata_record_from_state(client_id, "material_catalog", states["material_catalog"]),
            source_metadata_record_from_state(client_id, "product_catalog", states["product_catalog"]),
            source_metadata_record_from_state(client_id, "bcct", states["bcct"]),
            {
                "client_id": client_id,
                "module": "co_stock",
                "version_id": "",
                "version_no": 0,
                "published_row_count": 0,
                "reviewed_row_count": 0,
                "correction_candidate_count": 0,
                "state_mtime_ns": 0,
                "config_hash": "",
            },
        ]
        self.replace_client_indexes(
            client_id,
            catalog_records=[],
            bcct_records=[],
            invoice_records=[],
            stock_records=[],
            correction_records=[],
            metadata_records=metadata,
            source_state_records=[
                build_source_state_records(client_id, "material_catalog", states["material_catalog"]),
                build_source_state_records(client_id, "product_catalog", states["product_catalog"]),
                build_source_state_records(client_id, "bcct", states["bcct"]),
            ],
        )

    def _client_index_exists(self, client_id: str) -> bool:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "select 1 from source_index_metadata where client_id = %s limit 1",
                    (client_id,),
                )
                return cursor.fetchone() is not None

    def source_summary(self, client_id: str, client_config: dict) -> dict:
        self.ensure_client(client_id)
        rows = self.source_metadata_rows(client_id)
        by_module = {row[0]: row for row in rows}
        return {
            "client_config": client_config,
            "material_catalog": metadata_summary(by_module.get("material_catalog"), "material_catalog"),
            "product_catalog": metadata_summary(by_module.get("product_catalog"), "product_catalog"),
            "bcct": metadata_summary(by_module.get("bcct"), "bcct"),
            "co_stock_row_count": int((by_module.get("co_stock") or [None, None, None, 0])[3] or 0),
        }

    def source_workspace(self, client_id: str, client_config: dict) -> dict:
        self.ensure_client(client_id)
        metadata = {row[0]: row for row in self.source_metadata_rows(client_id)}
        return {
            "client_config": client_config,
            "material_catalog": indexed_module_workspace(
                metadata.get("material_catalog"),
                "material_catalog",
                self.catalog_rows(client_id, "material_catalog"),
                self.correction_candidates(client_id, "material_catalog"),
                self.source_uploads(client_id, "material_catalog"),
                self.source_versions(client_id, "material_catalog"),
                self.source_snapshot_rows_for_module(client_id, "material_catalog"),
                self.source_version_rows_for_module(client_id, "material_catalog"),
                self.source_audit_events(client_id, "material_catalog"),
            ),
            "product_catalog": indexed_module_workspace(
                metadata.get("product_catalog"),
                "product_catalog",
                self.catalog_rows(client_id, "product_catalog"),
                self.correction_candidates(client_id, "product_catalog"),
                self.source_uploads(client_id, "product_catalog"),
                self.source_versions(client_id, "product_catalog"),
                self.source_snapshot_rows_for_module(client_id, "product_catalog"),
                self.source_version_rows_for_module(client_id, "product_catalog"),
                self.source_audit_events(client_id, "product_catalog"),
            ),
            "bcct": indexed_module_workspace(
                metadata.get("bcct"),
                "bcct",
                self.bcct_rows(client_id),
                self.correction_candidates(client_id, "bcct"),
                self.source_uploads(client_id, "bcct"),
                self.source_versions(client_id, "bcct"),
                self.source_snapshot_rows_for_module(client_id, "bcct"),
                self.source_version_rows_for_module(client_id, "bcct"),
                self.source_audit_events(client_id, "bcct"),
            ),
            "co_stock_rows": self.co_stock_rows(client_id),
        }

    def source_metadata_rows(self, client_id: str) -> list[tuple]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select module, version_id, version_no, published_row_count,
                           reviewed_row_count, correction_candidate_count
                    from source_index_metadata
                    where client_id = %s
                    """,
                    (client_id,),
                )
                return cursor.fetchall()

    def catalog_rows(self, client_id: str, module: str) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select payload
                    from source_catalog_rows
                    where client_id = %s and module = %s
                    order by row_key
                    """,
                    (client_id, module),
                )
                return [dict(row[0]) for row in cursor.fetchall()]

    def bcct_rows(self, client_id: str) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select payload
                    from bcct_rows
                    where client_id = %s
                    order by direction, declaration_no, line_no, item_code
                    """,
                    (client_id,),
                )
                return [dict(row[0]) for row in cursor.fetchall()]

    def correction_candidates(self, client_id: str, module: str) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select payload
                    from source_correction_candidates
                    where client_id = %s and module = %s
                    order by transaction_key, candidate_id
                    """,
                    (client_id, module),
                )
                return [dict(row[0]) for row in cursor.fetchall()]

    def match_bcct_exports(
        self,
        client_id: str,
        invoice_no: str,
        relevant_types: list[str],
        export_declaration_nos: list[str] | str | None = None,
    ) -> list[dict]:
        declarations = declaration_refs(export_declaration_nos or [])
        if declarations:
            declaration_keys = [
                "".join(char for char in ref.upper() if char.isalnum())
                for ref in declarations
                if ref
            ]
            params: list[Any] = [client_id]
            type_clause = ""
            if relevant_types:
                type_clause = "and b.declaration_type = any(%s)"
                params.append(relevant_types)
            params.append(declaration_keys)
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        select b.payload
                        from bcct_rows b
                        where b.client_id = %s
                          and b.direction = 'export'
                          and b.review_status = 'reviewed'
                          {type_clause}
                          and regexp_replace(upper(b.payload->>'declaration_no'), '[^A-Z0-9]', '', 'g') = any(%s)
                        order by b.payload->>'declaration_no', b.payload->>'line_no', b.payload->>'item_code'
                        """,
                        params,
                    )
                    rows = [dict(row[0]) for row in cursor.fetchall()]
            invoice_tokens = invoice_keys(invoice_no)
            for row in rows:
                row_tokens = invoice_keys(row.get("invoice_ref", ""))
                invoice_mismatch = bool(invoice_tokens and row_tokens and not invoice_tokens.intersection(row_tokens))
                row["match_source"] = "declaration"
                row["invoice_mismatch"] = invoice_mismatch
                if invoice_mismatch:
                    row["reference_warning"] = (
                        f"Invoice nhập {invoice_no} không khớp invoice_ref {row.get('invoice_ref', '')} trên tờ khai {row.get('declaration_no', '')}."
                    )
                elif invoice_tokens and not row_tokens:
                    row["reference_warning"] = (
                        f"Tờ khai {row.get('declaration_no', '')} không có invoice_ref để đối chiếu với invoice nhập {invoice_no}."
                    )
            return rows
        keys = sorted(invoice_keys(invoice_no))
        if not keys:
            return []
        params: list[Any] = [client_id]
        type_clause = ""
        if relevant_types:
            type_clause = "and b.declaration_type = any(%s)"
            params.append(relevant_types)
        params.append(keys)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select b.payload
                    from bcct_rows b
                    where b.client_id = %s
                      and b.direction = 'export'
                      and b.review_status = 'reviewed'
                      {type_clause}
                      and exists (
                        select 1
                        from bcct_invoice_index i
                        where i.client_id = b.client_id
                          and i.transaction_key = b.transaction_key
                          and i.invoice_key = any(%s)
                      )
                    order by b.payload->>'declaration_no', b.payload->>'line_no', b.payload->>'item_code'
                    """,
                    params,
                )
                return [dict(row[0]) for row in cursor.fetchall()]

    def co_stock_rows(self, client_id: str) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select payload
                    from co_stock_rows
                    where client_id = %s
                    order by import_declaration_no, line_no, customs_item_code, source_row
                    """,
                    (client_id,),
                )
                return [dict(row[0]) for row in cursor.fetchall()]

    def source_uploads(self, client_id: str, module: str) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select payload
                    from source_uploads
                    where client_id = %s and module = %s
                    order by created_at desc, upload_id desc
                    """,
                    (client_id, module),
                )
                return [dict(row[0]) for row in cursor.fetchall()]

    def source_versions(self, client_id: str, module: str) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select payload
                    from source_versions
                    where client_id = %s and module = %s
                    order by version_no desc, created_at desc
                    """,
                    (client_id, module),
                )
                return [dict(row[0]) for row in cursor.fetchall()]

    def source_snapshot_rows(self, snapshot_id: str) -> list[dict]:
        if not snapshot_id:
            return []
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select payload
                    from source_snapshot_rows
                    where snapshot_id = %s
                    order by row_index
                    """,
                    (snapshot_id,),
                )
                return [dict(row[0]) for row in cursor.fetchall()]

    def source_version_rows(self, version_id: str) -> list[dict]:
        if not version_id:
            return []
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select payload
                    from source_version_rows
                    where version_id = %s
                    order by row_index
                    """,
                    (version_id,),
                )
                return [dict(row[0]) for row in cursor.fetchall()]

    def source_snapshot_rows_for_module(self, client_id: str, module: str) -> dict[str, list[dict]]:
        rows_by_snapshot: dict[str, list[dict]] = defaultdict(list)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select snapshot_id, payload
                    from source_snapshot_rows
                    where client_id = %s and module = %s
                    order by snapshot_id, row_index
                    """,
                    (client_id, module),
                )
                for snapshot_id, payload in cursor.fetchall():
                    rows_by_snapshot[snapshot_id].append(dict(payload))
        return dict(rows_by_snapshot)

    def source_version_rows_for_module(self, client_id: str, module: str) -> dict[str, list[dict]]:
        rows_by_version: dict[str, list[dict]] = defaultdict(list)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select version_id, payload
                    from source_version_rows
                    where client_id = %s and module = %s
                    order by version_id, row_index
                    """,
                    (client_id, module),
                )
                for version_id, payload in cursor.fetchall():
                    rows_by_version[version_id].append(dict(payload))
        return dict(rows_by_version)

    def source_audit_events(self, client_id: str, module: str) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select payload
                    from source_audit_events
                    where client_id = %s and module = %s
                    order by created_at desc, audit_event_id desc
                    """,
                    (client_id, module),
                )
                return [dict(row[0]) for row in cursor.fetchall()]

    def rebuild_client_from_files(self, client: dict) -> dict:
        from app.client_config_store import get_client_config
        from app.source_store import (
            _safe_customs_fx_rows,
            co_stock_rows_from_bcct,
            load_module_state,
            state_path,
        )

        material = load_module_state(client, "material_catalog")
        product = load_module_state(client, "product_catalog")
        bcct = load_module_state(client, "bcct")
        client_config = get_client_config(client)
        stock_rows = co_stock_rows_from_bcct(
            bcct["published_rows"],
            client_config,
            customs_fx_rows=_safe_customs_fx_rows(),
        )
        catalog_records = (
            build_catalog_index_records(client["id"], "material_catalog", material["published_rows"])
            + build_catalog_index_records(client["id"], "product_catalog", product["published_rows"])
        )
        bcct_records, invoice_records = build_bcct_index_records(client["id"], bcct["published_rows"])
        stock_records = build_co_stock_index_records(client["id"], stock_rows)
        correction_records = (
            build_correction_candidate_records(client["id"], "material_catalog", material.get("correction_candidates", []))
            + build_correction_candidate_records(client["id"], "product_catalog", product.get("correction_candidates", []))
            + build_correction_candidate_records(client["id"], "bcct", bcct.get("correction_candidates", []))
        )
        metadata = [
            source_metadata_record(client["id"], "material_catalog", material, state_path(client["id"], "material_catalog")),
            source_metadata_record(client["id"], "product_catalog", product, state_path(client["id"], "product_catalog")),
            source_metadata_record(client["id"], "bcct", bcct, state_path(client["id"], "bcct")),
            {
                "client_id": client["id"],
                "module": "co_stock",
                "version_id": "",
                "version_no": 0,
                "published_row_count": len(stock_rows),
                "reviewed_row_count": 0,
                "correction_candidate_count": 0,
                "state_mtime_ns": 0,
                "config_hash": client_config.get("config_hash", ""),
            },
        ]
        source_state_records = [
            build_source_state_records(client["id"], "material_catalog", material),
            build_source_state_records(client["id"], "product_catalog", product),
            build_source_state_records(client["id"], "bcct", bcct),
        ]
        self.ensure_schema()
        self.replace_client_indexes(
            client["id"],
            catalog_records,
            bcct_records,
            invoice_records,
            stock_records,
            correction_records,
            metadata,
            source_state_records,
        )
        return {
            "client_id": client["id"],
            "catalog_rows": len(catalog_records),
            "bcct_rows": len(bcct_records),
            "invoice_tokens": len(invoice_records),
            "co_stock_rows": len(stock_records),
        }

    def replace_client_indexes(
        self,
        client_id: str,
        catalog_records: list[dict],
        bcct_records: list[dict],
        invoice_records: list[dict],
        stock_records: list[dict],
        correction_records: list[dict],
        metadata_records: list[dict],
        source_state_records: list[dict] | None = None,
    ) -> None:
        from psycopg.types.json import Jsonb

        source_state_records = source_state_records or []
        module_state_records = [records["module_state"] for records in source_state_records]
        source_upload_records = [row for records in source_state_records for row in records["uploads"]]
        source_raw_file_records = [row for records in source_state_records for row in records["raw_files"]]
        source_snapshot_records = [row for records in source_state_records for row in records["snapshots"]]
        source_snapshot_row_records = [row for records in source_state_records for row in records["snapshot_rows"]]
        source_version_records = [row for records in source_state_records for row in records["versions"]]
        source_version_row_records = [row for records in source_state_records for row in records["version_rows"]]
        source_audit_records = [row for records in source_state_records for row in records["audit_events"]]

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("delete from bcct_invoice_index where client_id = %s", (client_id,))
                cursor.execute("delete from source_audit_events where client_id = %s", (client_id,))
                cursor.execute("delete from source_version_rows where client_id = %s", (client_id,))
                cursor.execute("delete from source_versions where client_id = %s", (client_id,))
                cursor.execute("delete from source_snapshot_rows where client_id = %s", (client_id,))
                cursor.execute("delete from source_snapshots where client_id = %s", (client_id,))
                cursor.execute("delete from source_raw_files where client_id = %s", (client_id,))
                cursor.execute("delete from source_uploads where client_id = %s", (client_id,))
                cursor.execute("delete from source_module_state where client_id = %s", (client_id,))
                cursor.execute("delete from source_correction_candidates where client_id = %s", (client_id,))
                cursor.execute("delete from source_catalog_rows where client_id = %s", (client_id,))
                cursor.execute("delete from co_stock_rows where client_id = %s", (client_id,))
                cursor.execute("delete from bcct_rows where client_id = %s", (client_id,))
                cursor.execute("delete from source_index_metadata where client_id = %s", (client_id,))
                cursor.executemany(
                    """
                    insert into source_module_state (
                        client_id, module, schema_version, latest_version_id, next_version_no,
                        published_row_count, upload_count, version_count, correction_candidate_count
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            row["client_id"],
                            row["module"],
                            row["schema_version"],
                            row["latest_version_id"],
                            row["next_version_no"],
                            row["published_row_count"],
                            row["upload_count"],
                            row["version_count"],
                            row["correction_candidate_count"],
                        )
                        for row in module_state_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into source_uploads (
                        upload_id, client_id, module, metadata_schema_version,
                        original_filename, safe_filename, stored_filename, stored_path,
                        storage_backend, content_sha256, size_bytes, file_ext, mime_type,
                        upload_scope, parse_status, parse_error, snapshot_id, row_count,
                        result, created_version_id, diff_summary, payload, created_at
                    )
                    values (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now())
                    )
                    """,
                    [
                        (
                            row["upload_id"],
                            row["client_id"],
                            row["module"],
                            row["metadata_schema_version"],
                            row["original_filename"],
                            row["safe_filename"],
                            row["stored_filename"],
                            row["stored_path"],
                            row["storage_backend"],
                            row["content_sha256"],
                            row["size_bytes"],
                            row["file_ext"],
                            row["mime_type"],
                            row["upload_scope"],
                            row["parse_status"],
                            row["parse_error"],
                            row["snapshot_id"],
                            row["row_count"],
                            row["result"],
                            row["created_version_id"],
                            Jsonb(row["diff_summary"]),
                            Jsonb(row),
                            row["created_at"],
                        )
                        for row in source_upload_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into source_raw_files (
                        raw_file_id, upload_id, client_id, module, storage_backend,
                        storage_key, filename, content_sha256, size_bytes, content_type, created_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()))
                    """,
                    [
                        (
                            row["raw_file_id"],
                            row["upload_id"],
                            row["client_id"],
                            row["module"],
                            row["storage_backend"],
                            row["storage_key"],
                            row["filename"],
                            row["content_sha256"],
                            row["size_bytes"],
                            row["content_type"],
                            row["created_at"],
                        )
                        for row in source_raw_file_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into source_snapshots (
                        snapshot_id, client_id, module, upload_id, row_count, rows_hash, payload, created_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()))
                    """,
                    [
                        (
                            row["snapshot_id"],
                            row["client_id"],
                            row["module"],
                            row["upload_id"],
                            row["row_count"],
                            row["rows_hash"],
                            Jsonb(row),
                            row["created_at"],
                        )
                        for row in source_snapshot_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into source_snapshot_rows (
                        snapshot_id, client_id, module, row_index, row_key,
                        customs_code, product_code, transaction_key, direction,
                        declaration_no, line_no, declaration_type, item_code,
                        hs_code, invoice_ref, payload
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            row["snapshot_id"],
                            row["client_id"],
                            row["module"],
                            row["row_index"],
                            row["row_key"],
                            row["customs_code"],
                            row["product_code"],
                            row["transaction_key"],
                            row["direction"],
                            row["declaration_no"],
                            row["line_no"],
                            row["declaration_type"],
                            row["item_code"],
                            row["hs_code"],
                            row["invoice_ref"],
                            Jsonb(row["payload"]),
                        )
                        for row in source_snapshot_row_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into source_versions (
                        version_id, client_id, module, version_no, source_upload_id,
                        snapshot_id, row_count, rows_hash, summary, payload, created_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()))
                    """,
                    [
                        (
                            row["version_id"],
                            row["client_id"],
                            row["module"],
                            row["version_no"],
                            row["source_upload_id"],
                            row["snapshot_id"],
                            row["row_count"],
                            row["rows_hash"],
                            Jsonb(row["summary"]),
                            Jsonb(row),
                            row["created_at"],
                        )
                        for row in source_version_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into source_version_rows (
                        version_id, client_id, module, row_index, row_key,
                        customs_code, product_code, transaction_key, direction,
                        declaration_no, line_no, declaration_type, item_code,
                        hs_code, invoice_ref, payload
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            row["version_id"],
                            row["client_id"],
                            row["module"],
                            row["row_index"],
                            row["row_key"],
                            row["customs_code"],
                            row["product_code"],
                            row["transaction_key"],
                            row["direction"],
                            row["declaration_no"],
                            row["line_no"],
                            row["declaration_type"],
                            row["item_code"],
                            row["hs_code"],
                            row["invoice_ref"],
                            Jsonb(row["payload"]),
                        )
                        for row in source_version_row_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into source_audit_events (
                        audit_event_id, client_id, module, event, upload_id, version_id,
                        snapshot_id, details, payload, created_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()))
                    """,
                    [
                        (
                            row["audit_event_id"],
                            row["client_id"],
                            row["module"],
                            row["event"],
                            row["upload_id"],
                            row["version_id"],
                            row["snapshot_id"],
                            Jsonb(row["details"]),
                            Jsonb(row),
                            row["created_at"],
                        )
                        for row in source_audit_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into source_catalog_rows (
                        client_id, module, row_key, customs_code, product_code,
                        hs_code, unit, status, payload
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            row["client_id"],
                            row["module"],
                            row["row_key"],
                            row["customs_code"],
                            row["product_code"],
                            row["hs_code"],
                            row["unit"],
                            row["status"],
                            Jsonb(row["payload"]),
                        )
                        for row in catalog_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into bcct_rows (
                        client_id, transaction_key, direction, review_status, declaration_no,
                        line_no, declaration_type, item_code, hs_code, quantity, unit,
                        invoice_ref, payload
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            row["client_id"],
                            row["transaction_key"],
                            row["direction"],
                            row["review_status"],
                            row["declaration_no"],
                            row["line_no"],
                            row["declaration_type"],
                            row["item_code"],
                            row["hs_code"],
                            row["quantity"],
                            row["unit"],
                            row["invoice_ref"],
                            Jsonb(row["payload"]),
                        )
                        for row in bcct_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into bcct_invoice_index (client_id, invoice_key, transaction_key)
                    values (%s, %s, %s)
                    on conflict do nothing
                    """,
                    [
                        (row["client_id"], row["invoice_key"], row["transaction_key"])
                        for row in invoice_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into co_stock_rows (
                        client_id, source_row, transaction_key, import_declaration_no,
                        line_no, declaration_type, customs_item_code, allocation_code,
                        eligibility_status, remaining_qty, payload
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            row["client_id"],
                            row["source_row"],
                            row["transaction_key"],
                            row["import_declaration_no"],
                            row["line_no"],
                            row["declaration_type"],
                            row["customs_item_code"],
                            row["allocation_code"],
                            row["eligibility_status"],
                            row["remaining_qty"],
                            Jsonb(row["payload"]),
                        )
                        for row in stock_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into source_correction_candidates (
                        client_id, module, candidate_id, transaction_key, status, payload
                    )
                    values (%s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            row["client_id"],
                            row["module"],
                            row["candidate_id"],
                            row["transaction_key"],
                            row["status"],
                            Jsonb(row["payload"]),
                        )
                        for row in correction_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into source_index_metadata (
                        client_id, module, version_id, version_no, published_row_count,
                        reviewed_row_count, correction_candidate_count, state_mtime_ns, config_hash
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            row["client_id"],
                            row["module"],
                            row["version_id"],
                            row["version_no"],
                            row["published_row_count"],
                            row["reviewed_row_count"],
                            row["correction_candidate_count"],
                            row["state_mtime_ns"],
                            row["config_hash"],
                        )
                        for row in metadata_records
                    ],
                )

    def _connect(self):
        return connect(self.url)


def source_metadata_record(client_id: str, module: str, state: dict, path: Path) -> dict:
    latest = state.get("latest_version") or {}
    return {
        "client_id": client_id,
        "module": module,
        "version_id": latest.get("version_id", ""),
        "version_no": int(latest.get("version_no") or 0),
        "published_row_count": len(state.get("published_rows", [])),
        "reviewed_row_count": sum(1 for row in state.get("published_rows", []) if row.get("review_status") == "reviewed"),
        "correction_candidate_count": len(state.get("correction_candidates", [])),
        "state_mtime_ns": path.stat().st_mtime_ns if path.exists() else 0,
        "config_hash": "",
    }


def metadata_summary(row, module: str) -> dict:
    if not row:
        return {
            "module": module,
            "published_row_count": 0,
            "latest_version": {},
            "version_count": 0,
            "upload_count": 0,
            "correction_candidate_count": 0,
            "reviewed_row_count": 0,
        }
    return {
        "module": module,
        "published_row_count": int(row[3] or 0),
        "latest_version": {"version_id": row[1] or "", "version_no": int(row[2] or 0)} if row[1] or row[2] else {},
        "version_count": 0,
        "upload_count": 0,
        "correction_candidate_count": int(row[5] or 0),
        "reviewed_row_count": int(row[4] or 0),
    }


def indexed_module_workspace(
    row,
    module: str,
    published_rows: list[dict],
    correction_candidates: list[dict],
    uploads: list[dict],
    versions: list[dict],
    snapshot_rows: dict[str, list[dict]],
    version_rows: dict[str, list[dict]],
    audit_events: list[dict],
) -> dict:
    summary = metadata_summary(row, module)
    return {
        "module": module,
        "published_rows": [dict(published_row) for published_row in published_rows],
        "latest_version": summary["latest_version"],
        "versions": [dict(version) for version in versions],
        "uploads": [dict(upload) for upload in uploads],
        "snapshot_rows": {
            snapshot_id: [dict(history_row) for history_row in rows]
            for snapshot_id, rows in snapshot_rows.items()
        },
        "version_rows": {
            version_id: [dict(history_row) for history_row in rows]
            for version_id, rows in version_rows.items()
        },
        "correction_candidates": [dict(candidate) for candidate in correction_candidates],
        "audit_events": [dict(event) for event in audit_events],
        "published_row_count": summary["published_row_count"],
        "version_count": len(versions),
        "upload_count": len(uploads),
        "reviewed_row_count": summary["reviewed_row_count"],
    }
