from __future__ import annotations

import json
import secrets

from hub.app.database import connect


def get_upload(upload_id: str, *, client_id: str | None = None) -> dict | None:
    """Fetch a file_uploads row (optionally scoped to a client) as a dict."""
    sql = (
        "select upload_id, client_id, module, original_filename, stored_path, "
        "       storage_backend, content_sha256, parse_status, parse_error, "
        "       row_count, result, created_at "
        "from hub.file_uploads where upload_id=%s"
    )
    params: tuple = (upload_id,)
    if client_id is not None:
        sql += " and client_id=%s"
        params = (upload_id, client_id)
    cols = ("upload_id", "client_id", "module", "original_filename",
            "stored_path", "storage_backend", "content_sha256", "parse_status",
            "parse_error", "row_count", "result", "created_at")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def set_upload_status(upload_id: str, status: str, *,
                      row_count: int | None = None,
                      parse_error: str | None = None,
                      result: dict | None = None) -> None:
    """Update parse_status (+ optional row_count / parse_error / result jsonb).
    Stamps parsed_at on every transition."""
    sets = ["parse_status=%s", "parsed_at=now()"]
    params: list = [status]
    if row_count is not None:
        sets.append("row_count=%s")
        params.append(row_count)
    if parse_error is not None:
        sets.append("parse_error=%s")
        params.append(parse_error)
    if result is not None:
        sets.append("result=%s::jsonb")
        params.append(json.dumps(result, ensure_ascii=False, default=str))
    params.append(upload_id)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"update hub.file_uploads set {', '.join(sets)} where upload_id=%s",
            tuple(params),
        )


def record_upload(*, client_id: str | None, module: str, original_filename: str,
                  stored_path: str, content_sha256: str, size_bytes: int,
                  mime_type: str | None = None,
                  uploader_user_id: str | None = None,
                  storage_backend: str = "localfs") -> str:
    upload_id = "upl_" + secrets.token_urlsafe(12)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.file_uploads
                  (upload_id, client_id, module, original_filename, stored_path,
                   storage_backend, content_sha256, size_bytes, mime_type,
                   uploader_user_id, parse_status)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                (upload_id, client_id, module, original_filename, stored_path,
                 storage_backend, content_sha256, size_bytes, mime_type,
                 uploader_user_id),
            )
    return upload_id
