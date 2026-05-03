"""Code mappings (BQD = Bảng Quy Đổi) — nested under /clients/{client_id}/.

Slice 2 of the unified upload flow. BQD now uses `_mapping_flow` shared
helpers, same shape as catalog (slice 1). BQD requires BOTH
`internal_code` AND `customs_code` mapped — handled via
`required_mapped_fields` on `ModuleConfig`.
"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect
from app.parsers.code_mappings import (
    LOGICAL_FIELDS,
    MIN_IDENTIFIER_FIELDS,
    REQUIRED_MAPPED_FIELDS,
    CodeMappingsParseError,
    parse_code_mappings_workbook,
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


# ── ModuleConfig ─────────────────────────────────────────────────────────

def _summarize_bqd(parsed_rows: list[dict]) -> dict:
    """Counts for the preview header strip — total + per-category breakdown."""
    by_cat: dict[str, int] = {}
    distinct_internal: set[str] = set()
    distinct_customs: set[str] = set()
    for r in parsed_rows:
        cat = r.get("category") or "—"
        by_cat[cat] = by_cat.get(cat, 0) + 1
        distinct_internal.add(r["internal_code"])
        distinct_customs.add(r["customs_code"])
    return {
        "total": len(parsed_rows),
        "by_category": by_cat,
        "n_distinct_internal": len(distinct_internal),
        "n_distinct_customs": len(distinct_customs),
        "n_one_to_many": sum(
            1 for ic in distinct_internal
            if sum(1 for r in parsed_rows if r["internal_code"] == ic) > 1
        ),
    }


def _ingest_bqd(
    cur, *, client_id: str, rows: list[dict], upload_id: str | None = None,
    **_kw,
) -> int:
    return _insert_mappings_with_cursor(cur, client_id=client_id, rows=rows)


BQD_CFG = ModuleConfig(
    name="bqd",
    upload_pending_module="bqd",
    save_upload_module="code_mappings",
    fallback_filename="bqd.xlsx",
    list_route=lambda cid: f"/clients/{cid}/bqd",
    preview_template="clients/bqd_preview.html",
    parser_fn=parse_code_mappings_workbook,
    parser_error=CodeMappingsParseError,
    summarize_fn=_summarize_bqd,
    ingest_fn=_ingest_bqd,
    logical_fields=LOGICAL_FIELDS,
    min_identifier_fields=MIN_IDENTIFIER_FIELDS,
    required_mapped_fields=REQUIRED_MAPPED_FIELDS,
)


# ── List + upload landing ────────────────────────────────────────────────

@router.get("/clients/{client_id}/bqd", response_class=HTMLResponse)
async def list_view(request: Request, client_id: str, q: str | None = None):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    page_params = parse_page_params(query_params=request.query_params)
    sort = SortSpec.from_params(
        query_params=request.query_params,
        whitelist=BQD_SORT_WHITELIST, default=BQD_SORT_DEFAULT,
    )
    order_by = sort.sql_clause(tiebreakers=("customs_code",)) \
        if sort.column != "customs_code" else sort.sql_clause()
    items = _list_mappings(
        client_id, q,
        order_by=order_by,
        limit=page_params.page_size, offset=page_params.offset,
    )
    total = _count_mappings(client_id, q)
    stats_basic = _mapping_stats(client_id)
    paging_ctx = pagination_context(
        request=request, page_params=page_params, total=total,
    )

    def _sort_link(col: str) -> str:
        return sort_link(request=request, column=col, current_sort=sort)
    return request.app.state.templates.TemplateResponse(
        request, "clients/bqd.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "items": items, "q": q or "",
            "mapping_stats": stats_basic,
            "paging": paging_ctx, "sort": sort, "sort_link": _sort_link,
            "freshness": freshness_for_template(request, client_id, "bqd"),
            "active_root": "clients", "active_tab": "bqd",
        },
    )


@router.get("/clients/{client_id}/bqd/upload", response_class=HTMLResponse)
async def upload_view(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/bqd_upload.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "active_root": "clients", "active_tab": "bqd",
        },
    )


# ── Upload submit ────────────────────────────────────────────────────────

@router.post("/clients/{client_id}/bqd/upload")
async def upload_submit(
    request: Request, client_id: str,
    file: UploadFile = File(...),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    blob = await file.read()
    sha = sha256_bytes(blob)
    stored = save_upload(blob, filename=file.filename or BQD_CFG.fallback_filename,
                         module=BQD_CFG.save_upload_module, client_id=client_id)
    upload_id = record_upload(
        client_id=client_id, module=BQD_CFG.save_upload_module,
        original_filename=file.filename or BQD_CFG.fallback_filename,
        stored_path=stored.path, content_sha256=sha, size_bytes=len(blob),
        mime_type=file.content_type, uploader_user_id=user.user_id,
    )
    redirect_url, _, _mode = upload_initial_dispatch(
        client_id=client_id, blob=blob, upload_id=upload_id, cfg=BQD_CFG,
    )
    return RedirectResponse(url=redirect_url, status_code=303)


# ── Mapping page ─────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/bqd/upload/mapping/{upload_id}",
            response_class=HTMLResponse)
async def mapping_view(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    ctx = render_mapping_page_context(
        client_id=client_id, upload_id=upload_id, cfg=BQD_CFG,
    )
    ctx.update({
        "client": client, "stats": stats_for_client(client_id),
        "module_label": "BQD",
        "active_root": "clients", "active_tab": "bqd",
    })
    return request.app.state.templates.TemplateResponse(
        request, "clients/_upload_mapping.html", ctx,
    )


@router.post("/clients/{client_id}/bqd/upload/mapping/{upload_id}/llm_suggest",
             response_class=HTMLResponse)
async def mapping_llm_suggest(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    ctx = render_mapping_page_with_llm_suggestion(
        client_id=client_id, upload_id=upload_id, cfg=BQD_CFG,
    )
    ctx.update({
        "client": client, "stats": stats_for_client(client_id),
        "module_label": "BQD",
        "active_root": "clients", "active_tab": "bqd",
    })
    return request.app.state.templates.TemplateResponse(
        request, "clients/_upload_mapping.html", ctx,
    )


@router.post("/clients/{client_id}/bqd/upload/mapping/{upload_id}/parse")
async def mapping_parse(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    form = await request.form()

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

    pending_id = parse_with_overrides_and_stash(
        client_id=client_id, upload_id=upload_id, user_id=user.user_id,
        column_map=column_map,
        header_row_override=header_row_override,
        extra_required_fields=extra_required,
        proposed_by="manual",
        cfg=BQD_CFG,
    )
    return RedirectResponse(
        url=f"/clients/{client_id}/bqd/preview/{pending_id}",
        status_code=303,
    )


# ── Preview ──────────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/bqd/preview/{pending_id}",
            response_class=HTMLResponse)
async def preview_view(request: Request, client_id: str, pending_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    ctx = render_preview_context(
        client_id=client_id, pending_id=pending_id, cfg=BQD_CFG,
    )
    ctx.update({
        "client": client, "stats": stats_for_client(client_id),
        "module_label": "BQD",
        "list_url": f"/clients/{client_id}/bqd",
        "active_root": "clients", "active_tab": "bqd",
    })
    return request.app.state.templates.TemplateResponse(
        request, "clients/bqd_preview.html", ctx,
    )


@router.post("/clients/{client_id}/bqd/preview/{pending_id}/confirm")
async def preview_confirm(request: Request, client_id: str, pending_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    form = await request.form()

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select diff_summary from hub.upload_pending
                where pending_id = %s and client_id = %s and module = 'bqd'
                """,
                (pending_id, client_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Pending upload not found or expired")
    diff_summary = (row[0] or {})
    skipped = diff_summary.get("skipped_rows") or []

    included_idx = {
        int(v) for v in form.getlist("include_skipped[]") if str(v).isdigit()
    }
    included_skipped = []
    for idx in sorted(included_idx):
        if idx >= len(skipped):
            continue
        original = skipped[idx]
        merged = dict(original.get("raw") or {})
        for k in list(form.keys()):
            prefix = f"skipped[{idx}]["
            if k.startswith(prefix) and k.endswith("]"):
                fname = k[len(prefix):-1]
                v = (form.get(k) or "").strip()
                if v:
                    merged[fname] = v
        ic = (merged.get("internal_code") or "").strip()
        cc = (merged.get("customs_code") or "").strip()
        if not ic or not cc:
            raise HTTPException(
                400,
                "Có dòng skipped được Include nhưng vẫn chưa đủ "
                "internal_code + customs_code. Hãy điền cả hai trước.",
            )
        promoted = {
            "internal_code": ic,
            "customs_code": cc,
            "category": (merged.get("category") or "").lower() or None,
            "notes": merged.get("notes"),
            "_promoted_from_skipped": True,
            "_skip_reason": original.get("reason"),
        }
        included_skipped.append(promoted)

    n = confirm_pending(
        client_id=client_id, pending_id=pending_id, user_id=user.user_id,
        cfg=BQD_CFG,
        included_skipped=included_skipped,
    )
    return RedirectResponse(
        url=f"/clients/{client_id}/bqd?ingested={n}", status_code=303,
    )


@router.post("/clients/{client_id}/bqd/preview/{pending_id}/reject")
async def preview_reject(request: Request, client_id: str, pending_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    reject_pending(
        client_id=client_id, pending_id=pending_id, user_id=user.user_id,
        cfg=BQD_CFG,
    )
    return RedirectResponse(
        url=f"/clients/{client_id}/bqd?rejected=1", status_code=303,
    )


# ── Manual single-row add ────────────────────────────────────────────────

@router.post("/clients/{client_id}/bqd/manual")
async def manual_add(
    request: Request, client_id: str,
    internal_code: str = Form(...),
    customs_code: str = Form(...),
    category: str = Form(""),
    notes: str = Form(""),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    with connect() as conn:
        with conn.cursor() as cur:
            _insert_mappings_with_cursor(
                cur,
                client_id=client_id,
                rows=[{
                    "internal_code": internal_code.strip(),
                    "customs_code": customs_code.strip(),
                    "category": category.strip() or None,
                    "notes": notes.strip() or None,
                }],
            )
    return RedirectResponse(url=f"/clients/{client_id}/bqd", status_code=303)


# ── Internals ────────────────────────────────────────────────────────────

BQD_SORT_WHITELIST = {
    "internal_code": "internal_code",
    "customs_code": "customs_code",
    "created_at": "created_at",
}
BQD_SORT_DEFAULT = ("internal_code", "asc")


def _bqd_where_clause(client_id: str, q: str | None) -> tuple[str, list]:
    sql = "where client_id = %s"
    params: list = [client_id]
    if q:
        sql += " and (internal_code ilike %s or customs_code ilike %s)"
        like = f"%{q}%"
        params.extend([like, like])
    return sql, params


def _list_mappings(client_id: str, q: str | None = None, *,
                   order_by: str = "internal_code asc, customs_code",
                   limit: int = 50, offset: int = 0) -> list[dict]:
    where, params = _bqd_where_clause(client_id, q)
    sql = f"""
        select internal_code, customs_code, category, notes, created_at
        from hub.code_mappings
        {where}
        order by {order_by}
        limit %s offset %s
    """
    params = [*params, limit, offset]
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _count_mappings(client_id: str, q: str | None) -> int:
    where, params = _bqd_where_clause(client_id, q)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"select count(*) from hub.code_mappings {where}", params)
            (n,) = cur.fetchone()
    return n


def _mapping_stats(client_id: str) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select count(*) total,
                       count(distinct internal_code) n_internal,
                       count(distinct customs_code) n_customs
                from hub.code_mappings where client_id = %s
                """,
                (client_id,),
            )
            row = cur.fetchone()
            cur.execute(
                """
                select count(*) from (
                  select internal_code from hub.code_mappings
                  where client_id = %s group by internal_code having count(*) > 1
                ) t
                """,
                (client_id,),
            )
            (n_1n,) = cur.fetchone()
            return {"total": row[0], "n_internal": row[1], "n_customs": row[2], "n_1n": n_1n}


def _insert_mappings_with_cursor(cur, *, client_id: str, rows: list[dict]) -> int:
    """Insert mappings on a shared cursor (for transactional confirm flow)."""
    n = 0
    for r in rows:
        cur.execute(
            """
            insert into hub.code_mappings
              (client_id, internal_code, customs_code, category, notes)
            values (%s, %s, %s, %s, %s)
            on conflict (client_id, internal_code, customs_code) do update set
              category = excluded.category,
              notes = excluded.notes
            """,
            (client_id, r["internal_code"], r["customs_code"],
             r.get("category"), r.get("notes")),
        )
        n += 1
    return n


def _insert_mappings(*, client_id: str, rows: list[dict]) -> int:
    """Standalone insert with a fresh connection (used by seed)."""
    with connect() as conn:
        with conn.cursor() as cur:
            return _insert_mappings_with_cursor(cur, client_id=client_id, rows=rows)
