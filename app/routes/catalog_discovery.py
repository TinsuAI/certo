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
    bulk_accept_codes,
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


def _truthy(v) -> bool:
    return str(v).lower() in {"1", "true", "on", "yes"}


def _filter_pending(rows, *, kind=None, source=None, q=None,
                    leaf=False, min_observed=0, show_machinery=False):
    """The shared filter predicate — the page render AND the bulk-accept
    POST both run this, so the button approves exactly what the table
    shows (#35: the filter is the rule). `excluded_non_material`
    (machinery) is dropped unless show_machinery is set."""
    out = [r for r in rows if r["status"] == "pending"]
    if not show_machinery:
        out = [r for r in out
               if r.get("customs_relevance") != "excluded_non_material"]
    if kind in VALID_KIND_FILTER:
        out = [r for r in out if r["code_kind"] == kind]
    if source in VALID_SOURCE_FILTER:
        out = [r for r in out if source in (r["sources"] or [])]
    if leaf:
        out = [r for r in out if r.get("leaf_in_flattened_bom")]
    if min_observed:
        out = [r for r in out if (r.get("observed_count") or 0) >= min_observed]
    if q:
        needle = q.lower()
        out = [r for r in out
               if needle in r["code"].lower()
               or needle in (r["sample_text"] or "").lower()]
    return out


# ── Page ──────────────────────────────────────────────────────────────────


def _filter_kwargs(*, kind, source, q, leaf, min_observed, show_machinery):
    return dict(
        kind=kind, source=source, q=q,
        leaf=_truthy(leaf), min_observed=min_observed,
        show_machinery=_truthy(show_machinery),
    )


@router.get(
    "/clients/{client_id}/catalog/candidates",
    response_class=HTMLResponse,
)
async def candidates_page(
    request: Request, client_id: str,
    kind: str | None = None,
    source: str | None = None,
    q: str | None = None,
    leaf: str | None = None,
    min_observed: int = 0,
    show_machinery: str | None = None,
):
    _, client = _require_client(request, client_id)

    rows = discovery_rows(client_id)
    kw = _filter_kwargs(kind=kind, source=source, q=q, leaf=leaf,
                        min_observed=min_observed, show_machinery=show_machinery)
    rejected = sorted(
        (r for r in rows if r["status"] == "rejected"),
        key=lambda r: r["code"],
    )
    # Base = pending after the machinery default (so kind chips count the
    # visible set), then apply the narrowing filters for the table.
    base = _filter_pending(rows, show_machinery=kw["show_machinery"])
    pending = _filter_pending(rows, **kw)
    pending.sort(key=lambda r: (-(r["observed_count"] or 0), r["code"]))
    pending_total = len(pending)

    page_params = parse_page_params(query_params=request.query_params)
    page = pending[page_params.offset:page_params.offset
                   + page_params.page_size]
    counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    leaf_count = 0
    for r in base:
        counts[r["code_kind"]] = counts.get(r["code_kind"], 0) + 1
        for s in (r["sources"] or []):
            source_counts[s] = source_counts.get(s, 0) + 1
        if r.get("leaf_in_flattened_bom"):
            leaf_count += 1
    machinery_total = sum(
        1 for r in rows if r["status"] == "pending"
        and r.get("customs_relevance") == "excluded_non_material")
    # A short sample of the codes the bulk button would act on.
    bulk_sample = [r["code"] for r in pending[:5]]
    paging = pagination_context(
        request=request, page_params=page_params, total=pending_total,
    )

    return request.app.state.templates.TemplateResponse(
        request, "clients/catalog_candidates.html",
        {
            "client": client,
            "pending": page,
            "pending_total": pending_total,
            "base_total": len(base),
            "leaf_count": leaf_count,
            "machinery_total": machinery_total,
            "rejected": rejected,
            "rejected_total": len(rejected),
            "kind_counts": counts,
            "source_counts": source_counts,
            "bulk_sample": bulk_sample,
            "active_kind": kind,
            "active_source": source,
            "active_q": q or "",
            "active_leaf": kw["leaf"],
            "active_min_observed": min_observed or 0,
            "active_show_machinery": kw["show_machinery"],
            "paging": paging,
            "page_params": page_params,
            "categories": sorted(VALID_CATEGORIES),
            "production_sources": sorted(VALID_PRODUCTION_SOURCES),
            "active_root": "clients",
            "active_tab": "catalog",
        },
    )


@router.post("/clients/{client_id}/catalog/candidates/bulk-accept")
async def bulk_accept(
    request: Request, client_id: str,
    kind: str = Form(""),
    source: str = Form(""),
    q: str = Form(""),
    leaf: str = Form(""),
    min_observed: int = Form(0),
    show_machinery: str = Form(""),
):
    """Approve every code matching the current filter. The filter is
    re-applied server-side (not trusted from a client-sent code list),
    so the button acts on exactly what the table showed."""
    user, _ = _require_client(request, client_id, edit=True)
    kw = _filter_kwargs(kind=kind or None, source=source or None,
                        q=q or None, leaf=leaf, min_observed=min_observed,
                        show_machinery=show_machinery)
    matching = _filter_pending(discovery_rows(client_id), **kw)
    result = bulk_accept_codes(
        client_id, rows=matching, actor=user.email,
        predicate={k: v for k, v in kw.items() if v},
    )
    return RedirectResponse(
        url=(f"/clients/{client_id}/catalog/candidates"
             f"?bulk_accepted={result['accepted']}"
             f"&bulk_skipped={result['skipped']}"),
        status_code=303,
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


def _validate_form(category: str, production_source: str | None) -> None:
    if category not in VALID_CATEGORIES:
        raise HTTPException(400, f"invalid category: {category!r}")
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
    uom: str = Form(""),
    production_source: str = Form(""),
    supplier_hint: str = Form(""),
):
    user, _ = _require_client(request, client_id, edit=True)
    row = get_row(client_id, code, code_kind)
    if row is None or row["status"] != "pending":
        raise HTTPException(404, "candidate not found")
    _validate_form(category, production_source or None)
    try:
        accept_code(
            client_id, code=code, code_kind=code_kind, actor=user.email,
            name=name.strip(), category=category,
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
