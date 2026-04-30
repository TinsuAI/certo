"""BOM proposal audit views — show approval/rejection history."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import auth
from app.database import connect
from app.routes.dncxs import get_dncx, list_dncxs

router = APIRouter()


@router.get("/proposals", response_class=HTMLResponse)
async def list_view(request: Request, dncx_id: str | None = None,
                    status: str | None = None):
    user = auth.require_user(request)
    dncxs = list_dncxs()
    if not dncxs:
        return request.app.state.templates.TemplateResponse(
            request, "proposals/empty.html",
            {"active": "proposals"},
        )
    dncx_id = dncx_id or dncxs[0]["dncx_id"]
    dncx = get_dncx(dncx_id)
    if not dncx:
        raise HTTPException(404, "DNCX not found")
    items = _list_proposals(dncx_id, status_filter=status)
    counts = _count_by_status(dncx_id)
    return request.app.state.templates.TemplateResponse(
        request,
        "proposals/list.html",
        {
            "dncxs": dncxs,
            "dncx": dncx,
            "items": items,
            "status": status,
            "counts": counts,
            "active": "proposals",
        },
    )


@router.get("/proposals/{proposal_id}", response_class=HTMLResponse)
async def detail_view(request: Request, proposal_id: str):
    user = auth.require_user(request)
    proposal = _get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(404, "Proposal not found")
    return request.app.state.templates.TemplateResponse(
        request,
        "proposals/detail.html",
        {"proposal": proposal, "active": "proposals"},
    )


def _list_proposals(dncx_id: str, *, status_filter: str | None = None) -> list[dict]:
    sql = """
        select proposal_id, dncx_id, product_code, actor, intent,
               parent_version_id, status, decided_at, decision_reason,
               failed_conditions, materialized_version_id, created_at
        from hub.bom_change_requests
        where dncx_id = %s
    """
    params: list = [dncx_id]
    if status_filter:
        sql += " and status = %s"
        params.append(status_filter)
    sql += " order by created_at desc limit 500"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _count_by_status(dncx_id: str) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select status, count(*) from hub.bom_change_requests
                where dncx_id = %s group by status
                """,
                (dncx_id,),
            )
            return dict(cur.fetchall())


def _get_proposal(proposal_id: str) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select proposal_id, dncx_id, product_code, actor, intent,
                       parent_version_id, context, rows_payload, status,
                       decided_at, decided_by, decision_reason,
                       failed_conditions, materialized_version_id,
                       normalized_hash, created_at
                from hub.bom_change_requests where proposal_id = %s
                """,
                (proposal_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
