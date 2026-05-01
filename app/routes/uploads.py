"""Upload audit — nested under /clients/{client_id}/."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import auth
from app.database import connect
from app.routes.clients import get_client, stats_for_client

router = APIRouter()


@router.get("/clients/{client_id}/uploads", response_class=HTMLResponse)
async def list_view(request: Request, client_id: str, module: str | None = None):
    auth.require_user(request)
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
