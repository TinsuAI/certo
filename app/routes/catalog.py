"""Catalog (Materials / Danh mục mã hàng) — nested under /clients/{client_id}/.

Slice 1 of the unified upload flow. The upload route now goes through
`_mapping_flow` helpers: cache lookup → (mapping page if cache miss) →
parse with overrides → preview with skipped-row inline-edit → confirm.

Per-module wiring:
  - parser: parse_materials_workbook (returns rows, skipped tuple)
  - logical_fields + min_identifier_fields: from materials.LOGICAL_FIELDS
  - ingest: _insert_materials_with_cursor (preserves provenance_kind)
  - preview template: clients/catalog_preview.html (extends shared)
"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect
from app.parsers.materials import (
    LOGICAL_FIELDS,
    MIN_IDENTIFIER_FIELDS,
    MaterialsParseError,
    parse_materials_workbook,
)
from app.routes._mapping_flow import (
    ModuleConfig,
    confirm_pending,
    parse_with_overrides_and_stash,
    reject_pending,
    render_mapping_page_context,
    render_mapping_page_with_llm_suggestion,
    render_preview_context,
    upload_initial_dispatch,
)
from app.routes._paging import (
    SortSpec,
    pagination_context,
    parse_page_params,
    sort_link,
)
from app.routes.clients import get_client, stats_for_client
from app.storage import save_upload, sha256_bytes
from app.stores.staleness import freshness_for_template
from app.stores.uploads import record_upload

router = APIRouter()

CATEGORIES = ["nvl", "btp_sx", "btp_nm", "tp", "ccdc"]


def _summarize_catalog(parsed_rows: list[dict]) -> dict:
    by_cat: dict[str, int] = {}
    by_status: dict[str, int] = {}
    n_with_customs = 0
    n_with_internal = 0
    for r in parsed_rows:
        cat = r.get("category") or "—"
        by_cat[cat] = by_cat.get(cat, 0) + 1
        st = r.get("status") or "active"
        by_status[st] = by_status.get(st, 0) + 1
        if r.get("customs_code"):
            n_with_customs += 1
        if r.get("internal_code"):
            n_with_internal += 1
    return {
        "total": len(parsed_rows),
        "by_category": by_cat,
        "by_status": by_status,
        "n_with_customs_code": n_with_customs,
        "n_with_internal_code": n_with_internal,
    }


def _ingest_materials(
    cur, *, client_id: str, rows: list[dict], upload_id: str | None,
    provenance_kind: str = "registered", **_kw,
) -> int:
    return _insert_materials_with_cursor(
        cur, client_id=client_id, rows=rows,
        upload_id=upload_id, provenance_kind=provenance_kind,
    )


CATALOG_CFG = ModuleConfig(
    name="catalog",
    upload_pending_module="catalog",
    save_upload_module="materials",
    fallback_filename="materials.xlsx",
    list_route=lambda cid: f"/clients/{cid}/catalog",
    preview_template="clients/catalog_preview.html",
    parser_fn=parse_materials_workbook,
    parser_error=MaterialsParseError,
    summarize_fn=_summarize_catalog,
    ingest_fn=_ingest_materials,
    logical_fields=LOGICAL_FIELDS,
    min_identifier_fields=MIN_IDENTIFIER_FIELDS,
    extra_required_fields_default=(),
)


# ── List + upload landing ────────────────────────────────────────────────

@router.get("/clients/{client_id}/catalog", response_class=HTMLResponse)
async def list_view(
    request: Request, client_id: str,
    category: str | None = None, q: str | None = None,
    provenance: str | None = None,
    status: str | None = None,
):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    page_params = parse_page_params(query_params=request.query_params)
    sort = SortSpec.from_params(
        query_params=request.query_params,
        whitelist=CATALOG_SORT_WHITELIST, default=CATALOG_SORT_DEFAULT,
    )
    order_by = sort.sql_clause(tiebreakers=("m.material_code",)) \
        if sort.column != "material_code" else sort.sql_clause()
    items = _query_materials(
        client_id=client_id, category=category, q=q,
        provenance=provenance, status=status,
        order_by=order_by,
        limit=page_params.page_size, offset=page_params.offset,
    )
    total = _count_materials(
        client_id=client_id, category=category, q=q,
        provenance=provenance, status=status,
    )
    counts = _category_counts(client_id)
    prov_counts = _provenance_counts(client_id)
    from app.database import connect as _connect
    from app.stores.provenance import (
        bom_unresolved_material_count, unregistered_seen_count,
    )
    with _connect() as _conn, _conn.cursor() as _cur:
        unregistered_bcct = unregistered_seen_count(_cur, client_id=client_id)
        unresolved_bom = bom_unresolved_material_count(_cur, client_id=client_id)
    paging_ctx = pagination_context(
        request=request, page_params=page_params, total=total,
    )

    # AI panel stats: how many materials embedded vs need re-analysis,
    # how many substitute pairs the catalog already has, latest job.
    from app import jobs as job_store
    from app.embedding import get_global_config as _emb_cfg
    with _connect() as _conn, _conn.cursor() as _cur:
        _cur.execute(
            """
            select
                count(*) filter (where status='active') as total,
                count(*) filter
                  (where status='active' and description_embedding is not null) as analyzed,
                count(*) filter
                  (where status='active' and (embedding_text_hash is null
                                              or embedding_model is null)) as needs_analysis,
                max(embedding_at) as last_at
              from hub.materials where client_id=%s
            """, (client_id,),
        )
        _stats_row = _cur.fetchone()
        _cur.execute(
            "select count(*) from hub.material_substitutes "
            "where client_id=%s and rejected_at is null",
            (client_id,),
        )
        _sub_count = _cur.fetchone()[0]
    _emb_active = job_store.latest(client_id, "embedding_refresh") \
        if job_store.has_active(client_id, "embedding_refresh") else None
    _sub_active = job_store.latest(client_id, "substitute_refresh") \
        if job_store.has_active(client_id, "substitute_refresh") else None
    _total = _stats_row[0] or 0
    _dirty = _stats_row[2] or 0

    def _eta(count: int, items_per_sec: float) -> str:
        """Friendly Vietnamese duration estimate. Calibrated from
        Johnson runs: embed ≈ 33/s end-to-end, substitute refresh
        scales with N² roughly but ~75/s effective for 12K."""
        if count <= 0:
            return "vài giây"
        seconds = count / items_per_sec
        if seconds < 5:
            return "vài giây"
        if seconds < 90:
            return f"khoảng {int(seconds)} giây"
        minutes = seconds / 60
        if minutes < 2:
            return "khoảng 1-2 phút"
        if minutes < 10:
            return f"khoảng {int(round(minutes))} phút"
        return f"khoảng {int(round(minutes))} phút (lâu — đề xuất chạy ngoài giờ)"

    ai_panel = {
        "materials_total": _total,
        "materials_analyzed": _stats_row[1] or 0,
        "materials_dirty": _dirty,
        "last_analysis_at": _stats_row[3],
        "substitute_pairs": _sub_count,
        "active_embedding_job_id": _emb_active.id if _emb_active else None,
        "active_substitute_job_id": _sub_active.id if _sub_active else None,
        "embedding_configured": _emb_cfg().is_live,
        "eta_dirty_embed": _eta(_dirty, 33),
        "eta_full_embed": _eta(_total, 33),
        "eta_substitute_refresh": _eta(_total, 75),
    }

    def _sort_link(col: str) -> str:
        return sort_link(request=request, column=col, current_sort=sort)
    return request.app.state.templates.TemplateResponse(
        request, "clients/catalog.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "items": items, "categories": CATEGORIES,
            "active_category": category, "q": q or "", "counts": counts,
            "active_provenance": provenance,
            "prov_counts": prov_counts,
            "unregistered_bcct": unregistered_bcct,
            "unresolved_bom": unresolved_bom,
            "ai_panel": ai_panel,
            "paging": paging_ctx, "sort": sort, "sort_link": _sort_link,
            "freshness": freshness_for_template(request, client_id, "catalog"),
            "active_root": "clients", "active_tab": "catalog",
        },
    )


@router.get("/clients/{client_id}/catalog/upload", response_class=HTMLResponse)
async def upload_view(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/catalog_upload.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "active_root": "clients", "active_tab": "catalog",
        },
    )


# ── Upload submit ────────────────────────────────────────────────────────

@router.post("/clients/{client_id}/catalog/upload")
async def upload_submit(
    request: Request, client_id: str,
    file: UploadFile = File(...),
    is_hq_registered: str = Form(""),
):
    """Save blob → cache lookup → mapping page (cache miss) or preview (cache hit).

    `is_hq_registered`: '1' = file is the official HQ-registered Danh Mục
    (every row marked registered_with_hq); empty = user_added (internal
    catalog without HQ status). Carried via diff_summary into ingest.
    """
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    blob = await file.read()
    sha = sha256_bytes(blob)
    stored = save_upload(blob, filename=file.filename or CATALOG_CFG.fallback_filename,
                         module=CATALOG_CFG.save_upload_module, client_id=client_id)
    upload_id = record_upload(
        client_id=client_id, module=CATALOG_CFG.save_upload_module,
        original_filename=file.filename or CATALOG_CFG.fallback_filename,
        stored_path=stored.path, content_sha256=sha, size_bytes=len(blob),
        mime_type=file.content_type, uploader_user_id=user.user_id,
    )
    provenance_kind = "registered" if is_hq_registered == "1" else "user_added"
    redirect_url, _, _mode = upload_initial_dispatch(
        client_id=client_id, blob=blob, upload_id=upload_id, cfg=CATALOG_CFG,
        extra_pending={"provenance_kind": provenance_kind},
    )
    return RedirectResponse(url=redirect_url, status_code=303)


# ── Mapping page (cache miss) ────────────────────────────────────────────

@router.get("/clients/{client_id}/catalog/upload/mapping/{upload_id}",
            response_class=HTMLResponse)
async def mapping_view(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    ctx = render_mapping_page_context(
        client_id=client_id, upload_id=upload_id, cfg=CATALOG_CFG,
    )
    ctx.update({
        "client": client, "stats": stats_for_client(client_id),
        "module_label": "Danh Mục",
        "active_root": "clients", "active_tab": "catalog",
    })
    return request.app.state.templates.TemplateResponse(
        request, "clients/_upload_mapping.html", ctx,
    )


@router.post("/clients/{client_id}/catalog/upload/mapping/{upload_id}/llm_suggest",
             response_class=HTMLResponse)
async def mapping_llm_suggest(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    ctx = render_mapping_page_with_llm_suggestion(
        client_id=client_id, upload_id=upload_id, cfg=CATALOG_CFG,
    )
    ctx.update({
        "client": client, "stats": stats_for_client(client_id),
        "module_label": "Danh Mục",
        "active_root": "clients", "active_tab": "catalog",
    })
    return request.app.state.templates.TemplateResponse(
        request, "clients/_upload_mapping.html", ctx,
    )


@router.post("/clients/{client_id}/catalog/upload/mapping/{upload_id}/parse")
async def mapping_parse(
    request: Request, client_id: str, upload_id: str,
):
    """Parse with the staff-confirmed mapping → stash pending → /preview."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    form = await request.form()

    # Extract per-column field selections from form fields named col_<idx>__field.
    column_map: dict[str, str] = {}
    for key, value in form.items():
        if key.startswith("col_") and key.endswith("__field"):
            idx = key[len("col_"):-len("__field")]
            field = (value or "").strip()
            if not field:
                continue
            header_value = (form.get(f"col_{idx}__header") or "").strip()
            if header_value:
                column_map[header_value] = field

    header_row_override_str = (form.get("header_row_override") or "").strip()
    header_row_override = (
        int(header_row_override_str) if header_row_override_str.isdigit() else None
    )
    extra_required_str = (form.get("extra_required_fields") or "").strip()
    extra_required = (
        [s.strip() for s in extra_required_str.split(",") if s.strip()]
        if extra_required_str else None
    )

    # Detect "did staff edit the LLM/rigid suggestion?" — by checking
    # whether the form was submitted from the LLM-suggest page (proposed_by
    # comes through the form as a hidden input set by the LLM page). For
    # MVP we simplify: treat any explicit submit as 'manual'. If staff
    # used "Apply LLM suggestion" earlier, the mapping cache will still
    # record proposed_by='manual' — that's fine; the LLM contributed but
    # staff is the one accepting.
    pending_id = parse_with_overrides_and_stash(
        client_id=client_id, upload_id=upload_id, user_id=user.user_id,
        column_map=column_map,
        header_row_override=header_row_override,
        extra_required_fields=extra_required,
        proposed_by="manual",
        cfg=CATALOG_CFG,
    )
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog/preview/{pending_id}",
        status_code=303,
    )


# ── Preview ──────────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/catalog/preview/{pending_id}",
            response_class=HTMLResponse)
async def preview_view(request: Request, client_id: str, pending_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    ctx = render_preview_context(
        client_id=client_id, pending_id=pending_id, cfg=CATALOG_CFG,
    )
    provenance_kind = (ctx.get("diff_summary") or {}).get(
        "provenance_kind", "registered",
    )
    ctx.update({
        "client": client, "stats": stats_for_client(client_id),
        "module_label": "Danh Mục",
        "list_url": f"/clients/{client_id}/catalog",
        "provenance_kind": provenance_kind,
        "active_root": "clients", "active_tab": "catalog",
    })
    return request.app.state.templates.TemplateResponse(
        request, "clients/catalog_preview.html", ctx,
    )


@router.post("/clients/{client_id}/catalog/preview/{pending_id}/confirm")
async def preview_confirm(request: Request, client_id: str, pending_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    form = await request.form()

    # Fetch pending to learn which skipped rows existed + provenance kind.
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select diff_summary from hub.upload_pending
                where pending_id = %s and client_id = %s and module = 'catalog'
                """,
                (pending_id, client_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Pending upload not found or expired")
    diff_summary = (row[0] or {})
    skipped = diff_summary.get("skipped_rows") or []
    provenance_kind = diff_summary.get("provenance_kind", "registered")

    # Resolve included skipped rows from the form. The preview template
    # uses `skipped[<idx>][<field>]` and `include_skipped[]=<idx>` names.
    included_idx = {
        int(v) for v in form.getlist("include_skipped[]") if str(v).isdigit()
    }
    included_skipped = []
    for idx in sorted(included_idx):
        if idx >= len(skipped):
            continue
        original = skipped[idx]
        merged = dict(original.get("raw") or {})
        # Apply staff-edited values for this row.
        for k in list(form.keys()):
            prefix = f"skipped[{idx}]["
            if k.startswith(prefix) and k.endswith("]"):
                fname = k[len(prefix):-1]
                v = (form.get(k) or "").strip()
                if v:
                    merged[fname] = v
        # Validate identifier rule for this promoted row.
        cc = merged.get("customs_code") or ""
        ic = merged.get("internal_code") or ""
        if not cc and ic:
            cc = ic
            merged["customs_code"] = ic
        if not cc and not ic:
            # Staff tried to include a row that still lacks an identifier.
            # Surface a 400 so they can go back and fill it.
            raise HTTPException(
                400,
                "Có dòng skipped được Include nhưng vẫn chưa có "
                "customs_code / internal_code. Hãy điền giá trị inline trước.",
            )
        # Build a row in the same shape as parsed_rows (the parser output).
        promoted = {
            "customs_code": cc,
            "internal_code": ic or cc,
            "name": merged.get("name"),
            "category": merged.get("category") or "nvl",
            "unit": merged.get("unit"),
            "hs_code": merged.get("hs_code"),
            "status": merged.get("status") or "active",
            "_promoted_from_skipped": True,
            "_skip_reason": original.get("reason"),
        }
        included_skipped.append(promoted)

    n = confirm_pending(
        client_id=client_id, pending_id=pending_id, user_id=user.user_id,
        cfg=CATALOG_CFG,
        included_skipped=included_skipped,
        ingest_extra={"provenance_kind": provenance_kind},
    )
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog?ingested={n}", status_code=303,
    )


@router.post("/clients/{client_id}/catalog/preview/{pending_id}/reject")
async def preview_reject(request: Request, client_id: str, pending_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    reject_pending(
        client_id=client_id, pending_id=pending_id, user_id=user.user_id,
        cfg=CATALOG_CFG,
    )
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog?rejected=1", status_code=303,
    )


# ── Internals ────────────────────────────────────────────────────────────

CATALOG_SORT_WHITELIST = {
    "customs_code": "m.material_code",
    "internal_code": "m.material_code",
    "name": "m.name",
    "category": "m.category",
    "updated_at": "m.updated_at",
}
CATALOG_SORT_DEFAULT = ("customs_code", "asc")


def _catalog_where_clause(*, client_id: str, category: str | None,
                          q: str | None, provenance: str | None,
                          status: str | None = None,
                          ) -> tuple[str, list]:
    sql = "where m.client_id = %s"
    params: list = [client_id]
    if category:
        sql += " and m.category = %s"
        params.append(category)
    if status:
        sql += " and m.status = %s"
        params.append(status)
    # Provenance filter — post-mig-042 maps to source enum + hq_registered.
    # Legacy values (registered/unregistered/user_added) accepted for
    # backward compat in URL params; translated to new schema.
    if provenance == "registered":
        sql += " and m.hq_registered = true"
    elif provenance == "unregistered":
        sql += " and m.source = 'bcct_observed' and (m.hq_registered is null or m.hq_registered = false)"
    elif provenance == "user_added":
        sql += " and m.source = 'client_declared'"
    if q:
        sql += (" and (m.material_code ilike %s "
                "or m.name ilike %s or m.hs_code ilike %s)")
        like = f"%{q}%"
        params.extend([like, like, like])
    return sql, params


def _query_materials(*, client_id: str, category: str | None,
                     q: str | None, provenance: str | None = None,
                     status: str | None = None,
                     order_by: str = "m.material_code asc",
                     limit: int = 50, offset: int = 0) -> list[dict]:
    """Query catalog rows with provenance signals annotated.

    `provenance` filter values:
      - 'registered'     → only rows with registered_with_hq
      - 'unregistered'   → seen_in_bcct but NOT registered_with_hq (audit case)
      - 'user_added'     → user_added present
    """
    where, params = _catalog_where_clause(
        client_id=client_id, category=category, q=q, provenance=provenance,
        status=status,
    )
    # Catalog roles refactor (mig 033): inline subqueries for has_imports/
    # has_exports/has_own_bom + Python-side is_multi_role replaced with
    # JOIN to hub.v_material_roles. is_dual_source kept as Python heuristic
    # per D11 (auto-detection badge, distinct from operator-confirmed
    # btp_sourcing dropdown).
    sql = f"""
        select m.material_code, m.name, m.category, m.category_override,
               m.status, m.unit, m.hs_code, m.updated_at, m.provenance,
               m.btp_sourcing, m.source, m.hq_registered, m.code_kind,
               m.promoted_to_declared_at, m.promoted_by,
               (m.hq_registered = true) as is_registered,
               (m.source = 'bcct_observed') as is_seen_in_bcct,
               (m.source = 'client_declared') as is_user_added,
               coalesce(vmr.has_imports, false) as has_imports,
               coalesce(vmr.has_exports, false) as has_exports,
               coalesce(vmr.is_consumed_in_bom, false) as is_consumed_in_bom,
               coalesce(vmr.has_own_bom, false) as has_own_bom,
               coalesce(vmr.observed_roles, '{{}}'::text[]) as observed_roles,
               coalesce(vmr.is_multi_role, false) as is_multi_role,
               coalesce(vmr.declared_observed_conflict, false) as declared_observed_conflict,
               coalesce(vmr.observed_count, 0) as observed_count,
               vmr.observed_first_at, vmr.observed_last_at,
               coalesce(vmr.observed_directions, '{{}}'::text[]) as observed_directions
        from hub.materials m
        left join hub.v_material_roles vmr
               on vmr.client_id = m.client_id
              and vmr.material_code = m.material_code
        {where}
        order by {order_by}
        limit %s offset %s
    """
    params = [*params, limit, offset]
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            for r in rows:
                if r.get("observed_roles") is None:
                    r["observed_roles"] = []
                # is_dual_source: derive from observed_roles having btp_nm.
                # Mig 046 added btp_nm to observed_roles when has_imports +
                # has_own_bom + is_consumed_in_bom = dual-source pattern.
                # btp_sourcing dropdown is the staff confirmation; if
                # confirmed value contradicts observed (e.g. observed dual
                # but staff says self_produced_only) → sourcing_conflict.
                roles = r.get("observed_roles") or []
                r["is_dual_source"] = "btp_nm" in roles
                # Sourcing-confirmation conflict (staff vs observed):
                src = r.get("btp_sourcing") or "unknown"
                if r["is_dual_source"]:
                    suggested = "dual_source"
                elif "btp_sx" in roles and "btp_nm" not in roles:
                    suggested = "self_produced_only"
                else:
                    suggested = None
                r["suggested_sourcing"] = suggested
                r["sourcing_conflict"] = bool(
                    suggested and src not in ("unknown", "", None)
                    and src != suggested
                )
            return rows


def _count_materials(*, client_id: str, category: str | None,
                     q: str | None, provenance: str | None,
                     status: str | None = None) -> int:
    where, params = _catalog_where_clause(
        client_id=client_id, category=category, q=q, provenance=provenance,
        status=status,
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"select count(*) from hub.materials m {where}", params)
            (n,) = cur.fetchone()
    return n


def _provenance_counts(client_id: str) -> dict:
    """Counts per provenance facet — drives the filter chip badges and
    the 'X codes seen on declaration but not registered' audit alarm."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                  count(*) as total,
                  count(*) filter (where provenance ? 'registered_with_hq') as registered,
                  count(*) filter (
                    where provenance ? 'seen_in_bcct'
                      and not provenance ? 'registered_with_hq') as unregistered,
                  count(*) filter (where provenance ? 'user_added') as user_added
                from hub.materials where client_id = %s
                """,
                (client_id,),
            )
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, cur.fetchone()))


def _category_counts(client_id: str) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select category, count(*) from hub.materials where client_id = %s group by category",
                (client_id,),
            )
            return dict(cur.fetchall())


def _insert_materials_with_cursor(cur, *, client_id: str, rows: list[dict],
                                  upload_id: str | None = None,
                                  provenance_kind: str = "registered") -> int:
    """Insert materials on a shared cursor (for transactional confirm flow).

    `provenance_kind`:
      - 'registered' (default): mark every row as registered_with_hq.
        Use when staff confirmed the file is the official Danh Mục
        (registered with customs).
      - 'user_added': mark rows as user_added — internal catalog without
        HQ status. Existing registered_with_hq is preserved.

    `upload_id` (when set) is recorded inside the provenance jsonb so
    staff can trace any catalog row back to the upload that wrote it.
    """
    if provenance_kind == "registered":
        prov_sql = (
            "jsonb_build_object('registered_with_hq', "
            "jsonb_build_object('first_seen', to_char(now(), 'YYYY-MM-DD'), "
            "'source_upload_id', %s::text))"
        )
    elif provenance_kind == "user_added":
        prov_sql = (
            "jsonb_build_object('user_added', "
            "jsonb_build_object('first_seen', to_char(now(), 'YYYY-MM-DD'), "
            "'source_upload_id', %s::text))"
        )
    else:
        raise ValueError(f"unknown provenance_kind: {provenance_kind}")

    # Mig 042: dropped materials.internal_code; renamed customs_code → material_code.
    # provenance jsonb still used for audit detail (registered_with_hq, btp_inferred);
    # primary signals moved to source/hq_registered columns.
    sql = f"""
        insert into hub.materials
          (client_id, material_code, name, category, status,
           unit, hs_code, provenance, source)
        values (%s, %s, %s, %s, %s, %s, %s, {prov_sql}, %s)
        on conflict (client_id, material_code) do update set
          name = excluded.name,
          category = excluded.category,
          status = excluded.status,
          unit = excluded.unit,
          hs_code = excluded.hs_code,
          provenance = hub.materials.provenance || excluded.provenance,
          updated_at = now()
    """
    # New rows from agency Excel upload → source='client_declared'.
    # Existing rows keep their existing source on conflict (above).
    source_value = "client_declared"
    n = 0
    for r in rows:
        # legacy r["customs_code"] / r["internal_code"] supported (uploads
        # parse from Excel using legacy header names); use customs_code as
        # the material_code, ignore internal_code.
        material_code = r.get("material_code") or r["customs_code"]
        cur.execute(
            sql,
            (client_id, material_code, r.get("name"),
             r["category"], r.get("status", "active"), r.get("unit"), r.get("hs_code"),
             upload_id, source_value),
        )
        n += 1
    return n


def _insert_materials(*, client_id: str, rows: list[dict]) -> int:
    """Standalone insert with a fresh connection (used by seed)."""
    with connect() as conn:
        with conn.cursor() as cur:
            return _insert_materials_with_cursor(cur, client_id=client_id, rows=rows)


_BTP_SOURCING_VALUES = {
    "purchased_only", "self_produced_only", "dual_source", "unknown",
}


@router.get("/clients/{client_id}/catalog/{material_code:path}/edit",
            response_class=HTMLResponse)
async def edit_material_form(request: Request, client_id: str, material_code: str):
    """Form to edit a single material row. Permission via can_edit_client
    (already configurable per-role: dev/admin always; manager if managed;
    staff iff scope='edit')."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select material_code, name, category, status, code_kind, "
            "       uom, production_source, supplier_hint, hq_registered, "
            "       source "
            "from hub.materials where client_id=%s and material_code=%s",
            (client_id, material_code),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "material not found")
        cols = [d[0] for d in cur.description]
        material = dict(zip(cols, row))
    return request.app.state.templates.TemplateResponse(
        request, "clients/catalog_material_edit.html",
        {
            "client": client, "material": material,
            "categories": CATEGORIES,
            "production_sources": ["nk", "sx", "mixed", "unknown"],
            "active_root": "clients", "active_tab": "catalog",
        },
    )


@router.post("/clients/{client_id}/catalog/{material_code:path}/edit")
async def edit_material_submit(
    request: Request, client_id: str, material_code: str,
    name: str = Form(...),
    category: str = Form(...),
    status: str = Form(...),
    uom: str = Form(""),
    production_source: str = Form(""),
    supplier_hint: str = Form(""),
    hq_registered: str = Form(""),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if category not in CATEGORIES:
        raise HTTPException(400, f"invalid category: {category!r}")
    if status not in {"active", "under_review", "deprecated", "tombstoned"}:
        raise HTTPException(400, f"invalid status: {status!r}")
    if production_source and production_source not in {"nk", "sx", "mixed", "unknown"}:
        raise HTTPException(400, f"invalid production_source: {production_source!r}")
    with connect(user_id=user.user_id) as conn, conn.cursor() as cur:
        cur.execute(
            """
            update hub.materials
               set name = %s, category = %s, status = %s,
                   uom = %s, production_source = %s, supplier_hint = %s,
                   hq_registered = %s, updated_at = now()
             where client_id = %s and material_code = %s
            """,
            (name.strip(), category, status,
             uom.strip() or None,
             production_source.strip() or None,
             supplier_hint.strip() or None,
             hq_registered == "on",
             client_id, material_code),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "material not found")
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog/{material_code}/detail?edited=1",
        status_code=303,
    )


@router.post("/clients/{client_id}/catalog/{material_code:path}/promote")
async def promote_material(request: Request, client_id: str, material_code: str):
    """Mig 042: promote a `bcct_observed` / `under_review` material to
    `client_declared` / `active`. Sets promoted_to_declared_at + promoted_by
    audit trail."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    with connect(user_id=user.user_id) as conn, conn.cursor() as cur:
        cur.execute(
            """
            update hub.materials
               set source = 'client_declared',
                   status = 'active',
                   promoted_to_declared_at = now(),
                   promoted_by = %s,
                   updated_at = now()
             where client_id = %s and material_code = %s
               and status = 'under_review'
            """,
            (user.email, client_id, material_code),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "material not under_review or not found")
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog?status=under_review",
        status_code=303,
    )


@router.get("/clients/{client_id}/catalog/{material_code:path}/detail",
            response_class=HTMLResponse)
async def catalog_detail(request: Request, client_id: str, material_code: str):
    """Detail page for a single material — full state + observation stats from
    v_material_roles + audit history from material_audit_events."""
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select m.*,
                   coalesce(vmr.has_imports, false) as has_imports,
                   coalesce(vmr.has_exports, false) as has_exports,
                   coalesce(vmr.has_nvl_import, false) as has_nvl_import,
                   coalesce(vmr.is_consumed_in_bom, false) as is_consumed_in_bom,
                   coalesce(vmr.has_own_bom, false) as has_own_bom,
                   coalesce(vmr.observed_roles, '{}'::text[]) as observed_roles,
                   coalesce(vmr.is_multi_role, false) as is_multi_role,
                   coalesce(vmr.declared_observed_conflict, false) as declared_observed_conflict,
                   coalesce(vmr.observed_count, 0) as observed_count,
                   vmr.observed_first_at, vmr.observed_last_at,
                   coalesce(vmr.observed_directions, '{}'::text[]) as observed_directions
            from hub.materials m
            left join hub.v_material_roles vmr
                   on vmr.client_id = m.client_id and vmr.material_code = m.material_code
            where m.client_id = %s and m.material_code = %s
            """,
            (client_id, material_code),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "material not found")
        cols = [d[0] for d in cur.description]
        material = dict(zip(cols, row))

        # Audit history (mig 045 will populate via trigger; for now empty
        # is OK — table exists, no rows yet for non-trigger-tracked materials).
        cur.execute(
            """
            select event_type, actor, payload, occurred_at
            from hub.material_audit_events
            where client_id = %s and material_code = %s
            order by occurred_at desc
            limit 100
            """,
            (client_id, material_code),
        )
        audit_cols = [d[0] for d in cur.description]
        audit_events = [dict(zip(audit_cols, r)) for r in cur.fetchall()]

        # BCCT references (sample 20 most recent rows where this code appears
        # as customs_code OR is parsed-extractable from goods_name)
        cur.execute(
            """
            select transaction_key, line_no, declaration_no, registration_date,
                   direction, declaration_type, customs_code, goods_name,
                   total_value_nt, currency_nt
            from hub.bcct_rows
            where client_id = %s
              and (customs_code = %s
                   or goods_name like %s)
            order by registration_date desc nulls last
            limit 20
            """,
            (client_id, material_code, f"%({material_code})%"),
        )
        bcct_cols = [d[0] for d in cur.description]
        bcct_rows = [dict(zip(bcct_cols, r)) for r in cur.fetchall()]

        # BOM artifacts where this code appears (as product or as edge member)
        cur.execute(
            """
            select distinct a.artifact_id, a.product_code, a.artifact_no,
                   a.flatten_status, a.flatten_strategy, a.created_at
            from hub.bom_artifacts a
            where a.client_id = %s
              and (a.product_code = %s
                   or exists (
                     select 1 from hub.bom_edges e
                     where e.artifact_id = a.artifact_id
                       and (e.parent_code = %s or e.child_code = %s)
                   ))
              and a.tombstoned_at is null
            order by a.created_at desc
            limit 20
            """,
            (client_id, material_code, material_code, material_code),
        )
        bom_cols = [d[0] for d in cur.description]
        bom_artifacts = [dict(zip(bom_cols, r)) for r in cur.fetchall()]

    from app.stores.catalog_warnings import compute_warnings
    from app.stores.catalog_audit import audit_diff
    warnings = compute_warnings(client_id, material_code)
    for ev in audit_events:
        ev["diff"] = audit_diff(ev["event_type"], ev["payload"])

    # Supplement v_material_roles when it returns 0 observations but BCCT
    # actually references this material via paren-extract (Growatt-shape).
    # Generic fix via per-client parser_rules — see material_observations.py.
    if material.get("observed_count", 0) == 0:
        from app.stores.material_observations import compute_observations
        obs = compute_observations(client_id, material_code)
        if obs.observed_count > 0:
            material["has_imports"] = obs.has_imports
            material["has_exports"] = obs.has_exports
            material["observed_count"] = obs.observed_count
            material["observed_first_at"] = obs.observed_first_at
            material["observed_last_at"] = obs.observed_last_at
            material["observed_directions"] = obs.observed_directions

    # code_mappings panel: full NB↔HQ relationships for this material.
    with connect() as conn, conn.cursor() as cur:
        # Cases: this material as NB → which HQ codes; as HQ → which NB codes.
        # When this material's code appears as `internal_code` → it plays the
        # NB role; the paired `customs_code` is the HQ counterpart. Tag 'as_nb'.
        # When it appears as `customs_code` → it plays the HQ role; paired
        # `internal_code` is the NB counterpart. Tag 'as_hq'.
        cur.execute(
            "select customs_code as paired_code, 'as_nb' as direction "
            "from hub.code_mappings "
            "where client_id=%s and internal_code=%s "
            "union all "
            "select internal_code as paired_code, 'as_hq' as direction "
            "from hub.code_mappings "
            "where client_id=%s and customs_code=%s "
            "order by direction, paired_code",
            (client_id, material_code, client_id, material_code),
        )
        mappings = [{"paired_code": p, "direction": d}
                    for p, d in cur.fetchall()]
    # Group by direction for the template.
    mapping_panel = {
        "as_nb": [m for m in mappings if m["direction"] == "as_nb"],
        "as_hq": [m for m in mappings if m["direction"] == "as_hq"],
    }
    # Strip dups (same string appearing both sides = self-loop).
    self_loop_count = sum(
        1 for m in mappings if m["paired_code"] == material_code
    )

    from app.stores.catalog_bcct_analysis import analyze_material_bcct
    bcct_analysis = analyze_material_bcct(
        client_id=client_id, material_code=material_code,
    )

    from app.stores.material_substitutes import list_for_material as list_subs
    substitutes_active = list_subs(
        client_id=client_id, material_code=material_code,
        min_score=0.0, include_rejected=False, limit=20,
    )
    substitutes_rejected = list_subs(
        client_id=client_id, material_code=material_code,
        min_score=0.0, include_rejected=True, limit=50,
    )
    # Filter to ONLY rejected (since include_rejected returns both)
    rejected_codes = {
        c.material_b_code for c in substitutes_rejected
    } - {c.material_b_code for c in substitutes_active}
    substitutes_rejected = [
        c for c in substitutes_rejected if c.material_b_code in rejected_codes
    ]

    return request.app.state.templates.TemplateResponse(
        request, "clients/catalog_detail.html",
        {"client": client, "material": material,
         "audit_events": audit_events, "bcct_rows": bcct_rows,
         "bcct_analysis": bcct_analysis,
         "substitutes_active": substitutes_active,
         "substitutes_rejected": substitutes_rejected,
         "bom_artifacts": bom_artifacts,
         "warnings": warnings,
         "mapping_panel": mapping_panel,
         "self_loop_mapping": self_loop_count > 0,
         "categories": CATEGORIES,
         "production_sources": ["nk", "sx", "mixed", "unknown"],
         "active_root": "clients", "active_tab": "catalog"},
    )


@router.post("/clients/{client_id}/catalog/{material_code:path}/tombstone")
async def tombstone_material(request: Request, client_id: str, material_code: str):
    """Mig 042: tombstone a material (lifecycle, never DELETE)."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    with connect(user_id=user.user_id) as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set status='tombstoned', updated_at=now() "
            "where client_id=%s and material_code=%s",
            (client_id, material_code),
        )
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog", status_code=303,
    )


@router.post("/clients/{client_id}/catalog/{material_code:path}/btp_sourcing")
async def set_btp_sourcing(request: Request, client_id: str, material_code: str,
                            btp_sourcing: str = Form(...)):
    """Staff override of materials.btp_sourcing for one BTP material.

    Phase 3a — last-write-wins. Future: respect a separate
    `btp_sourcing_overridden_at` flag so classifier reruns don't
    overwrite manual overrides (BACKLOG)."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if btp_sourcing not in _BTP_SOURCING_VALUES:
        raise HTTPException(400, f"invalid btp_sourcing: {btp_sourcing!r}")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select category from hub.materials "
            "where client_id=%s and material_code=%s",
            (client_id, material_code),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "material not found")
        if row[0] != "btp_sx":
            raise HTTPException(400, "btp_sourcing only applies to btp_sx materials")
        cur.execute(
            "update hub.materials set btp_sourcing=%s "
            "where client_id=%s and material_code=%s",
            (btp_sourcing, client_id, material_code),
        )
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog?category=btp_sx",
        status_code=303,
    )
