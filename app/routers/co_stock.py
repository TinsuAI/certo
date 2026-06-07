from __future__ import annotations

import hashlib

from fastapi import APIRouter
from app import co_stock_adjustments_store, co_stock_events_store, co_stock_ledger, co_stock_materializer
from app.co_stock_template import CoStockTemplateError, read_standard_co_stock, write_standard_co_stock
from app.data_hub_settings import data_hub_link_settings
from app.portfolio import portfolio_service
from app.table_view import build_table_view
from app.web.client_context import client_context, resolve_client, source_stats
from app.web.co_case_context import _CO_CASE_SOURCE_CACHE, _refresh_co_stock_delta_or_full
from app.web.templating import templates
from datetime import date
from fastapi import File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response


router = APIRouter()

CO_STOCK_COLUMNS = [
    {"key": "source_row", "label": "Dòng nguồn", "class": "mono"},
    {"key": "import_declaration_no", "label": "Tờ khai nhập", "class": "mono"},
    {"key": "line_no", "label": "STT", "class": "mono"},
    {"key": "declaration_type", "label": "LH", "class": "mono"},
    {"key": "customs_item_code", "label": "Mã HQ", "class": "mono"},
    {"key": "allocation_code", "label": "Mã phân bổ", "class": "mono"},
    {"key": "available_qty", "label": "Tồn CO", "class": "num"},
    {"key": "used_qty", "label": "Đã dùng", "class": "num"},
    {"key": "remaining_qty", "label": "Còn lại", "class": "num"},
    {"key": "status_label", "label": "Trạng thái"},
    {"key": "stock_reason_label", "label": "Lý do"},
    {"key": "history_action", "label": "Lịch sử", "kind": "history", "sortable": False},
]
def _co_stock_lean_client_context(client_id: str, co_stock_row_count: int | None = None) -> dict:
    """Lean context for /co-stock — skips full source_workspace pagination.

    Standard client_context calls source_workspace_for_client which paginates
    full BCCT from Data Hub (~10s on Johnson). /co-stock only needs client
    meta + client_config + counts + materialized co_stock_rows, so we build
    those directly.

    Also computes sync_status by comparing current BCCT row count against
    the snapshot's recorded count (see co_stock_materializer.compute_sync_status).
    """
    client = resolve_client(client_id)
    source_summary, source_backend = portfolio_service.source_summary(client)
    client_config = source_summary.get("client_config") or portfolio_service.get_client_config(client)
    bcct_row_count = source_summary.get("bcct", {}).get("published_row_count", 0)
    if co_stock_row_count is None:
        co_stock_row_count = co_stock_materializer.row_count(client["id"])
    counts = {
        **client.get("counts", {}),
        "materials": source_summary.get("material_catalog", {}).get("published_row_count", 0),
        "products": source_summary.get("product_catalog", {}).get("published_row_count", 0),
        "bcct": bcct_row_count,
        "co_stock": co_stock_row_count,
    }
    client = {**client, "counts": counts}
    sync_status = co_stock_materializer.compute_sync_status(client["id"], bcct_row_count)
    try:
        stock_summary = co_stock_materializer.co_stock_summary(client["id"], "", "")
    except Exception:  # noqa: BLE001
        stock_summary = {}
    return {
        "client": client,
        "active": "co-stock",
        "source_backend": source_backend,
        "client_config": client_config,
        "source_stats": source_stats("co-stock", counts=client.get("counts", {}), stock_summary=stock_summary),
        "source_workspace": {
            "client_config": client_config,
            "bcct": {"latest_version": source_summary.get("bcct", {}).get("latest_version") or {},
                     "correction_candidates": []},
            "material_catalog": {"latest_version": source_summary.get("material_catalog", {}).get("latest_version") or {}},
            "product_catalog": {"latest_version": source_summary.get("product_catalog", {}).get("latest_version") or {}},
        },
        "co_stock_last_refresh_at": co_stock_materializer.last_refresh_at(client["id"]),
        "co_stock_sync_status": sync_status,
    }
_CO_STOCK_STATUS_OPTIONS = [
    {"value": "available", "label": "Khả dụng"},
    {"value": "review_required", "label": "Cần review"},
    {"value": "inactive", "label": "Không dùng"},
    {"value": "depleted", "label": "Hết tồn"},
]
def co_stock_table_context(request: Request, client_id: str) -> dict:
    """SQL-paginated Tồn CO context. The DB does WHERE/ORDER/LIMIT so the
    page returns ~50 rows × few-ms even on 60k-row clients (Johnson).
    Ledger + adjustments apply only to the visible slice.

    Falls back to in-memory build_table_view for clients whose stock pool
    hasn't been materialized into `co_stock_rows` yet (file-mode demo
    fixtures + first-time-ever loads when no refresh has run).
    """
    from app.table_view import (
        DEFAULT_PAGE_SIZE,
        PAGE_SIZES,
        normalize_column,
        normalize_query,
        page_query,
        parse_int,
        table_field_names,
    )

    total_co_stock_rows = co_stock_materializer.row_count(client_id)
    # File-mode (no DB or no Data Hub configured) → legacy in-memory path so
    # Growatt-style fixtures keep working. Data Hub mode always uses the
    # materialized table — when empty, the UI shows a "Chưa có snapshot"
    # state that prompts the operator to click Refresh.
    use_legacy_path = total_co_stock_rows == 0 and not data_hub_link_settings().source_enabled
    if use_legacy_path:
        context = client_context(client_id, "co-stock")
        rows = [co_stock_table_row(row) for row in context["client"]["co_stock"]]
        context["co_stock_last_refresh_at"] = co_stock_materializer.last_refresh_at(client_id)
        context["co_stock_empty_needs_refresh"] = not context["client"]["co_stock"]
        context["co_stock_sync_status"] = {"status": "no_snapshot", "snapshot_rows": 0,
                                           "snapshot_bcct_rows": 0, "bcct_now_rows": 0,
                                           "refreshed_at": "", "delta": 0}
        context["source_table"] = build_table_view(
            rows,
            columns=CO_STOCK_COLUMNS,
            query=request.query_params,
            filters=[{"name": "status", "field": "status", "label": "Trạng thái",
                      "options": _CO_STOCK_STATUS_OPTIONS}],
            summary_fields=[
                {"field": "status_label", "label": "Trạng thái"},
                {"field": "declaration_type", "label": "Loại hình"},
            ],
            default_sort="import_declaration_no",
        )
        return context

    context = _co_stock_lean_client_context(client_id, co_stock_row_count=total_co_stock_rows)
    client = context["client"]
    context["co_stock_empty_needs_refresh"] = total_co_stock_rows == 0

    query_values = normalize_query(request.query_params)
    field_names = table_field_names("")
    q = query_values.get(field_names["q"], "").strip()
    status_value = query_values.get("status", "").strip()
    sort_key = query_values.get(field_names["sort"]) or "import_declaration_no"
    direction = "desc" if query_values.get(field_names["dir"]) == "desc" else "asc"
    per_page = min(max(1, parse_int(query_values.get(field_names["per_page"]), DEFAULT_PAGE_SIZE)), 500)
    page = max(1, parse_int(query_values.get(field_names["page"]), 1))

    page_rows, filtered_count = co_stock_materializer.read_co_stock_page(
        client["id"],
        q=q,
        status=status_value,
        sort=sort_key,
        direction=direction,
        offset=(page - 1) * per_page,
        limit=per_page,
    )
    # Trừ-lùi is already folded into the snapshot; overlay only the live ledger.
    if page_rows:
        used_by_lot = co_stock_ledger.used_qty_by_lot(client["id"])
        page_rows = co_stock_ledger.apply_used_qty(page_rows, used_by_lot)
    rows = [co_stock_table_row(row) for row in page_rows]

    column_defs = [normalize_column(col) for col in CO_STOCK_COLUMNS]
    page_count = max(1, (filtered_count + per_page - 1) // per_page)
    page = min(page, page_count)

    prepared_query = {k: v for k, v in query_values.items() if k != field_names["page"]}
    owned_names = set(field_names.values()) | {"status"}
    reset_query = {k: v for k, v in query_values.items() if k not in owned_names}

    for col in column_defs:
        col["sort_active"] = col["key"] == sort_key
        col["sort_dir"] = direction if col["sort_active"] else ""
        col["sort_query"] = page_query(
            prepared_query,
            **{
                field_names["sort"]: col["key"],
                field_names["dir"]: "desc" if col["sort_active"] and direction == "asc" else "asc",
                field_names["page"]: 1,
            },
        )

    filter_defs = [
        {
            "name": "status",
            "query_name": "status",
            "label": "Trạng thái",
            "field": "status",
            "options": _CO_STOCK_STATUS_OPTIONS,
            "value": status_value,
        }
    ]

    context["source_table"] = {
        "rows": rows,
        "columns": column_defs,
        "filters": filter_defs,
        "summary_chips": [],
        "query": query_values,
        "field_names": field_names,
        "passthrough_params": reset_query,
        "param_prefix": "",
        "q": q,
        "sort": sort_key,
        "dir": direction,
        "page": page,
        "per_page": per_page,
        "page_sizes": PAGE_SIZES,
        "total_pages": page_count,
        "total_count": total_co_stock_rows,
        "filtered_count": filtered_count,
        "start_index": (page - 1) * per_page + 1 if rows else 0,
        "end_index": min(page * per_page, filtered_count),
        "has_previous": page > 1,
        "has_next": page < page_count,
        "previous_query": page_query(prepared_query, **{field_names["page"]: page - 1}),
        "next_query": page_query(prepared_query, **{field_names["page"]: page + 1}),
        "first_query": page_query(prepared_query, **{field_names["page"]: 1}),
        "last_query": page_query(prepared_query, **{field_names["page"]: page_count}),
        "reset_query": page_query(reset_query),
    }
    return context
def co_stock_table_row(row: dict) -> dict:
    remaining_qty = str(row.get("remaining_qty", ""))
    if row.get("eligibility_status") == "inactive":
        status = "inactive"
    elif row.get("allocation_code_status") != "resolved":
        status = "review_required"
    else:
        status = "depleted" if remaining_qty in {"", "0", "0.0", "0.00"} else "available"
    return {
        **row,
        "status": status,
        "status_label": {
            "available": "Khả dụng",
            "depleted": "Hết tồn",
            "inactive": "Không dùng",
            "review_required": "Cần review",
        }[status],
        "stock_reason_label": stock_reason_label(row, status),
    }
def stock_reason_label(row: dict, status: str) -> str:
    if row.get("ledger_overclaim"):
        from decimal import Decimal, InvalidOperation
        raw = str(row.get("remaining_signed_qty") or "0").lstrip("-")
        try:
            amount = format(Decimal(raw).normalize(), "f")
        except (InvalidOperation, ValueError):
            amount = raw
        return f"⚠ Vượt tồn {amount}"
    if status == "inactive" and row.get("eligibility_reason") == "excluded_by_declaration_type_config":
        return "Loại hình không active trong config"
    if status == "review_required":
        return row.get("allocation_code_reason") or "Cần review mã phân bổ"
    return row.get("eligibility_reason", "")
@router.get("/clients/{client_id}/co-stock", response_class=HTMLResponse)
async def co_stock(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="co_stock.html",
        context=co_stock_table_context(request, client_id),
    )
@router.post("/clients/{client_id}/co-stock/import")
async def import_co_stock_workbook(client_id: str, file: UploadFile = File(...)):
    """Upload a standard CO stock template xlsx. Overwrites prior snapshot
    rows for the same (declaration_no, line_no, customs_code) keys; preserves
    rows untouched by this upload (so a partial upload only updates what it
    covers).

    Run scripts/convert_co_stock.py first if uploading from the agency
    `tru-lui-co-template.xlsm` workbook.
    """
    client = resolve_client(client_id)
    content = await file.read()
    try:
        rows, parse_errors = read_standard_co_stock(content)
    except CoStockTemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    batch_id = "batch_" + hashlib.sha1(content).hexdigest()[:16]
    summary = co_stock_adjustments_store.upsert_batch(
        client["id"],
        rows,
        batch_id=batch_id,
        source_file_ref=file.filename or "co_stock.xlsx",
    )
    # Fold the new trừ-lùi values straight into the materialized snapshot so
    # remaining_qty (and the lock guard, which reads it) are immediately
    # authoritative — without waiting for the next BCCT refresh.
    keys = [
        (str(r.get("declaration_no") or ""), str(r.get("line_no") or ""), str(r.get("customs_code") or ""))
        for r in rows
        if r.get("declaration_no") and r.get("line_no") and r.get("customs_code")
    ]
    refolded = co_stock_materializer.refold_adjustment_lots(client["id"], keys)
    summary = {**summary, "lots_refolded": refolded}
    # Invalidate the cached source context so the next case page reflects the
    # new adjustments. The cache is process-local so this is cheap.
    _CO_CASE_SOURCE_CACHE.clear()
    return JSONResponse({
        "ok": not summary.get("errors"),
        "client_id": client["id"],
        "batch_id": batch_id,
        "filename": file.filename or "",
        "parsed_rows": len(rows),
        "parse_errors": parse_errors,
        "upsert": summary,
    })
@router.post("/clients/{client_id}/co-stock/refresh")
async def refresh_co_stock_endpoint(client_id: str):
    """Materialize the derived stock pool for one client into CO's
    co_stock_rows table.

    Tries the Data Hub delta path first (`list_bcct_with_envelope` with
    `since` + `include_tombstones`) when we have a stored
    `last_bcct_server_time` AND the response carries a fresh `server_time`.
    Falls back to full-pull when either is missing — the very first refresh
    of a client, or when Data Hub is on an older contract.
    """
    client = resolve_client(client_id)
    summary = _refresh_co_stock_delta_or_full(client)
    # Invalidate the case-source cache so the substitute modal / sheet calc
    # paths see the same fresh data.
    _CO_CASE_SOURCE_CACHE.clear()
    return JSONResponse({"ok": not summary.get("errors"), **summary})
@router.get("/clients/{client_id}/co-stock/summary")
async def co_stock_summary_endpoint(client_id: str, date_from: str = "", date_to: str = ""):
    """Free-remaining CO stock value (VND) + code/lot counts, optionally within
    a registration-date window. Backs the Tồn CO overview strip + its date
    filter on the làm-CO page (feedback #12)."""
    client = resolve_client(client_id)
    return JSONResponse(co_stock_materializer.co_stock_summary(client["id"], date_from, date_to))
@router.get("/clients/{client_id}/co-stock/lot-history")
async def co_stock_lot_history(
    client_id: str,
    declaration_no: str = "",
    line_no: str = "",
    customs_code: str = "",
    limit: int = 200,
):
    """Return chronological audit log for one lot: claim_lock/release events
    from sheet allocations + adjustment_import_insert/update from manual
    workbook uploads. Newest first.
    """
    client = resolve_client(client_id)
    if not (declaration_no.strip() and line_no.strip() and customs_code.strip()):
        raise HTTPException(status_code=400, detail="declaration_no, line_no, customs_code required")
    events = co_stock_events_store.events_for_lot(
        client["id"],
        declaration_no.strip(),
        line_no.strip(),
        customs_code.strip(),
        limit=max(1, min(int(limit), 500)),
    )
    anchor = _lot_effective_anchor(
        client["id"], declaration_no.strip(), line_no.strip(), customs_code.strip()
    )
    return JSONResponse({
        "ok": True,
        "client_id": client["id"],
        "lot": {
            "declaration_no": declaration_no,
            "line_no": line_no,
            "customs_code": customs_code,
            **anchor,
        },
        # Default modal view folds the chốt/mở-chốt churn into one net row per
        # (case, sheet); `events` keeps the raw log for the "Chi tiết" toggle.
        "groups": co_stock_events_store.fold_lot_events(events),
        "events": events,
        "count": len(events),
    })
def _lot_effective_anchor(client_id: str, declaration_no: str, line_no: str, customs_code: str) -> dict:
    """Current BCCT opening + effective remaining for one lot — anchors the
    history modal's running-balance (SAU) column.

    Mirrors the Tồn CO table pipeline (snapshot → ledger → adjustments) for
    `available_qty`/`used_qty`, but reports remaining UN-clamped: the table
    floors remaining at 0 for allocation UX, whereas the audit history must
    show the true figure so the backward-walk stays arithmetically consistent.
    A genuinely over-allocated lot therefore anchors on a negative remaining
    (flagged via `overclaim`) instead of a clamped 0 that would skew every
    historical SAU. Returns {} when no snapshot row matches (file-mode /
    un-materialized client), letting the UI leave SAU blank.
    """
    page_rows, _ = co_stock_materializer.read_co_stock_page(
        client_id, q=declaration_no, limit=500
    )
    matched = [
        row for row in page_rows
        if str(row.get("import_declaration_no") or "") == declaration_no
        and str(row.get("line_no") or "") == line_no
        and str(row.get("customs_item_code") or "") == customs_code
    ]
    if not matched:
        return {}
    # Trừ-lùi is folded into the snapshot; overlay only the live ledger. The
    # helper exposes remaining_signed_qty (un-clamped), which is the honest
    # anchor for the history modal's running-balance walk.
    used_by_lot = co_stock_ledger.used_qty_by_lot(client_id)
    matched = co_stock_ledger.apply_used_qty(matched, used_by_lot)
    from decimal import Decimal, InvalidOperation

    def _sum(field: str) -> Decimal:
        total = Decimal("0")
        for row in matched:
            try:
                total += Decimal(str(row.get(field) or "0"))
            except (InvalidOperation, ValueError):
                pass
        return total

    opening = _sum("opening_qty") or _sum("available_qty")
    remaining = _sum("remaining_signed_qty")
    return {
        "available_qty": str(opening),
        "remaining_qty": str(remaining),
        "overclaim": remaining < 0,
    }
@router.get("/clients/{client_id}/co-stock/export.xlsx")
async def export_co_stock_workbook(client_id: str):
    """Dump effective ton CO state (BCCT opening + ledger + adjustments) into
    a standard template xlsx. Heavy for big clients (full BCCT pagination
    on Data Hub mode); intended for on-demand download.
    """
    client = resolve_client(client_id)
    workspace, _backend = portfolio_service.source_workspace(client)
    stock_rows = [dict(row) for row in workspace.get("co_stock_rows") or []]
    client_id_value = client.get("id", "")
    # Export may run against fresh-derived rows (not the materialized snapshot),
    # so fold the static trừ-lùi here too (idempotent) before overlaying the
    # live ledger — keeping export identical to what the Tồn CO table shows.
    adjustments = co_stock_adjustments_store.aggregate_by_lookup_key(client_id_value)
    co_stock_adjustments_store.fold_baseline(stock_rows, adjustments or {})
    used_by_lot = co_stock_ledger.used_qty_by_lot(client_id_value)
    stock_rows = co_stock_ledger.apply_used_qty(stock_rows, used_by_lot)
    rows_for_template = []
    for row in stock_rows:
        rows_for_template.append({
            "declaration_no": row.get("import_declaration_no", ""),
            "registration_date": row.get("registration_date") or row.get("declaration_date") or row.get("import_declaration_date") or "",
            "declaration_type": row.get("declaration_type", ""),
            "line_no": row.get("line_no", ""),
            "customs_code": row.get("customs_item_code", ""),
            "hs_code": row.get("hs_code", ""),
            "goods_name": row.get("material_description") or row.get("goods_name", ""),
            "origin_country": row.get("origin_country", ""),
            "unit_price": row.get("unit_value") or row.get("unit_price", ""),
            "taxable_unit_price": row.get("taxable_unit_price", ""),
            "opening_qty": row.get("available_qty", ""),
            "unit": row.get("unit", ""),
            "partner": row.get("partner", ""),
            "invoice_no": row.get("invoice_no") or row.get("invoice_ref", ""),
            "invoice_date": row.get("invoice_date", ""),
            "exchange_rate": row.get("exchange_rate", ""),
            "used_qty": row.get("used_qty", ""),
            "source_co_no": "",  # Per-CO attribution requires reading co_stock_claims.case_id; out of scope here.
            "transaction_key": row.get("source_transaction_key", ""),
        })
    xlsx = write_standard_co_stock(rows_for_template, use_labels=True)
    filename = f"{client_id_value}-co-stock-{date.today().isoformat()}.xlsx"
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
