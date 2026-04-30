"""Upload audit log — see all file uploads + parse status across modules."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import auth
from app.database import connect
from app.routes.dncxs import get_dncx, list_dncxs

router = APIRouter()


@router.get("/uploads", response_class=HTMLResponse)
async def list_view(request: Request, dncx_id: str | None = None,
                    module: str | None = None):
    user = auth.require_user(request)
    dncxs = list_dncxs()
    items = _list_uploads(dncx_id=dncx_id, module=module)
    counts = _count_by_status()
    return request.app.state.templates.TemplateResponse(
        request,
        "uploads/list.html",
        {
            "dncxs": dncxs,
            "selected_dncx": dncx_id,
            "selected_module": module,
            "items": items,
            "counts": counts,
            "active": "uploads",
        },
    )


def _list_uploads(*, dncx_id: str | None, module: str | None) -> list[dict]:
    sql = """
        select fu.upload_id, fu.dncx_id, d.name as dncx_name, fu.module,
               fu.original_filename, fu.size_bytes, fu.parse_status,
               fu.parse_error, fu.row_count, fu.created_at, fu.parsed_at,
               fu.uploader_user_id
        from hub.file_uploads fu
        left join hub.dncxs d on d.dncx_id = fu.dncx_id
        where 1=1
    """
    params: list = []
    if dncx_id:
        sql += " and fu.dncx_id = %s"
        params.append(dncx_id)
    if module:
        sql += " and fu.module = %s"
        params.append(module)
    sql += " order by fu.created_at desc limit 500"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _count_by_status() -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select parse_status, count(*) from hub.file_uploads group by parse_status"
            )
            return dict(cur.fetchall())
