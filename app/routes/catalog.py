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
    order_by = sort.sql_clause(tiebreakers=("m.customs_code",)) \
        if sort.column != "customs_code" else sort.sql_clause()
    items = _query_materials(
        client_id=client_id, category=category, q=q,
        provenance=provenance,
        order_by=order_by,
        limit=page_params.page_size, offset=page_params.offset,
    )
    total = _count_materials(
        client_id=client_id, category=category, q=q, provenance=provenance,
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
    "customs_code": "m.customs_code",
    "internal_code": "m.internal_code",
    "name": "m.name",
    "category": "m.category",
    "updated_at": "m.updated_at",
}
CATALOG_SORT_DEFAULT = ("customs_code", "asc")


def _catalog_where_clause(*, client_id: str, category: str | None,
                          q: str | None, provenance: str | None
                          ) -> tuple[str, list]:
    sql = "where m.client_id = %s"
    params: list = [client_id]
    if category:
        sql += " and m.category = %s"
        params.append(category)
    if provenance == "registered":
        sql += " and (m.provenance ? 'registered_with_hq')"
    elif provenance == "unregistered":
        sql += (" and (m.provenance ? 'seen_in_bcct')"
                " and not (m.provenance ? 'registered_with_hq')")
    elif provenance == "user_added":
        sql += " and (m.provenance ? 'user_added')"
    if q:
        sql += (" and (m.customs_code ilike %s or m.internal_code ilike %s "
                "or m.name ilike %s or m.hs_code ilike %s)")
        like = f"%{q}%"
        params.extend([like, like, like, like])
    return sql, params


def _query_materials(*, client_id: str, category: str | None,
                     q: str | None, provenance: str | None = None,
                     order_by: str = "m.customs_code asc",
                     limit: int = 50, offset: int = 0) -> list[dict]:
    """Query catalog rows with provenance signals annotated.

    `provenance` filter values:
      - 'registered'     → only rows with registered_with_hq
      - 'unregistered'   → seen_in_bcct but NOT registered_with_hq (audit case)
      - 'user_added'     → user_added present
    """
    where, params = _catalog_where_clause(
        client_id=client_id, category=category, q=q, provenance=provenance,
    )
    sql = f"""
        select m.customs_code, m.internal_code, m.name, m.category, m.category_override,
               m.status, m.unit, m.hs_code, m.updated_at, m.provenance,
               m.btp_sourcing,
               (m.provenance ? 'registered_with_hq') as is_registered,
               (m.provenance ? 'seen_in_bcct') as is_seen_in_bcct,
               (m.provenance ? 'user_added') as is_user_added,
               exists (
                 select 1 from hub.bcct_rows b
                 where b.client_id = m.client_id
                   and b.customs_code = m.customs_code
                   and b.direction = 'import'
               ) as has_imports,
               exists (
                 select 1 from hub.bcct_rows b
                 where b.client_id = m.client_id
                   and b.customs_code = m.customs_code
                   and b.direction = 'export'
               ) as has_exports,
               exists (
                 select 1 from hub.bom_artifacts v
                 where v.client_id = m.client_id
                   and v.product_code = m.customs_code
                   and v.tombstoned_at is null
                   and v.status = 'published'
               ) as has_bom
        from hub.materials m
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
                r["is_dual_source"] = bool(r.get("has_imports") and r.get("has_bom"))
                # Multi-role: btp_sx that's also exported as a finished
                # good (rework / cải chế per project_bom_code_multirole memory).
                r["is_multi_role"] = bool(
                    r.get("category") == "btp_sx" and r.get("has_exports")
                )
            return rows


def _count_materials(*, client_id: str, category: str | None,
                     q: str | None, provenance: str | None) -> int:
    where, params = _catalog_where_clause(
        client_id=client_id, category=category, q=q, provenance=provenance,
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

    sql = f"""
        insert into hub.materials
          (client_id, customs_code, internal_code, name, category, status,
           unit, hs_code, provenance)
        values (%s, %s, %s, %s, %s, %s, %s, %s, {prov_sql})
        on conflict (client_id, customs_code) do update set
          internal_code = excluded.internal_code,
          name = excluded.name,
          category = excluded.category,
          status = excluded.status,
          unit = excluded.unit,
          hs_code = excluded.hs_code,
          -- Merge: only the chosen key overwrites; other keys
          -- (seen_in_bcct, the other of registered_with_hq/user_added)
          -- are preserved.
          provenance = hub.materials.provenance || excluded.provenance,
          updated_at = now()
    """
    n = 0
    for r in rows:
        cur.execute(
            sql,
            (client_id, r["customs_code"], r.get("internal_code"), r.get("name"),
             r["category"], r.get("status", "active"), r.get("unit"), r.get("hs_code"),
             upload_id),
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


@router.post("/clients/{client_id}/catalog/{customs_code:path}/btp_sourcing")
async def set_btp_sourcing(request: Request, client_id: str, customs_code: str,
                            btp_sourcing: str = Form(...)):
    """Staff override of materials.btp_sourcing for one BTP material.

    Phase 3a — last-write-wins. Future: respect a separate
    `btp_sourcing_overridden_at` flag so classifier reruns don't
    overwrite manual overrides (BACKLOG)."""
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    if btp_sourcing not in _BTP_SOURCING_VALUES:
        raise HTTPException(400, f"invalid btp_sourcing: {btp_sourcing!r}")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select category from hub.materials "
            "where client_id=%s and customs_code=%s",
            (client_id, customs_code),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "material not found")
        if row[0] != "btp_sx":
            raise HTTPException(400, "btp_sourcing only applies to btp_sx materials")
        cur.execute(
            "update hub.materials set btp_sourcing=%s "
            "where client_id=%s and customs_code=%s",
            (btp_sourcing, client_id, customs_code),
        )
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog?category=btp_sx",
        status_code=303,
    )
