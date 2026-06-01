from __future__ import annotations

import hashlib
import json
import mimetypes

from app.co_case_store import invoice_keys
from pathlib import Path


CATALOG_KEY_FIELDS = {
    "material_catalog": "customs_code",
    "product_catalog": "product_code",
}
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
    def _t(value) -> str:
        # Coerce None / missing to "" — co_stock_rows has NOT NULL constraints
        # on customs_item_code / declaration_no / line_no etc. Upstream BCCT
        # rows occasionally land with null fields (item_code missing on Vietnamese
        # bao bì lines) and must not break the materializer.
        return "" if value is None else str(value)

    return [
        {
            "client_id": client_id,
            "source_row": row["source_row"],
            "transaction_key": _t(row.get("source_transaction_key")),
            "import_declaration_no": _t(row.get("import_declaration_no")),
            "line_no": _t(row.get("line_no")),
            "declaration_type": _t(row.get("declaration_type")),
            "customs_item_code": _t(row.get("customs_item_code")),
            "allocation_code": _t(row.get("allocation_code")),
            "eligibility_status": _t(row.get("eligibility_status")),
            "remaining_qty": _t(row.get("remaining_qty")),
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
