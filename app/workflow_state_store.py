from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any

from app.database import apply_migrations, connect, database_url


class CaseRevisionConflict(RuntimeError):
    """Optimistic-concurrency conflict from `save_case_record`.

    Carries the expected and current revisions so the caller (Phase 2.4
    `update_case_record` retry loop) can reload, reapply its mutation,
    and retry without clobbering the writer that won the race.
    """

    def __init__(self, client_id: str, case_id: str, expected_revision: int, current_revision: int):
        self.client_id = client_id
        self.case_id = case_id
        self.expected_revision = int(expected_revision)
        self.current_revision = int(current_revision)
        super().__init__(
            f"Case {client_id}/{case_id} revision {current_revision} "
            f"!= expected {expected_revision}"
        )


def get_bom_state_store() -> "PostgresBomStateStore | None":
    url = database_url()
    return PostgresBomStateStore(url) if url else None


def get_co_case_state_store() -> "PostgresCoCaseStateStore | None":
    url = database_url()
    return PostgresCoCaseStateStore(url) if url else None


class PostgresBomStateStore:
    def __init__(self, url: str):
        self.url = url

    def ensure_schema(self) -> None:
        apply_migrations(self.url)

    def get_state(self, client_id: str) -> dict | None:
        self.ensure_schema()
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select payload from bom_states where client_id = %s", (client_id,))
                row = cursor.fetchone()
                if row is None:
                    return None
                state = dict(row[0])
                state.setdefault("snapshot_rows", self.snapshot_rows(client_id))
                return state

    def snapshot_rows(self, client_id: str) -> dict[str, list[dict]]:
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select snapshot_id, payload
                    from bom_snapshot_rows
                    where client_id = %s
                    order by snapshot_id, row_index
                    """,
                    (client_id,),
                )
                rows: dict[str, list[dict]] = {}
                for snapshot_id, payload in cursor.fetchall():
                    rows.setdefault(snapshot_id, []).append(dict(payload))
                return rows

    def save_state(self, client_id: str, state: dict) -> None:
        from psycopg.types.json import Jsonb

        self.ensure_schema()
        uploads = bom_upload_records(client_id, state)
        snapshots = bom_snapshot_records(client_id, state)
        snapshot_rows = bom_snapshot_row_records(client_id, state)
        product_versions = bom_product_version_records(client_id, state)
        product_version_rows = bom_product_version_row_records(client_id, state)
        versions = bom_version_records(client_id, state)
        version_rows = bom_version_row_records(client_id, state)
        audit_events = bom_audit_event_records(client_id, state)
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("delete from bom_audit_events where client_id = %s", (client_id,))
                cursor.execute("delete from bom_version_rows where client_id = %s", (client_id,))
                cursor.execute("delete from bom_versions where client_id = %s", (client_id,))
                cursor.execute("delete from bom_product_version_rows where client_id = %s", (client_id,))
                cursor.execute("delete from bom_product_versions where client_id = %s", (client_id,))
                cursor.execute("delete from bom_snapshot_rows where client_id = %s", (client_id,))
                cursor.execute("delete from bom_snapshots where client_id = %s", (client_id,))
                cursor.execute("delete from bom_uploads where client_id = %s", (client_id,))
                cursor.execute(
                    """
                    insert into bom_states (client_id, schema_version, config, payload, updated_at)
                    values (%s, %s, %s, %s, now())
                    on conflict (client_id) do update set
                      schema_version = excluded.schema_version,
                      config = excluded.config,
                      payload = excluded.payload,
                      updated_at = now()
                    """,
                    (
                        client_id,
                        int(state.get("schema_version") or 1),
                        Jsonb(state.get("config", {})),
                        Jsonb(state),
                    ),
                )
                cursor.executemany(
                    """
                    insert into bom_uploads (
                      client_id, upload_id, original_filename, safe_filename, stored_filename,
                      stored_path, storage_backend, content_sha256, size_bytes, file_ext,
                      mime_type, profile_used, upload_mode, upload_scope, parse_status,
                      parse_error, result, snapshot_id, normalized_hash, row_count,
                      created_version_id, created_aggregate_version_no, duplicate_of,
                      diff_summary, product_results, payload, created_at
                    )
                    values (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now())
                    )
                    """,
                    [
                        (
                            row["client_id"],
                            row["upload_id"],
                            row["original_filename"],
                            row["safe_filename"],
                            row["stored_filename"],
                            row["stored_path"],
                            row["storage_backend"],
                            row["content_sha256"],
                            row["size_bytes"],
                            row["file_ext"],
                            row["mime_type"],
                            row["profile_used"],
                            row["upload_mode"],
                            row["upload_scope"],
                            row["parse_status"],
                            row["parse_error"],
                            row["result"],
                            row["snapshot_id"],
                            row["normalized_hash"],
                            row["row_count"],
                            row["created_version_id"],
                            row["created_aggregate_version_no"],
                            row["duplicate_of"],
                            Jsonb(row["diff_summary"]),
                            Jsonb(row["product_results"]),
                            Jsonb(row["payload"]),
                            timestamp(row["created_at"]),
                        )
                        for row in uploads
                    ],
                )
                cursor.executemany(
                    """
                    insert into bom_snapshots (
                      client_id, snapshot_id, upload_id, profile, upload_mode,
                      normalized_hash, row_count, payload, created_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()))
                    """,
                    [
                        (
                            row["client_id"],
                            row["snapshot_id"],
                            row["upload_id"],
                            row["profile"],
                            row["upload_mode"],
                            row["normalized_hash"],
                            row["row_count"],
                            Jsonb(row["payload"]),
                            timestamp(row["created_at"]),
                        )
                        for row in snapshots
                    ],
                )
                cursor.executemany(
                    """
                    insert into bom_snapshot_rows (
                      client_id, snapshot_id, row_index, row_key, product_code,
                      bom_code, bom_variant_id, material_code, uom, payload
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            row["client_id"],
                            row["snapshot_id"],
                            row["row_index"],
                            row["row_key"],
                            row["product_code"],
                            row["bom_code"],
                            row["bom_variant_id"],
                            row["material_code"],
                            row["uom"],
                            Jsonb(row["payload"]),
                        )
                        for row in snapshot_rows
                    ],
                )
                cursor.executemany(
                    """
                    insert into bom_product_versions (
                      client_id, product_version_id, product_code, product_version_no,
                      status, source_snapshot_id, source_upload_id, previous_product_version_id,
                      profile, version_hash, row_count, diff_summary, payload,
                      created_at, published_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()), coalesce(%s::timestamptz, now()))
                    """,
                    [
                        (
                            row["client_id"],
                            row["product_version_id"],
                            row["product_code"],
                            row["product_version_no"],
                            row["status"],
                            row["source_snapshot_id"],
                            row["source_upload_id"],
                            row["previous_product_version_id"],
                            row["profile"],
                            row["version_hash"],
                            row["row_count"],
                            Jsonb(row["diff_summary"]),
                            Jsonb(row["payload"]),
                            timestamp(row["created_at"]),
                            timestamp(row["published_at"]),
                        )
                        for row in product_versions
                    ],
                )
                insert_bom_rows(cursor, "bom_product_version_rows", "product_version_id", product_version_rows, Jsonb)
                cursor.executemany(
                    """
                    insert into bom_versions (
                      client_id, version_id, version_no, aggregate_version_no, status,
                      source_snapshot_id, source_upload_id, previous_version_id, version_hash,
                      composition_hash, row_count, changed_products, diff_summary,
                      product_versions, payload, created_at, published_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()), coalesce(%s::timestamptz, now()))
                    """,
                    [
                        (
                            row["client_id"],
                            row["version_id"],
                            row["version_no"],
                            row["aggregate_version_no"],
                            row["status"],
                            row["source_snapshot_id"],
                            row["source_upload_id"],
                            row["previous_version_id"],
                            row["version_hash"],
                            row["composition_hash"],
                            row["row_count"],
                            Jsonb(row["changed_products"]),
                            Jsonb(row["diff_summary"]),
                            Jsonb(row["product_versions"]),
                            Jsonb(row["payload"]),
                            timestamp(row["created_at"]),
                            timestamp(row["published_at"]),
                        )
                        for row in versions
                    ],
                )
                insert_bom_rows(cursor, "bom_version_rows", "version_id", version_rows, Jsonb)
                cursor.executemany(
                    """
                    insert into bom_audit_events (
                      client_id, audit_event_id, event, actor, details, payload, occurred_at
                    )
                    values (%s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()))
                    """,
                    [
                        (
                            row["client_id"],
                            row["audit_event_id"],
                            row["event"],
                            row["actor"],
                            Jsonb(row["details"]),
                            Jsonb(row["payload"]),
                            timestamp(row["occurred_at"]),
                        )
                        for row in audit_events
                    ],
                )


class PostgresCoCaseStateStore:
    def __init__(self, url: str):
        self.url = url

    def ensure_schema(self) -> None:
        apply_migrations(self.url)

    def get_state(self, client_id: str) -> dict | None:
        self.ensure_schema()
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select payload from co_case_states where client_id = %s", (client_id,))
                row = cursor.fetchone()
                return dict(row[0]) if row else None

    def acquire_client_lock(self, client_id: str):
        """Open a dedicated session-scoped advisory lock on this client.

        The returned connection holds the lock — session-scoped advisory
        locks (pg_advisory_lock) survive across transactions but are
        bound to the backend, so the caller MUST keep the connection
        open and pass it back to `release_client_lock`. We commit after
        acquiring so the implicit SET-search_path transaction from
        connect() doesn't stay open.

        This is the Phase 1 cross-process serialization that keeps two
        operators editing the same client from clobbering each other's
        payload (audit gap HIGH #3 band-aid). Per-case rows + optimistic
        concurrency lands in Phase 2.
        """
        self.ensure_schema()
        connection = connect(self.url)
        with connection.cursor() as cursor:
            cursor.execute(
                "select pg_advisory_lock(hashtext(%s))",
                (f"co_case_states:{client_id}",),
            )
        connection.commit()
        return connection

    def release_client_lock(self, client_id: str, connection) -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "select pg_advisory_unlock(hashtext(%s))",
                    (f"co_case_states:{client_id}",),
                )
            connection.commit()
        finally:
            connection.close()

    def get_case(self, client_id: str, case_id: str) -> tuple[dict, int] | None:
        """Returns (case_payload, revision) for a single case or None.

        Phase 2.2 entry point — `co_cases` is the per-case row + revision
        token. Phase 2.5 makes this table the source of truth (currently
        callers still read through `get_state` for the merged view).
        """
        self.ensure_schema()
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "select payload, revision from co_cases where client_id = %s and case_id = %s",
                    (client_id, case_id),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                return dict(row[0]), int(row[1])

    def save_case_record(
        self,
        client_id: str,
        case_payload: dict,
        expected_revision: int,
    ) -> int:
        """Upsert a single case with optimistic concurrency on `revision`.

        - `expected_revision == 0` and no row: INSERT, returns 1.
        - existing row with `revision == expected_revision`: UPDATE,
          bumps to `expected_revision + 1`, returns the new revision.
        - existing row with mismatched revision: raises
          `CaseRevisionConflict` carrying the current DB revision so
          the caller can reload + reapply (Phase 2.4 retry loop).

        Phase 2.5 wires this into update_case_record and drops the
        cases[] block from co_case_states.payload.
        """
        from psycopg.types.json import Jsonb

        self.ensure_schema()
        case_id = str(case_payload.get("case_id") or "").strip()
        if not case_id:
            raise ValueError("case_payload missing case_id")
        record = _co_case_record_fields(client_id, case_payload)
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                if expected_revision <= 0:
                    cursor.execute(
                        """
                        insert into co_cases (
                          client_id, case_id, title, case_code, destination_market,
                          agreement, co_form_type, rule, invoice_no, bill_of_lading_no,
                          supporting_file_count, payload, revision, created_at, updated_at
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1,
                                coalesce(%s::timestamptz, now()), coalesce(%s::timestamptz, now()))
                        on conflict (client_id, case_id) do nothing
                        returning revision
                        """,
                        (
                            client_id, case_id, record["title"], record["case_code"],
                            record["destination_market"], record["agreement"],
                            record["co_form_type"], record["rule"], record["invoice_no"],
                            record["bill_of_lading_no"], record["supporting_file_count"],
                            Jsonb(record["payload"]),
                            timestamp(record["created_at"]), timestamp(record["updated_at"]),
                        ),
                    )
                    inserted = cursor.fetchone()
                    if inserted:
                        return int(inserted[0])
                    # Row already exists — fall through to fetch current revision.
                    cursor.execute(
                        "select revision from co_cases where client_id = %s and case_id = %s",
                        (client_id, case_id),
                    )
                    current = cursor.fetchone()
                    raise CaseRevisionConflict(
                        client_id, case_id, expected_revision, int(current[0]) if current else 0
                    )
                cursor.execute(
                    """
                    update co_cases
                       set title = %s, case_code = %s, destination_market = %s,
                           agreement = %s, co_form_type = %s, rule = %s,
                           invoice_no = %s, bill_of_lading_no = %s,
                           supporting_file_count = %s, payload = %s,
                           revision = revision + 1, updated_at = now()
                     where client_id = %s and case_id = %s and revision = %s
                     returning revision
                    """,
                    (
                        record["title"], record["case_code"], record["destination_market"],
                        record["agreement"], record["co_form_type"], record["rule"],
                        record["invoice_no"], record["bill_of_lading_no"],
                        record["supporting_file_count"], Jsonb(record["payload"]),
                        client_id, case_id, expected_revision,
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    cursor.execute(
                        "select revision from co_cases where client_id = %s and case_id = %s",
                        (client_id, case_id),
                    )
                    current = cursor.fetchone()
                    raise CaseRevisionConflict(
                        client_id, case_id, expected_revision, int(current[0]) if current else 0
                    )
                return int(row[0])

    def delete_case(self, client_id: str, case_id: str) -> None:
        """Remove a single case row + its supporting files. Phase 2.5 makes
        this the canonical case-delete path; Phase 2.2 ships it for the
        retry-loop and future cutover use without removing the legacy
        save_state path.
        """
        self.ensure_schema()
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "delete from co_supporting_files where client_id = %s and case_id = %s",
                    (client_id, case_id),
                )
                cursor.execute(
                    "delete from co_cases where client_id = %s and case_id = %s",
                    (client_id, case_id),
                )

    def save_state(self, client_id: str, state: dict) -> None:
        from psycopg.types.json import Jsonb

        self.ensure_schema()
        cases = co_case_records(client_id, state)
        supporting_files = co_supporting_file_records(client_id, state)
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("delete from co_supporting_files where client_id = %s", (client_id,))
                cursor.execute("delete from co_cases where client_id = %s", (client_id,))
                cursor.execute(
                    """
                    insert into co_case_states (client_id, schema_version, payload, updated_at)
                    values (%s, %s, %s, now())
                    on conflict (client_id) do update set
                      schema_version = excluded.schema_version,
                      payload = excluded.payload,
                      updated_at = now()
                    """,
                    (client_id, int(state.get("schema_version") or 1), Jsonb(state)),
                )
                cursor.executemany(
                    """
                    insert into co_cases (
                      client_id, case_id, title, case_code, destination_market,
                      agreement, co_form_type, rule, invoice_no, bill_of_lading_no,
                      supporting_file_count, payload, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()), coalesce(%s::timestamptz, now()))
                    """,
                    [
                        (
                            row["client_id"],
                            row["case_id"],
                            row["title"],
                            row["case_code"],
                            row["destination_market"],
                            row["agreement"],
                            row["co_form_type"],
                            row["rule"],
                            row["invoice_no"],
                            row["bill_of_lading_no"],
                            row["supporting_file_count"],
                            Jsonb(row["payload"]),
                            timestamp(row["created_at"]),
                            timestamp(row["updated_at"]),
                        )
                        for row in cases
                    ],
                )
                cursor.executemany(
                    """
                    insert into co_supporting_files (
                      client_id, case_id, upload_id, slot, original_filename, safe_filename,
                      stored_filename, stored_path, storage_backend, content_sha256,
                      size_bytes, file_ext, mime_type, invoice_no, bill_of_lading_no,
                      payload, uploaded_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()))
                    """,
                    [
                        (
                            row["client_id"],
                            row["case_id"],
                            row["upload_id"],
                            row["slot"],
                            row["original_filename"],
                            row["safe_filename"],
                            row["stored_filename"],
                            row["stored_path"],
                            row["storage_backend"],
                            row["content_sha256"],
                            row["size_bytes"],
                            row["file_ext"],
                            row["mime_type"],
                            row["invoice_no"],
                            row["bill_of_lading_no"],
                            Jsonb(row["payload"]),
                            timestamp(row["uploaded_at"]),
                        )
                        for row in supporting_files
                    ],
                )


def insert_bom_rows(cursor, table: str, owner_field: str, rows: list[dict], jsonb_type) -> None:
    cursor.executemany(
        f"""
        insert into {table} (
          client_id, {owner_field}, row_index, row_key, product_code,
          bom_code, bom_variant_id, material_code, uom, payload
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        [
            (
                row["client_id"],
                row[owner_field],
                row["row_index"],
                row["row_key"],
                row["product_code"],
                row["bom_code"],
                row["bom_variant_id"],
                row["material_code"],
                row["uom"],
                jsonb_type(row["payload"]),
            )
            for row in rows
        ],
    )


def bom_upload_records(client_id: str, state: dict) -> list[dict]:
    return [bom_upload_record(client_id, upload) for upload in state.get("uploads", [])]


def bom_upload_record(client_id: str, upload: dict) -> dict:
    original_filename = upload.get("original_filename") or upload.get("filename", "")
    stored_path = upload.get("stored_path") or upload.get("storage_path", "")
    stored_filename = upload.get("stored_filename") or Path(stored_path).name or safe_storage_filename(original_filename)
    safe_name = upload.get("safe_filename") or safe_storage_filename(original_filename)
    size_bytes = int(upload.get("size_bytes") or upload.get("file_size") or 0)
    return {
        "client_id": client_id,
        "upload_id": upload["upload_id"],
        "original_filename": original_filename,
        "safe_filename": safe_name,
        "stored_filename": stored_filename,
        "stored_path": stored_path,
        "storage_backend": upload.get("storage_backend") or ("filesystem" if stored_path else ""),
        "content_sha256": upload.get("content_sha256", ""),
        "size_bytes": size_bytes,
        "file_ext": upload.get("file_ext") or Path(original_filename).suffix.lower(),
        "mime_type": upload.get("mime_type") or mimetypes.guess_type(original_filename)[0] or "",
        "profile_used": upload.get("profile_used", ""),
        "upload_mode": upload.get("upload_mode", ""),
        "upload_scope": upload.get("upload_scope", ""),
        "parse_status": upload.get("parse_status", ""),
        "parse_error": upload.get("parse_error", ""),
        "result": upload.get("result", ""),
        "snapshot_id": upload.get("snapshot_id", ""),
        "normalized_hash": upload.get("normalized_hash", ""),
        "row_count": int(upload.get("row_count") or 0),
        "created_version_id": upload.get("created_version_id", ""),
        "created_aggregate_version_no": int(upload.get("created_aggregate_version_no") or 0),
        "duplicate_of": upload.get("duplicate_of", ""),
        "diff_summary": dict(upload.get("diff_summary") or {}),
        "product_results": list(upload.get("product_results") or []),
        "payload": dict(upload),
        "created_at": upload.get("created_at"),
    }


def bom_snapshot_records(client_id: str, state: dict) -> list[dict]:
    records = []
    for upload in state.get("uploads", []):
        snapshot_id = upload.get("snapshot_id", "")
        if not snapshot_id:
            continue
        snapshot = legacy_bom_snapshot(client_id, snapshot_id) or {
            "snapshot_id": snapshot_id,
            "upload_id": upload.get("upload_id", ""),
            "client_id": client_id,
            "profile": upload.get("profile_used", ""),
            "upload_mode": upload.get("upload_mode", ""),
            "normalized_hash": upload.get("normalized_hash", ""),
            "row_count": int(upload.get("row_count") or 0),
            "created_at": upload.get("created_at"),
        }
        records.append({
            "client_id": client_id,
            "snapshot_id": snapshot_id,
            "upload_id": snapshot.get("upload_id", upload.get("upload_id", "")),
            "profile": snapshot.get("profile", upload.get("profile_used", "")),
            "upload_mode": snapshot.get("upload_mode", upload.get("upload_mode", "")),
            "normalized_hash": snapshot.get("normalized_hash", upload.get("normalized_hash", "")),
            "row_count": int(snapshot.get("row_count") or upload.get("row_count") or 0),
            "payload": snapshot,
            "created_at": snapshot.get("created_at") or upload.get("created_at"),
        })
    return records


def bom_snapshot_row_records(client_id: str, state: dict) -> list[dict]:
    rows = []
    snapshot_rows = state.get("snapshot_rows") or {}
    for upload in state.get("uploads", []):
        snapshot_id = upload.get("snapshot_id", "")
        if not snapshot_id:
            continue
        source_rows = snapshot_rows.get(snapshot_id) or legacy_bom_snapshot_rows(client_id, snapshot_id)
        rows.extend(bom_row_records(client_id, "snapshot_id", snapshot_id, source_rows))
    return rows


def bom_product_version_records(client_id: str, state: dict) -> list[dict]:
    records = []
    for versions in state.get("product_versions", {}).values():
        for version in versions:
            records.append({
                "client_id": client_id,
                "product_version_id": version["product_version_id"],
                "product_code": version.get("product_code", ""),
                "product_version_no": int(version.get("product_version_no") or 0),
                "status": version.get("status", ""),
                "source_snapshot_id": version.get("source_snapshot_id", ""),
                "source_upload_id": version.get("source_upload_id", ""),
                "previous_product_version_id": version.get("previous_product_version_id", ""),
                "profile": version.get("profile", ""),
                "version_hash": version.get("version_hash", ""),
                "row_count": int(version.get("row_count") or len(version.get("rows", []))),
                "diff_summary": dict(version.get("diff_summary") or {}),
                "payload": dict(version),
                "created_at": version.get("created_at"),
                "published_at": version.get("published_at"),
            })
    return records


def bom_product_version_row_records(client_id: str, state: dict) -> list[dict]:
    rows = []
    for versions in state.get("product_versions", {}).values():
        for version in versions:
            rows.extend(bom_row_records(client_id, "product_version_id", version["product_version_id"], version.get("rows", [])))
    return rows


def bom_version_records(client_id: str, state: dict) -> list[dict]:
    return [
        {
            "client_id": client_id,
            "version_id": version["version_id"],
            "version_no": int(version.get("version_no") or 0),
            "aggregate_version_no": int(version.get("aggregate_version_no") or version.get("version_no") or 0),
            "status": version.get("status", ""),
            "source_snapshot_id": version.get("source_snapshot_id", ""),
            "source_upload_id": version.get("source_upload_id", ""),
            "previous_version_id": version.get("previous_version_id", ""),
            "version_hash": version.get("version_hash", ""),
            "composition_hash": version.get("composition_hash", ""),
            "row_count": int(version.get("row_count") or len(version.get("rows", []))),
            "changed_products": list(version.get("changed_products") or []),
            "diff_summary": dict(version.get("diff_summary") or {}),
            "product_versions": list(version.get("product_versions") or []),
            "payload": dict(version),
            "created_at": version.get("created_at"),
            "published_at": version.get("published_at"),
        }
        for version in state.get("versions", [])
    ]


def bom_version_row_records(client_id: str, state: dict) -> list[dict]:
    rows = []
    for version in state.get("versions", []):
        rows.extend(bom_row_records(client_id, "version_id", version["version_id"], version.get("rows", [])))
    return rows


def bom_row_records(client_id: str, owner_field: str, owner_id: str, rows: list[dict]) -> list[dict]:
    return [
        {
            "client_id": client_id,
            owner_field: owner_id,
            "row_index": index,
            "row_key": row.get("row_key", "") or f"row-{index}",
            "product_code": row.get("product_code", ""),
            "bom_code": row.get("bom_code", ""),
            "bom_variant_id": row.get("bom_variant_id", ""),
            "material_code": row.get("material_code", ""),
            "uom": row.get("uom", ""),
            "payload": dict(row),
        }
        for index, row in enumerate(rows, start=1)
    ]


def bom_audit_event_records(client_id: str, state: dict) -> list[dict]:
    return [
        {
            "client_id": client_id,
            "audit_event_id": stable_event_id(client_id, "bom", event, index),
            "event": event.get("event", ""),
            "actor": event.get("actor", ""),
            "details": dict(event.get("details") or {}),
            "payload": dict(event),
            "occurred_at": event.get("at"),
        }
        for index, event in enumerate(state.get("audit", []), start=1)
    ]


def legacy_bom_snapshot(client_id: str, snapshot_id: str) -> dict:
    path = bom_client_root(client_id) / "snapshots" / snapshot_id / "snapshot.json"
    return read_json_dict(path)


def legacy_bom_snapshot_rows(client_id: str, snapshot_id: str) -> list[dict]:
    path = bom_client_root(client_id) / "snapshots" / snapshot_id / "rows.json"
    return read_json_rows(path)


def bom_client_root(client_id: str) -> Path:
    return Path(os.environ.get("BOM_STORE_ROOT", "data/local/bom-builder")) / "clients" / safe_storage_filename(client_id)


def _co_case_record_fields(client_id: str, case: dict) -> dict:
    shipment = dict(case.get("shipment") or {})
    return {
        "client_id": client_id,
        "case_id": case["case_id"],
        "title": case.get("title", ""),
        "case_code": case.get("case_code", ""),
        "destination_market": case.get("destination_market", ""),
        "agreement": case.get("agreement", ""),
        "co_form_type": case.get("co_form_type", ""),
        "rule": case.get("rule", ""),
        "invoice_no": shipment.get("invoice_no", ""),
        "bill_of_lading_no": shipment.get("bill_of_lading_no", ""),
        "supporting_file_count": len(case.get("supporting_files", [])),
        "payload": dict(case),
        "created_at": case.get("created_at"),
        "updated_at": case.get("updated_at"),
    }


def co_case_records(client_id: str, state: dict) -> list[dict]:
    return [_co_case_record_fields(client_id, case) for case in state.get("cases", [])]


def co_supporting_file_records(client_id: str, state: dict) -> list[dict]:
    records = []
    for case in state.get("cases", []):
        for file_row in case.get("supporting_files", []):
            records.append(co_supporting_file_record(client_id, case["case_id"], file_row))
    return records


def co_supporting_file_record(client_id: str, case_id: str, file_row: dict) -> dict:
    original_filename = file_row.get("original_filename") or file_row.get("filename", "")
    stored_path = file_row.get("stored_path", "")
    stored_filename = file_row.get("stored_filename") or Path(stored_path).name or safe_storage_filename(original_filename)
    safe_name = file_row.get("safe_filename") or file_row.get("filename") or safe_storage_filename(original_filename)
    content_sha256 = file_row.get("content_sha256") or file_sha256(co_case_client_root(client_id) / stored_path)
    mime_type = file_row.get("mime_type") or mimetypes.guess_type(original_filename)[0] or ""
    return {
        "client_id": client_id,
        "case_id": case_id,
        "upload_id": file_row["upload_id"],
        "slot": file_row.get("slot", ""),
        "original_filename": original_filename,
        "safe_filename": safe_name,
        "stored_filename": stored_filename,
        "stored_path": stored_path,
        "storage_backend": file_row.get("storage_backend") or ("filesystem" if stored_path else ""),
        "content_sha256": content_sha256,
        "size_bytes": int(file_row.get("size_bytes") or 0),
        "file_ext": file_row.get("file_ext") or Path(original_filename).suffix.lower(),
        "mime_type": mime_type,
        "invoice_no": file_row.get("invoice_no", ""),
        "bill_of_lading_no": file_row.get("bill_of_lading_no", ""),
        "payload": dict(file_row),
        "uploaded_at": file_row.get("uploaded_at"),
    }


def co_case_client_root(client_id: str) -> Path:
    return Path(os.environ.get("CO_CASE_STORE_ROOT", "data/local/co-cases")) / "clients" / client_id


def read_json_dict(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def read_json_rows(path: Path) -> list[dict]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def stable_event_id(client_id: str, scope: str, event: dict, index: int) -> str:
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha1(f"{client_id}|{scope}|{index}|{payload}".encode("utf-8")).hexdigest()[:16]
    return f"{scope}-audit-{digest}"


def timestamp(value: Any) -> str | None:
    return str(value).strip() if value else None


def safe_storage_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(filename or "").strip()).strip("-")
    return cleaned or "file"
