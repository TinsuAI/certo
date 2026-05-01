from __future__ import annotations

import secrets

from app.database import connect


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
