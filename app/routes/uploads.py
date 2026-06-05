"""Upload audit — nested under /clients/{client_id}/."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect
from app.routes.clients import get_client, stats_for_client

router = APIRouter()

# Only failed/abandoned uploads may be deleted — a 'done' row backs a real
# artifact via source_upload_id and must stay for provenance.
_DELETABLE_STATUSES = ("error", "rejected")


@router.get("/clients/{client_id}/uploads", response_class=HTMLResponse)
async def list_view(request: Request, client_id: str, module: str | None = None):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    items = _list_uploads(client_id=client_id, module=module)
    counts = _count_by_status(client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/uploads.html",
        {"client": client, "stats": stats_for_client(client_id),
         "items": items, "selected_module": module, "counts": counts,
         "active_root": "clients", "active_tab": "uploads"},
    )


@router.post("/clients/{client_id}/uploads/{upload_id}/delete")
async def delete_upload(request: Request, client_id: str, upload_id: str):
    """Remove a failed/rejected upload row (and its blob). Refuses 'done'
    and other statuses that back a stored artifact."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    with connect(user_id=user.user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select parse_status, stored_path from hub.file_uploads "
                "where upload_id=%s and client_id=%s",
                (upload_id, client_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Upload not found")
            parse_status, stored_path = row
            if parse_status not in _DELETABLE_STATUSES:
                raise HTTPException(
                    400, "Chỉ xoá được upload lỗi hoặc đã bị từ chối.")
            cur.execute(
                "delete from hub.file_uploads where upload_id=%s and client_id=%s",
                (upload_id, client_id),
            )
    if stored_path:
        try:
            from app.storage import get_backend
            get_backend().delete(stored_path)
        except Exception:  # noqa: BLE001 — blob may already be gone
            pass
    return RedirectResponse(
        url=f"/clients/{client_id}/uploads?deleted=1", status_code=303,
    )


def _list_uploads(*, client_id: str, module: str | None) -> list[dict]:
    sql = """
        select upload_id, module, original_filename, size_bytes, parse_status,
               parse_error, row_count, created_at, parsed_at, uploader_user_id
        from hub.file_uploads
        where client_id = %s
    """
    params: list = [client_id]
    if module:
        sql += " and module = %s"
        params.append(module)
    sql += " order by created_at desc limit 500"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _count_by_status(client_id: str) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select parse_status, count(*) from hub.file_uploads where client_id = %s group by parse_status",
                (client_id,))
            return dict(cur.fetchall())
