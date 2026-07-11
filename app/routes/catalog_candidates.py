"""Mã chờ duyệt — passive candidate feed.

Brief: .ai/features/2026-05-09-ma-cho-duyet/brief.md

Page handler GETs the feed (refreshes candidates on render). POST handlers
implement the state-machine transitions: accept, reject, unreject.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect
from app.routes._paging import (
    pagination_context, parse_page_params,
)
from app.routes.clients import get_client
from app.stores.catalog_candidates import (
    accept_candidate,
    refresh_candidates,
    reject_candidate,
    unreject_candidate,
)


router = APIRouter()

VALID_KIND_FILTER = {"nb", "hq", "unified"}
VALID_SOURCE_FILTER = {"bcct", "bom", "bqd"}
VALID_CATEGORIES = {"nvl", "tp", "btp_sx", "btp_nm", "ccdc"}
VALID_STATUSES = {"under_review", "active"}
VALID_PRODUCTION_SOURCES = {"nk", "sx", "mixed", "unknown"}


SELECT_COLS = (
    "candidate_id, code, code_kind, sources, observed_count, "
    "first_seen, last_seen, sample_text, suggested_category, "
    "multi_direction, import_count, export_count, decl_count, "
    "bom_role, bom_sample, co_occurrence_count, "
    "hs_code, hs_alternates_count, uom, origin, "
    "inferred_production_source, "
    "status, decided_at, decided_by, decision_reason"
)


def _build_where(client_id, status, kind, source, q):
    where = ["client_id = %s", "status = %s"]
    params: list = [client_id, status]
    if kind in VALID_KIND_FILTER:
        where.append("code_kind = %s")
        params.append(kind)
    if source in VALID_SOURCE_FILTER:
        where.append("%s = any(sources)")
        params.append(source)
    if q:
        where.append("(code ilike %s or sample_text ilike %s)")
        like = f"%{q}%"
        params.extend([like, like])
    return where, params


def _list_candidates(
    client_id: str, *,
    status: str = "pending",
    kind: str | None = None,
    source: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    where, params = _build_where(client_id, status, kind, source, q)
    sql = (
        f"select {SELECT_COLS} "
        "from hub.catalog_candidates where " + " and ".join(where) +
        " order by observed_count desc nulls last, code "
        " limit %s offset %s"
    )
    params.extend([limit, offset])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _total_count(client_id: str, *, status: str = "pending",
                 kind: str | None = None, source: str | None = None,
                 q: str | None = None) -> int:
    where, params = _build_where(client_id, status, kind, source, q)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.catalog_candidates where "
            + " and ".join(where), params,
        )
        return cur.fetchone()[0]


def _candidate(candidate_id: int) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select candidate_id, client_id, code, code_kind, status "
            "from hub.catalog_candidates where candidate_id=%s",
            (candidate_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def _kind_counts(client_id: str) -> dict:
    """Count pending candidates by kind for the filter chips."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select code_kind, count(*) from hub.catalog_candidates "
            "where client_id=%s and status='pending' group by code_kind",
            (client_id,),
        )
        return {k: n for k, n in cur.fetchall()}


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
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")

    page_params = parse_page_params(query_params=request.query_params)
    pending = _list_candidates(
        client_id, status="pending", kind=kind, source=source, q=q,
        limit=page_params.page_size, offset=page_params.offset,
    )
    pending_total = _total_count(client_id, status="pending",
                                 kind=kind, source=source, q=q)
    rejected = _list_candidates(client_id, status="rejected", limit=100)
    rejected_total = _total_count(client_id, status="rejected")
    counts = _kind_counts(client_id)
    paging = pagination_context(
        request=request, page_params=page_params, total=pending_total,
    )

    return request.app.state.templates.TemplateResponse(
        request, "clients/catalog_candidates.html",
        {
            "client": client,
            "pending": pending,
            "pending_total": pending_total,
            "rejected": rejected,
            "rejected_total": rejected_total,
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
async def refresh_candidates_route(request: Request, client_id: str):
    """Explicit "Làm mới" button. The refresh left the GET handler in #32 —
    it scanned all bcct_rows and wrote thousands of candidate rows on every
    page view (measured 2.2s+ on Growatt). Ingest flows also call
    `refresh_candidates_after_ingest`, so the button is for catch-up
    (script-loaded data, rule edits)."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    n = refresh_candidates(client_id)
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog/candidates?refreshed={n}",
        status_code=303,
    )


# ── State-machine transitions ─────────────────────────────────────────────


def _validate_form(category: str, status: str,
                   production_source: str | None) -> None:
    if category not in VALID_CATEGORIES:
        raise HTTPException(400, f"invalid category: {category!r}")
    if status not in VALID_STATUSES:
        raise HTTPException(400, f"invalid status: {status!r}")
    if production_source and production_source not in VALID_PRODUCTION_SOURCES:
        raise HTTPException(400,
                             f"invalid production_source: {production_source!r}")


@router.get(
    "/clients/{client_id}/catalog/candidates/{candidate_id}",
    response_class=HTMLResponse,
)
async def candidate_detail(
    request: Request, client_id: str, candidate_id: int,
):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"select {SELECT_COLS} from hub.catalog_candidates "
            "where candidate_id=%s and client_id=%s",
            (candidate_id, client_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "candidate not found")
        cols = [d[0] for d in cur.description]
        candidate = dict(zip(cols, row))

        # Co-occurring codes (paired NB↔HQ via BCCT goods_name parens).
        co_occurrences = _co_occurring_codes(client_id, candidate)

        # BCCT lines that mention this code.
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
            (client_id, candidate["code"],
             f"%({candidate['code']})%"),
        )
        bcct_cols = [d[0] for d in cur.description]
        bcct_samples = [dict(zip(bcct_cols, r)) for r in cur.fetchall()]

        # BOM artifacts that reference this code.
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


def _co_occurring_codes(client_id: str, candidate: dict) -> list[dict]:
    """Find codes paired with this candidate's code in BCCT goods_name parens.

    For an HQ candidate: returns NB codes paired in goods_name.
    For an NB candidate: returns HQ values from customs_code field.
    """
    code = candidate["code"]
    kind = candidate["code_kind"]
    if kind == "unified":
        return []
    pairs: dict[str, int] = {}
    with connect() as conn, conn.cursor() as cur:
        if kind == "hq":
            cur.execute(
                "select goods_name from hub.bcct_rows "
                "where client_id=%s and customs_code=%s",
                (client_id, code),
            )
            from app.parsers.client_parser_rules import (
                load_rules, extract_all_matches_from_compiled,
            )
            rules = load_rules(client_id=client_id, output_field="internal_code")
            if rules:
                for (gn,) in cur.fetchall():
                    matches = extract_all_matches_from_compiled(
                        rules, row={"customs_code": code, "goods_name": gn},
                    )
                    for m in matches:
                        nb = m.get("product_code")
                        if nb and nb != code:
                            pairs[nb] = pairs.get(nb, 0) + 1
        elif kind == "nb":
            from app.parsers.client_parser_rules import (
                load_rules, extract_all_matches_from_compiled,
            )
            from app.parsers.catalog_candidates import _is_missing_hq
            from app.stores.provenance import customs_code_placeholders
            rules = load_rules(client_id=client_id, output_field="internal_code")
            if rules:
                placeholders = customs_code_placeholders(cur, client_id=client_id)
                cur.execute(
                    "select customs_code, goods_name from hub.bcct_rows "
                    "where client_id=%s",
                    (client_id,),
                )
                for cc, gn in cur.fetchall():
                    if _is_missing_hq(cc, placeholders):
                        continue
                    matches = extract_all_matches_from_compiled(
                        rules, row={"customs_code": cc, "goods_name": gn},
                    )
                    for m in matches:
                        if m.get("product_code") == code:
                            pairs[cc] = pairs.get(cc, 0) + 1
                            break
    out = sorted(
        ({"code": c, "n": n} for c, n in pairs.items()),
        key=lambda x: (-x["n"], x["code"]),
    )
    return out[:50]


@router.post(
    "/clients/{client_id}/catalog/candidates/{candidate_id}/accept",
)
async def accept(
    request: Request, client_id: str, candidate_id: int,
    name: str = Form(...),
    category: str = Form(...),
    status: str = Form("under_review"),
    uom: str = Form(""),
    production_source: str = Form(""),
    supplier_hint: str = Form(""),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    cand = _candidate(candidate_id)
    if cand is None or cand["client_id"] != client_id:
        raise HTTPException(404, "candidate not found")

    _validate_form(category, status, production_source or None)
    accept_candidate(
        candidate_id,
        actor=user.email,
        name=name.strip(),
        category=category,
        status=status,
        uom=uom.strip() or None,
        production_source=production_source.strip() or None,
        supplier_hint=supplier_hint.strip() or None,
    )
    from urllib.parse import quote
    return RedirectResponse(
        url=(f"/clients/{client_id}/catalog/candidates"
             f"?accepted={candidate_id}&code={quote(cand['code'])}"),
        status_code=303,
    )


@router.post(
    "/clients/{client_id}/catalog/candidates/{candidate_id}/reject",
)
async def reject(
    request: Request, client_id: str, candidate_id: int,
    reason: str = Form(""),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    cand = _candidate(candidate_id)
    if cand is None or cand["client_id"] != client_id:
        raise HTTPException(404, "candidate not found")

    reject_candidate(candidate_id, actor=user.email,
                      reason=reason.strip() or None)
    from urllib.parse import quote
    return RedirectResponse(
        url=(f"/clients/{client_id}/catalog/candidates"
             f"?rejected={candidate_id}&code={quote(cand['code'])}"),
        status_code=303,
    )


@router.post(
    "/clients/{client_id}/catalog/candidates/{candidate_id}/unreject",
)
async def unreject(
    request: Request, client_id: str, candidate_id: int,
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    cand = _candidate(candidate_id)
    if cand is None or cand["client_id"] != client_id:
        raise HTTPException(404, "candidate not found")

    unreject_candidate(candidate_id, actor=user.email)
    from urllib.parse import quote
    return RedirectResponse(
        url=(f"/clients/{client_id}/catalog/candidates"
             f"?unrejected={candidate_id}&code={quote(cand['code'])}"),
        status_code=303,
    )
