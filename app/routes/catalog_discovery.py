"""Mã chờ duyệt — the discovery feed, computed live (ADR-0001, #34).

GET renders straight from hub.catalog_discovery(client) — one function
call per request, filtered and paginated in Python (3.3k rows max on
current data). No stored queue, no candidate_id: rows are keyed by
(code, code_kind). POST handlers: accept (→ hub.materials), reject
(→ hub.catalog_rejections), unreject (lift suppression), and the
«Làm mới» button which re-extracts hub.bcct_nb_codes (the one persisted
discovery ingredient) for script-loaded data and rule edits.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from urllib.parse import quote

from app import auth
from app.database import connect
from app.routes._paging import (
    pagination_context, parse_page_params,
)
from app.routes.clients import get_client
from app.stores.bcct_nb_codes import rebuild_for_client
from app.stores.catalog_discovery import (
    AlreadyInCatalog,
    accept_code,
    co_occurring_codes,
    discovery_rows,
    get_row,
    reject_code,
    unreject_code,
)


router = APIRouter()

VALID_KIND_FILTER = {"nb", "hq", "unified"}
VALID_SOURCE_FILTER = {"bcct", "bom", "bqd"}
VALID_CATEGORIES = {"nvl", "tp", "btp_sx", "btp_nm", "ccdc"}
VALID_STATUSES = {"under_review", "active"}
VALID_PRODUCTION_SOURCES = {"nk", "sx", "mixed", "unknown"}


def _require_client(request: Request, client_id: str, *, edit: bool = False):
    user = auth.require_user(request)
    if edit:
        auth.require_can_edit_client(user, client_id)
    else:
        auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return user, client


def _filter_pending(rows, *, kind=None, source=None, q=None):
    out = [r for r in rows if r["status"] == "pending"]
    if kind in VALID_KIND_FILTER:
        out = [r for r in out if r["code_kind"] == kind]
    if source in VALID_SOURCE_FILTER:
        out = [r for r in out if source in (r["sources"] or [])]
    if q:
        needle = q.lower()
        out = [r for r in out
               if needle in r["code"].lower()
               or needle in (r["sample_text"] or "").lower()]
    return out


# ── Page ──────────────────────────────────────────────────────────────────


@router.get(
    "/clients/{client_id}/catalog/candidates",
    response_class=HTMLResponse,
)
async def candidates_page(
    request: Request, client_id: str,
    kind: str | None = None,
    source: str | None = None,
    q: str | None = None,
):
    _, client = _require_client(request, client_id)

    rows = discovery_rows(client_id)
    pending_all = [r for r in rows if r["status"] == "pending"]
    rejected = sorted(
        (r for r in rows if r["status"] == "rejected"),
        key=lambda r: r["code"],
    )
    pending = _filter_pending(rows, kind=kind, source=source, q=q)
    pending.sort(key=lambda r: (-(r["observed_count"] or 0), r["code"]))
    pending_total = len(pending)

    page_params = parse_page_params(query_params=request.query_params)
    page = pending[page_params.offset:page_params.offset
                   + page_params.page_size]
    counts: dict[str, int] = {}
    for r in pending_all:
        counts[r["code_kind"]] = counts.get(r["code_kind"], 0) + 1
    paging = pagination_context(
        request=request, page_params=page_params, total=pending_total,
    )

    return request.app.state.templates.TemplateResponse(
        request, "clients/catalog_candidates.html",
        {
            "client": client,
            "pending": page,
            "pending_total": pending_total,
            "rejected": rejected,
            "rejected_total": len(rejected),
            "kind_counts": counts,
            "active_kind": kind,
            "active_source": source,
            "active_q": q or "",
            "paging": paging,
            "page_params": page_params,
            "categories": sorted(VALID_CATEGORIES),
            "production_sources": sorted(VALID_PRODUCTION_SOURCES),
            "active_root": "clients",
            "active_tab": "catalog",
        },
    )


@router.post("/clients/{client_id}/catalog/candidates/refresh")
async def refresh_route(request: Request, client_id: str):
    """«Làm mới»: re-extract the persisted paren links. The feed itself
    is live (a function, not a table) — this catches up bcct_nb_codes
    after script-loaded BCCT or out-of-band rule edits."""
    _require_client(request, client_id, edit=True)
    rebuild_for_client(client_id)
    n = len([r for r in discovery_rows(client_id)
             if r["status"] == "pending"])
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog/candidates?refreshed={n}",
        status_code=303,
    )


# ── Detail ────────────────────────────────────────────────────────────────


@router.get(
    "/clients/{client_id}/catalog/candidates/detail",
    response_class=HTMLResponse,
)
async def candidate_detail(
    request: Request, client_id: str, code: str, kind: str | None = None,
):
    _, client = _require_client(request, client_id)
    candidate = get_row(client_id, code, kind)
    if candidate is None:
        raise HTTPException(404, "candidate not found")

    co_occurrences = co_occurring_codes(
        client_id, candidate["code"], candidate["code_kind"],
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select transaction_key, line_no, declaration_no, registration_date,
                   direction, declaration_type, customs_code, goods_name,
                   hs_code, unit, origin
            from hub.bcct_rows
            where client_id=%s
              and (customs_code=%s or goods_name like %s)
            order by registration_date desc nulls last
            limit 20
            """,
            (client_id, candidate["code"], f"%({candidate['code']})%"),
        )
        bcct_cols = [d[0] for d in cur.description]
        bcct_samples = [dict(zip(bcct_cols, r)) for r in cur.fetchall()]

        cur.execute(
            """
            select distinct a.artifact_id, a.product_code, a.artifact_no,
                   a.flatten_status, a.created_at,
                   (a.product_code = %s) as is_root
            from hub.bom_artifacts a
            where a.client_id=%s and a.tombstoned_at is null
              and (a.product_code=%s or exists (
                select 1 from hub.bom_edges e
                where e.artifact_id=a.artifact_id
                  and (e.parent_code=%s or e.child_code=%s)
              ))
            order by is_root desc, a.created_at desc
            limit 20
            """,
            (candidate["code"], client_id, candidate["code"],
             candidate["code"], candidate["code"]),
        )
        bom_cols = [d[0] for d in cur.description]
        bom_artifacts = [dict(zip(bom_cols, r)) for r in cur.fetchall()]

    return request.app.state.templates.TemplateResponse(
        request, "clients/catalog_candidate_detail.html",
        {
            "client": client,
            "candidate": candidate,
            "co_occurrences": co_occurrences,
            "bcct_samples": bcct_samples,
            "bom_artifacts": bom_artifacts,
            "categories": sorted(VALID_CATEGORIES),
            "production_sources": sorted(VALID_PRODUCTION_SOURCES),
            "active_root": "clients", "active_tab": "catalog",
        },
    )


# ── Decisions ─────────────────────────────────────────────────────────────


def _validate_form(category: str, status: str,
                   production_source: str | None) -> None:
    if category not in VALID_CATEGORIES:
        raise HTTPException(400, f"invalid category: {category!r}")
    if status not in VALID_STATUSES:
        raise HTTPException(400, f"invalid status: {status!r}")
    if production_source and production_source not in VALID_PRODUCTION_SOURCES:
        raise HTTPException(400,
                            f"invalid production_source: {production_source!r}")


@router.post("/clients/{client_id}/catalog/candidates/accept")
async def accept(
    request: Request, client_id: str,
    code: str = Form(...),
    code_kind: str = Form(...),
    name: str = Form(...),
    category: str = Form(...),
    status: str = Form("under_review"),
    uom: str = Form(""),
    production_source: str = Form(""),
    supplier_hint: str = Form(""),
):
    user, _ = _require_client(request, client_id, edit=True)
    row = get_row(client_id, code, code_kind)
    if row is None or row["status"] != "pending":
        raise HTTPException(404, "candidate not found")
    _validate_form(category, status, production_source or None)
    try:
        accept_code(
            client_id, code=code, code_kind=code_kind, actor=user.email,
            name=name.strip(), category=category, status=status,
            uom=uom.strip() or None,
            production_source=production_source or None,
            supplier_hint=supplier_hint.strip() or None,
            sources=row.get("sources"),
        )
    except AlreadyInCatalog:
        raise HTTPException(409, "code is already in the catalog")
    return RedirectResponse(
        url=(f"/clients/{client_id}/catalog/candidates"
             f"?accepted=1&code={quote(code, safe='')}"),
        status_code=303,
    )


@router.post("/clients/{client_id}/catalog/candidates/reject")
async def reject(
    request: Request, client_id: str,
    code: str = Form(...),
    code_kind: str = Form(""),
    reason: str = Form(""),
):
    user, _ = _require_client(request, client_id, edit=True)
    row = get_row(client_id, code, code_kind or None)
    if row is None:
        raise HTTPException(404, "candidate not found")
    reject_code(client_id, code=code, code_kind=code_kind or None,
                actor=user.email, reason=reason.strip() or None)
    return RedirectResponse(
        url=(f"/clients/{client_id}/catalog/candidates"
             f"?rejected=1&code={quote(code, safe='')}"),
        status_code=303,
    )


@router.post("/clients/{client_id}/catalog/candidates/unreject")
async def unreject(
    request: Request, client_id: str,
    code: str = Form(...),
):
    user, _ = _require_client(request, client_id, edit=True)
    if not unreject_code(client_id, code=code, actor=user.email):
        raise HTTPException(404, "no rejection recorded for this code")
    return RedirectResponse(
        url=(f"/clients/{client_id}/catalog/candidates"
             f"?unrejected=1&code={quote(code, safe='')}"),
        status_code=303,
    )
