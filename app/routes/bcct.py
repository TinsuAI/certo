"""BCCT routes — nested under /clients/{client_id}/.

Slice 4 of the unified upload flow. BCCT now routes upload through the
shared mapping page (`_mapping_flow`) on cache miss; cache hit preserves
the inline rigid-parse path. The bespoke `parse-mapping` 2-stage UI
endpoints remain for backward compat but are unreachable from the new
flow — slated for deletion in slice 5 once the new path is validated.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect
from app.parsers._excel import compute_file_signature, header_row, load_xlsx
from app.parsers.bcct import (
    LOGICAL_FIELDS as BCCT_LOGICAL_FIELDS,
    MIN_IDENTIFIER_FIELDS as BCCT_MIN_IDENTIFIER,
    REQUIRED_MAPPED_FIELDS as BCCT_REQUIRED_MAPPED,
    parse_bcct_workbook,
    BcctParseError,
)
from app.parsers.derivations import compute_internal_code
from app.routes._mapping_flow import (
    ModuleConfig,
    _load_unmapped,
    render_mapping_page_context,
    render_mapping_page_with_llm_suggestion,
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


def _headers_per_sheet(blob: bytes) -> list[list[str]]:
    """Extract the best header row from each sheet for signature + LLM input."""
    wb = load_xlsx(blob)
    out: list[list[str]] = []
    for ws in wb.worksheets:
        hdr = header_row(ws, max_scan=20)
        if hdr:
            out.append([h for h in hdr[1] if h])
    return out


def _sample_rows_first_sheet(blob: bytes, n: int = 5) -> tuple[list[str], list[list]]:
    """Return (headers, first n data rows) of the first plausible sheet — used
    to brief the LLM."""
    wb = load_xlsx(blob)
    for ws in wb.worksheets:
        hdr = header_row(ws, max_scan=20)
        if not hdr:
            continue
        header_idx, headers = hdr
        rows: list[list] = []
        for raw in ws.iter_rows(min_row=header_idx + 1, values_only=True):
            if all(c is None or (isinstance(c, str) and not c.strip()) for c in raw):
                continue
            rows.append(list(raw))
            if len(rows) >= n:
                break
        return [h for h in headers if h], rows
    return [], []


def _lookup_cached_mapping(*, client_id: str, file_signature: str) -> dict | None:
    """Read-only lookup. `use_count` is incremented separately by
    `_record_mapping_use` only AFTER the cached mapping was actually
    used to parse successfully — otherwise the counter overcounts when
    cached mapping fails and the route falls back to rigid (or LLM)."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select mapping from hub.parser_mappings
                where client_id = %s and module = 'bcct' and file_signature = %s
                  and confirmed_at is not null
                """,
                (client_id, file_signature),
            )
            row = cur.fetchone()
            return row[0] if row else None


def _record_mapping_use(*, client_id: str, file_signature: str) -> None:
    """Bump usage counter after a cached mapping successfully parses."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.parser_mappings
                  set use_count = use_count + 1, last_used_at = now()
                where client_id = %s and module = 'bcct' and file_signature = %s
                """,
                (client_id, file_signature),
            )


@router.get("/clients/{client_id}/bcct", response_class=HTMLResponse)
async def list_view(request: Request, client_id: str,
                    year: int | None = None, direction: str | None = None,
                    q: str | None = None,
                    ingested: int | None = None,
                    new: int | None = None,
                    updated: int | None = None,
                    deleted: int | None = None,
                    noop: int | None = None,
                    skipped: int | None = None):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    page_params = parse_page_params(query_params=request.query_params)
    sort = SortSpec.from_params(
        query_params=request.query_params,
        whitelist=BCCT_SORT_WHITELIST, default=BCCT_SORT_DEFAULT,
    )
    order_by = sort.sql_clause(tiebreakers=BCCT_SORT_TIEBREAKERS)
    items = _list_bcct(
        client_id, year, direction, q,
        order_by=order_by,
        limit=page_params.page_size, offset=page_params.offset,
    )
    total = _count_bcct(client_id, year, direction, q)
    years = _years(client_id)
    upload_summary = None
    if ingested is not None:
        upload_summary = {
            "ingested": ingested or 0,
            "new": new or 0, "updated": updated or 0,
            "deleted": deleted or 0, "noop": noop or 0,
            "skipped": skipped or 0,
        }
    paging_ctx = pagination_context(
        request=request, page_params=page_params, total=total,
    )

    def _sort_link(col: str) -> str:
        return sort_link(request=request, column=col, current_sort=sort)
    return request.app.state.templates.TemplateResponse(
        request, "clients/bcct.html",
        {"client": client, "stats": stats_for_client(client_id),
         "items": items, "years": years,
         "year": year, "direction": direction, "q": q or "",
         "upload_summary": upload_summary,
         "paging": paging_ctx, "sort": sort, "sort_link": _sort_link,
         "freshness": freshness_for_template(request, client_id, "bcct"),
         "active_root": "clients", "active_tab": "bcct"},
    )


@router.get("/clients/{client_id}/bcct/upload", response_class=HTMLResponse)
async def upload_view(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/bcct_upload.html",
        {"client": client, "stats": stats_for_client(client_id),
         "active_root": "clients", "active_tab": "bcct"},
    )


@router.post("/clients/{client_id}/bcct/upload")
async def upload_submit(request: Request, client_id: str,
                        file: UploadFile = File(...)):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    blob = await file.read()
    sha = sha256_bytes(blob)
    stored = save_upload(blob, filename=file.filename or "bcct.xlsx",
                         module="bcct", client_id=client_id)
    upload_id = record_upload(
        client_id=client_id, module="bcct",
        original_filename=file.filename or "bcct.xlsx",
        stored_path=stored.path, content_sha256=sha, size_bytes=len(blob),
        mime_type=file.content_type, uploader_user_id=user.user_id,
    )

    # ── Step 1: cached parser_mapping for this client + file shape? ──
    file_signature = None
    cached_mapping = None
    try:
        sheets = _headers_per_sheet(blob)
        if sheets:
            file_signature = compute_file_signature(
                client_id=client_id, module="bcct",
                headers_per_sheet=sheets,
            )
            cached_mapping = _lookup_cached_mapping(
                client_id=client_id, file_signature=file_signature,
            )
    except Exception:  # noqa: BLE001 — best-effort; falls through to rigid
        pass

    # Slice 4: cache miss → unified mapping page (replaces old rigid → LLM
    # bespoke cascade). Cache hit still parses inline for the no-friction
    # repeat-upload case.
    if cached_mapping is None:
        from app.routes._mapping_flow import _stash_unmapped as _flow_stash_unmapped
        _flow_stash_unmapped(
            upload_id=upload_id, file_signature=file_signature, extra={},
        )
        return RedirectResponse(
            url=f"/clients/{client_id}/bcct/upload/mapping/{upload_id}",
            status_code=303,
        )

    # ── Step 2: cache hit → parse with cached mapping. ──
    rows: list[dict] | None = None
    try:
        rows = parse_bcct_workbook(blob, mapping_override=cached_mapping)
        _record_mapping_use(client_id=client_id, file_signature=file_signature)
    except BcctParseError as e:
        # Cached mapping went stale → fall through to mapping page.
        from app.routes._mapping_flow import _stash_unmapped as _flow_stash_unmapped
        _flow_stash_unmapped(
            upload_id=upload_id, file_signature=file_signature,
            extra={"stale_cache_error": str(e)},
        )
        return RedirectResponse(
            url=f"/clients/{client_id}/bcct/upload/mapping/{upload_id}",
            status_code=303,
        )

    # Stash request.state.user for downstream ingest/audit attribution.
    request.state.user = user
    return _ingest_rows(
        client_id=client_id, client=client,
        rows=rows, upload_id=upload_id, request=request,
    )


# ── Slice 4: mapping page endpoints ──────────────────────────────────────


def _bcct_parser_for_mapping(blob, *, mapping_override=None,
                              header_row_override=None,
                              extra_required_fields=None):
    """Adapter so `_mapping_flow.render_mapping_page_context` works for
    BCCT. The mapping page never actually parses (it just renders); this
    stub satisfies the cfg.parser_fn type."""
    return parse_bcct_workbook(
        blob, mapping_override=mapping_override,
        header_row_override=header_row_override,
        extra_required_fields=extra_required_fields,
        return_skipped=True,
    )


BCCT_MAPPING_CFG = ModuleConfig(
    name="bcct",
    upload_pending_module="bcct",
    save_upload_module="bcct",
    fallback_filename="bcct.xlsx",
    list_route=lambda cid: f"/clients/{cid}/bcct",
    preview_template="clients/bcct_upload_preview.html",
    parser_fn=_bcct_parser_for_mapping,
    parser_error=BcctParseError,
    summarize_fn=lambda _: {},   # not called via this cfg
    ingest_fn=lambda *a, **kw: 0,  # not called via this cfg
    logical_fields=BCCT_LOGICAL_FIELDS,
    min_identifier_fields=BCCT_MIN_IDENTIFIER,
    required_mapped_fields=BCCT_REQUIRED_MAPPED,
    extra_required_fields_default=(),
)


@router.get("/clients/{client_id}/bcct/upload/mapping/{upload_id}",
            response_class=HTMLResponse)
async def mapping_view(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    ctx = render_mapping_page_context(
        client_id=client_id, upload_id=upload_id, cfg=BCCT_MAPPING_CFG,
    )
    ctx.update({
        "client": client, "stats": stats_for_client(client_id),
        "module_label": "BCCT",
        "active_root": "clients", "active_tab": "bcct",
    })
    return request.app.state.templates.TemplateResponse(
        request, "clients/_upload_mapping.html", ctx,
    )


@router.post("/clients/{client_id}/bcct/upload/mapping/{upload_id}/llm_suggest",
             response_class=HTMLResponse)
async def mapping_llm_suggest(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    ctx = render_mapping_page_with_llm_suggestion(
        client_id=client_id, upload_id=upload_id, cfg=BCCT_MAPPING_CFG,
    )
    ctx.update({
        "client": client, "stats": stats_for_client(client_id),
        "module_label": "BCCT",
        "active_root": "clients", "active_tab": "bcct",
    })
    return request.app.state.templates.TemplateResponse(
        request, "clients/_upload_mapping.html", ctx,
    )


@router.post("/clients/{client_id}/bcct/upload/mapping/{upload_id}/parse")
async def mapping_parse(request: Request, client_id: str, upload_id: str):
    """Parse BCCT with staff-confirmed mapping, then route into the
    existing classify + preview pipeline (preserving confirm-on-update +
    diff-on-update + history insert semantics)."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    blob, file_signature, _extra = _load_unmapped(upload_id, module="bcct")
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

    mapped_logical = set(column_map.values())
    missing_mapped = BCCT_REQUIRED_MAPPED - mapped_logical
    if missing_mapped:
        raise HTTPException(
            400,
            "Thiếu mapping cho các trường bắt buộc: " +
            ", ".join(sorted(missing_mapped)),
        )

    header_row_override_str = (form.get("header_row_override") or "").strip()
    header_row_override = (
        int(header_row_override_str) if header_row_override_str.isdigit() else None
    )
    extra_required_str = (form.get("extra_required_fields") or "").strip()
    extra_required = (
        [s.strip() for s in extra_required_str.split(",") if s.strip()]
        if extra_required_str else None
    )

    try:
        rows, _skipped = parse_bcct_workbook(
            blob, mapping_override=column_map,
            header_row_override=header_row_override,
            extra_required_fields=extra_required,
            return_skipped=True,
        )
    except BcctParseError as e:
        raise HTTPException(400, f"Parse error: {e}") from e

    # Persist this confirmed mapping to the cache so the next upload of
    # the same shape skips the mapping page.
    try:
        if file_signature:
            with connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    insert into hub.parser_mappings
                      (client_id, module, file_signature, mapping, sample_headers,
                       proposed_by, confirmed_by, confirmed_at)
                    values (%s, 'bcct', %s, %s::jsonb, %s::jsonb,
                            'manual', %s, now())
                    on conflict (client_id, module, file_signature) do update set
                      mapping = excluded.mapping,
                      proposed_by = excluded.proposed_by,
                      confirmed_by = excluded.confirmed_by,
                      confirmed_at = excluded.confirmed_at
                    """,
                    (client_id, file_signature,
                     json.dumps(column_map, ensure_ascii=False),
                     json.dumps(list(column_map.keys()), ensure_ascii=False),
                     user.user_id),
                )
    except Exception:  # noqa: BLE001 — cache write is best-effort
        pass

    # Mark file_uploads as parsed (clears mapping_pending status from
    # _stash_unmapped) and route into the existing classify pipeline.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.file_uploads set parse_status='parsed', "
            "row_count=%s, parsed_at=now() where upload_id=%s",
            (len(rows), upload_id),
        )

    request.state.user = user
    return _ingest_rows(
        client_id=client_id, client=client,
        rows=rows, upload_id=upload_id, request=request,
    )


def _ingest_rows(*, client_id: str, client: dict, rows: list[dict],
                 upload_id: str, request: Request | None = None,
                 confirm_diffs: bool = False, confirm_orphans: bool = False,
                 ) -> RedirectResponse:
    """Ingest parsed BCCT rows. If existing rows would change (DIFF) or
    rows in DB scope are missing from upload (ORPHAN), block and route to
    a preview-confirm flow unless confirm_* flags are explicitly set.

    confirm_diffs=False (default): UPDATE on existing rows is gated. NEW-only
    uploads still flow straight through.
    """
    rows_with_date = [r for r in rows if r.get("registration_date")]
    skipped = len(rows) - len(rows_with_date)

    diff_summary = _classify_rows(client_id=client_id, parsed=rows_with_date,
                                  client=client)
    # Carry the row-skipped-without-date count into the preview so staff
    # sees it alongside NEW/UPDATED/DELETED/NOOP counts.
    diff_summary["skipped_no_date"] = skipped

    if not (confirm_diffs and confirm_orphans):
        # Phase 2: universal preview — every BCCT upload goes through the
        # confirm gate. NEW-only uploads previously bypassed this; closing
        # the gap means staff always eyeballs parsed rows + diff before
        # commit (defense in depth against any future parser regression
        # that might silently misclassify rows).
        actor_id = request.state.user.user_id if (request and hasattr(request.state, "user")) else None
        pending_id = _stash_pending(
            client_id=client_id, upload_id=upload_id, parsed=rows_with_date,
            diff_summary=diff_summary, created_by=actor_id,
        )
        # Notify the uploader: their file is parked at the preview gate.
        # Useful as a reminder if they navigate away — and as an audit
        # trail showing what's pending across past sessions.
        if actor_id:
            from app import notifications as _notifs
            n_total = diff_summary.get("total", 0)
            n_diff = len(diff_summary.get("diff", []))
            n_orph = len(diff_summary.get("orphan", []))
            body = f"Tổng {n_total} dòng"
            if n_diff or n_orph:
                body += f" · {n_diff} cập nhật · {n_orph} xóa-có-thể"
            try:
                _notifs.notify(
                    user_id=actor_id, kind="bcct_preview_pending",
                    title=f"BCCT của {client_id} chờ xác nhận",
                    body=body,
                    link_url=f"/clients/{client_id}/bcct/upload/preview/{pending_id}",
                    client_id=client_id, related_kind="upload_pending",
                    related_id=pending_id,
                )
            except Exception:
                pass  # notification is non-critical
        return RedirectResponse(
            url=f"/clients/{client_id}/bcct/upload/preview/{pending_id}",
            status_code=303,
        )

    # Confirmed → apply.
    user_id = request.state.user.user_id if (request and hasattr(request.state, "user")) else None
    n = _apply_bcct_rows(client_id=client_id, rows=rows_with_date,
                        upload_id=upload_id, client=client,
                        orphans_to_delete=diff_summary["orphan"] if confirm_orphans else [],
                        user_id=user_id)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.file_uploads set parse_status='done', row_count=%s, parsed_at=now() where upload_id=%s",
                (n, upload_id))
    # Return query string so the list view can flash a toast. Counts:
    #   ingested = total rows applied (insert+update)
    #   new      = brand-new rows (DB had nothing at this PK)
    #   updated  = existing rows confirmed for overwrite
    #   noop     = identical rows (skipped silently)
    #   skipped  = rows missing registration_date (rejected)
    new_count = diff_summary.get("new", 0)
    updated_count = len(diff_summary.get("diff", [])) if confirm_diffs else 0
    deleted_count = len(diff_summary.get("orphan", [])) if confirm_orphans else 0
    noop_count = diff_summary.get("noop", 0)
    qs = (
        f"?ingested={n}&new={new_count}&updated={updated_count}"
        f"&deleted={deleted_count}&noop={noop_count}"
    )
    if skipped:
        qs += f"&skipped={skipped}"
    return RedirectResponse(url=f"/clients/{client_id}/bcct{qs}",
                            status_code=303)


# Fields whose change matters for the diff. Excludes purely-derived fields
# (year is GENERATED) and bookkeeping (upload_id, indexed_at).
_DIFF_FIELDS = (
    "declaration_no", "declaration_type", "direction", "customs_code",
    "goods_name", "hs_code", "quantity", "unit", "total_value",
    "currency", "origin", "invoice_ref",
    "exporter_name", "exporter_tax_code", "consignee_name", "incoterms",
    "weight", "weight_unit", "package_count", "package_unit",
    "invoice_date", "departure_date",
    "destination_code", "destination_name",
    "transport_mode", "exchange_rate",
)


def _classify_rows(*, client_id: str, parsed: list[dict], client: dict) -> dict:
    """Categorize parsed rows vs DB state. Returns:
        {new: int, noop: int, diff: list[{key, old, new, changed_fields}],
         orphan: list[{key, decl_no, line_no}], total: int}
    Orphans are scoped to declarations present in the upload (per critic):
    a partial re-upload of just one declaration shouldn't soft-delete others.
    """
    if not parsed:
        return {"new": 0, "noop": 0, "diff": [], "orphan": [], "total": 0}
    keys_in_upload: set[tuple[str, str]] = set()
    decl_nos_in_upload: set[str] = set()
    rows_by_key: dict[tuple[str, str], dict] = {}
    for r in parsed:
        decl = r.get("declaration_no")
        line = r.get("line_no", "0")
        txn = r.get("transaction_key")
        keys_in_upload.add((txn, line))
        if decl:
            decl_nos_in_upload.add(decl)
        rows_by_key[(txn, line)] = r

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select transaction_key, line_no, declaration_no, "
                "       declaration_type, direction, customs_code, "
                "       goods_name, hs_code, quantity, unit, total_value, currency, "
                "       origin, invoice_ref, "
                "       exporter_name, exporter_tax_code, consignee_name, incoterms, "
                "       weight, weight_unit, package_count, package_unit, "
                "       invoice_date, departure_date, "
                "       destination_code, destination_name, "
                "       transport_mode, exchange_rate "
                "from hub.bcct_rows where client_id = %s "
                "  and declaration_no = any(%s)",
                (client_id, list(decl_nos_in_upload) if decl_nos_in_upload else [None]),
            )
            db_rows = {(r[0], r[1]): r for r in cur.fetchall()}

    diff: list[dict] = []
    orphan: list[dict] = []
    new_count = 0
    noop_count = 0

    db_field_names = list(_DIFF_FIELDS)

    for key, parsed_row in rows_by_key.items():
        db_row = db_rows.get(key)
        if db_row is None:
            new_count += 1
            continue
        # db_row layout: (txn, line, then _DIFF_FIELDS in order). Note
        # internal_code is no longer persisted; computed at runtime via
        # client_parser_rules engine — not part of the diff anymore.
        db_dict = dict(zip(["transaction_key", "line_no"] + db_field_names, db_row))
        merged_parsed = dict(parsed_row)
        changed: list[str] = []
        for f in _DIFF_FIELDS:
            old_v = db_dict.get(f)
            new_v = merged_parsed.get(f)
            if _coerce(old_v) != _coerce(new_v):
                changed.append(f)
        if not changed:
            noop_count += 1
        else:
            diff.append({
                "key": list(key),
                "decl_no": parsed_row.get("declaration_no"),
                "line_no": parsed_row.get("line_no"),
                "old": {f: _serialize(db_dict.get(f)) for f in changed},
                "new": {f: _serialize(merged_parsed.get(f)) for f in changed},
                "changed_fields": changed,
            })

    # Orphans: rows in DB whose declaration_no is in upload but key not in upload.
    for db_key, db_row in db_rows.items():
        if db_key not in keys_in_upload:
            orphan.append({
                "key": list(db_key),
                "decl_no": db_row[2],
                "line_no": db_row[1],
            })

    return {
        "new": new_count, "noop": noop_count,
        "diff": diff, "orphan": orphan,
        "total": len(parsed),
    }


def _coerce(v):
    """Cross-type comparison helper for diff. Decimal vs float etc."""
    from decimal import Decimal
    if v is None or v == "":
        return None
    if isinstance(v, (int, Decimal, float)):
        return float(v)
    return str(v).strip()


def _serialize(v):
    """JSON-safe serialize for stashed diff payload."""
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    from decimal import Decimal
    if isinstance(v, Decimal):
        return float(v)
    return v


def _stash_pending(*, client_id: str, upload_id: str, parsed: list[dict],
                   diff_summary: dict, created_by: str | None) -> str:
    """Insert into upload_pending; return the new pending_id."""
    import secrets
    pending_id = secrets.token_urlsafe(16)
    serialized_rows = [
        {k: _serialize(v) for k, v in r.items()}
        for r in parsed
    ]
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.upload_pending
                  (pending_id, client_id, module, upload_id, parsed_rows,
                   diff_summary, created_by)
                values (%s, %s, 'bcct', %s, %s::jsonb, %s::jsonb, %s)
                """,
                (pending_id, client_id, upload_id,
                 json.dumps(serialized_rows, ensure_ascii=False, default=str),
                 json.dumps(diff_summary, ensure_ascii=False, default=str),
                 created_by),
            )
    return pending_id


def _apply_bcct_rows(*, client_id: str, rows: list[dict], upload_id: str | None,
                    client: dict, orphans_to_delete: list[dict],
                    user_id: str | None) -> int:
    """Insert/update parsed rows; delete confirmed orphans. SHARED CONNECTION
    so the whole apply runs in a single transaction — partial failure
    (insert succeeds, delete crashes) cannot leave the DB inconsistent.

    Also derives catalog provenance for the touched customs_codes so the
    'seen on declaration but not registered' alarm stays in sync (Sprint A4).
    """
    from app.stores.provenance import derive_from_bcct, unregistered_seen_count

    touched_codes: set[str] = set()
    for r in rows:
        c = r.get("customs_code")
        if c:
            touched_codes.add(c)

    unreg_before = 0
    unreg_after = 0
    with connect(user_id=user_id) as conn:
        with conn.cursor() as cur:
            if touched_codes:
                unreg_before = unregistered_seen_count(cur, client_id=client_id)
            n = _insert_bcct_with_cursor(
                cur, client_id=client_id, rows=rows,
                upload_id=upload_id, client=client,
            )
            for o in orphans_to_delete:
                txn, line = o["key"]
                cur.execute(
                    "delete from hub.bcct_rows where client_id=%s "
                    "  and transaction_key=%s and line_no=%s",
                    (client_id, txn, line),
                )
            if touched_codes:
                derive_from_bcct(
                    cur, client_id=client_id, customs_codes=touched_codes,
                )
                unreg_after = unregistered_seen_count(cur, client_id=client_id)

    # Fan-out alarm if new unregistered codes appeared. Fires once per
    # apply-batch even if many codes — staff doesn't get spam.
    if unreg_after > unreg_before:
        try:
            from app import notifications as _notifs
            new_unreg = unreg_after - unreg_before
            user_ids = _notifs.staff_with_edit_access_to_client(client_id)
            _notifs.notify_many(
                user_ids=user_ids, kind="provenance_alarm",
                title=f"{new_unreg} mã trên BCCT chưa đăng ký HQ",
                body=(
                    f"Khách hàng {client_id} vừa có {new_unreg} mã mới "
                    f"xuất hiện trên tờ khai nhưng chưa được đăng ký với HQ. "
                    f"Tổng còn chờ: {unreg_after}."
                ),
                link_url=f"/clients/{client_id}/catalog?provenance=unregistered",
                client_id=client_id, related_kind="materials",
            )
        except Exception:
            pass  # notification is non-critical
    return n

# ── Confirm-on-update preview/confirm routes ─────────────────────────────

@router.get("/clients/{client_id}/bcct/upload/preview/{pending_id}",
            response_class=HTMLResponse)
async def upload_preview_view(request: Request, client_id: str, pending_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select diff_summary, expires_at, created_at
                from hub.upload_pending
                where pending_id = %s and client_id = %s and module = 'bcct'
                """,
                (pending_id, client_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Pending upload not found or expired")
    diff_summary, expires_at, created_at = row
    return request.app.state.templates.TemplateResponse(
        request, "clients/bcct_upload_preview.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "pending_id": pending_id,
            "summary": diff_summary,
            "expires_at": expires_at, "created_at": created_at,
            "active_root": "clients", "active_tab": "bcct",
        },
    )


@router.get("/clients/{client_id}/bcct/history/{transaction_key}/{line_no}",
            response_class=HTMLResponse)
async def bcct_row_history(request: Request, client_id: str,
                           transaction_key: str, line_no: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    with connect() as conn:
        with conn.cursor() as cur:
            # LEFT JOIN hub.users so 'Ai' column shows the human's email +
            # display_name, not the raw u_xxx id. Sentinel actors
            # ('system', 'ops:script') don't match a user row → JOIN
            # returns NULL on email/name and template falls back to raw.
            cur.execute(
                """
                select h.action, h.changed_by, h.changed_at, h.upload_id,
                       h.old_row, h.new_row,
                       u.email as actor_email,
                       u.display_name as actor_display_name
                from hub.bcct_row_history h
                left join hub.users u on u.user_id = h.changed_by
                where h.client_id = %s and h.transaction_key = %s
                  and h.line_no = %s
                order by h.changed_at desc
                limit 200
                """,
                (client_id, transaction_key, line_no),
            )
            cols = [d[0] for d in cur.description]
            events = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.execute(
                """
                select declaration_no, registration_date, customs_code,
                       goods_name, quantity, unit, total_value
                from hub.bcct_rows
                where client_id = %s and transaction_key = %s and line_no = %s
                """,
                (client_id, transaction_key, line_no),
            )
            current_row = cur.fetchone()
    # Compute changed fields per event for the template
    for ev in events:
        old_row = ev.get("old_row") or {}
        new_row = ev.get("new_row") or {}
        if ev["action"] == "delete":
            ev["changed_fields"] = list(old_row.keys())
        else:
            ev["changed_fields"] = sorted(
                k for k in (old_row.keys() | new_row.keys())
                if old_row.get(k) != new_row.get(k)
            )
    return request.app.state.templates.TemplateResponse(
        request, "clients/bcct_history.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "transaction_key": transaction_key, "line_no": line_no,
            "events": events,
            "current_row": current_row,
            "active_root": "clients", "active_tab": "bcct",
        },
    )


@router.post("/clients/{client_id}/bcct/upload/preview/{pending_id}/confirm")
async def upload_preview_confirm(request: Request, client_id: str, pending_id: str):
    """Apply a stashed upload, honouring the user's confirm choices.

    CRITICAL: this path uses the *stashed* diff_summary as the single source
    of truth for what's NEW / DIFF / ORPHAN. It does NOT re-classify after
    filtering rows, because filtering would turn unconfirmed-DIFF rows into
    new ORPHANs (they're now missing from `rows`), and a `confirm_orphans=
    True` would then DELETE rows the user explicitly chose to preserve.
    """
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")

    form = await request.form()
    confirm_diffs = form.get("confirm_diffs") == "on"
    confirm_orphans = form.get("confirm_orphans") == "on"

    # Single-use: DELETE in same tx as load. Double-click → second click 404s.
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from hub.upload_pending
                where pending_id = %s and client_id = %s and module = 'bcct'
                returning upload_id, parsed_rows, diff_summary
                """,
                (pending_id, client_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Pending upload not found or already applied")
    upload_id, parsed_rows, diff_summary = row

    # parsed_rows is jsonb so dates come back as strings; coerce back to
    # date for the DB insert.
    from datetime import date as _date
    def _restore_dates(r):
        for k in ("registration_date", "invoice_date", "departure_date"):
            v = r.get(k)
            if isinstance(v, str) and len(v) >= 10:
                try:
                    r[k] = _date.fromisoformat(v[:10])
                except ValueError:
                    r[k] = None
        return r
    parsed_rows = [_restore_dates(r) for r in parsed_rows]

    # Use stashed diff to bucket rows. Don't re-classify.
    diff_keys = {tuple(d["key"]) for d in diff_summary.get("diff", [])}
    # Rows to apply:
    #   • all NEW + NOOP rows (always — NOOPs are no-op upserts, NEWs insert)
    #   • DIFF rows iff confirm_diffs (otherwise the existing DB row is
    #     left untouched)
    rows_to_apply: list[dict] = []
    for r in parsed_rows:
        key = (r.get("transaction_key"), r.get("line_no", "0"))
        if key in diff_keys:
            if confirm_diffs:
                rows_to_apply.append(r)
            # else: skip — leave DB row as-is
        else:
            rows_to_apply.append(r)

    orphans_to_delete = diff_summary.get("orphan", []) if confirm_orphans else []

    n = _apply_bcct_rows(
        client_id=client_id, rows=rows_to_apply, upload_id=upload_id,
        client=client, orphans_to_delete=orphans_to_delete,
        user_id=user.user_id,
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.file_uploads set parse_status='done', "
                "  row_count=%s, parsed_at=now() where upload_id=%s",
                (n, upload_id),
            )
    return RedirectResponse(
        url=f"/clients/{client_id}/bcct", status_code=303,
    )


# Sort whitelist for the BCCT list view. Keys are URL-facing names
# (?sort=...); values are SQL fragments. Tiebreakers follow the
# primary in ORDER BY for stable pagination.
BCCT_SORT_WHITELIST = {
    "registration_date": "b.registration_date",
    "declaration_no": "b.declaration_no",
    "customs_code": "b.customs_code",
}
BCCT_SORT_DEFAULT = ("registration_date", "desc")
BCCT_SORT_TIEBREAKERS = ("b.declaration_no", "b.line_no")


def _bcct_where_clause(client_id: str, year: int | None,
                       direction: str | None, q: str | None
                       ) -> tuple[str, list]:
    """Build the shared WHERE clause + params used by both the
    paginated list query and the count query."""
    sql = "where b.client_id = %s"
    params: list = [client_id]
    if year:
        sql += " and b.year = %s"
        params.append(year)
    if direction:
        sql += " and b.direction = %s"
        params.append(direction)
    if q:
        sql += (" and (b.declaration_no ilike %s or b.customs_code ilike %s "
                "or b.goods_name ilike %s)")
        like = f"%{q}%"
        params.extend([like, like, like])
    return sql, params


def _list_bcct(client_id: str, year: int | None, direction: str | None,
               q: str | None, *, order_by: str, limit: int, offset: int
               ) -> list[dict]:
    where, params = _bcct_where_clause(client_id, year, direction, q)
    sql = f"""
        select b.transaction_key, b.line_no, b.declaration_no, b.declaration_type,
               b.direction, b.registration_date, b.customs_code,
               b.goods_name, b.hs_code, b.quantity, b.unit, b.total_value,
               b.currency, b.origin,
               coalesce(h.event_count, 0) as history_count,
               h.last_changed_at
        from hub.bcct_rows b
        left join lateral (
          select count(*) as event_count, max(changed_at) as last_changed_at
          from hub.bcct_row_history hh
          where hh.client_id = b.client_id
            and hh.transaction_key = b.transaction_key
            and hh.line_no = b.line_no
        ) h on true
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


def _count_bcct(client_id: str, year: int | None, direction: str | None,
                q: str | None) -> int:
    where, params = _bcct_where_clause(client_id, year, direction, q)
    sql = f"select count(*) from hub.bcct_rows b {where}"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            (n,) = cur.fetchone()
    return n


def _years(client_id: str) -> list[int]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select distinct year from hub.bcct_rows where client_id = %s order by year desc",
                (client_id,))
            return [y for (y,) in cur.fetchall()]


def _insert_bcct(*, client_id: str, rows: list[dict],
                 upload_id: str | None, client: dict, user_id: str | None = None) -> int:
    """Insert BCCT rows. Opens its own connection. For multi-step apply
    paths (e.g. confirm flow that also DELETEs orphans), call
    `_insert_bcct_with_cursor` directly to share the transaction."""
    with connect(user_id=user_id) as conn:
        with conn.cursor() as cur:
            return _insert_bcct_with_cursor(
                cur, client_id=client_id, rows=rows,
                upload_id=upload_id, client=client,
            )


def _insert_bcct_with_cursor(cur, *, client_id: str, rows: list[dict],
                             upload_id: str | None, client: dict) -> int:
    """Insert/upsert BCCT rows on the given cursor. `year` is GENERATED
    ALWAYS AS STORED (from registration_date); not in the column list.

    `internal_code` is no longer persisted (mig 035 dropped it).
    Computed at runtime via `compute_internal_code(row, client=client)`
    for resolver input + serializer output.
    """
    import json
    from app.resolvers.bcct_material_identity import (
        ResolverContext, resolve_material_identity,
    )
    pid_ctx = ResolverContext.from_db(client_id, cur)
    n = 0
    for r in rows:
        customs_code = r.get("customs_code")
        goods_name = r.get("goods_name") or ""
        internal_code = compute_internal_code(r, client=client)
        payload_json = json.dumps(r.get("payload") or {}, ensure_ascii=False)
        pid_row = {
            "transaction_key": r["transaction_key"],
            "declaration_no": r.get("declaration_no"),
            "line_no": r.get("line_no", "0"),
            "customs_code": customs_code,
            "internal_code": internal_code,
            "goods_name": goods_name,
        }
        material_identity = resolve_material_identity(pid_row, ctx=pid_ctx)
        material_identity_json = json.dumps(material_identity, ensure_ascii=False)
        cur.execute(
            """
            insert into hub.bcct_rows
              (client_id, transaction_key, line_no, declaration_no,
               declaration_type, direction, registration_date, customs_code,
               goods_name, hs_code, quantity, unit,
               quantity_2, unit_2, unit_price, total_value, currency, origin,
               invoice_ref,
               exporter_name, exporter_tax_code, consignee_name, incoterms,
               weight, weight_unit, package_count, package_unit,
               invoice_date, departure_date,
               destination_code, destination_name,
               transport_mode, exchange_rate,
               upload_id, payload, material_identity)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s::jsonb, %s::jsonb)
            on conflict (client_id, year, transaction_key, line_no) do update set
              declaration_no = excluded.declaration_no,
              customs_code = excluded.customs_code,
              goods_name = excluded.goods_name,
              quantity = excluded.quantity,
              total_value = excluded.total_value,
              exporter_name = excluded.exporter_name,
              exporter_tax_code = excluded.exporter_tax_code,
              consignee_name = excluded.consignee_name,
              incoterms = excluded.incoterms,
              weight = excluded.weight,
              weight_unit = excluded.weight_unit,
              package_count = excluded.package_count,
              package_unit = excluded.package_unit,
              invoice_date = excluded.invoice_date,
              departure_date = excluded.departure_date,
              destination_code = excluded.destination_code,
              destination_name = excluded.destination_name,
              transport_mode = excluded.transport_mode,
              exchange_rate = excluded.exchange_rate,
              payload = excluded.payload,
              upload_id = excluded.upload_id,
              material_identity = excluded.material_identity,
              indexed_at = now()
            """,
            (client_id, r["transaction_key"], r.get("line_no", "0"),
             r.get("declaration_no"), r.get("declaration_type"),
             r.get("direction"), r.get("registration_date"),
             customs_code, goods_name, r.get("hs_code"),
             r.get("quantity"), r.get("unit"),
             r.get("quantity_2"), r.get("unit_2"),
             r.get("unit_price"), r.get("total_value"),
             r.get("currency"), r.get("origin"), r.get("invoice_ref"),
             r.get("exporter_name"), r.get("exporter_tax_code"),
             r.get("consignee_name"), r.get("incoterms"),
             r.get("weight"), r.get("weight_unit"),
             r.get("package_count"), r.get("package_unit"),
             r.get("invoice_date"), r.get("departure_date"),
             r.get("destination_code"), r.get("destination_name"),
             r.get("transport_mode"), r.get("exchange_rate"),
             upload_id, payload_json, material_identity_json))
        n += 1
    return n
