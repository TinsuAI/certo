"""Substitute material routes — Feature 4 MVP.

Web actions on a material's "Vật tư thay thế" panel + JSON API for
sister-app C/O lookup.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from hub.app import auth
from hub.app.routes.clients import get_client
from hub.app.stores.material_substitutes import (
    insert_candidate,
    list_for_material,
    refresh_candidates,
    reject_pair,
    unreject_pair,
)


router = APIRouter()


# ── web POST: reject / unreject / manual add ──────────────────────


@router.post("/clients/{client_id}/catalog/{material_code:path}/substitutes/reject")
async def reject_substitute(
    request: Request, client_id: str, material_code: str,
    pair_b: str = Form(...),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    reject_pair(
        client_id=client_id, material_a_code=material_code,
        material_b_code=pair_b, rejected_by=user.user_id,
    )
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog/{material_code}/detail",
        status_code=303,
    )


@router.post("/clients/{client_id}/catalog/{material_code:path}/substitutes/unreject")
async def unreject_substitute(
    request: Request, client_id: str, material_code: str,
    pair_b: str = Form(...),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    unreject_pair(
        client_id=client_id, material_a_code=material_code,
        material_b_code=pair_b,
    )
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog/{material_code}/detail",
        status_code=303,
    )


@router.post("/clients/{client_id}/catalog/{material_code:path}/substitutes/add")
async def add_substitute(
    request: Request, client_id: str, material_code: str,
    pair_b: str = Form(...),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not pair_b or pair_b == material_code:
        raise HTTPException(400, "Invalid substitute target")
    insert_candidate(
        client_id=client_id, material_a_code=material_code,
        material_b_code=pair_b, source="manual_user",
        confirmed_by=user.user_id,
    )
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog/{material_code}/detail",
        status_code=303,
    )


@router.post("/clients/{client_id}/substitutes/refresh")
async def refresh_substitutes_route(request: Request, client_id: str):
    """Manual trigger button for the per-client refresh job. Sized to
    operator usage — not a UI form for end users."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    stats = refresh_candidates(client_id=client_id)
    return RedirectResponse(
        url=(f"/clients/{client_id}/catalog?refresh_subs=ok"
             f"&hs_n={stats.same_hs_inserted}"
             f"&trgm_n={stats.trigram_inserted}"),
        status_code=303,
    )


# ── JSON API ──────────────────────────────────────────────────────


@router.get(
    "/api/v1/clients/{client_id}/materials/{material_code}/substitutes",
)
async def api_list_substitutes(
    request: Request, client_id: str, material_code: str,
    min_score: float = 0.5, include_rejected: bool = False,
    limit: int = 20,
):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    cands = list_for_material(
        client_id=client_id, material_code=material_code,
        min_score=min_score, include_rejected=include_rejected,
        limit=min(limit, 100),
    )
    return {
        "client_id": client_id,
        "material_a_code": material_code,
        "count": len(cands),
        "items": [
            {
                "material_b_code": c.material_b_code,
                "name": c.name,
                "category": c.category,
                "hs_code": c.hs_code,
                "sources": c.sources,
                "raw_scores": c.raw_scores,
                "combined_score": round(c.combined_score, 4),
                "confirmed": c.confirmed,
                "confirmed_at": (
                    c.confirmed_at.isoformat() if c.confirmed_at else None
                ),
            }
            for c in cands
        ],
    }
