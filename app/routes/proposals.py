"""BOM proposal audit — nested under /clients/{client_id}/."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import auth
from app.database import connect
from app.routes.clients import get_client, stats_for_client

router = APIRouter()


@router.get("/clients/{client_id}/proposals", response_class=HTMLResponse)
async def list_view(request: Request, client_id: str, status: str | None = None):
    auth.require_user(request)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    items = _list_proposals(client_id, status_filter=status)
    counts = _count_by_status(client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/proposals.html",
        {"client": client, "stats": stats_for_client(client_id),
         "items": items, "status": status, "counts": counts,
         "active_root": "clients", "active_tab": "proposals"},
    )


@router.get("/clients/{client_id}/proposals/{proposal_id}", response_class=HTMLResponse)
async def detail_view(request: Request, client_id: str, proposal_id: str):
    auth.require_user(request)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    proposal = _get_proposal(proposal_id)
    if not proposal or proposal["client_id"] != client_id:
        raise HTTPException(404, "Proposal not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/proposal_detail.html",
        {"client": client, "stats": stats_for_client(client_id),
         "proposal": proposal,
         "active_root": "clients", "active_tab": "proposals"},
    )


def _list_proposals(client_id: str, *, status_filter: str | None = None) -> list[dict]:
    sql = """
        select proposal_id, client_id, product_code, actor, intent,
               parent_version_id, status, decided_at, decision_reason,
               failed_conditions, materialized_version_id, created_at
        from hub.bom_change_requests where client_id = %s
    """
    params: list = [client_id]
    if status_filter:
        sql += " and status = %s"
        params.append(status_filter)
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
                "select status, count(*) from hub.bom_change_requests where client_id = %s group by status",
                (client_id,))
            return dict(cur.fetchall())


def _get_proposal(proposal_id: str) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select proposal_id, client_id, product_code, actor, intent,
                       parent_version_id, context, rows_payload, status,
                       decided_at, decided_by, decision_reason,
                       failed_conditions, materialized_version_id,
                       normalized_hash, created_at
                from hub.bom_change_requests where proposal_id = %s
                """,
                (proposal_id,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
