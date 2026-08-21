"""BOM proposal audit + manual review actions — nested under /clients/{cid}/."""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from hub.app import auth
from hub.app.database import connect
from hub.app.routes.clients import get_client, stats_for_client
from hub.app.stores.bom import (
    ProposalNotFound,
    ProposalNotPending,
    approve_proposal,
    get_proposal,
    reject_proposal,
    withdraw_proposal,
)

router = APIRouter()


@router.get("/clients/{client_id}/proposals", response_class=HTMLResponse)
async def list_view(request: Request, client_id: str, status: str | None = None):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    items = _list_proposals(client_id, status_filter=status)
    counts = _count_by_status(client_id)
    stats = stats_for_client(client_id)
    _labels = {"pending": "Chờ duyệt", "approved": "Đã duyệt",
               "rejected": "Từ chối", "applied": "Đã áp dụng",
               "auto_applied": "Tự áp dụng", "superseded": "Thay thế"}
    dash_cards = [{"value": stats["proposals"], "label": "Tổng đề xuất",
                   "tone": "primary"}]
    for _st, _n in sorted(counts.items()):
        dash_cards.append({"value": _n, "label": _labels.get(_st, _st),
                           "tone": "warn" if _st == "pending" else None})
    return request.app.state.templates.TemplateResponse(
        request, "clients/proposals.html",
        {"client": client, "stats": stats,
         "items": items, "status": status, "counts": counts,
         "dash_cards": dash_cards,
         "can_approve": auth.can_approve_proposal(user, client_id),
         "active_root": "clients", "active_tab": "proposals"},
    )


@router.get("/clients/{client_id}/proposals/{proposal_id}", response_class=HTMLResponse)
async def detail_view(request: Request, client_id: str, proposal_id: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    proposal = get_proposal(proposal_id)
    if not proposal or proposal["client_id"] != client_id:
        raise HTTPException(404, "Proposal not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/proposal_detail.html",
        {"client": client, "stats": stats_for_client(client_id),
         "proposal": proposal,
         "can_approve": auth.can_approve_proposal(user, client_id),
         "can_edit": auth.can_edit_client(user, client_id),
         "active_root": "clients", "active_tab": "proposals"},
    )


@router.post("/clients/{client_id}/proposals/{proposal_id}/approve")
async def approve_view(request: Request, client_id: str, proposal_id: str,
                       reason: str = Form("")):
    user = auth.require_user(request)
    auth.require_can_approve_proposal(user, client_id)
    proposal = get_proposal(proposal_id)
    if not proposal or proposal["client_id"] != client_id:
        raise HTTPException(404, "Proposal not found")
    try:
        approve_proposal(
            proposal_id=proposal_id, decided_by=user.user_id,
            reason=(reason.strip() or None),
        )
    except ProposalNotFound:
        raise HTTPException(404, "Proposal not found")
    except ProposalNotPending as exc:
        raise HTTPException(409, f"Proposal not pending (current status: {exc})")
    return RedirectResponse(
        url=f"/clients/{client_id}/proposals/{proposal_id}", status_code=303,
    )


@router.post("/clients/{client_id}/proposals/{proposal_id}/reject")
async def reject_view(request: Request, client_id: str, proposal_id: str,
                      reason: str = Form("")):
    user = auth.require_user(request)
    auth.require_can_approve_proposal(user, client_id)
    proposal = get_proposal(proposal_id)
    if not proposal or proposal["client_id"] != client_id:
        raise HTTPException(404, "Proposal not found")
    try:
        reject_proposal(
            proposal_id=proposal_id, decided_by=user.user_id,
            reason=reason.strip() or "rejected by reviewer",
        )
    except ProposalNotFound:
        raise HTTPException(404, "Proposal not found")
    except ProposalNotPending as exc:
        raise HTTPException(409, f"Proposal not pending (current status: {exc})")
    return RedirectResponse(
        url=f"/clients/{client_id}/proposals/{proposal_id}", status_code=303,
    )


@router.post("/clients/{client_id}/proposals/{proposal_id}/withdraw")
async def withdraw_view(request: Request, client_id: str, proposal_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    proposal = get_proposal(proposal_id)
    if not proposal or proposal["client_id"] != client_id:
        raise HTTPException(404, "Proposal not found")
    try:
        withdraw_proposal(proposal_id=proposal_id, by=user.user_id)
    except ProposalNotFound:
        raise HTTPException(404, "Proposal not found")
    except ProposalNotPending as exc:
        raise HTTPException(409, f"Proposal not pending (current status: {exc})")
    return RedirectResponse(
        url=f"/clients/{client_id}/proposals/{proposal_id}", status_code=303,
    )


def _list_proposals(client_id: str, *, status_filter: str | None = None) -> list[dict]:
    sql = """
        select proposal_id, client_id, product_code, actor, intent,
               parent_artifact_id, status, decided_at, decision_reason,
               failed_conditions, materialized_artifact_id, created_at
        from hub.bom_change_requests where client_id = %s
    """
    params: list = [client_id]
    if status_filter:
        sql += " and status = %s"
        params.append(status_filter)
    sql += " order by case when status='pending' then 0 else 1 end, created_at desc limit 500"
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
