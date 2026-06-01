from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import co_auth
from app.bom_store import attach_case_bom_snapshot
from app.bom_service import bom_service
from app.co_case_store import (
    MAX_SUPPORTING_FILE_BYTES,
    CaseClosedError,
    CaseHasActiveClaimsError,
    acquire_origin_calculation_lock,
    active_origin_calculation_lock,
    build_case_criteria_rows,
    case_from_record,
    co_case_delete_block_reason,
    co_case_is_completed,
    create_case_record,
    create_case_workbook,
    declaration_refs,
    delete_case_record,
    get_case_record,
    get_case_workspace,
    get_supporting_file,
    invoice_keys,
    json_safe,
    match_case_bcct_exports,
    safe_filename,
    save_supporting_file,
    release_origin_calculation_lock,
    update_case_record,
)
from app.co_forms import (
    COMMON_MARKET_PRESETS,
    common_market_guidance,
    criteria_preview_for_hs,
    form_candidates_for_market,
    prioritized_form_lanes,
    recommended_form_lane,
)
from app.co_form_config_store import (
    co_form_config_path,
    load_co_form_config,
    reset_co_form_config,
    sanitize_co_form_config,
    save_co_form_config,
    unique_text_list,
)
from app import co_stock_adjustments_store, co_stock_eligibility, co_stock_events_store, co_stock_ledger, co_stock_materializer
from app.co_stock_template import CoStockTemplateError, read_standard_co_stock, write_standard_co_stock
from app.co_market_hints import infer_market_from_invoice_matches
from app.client_registry import get_client as registry_get_client
from app.client_registry import get_client_case
from app.customs_fx_store import CUSTOMS_FX_CLIENT_ID, get_customs_fx_store
from app.database import apply_migrations, database_url
from app.data_hub_client import (
    DataHubClient,
    bom_product_code_from_material_identity,
    reset_current_data_hub_token,
    set_current_data_hub_token,
)
from app.data_hub_settings import (
    DATA_HUB_LINK_ENV_KEYS,
    DataHubLinkSettings,
    data_hub_config_path,
    data_hub_link_settings,
    load_data_hub_overrides,
    save_data_hub_overrides,
)
from app.demo_data import (
    DEMO_CASE,
    SOURCE_NOTES,
    attach_results,
    clone_case,
    update_products_from_form,
)
from app.origin import evaluate_tariff_shift
from app import material_search
from app.app_state_store import get_app_state_store
from app.portfolio import SourceBackendUnavailable, portfolio_app, portfolio_service
from app.routers import auth as auth_routes
from app.routers import catalog as catalog_routes
from app.routers import customs_fx as customs_fx_routes
from app.routers import settings as settings_routes
from app.source_store import (
    attach_case_source_snapshot,
    co_stock_rows_from_bcct,
    enrich_client_with_source_workspace,
)
from app.table_view import build_table_view
from app.web.client_context import (
    _data_hub_overview_context,
    case_finished_hs_codes,
    client_case,
    client_context,
    default_client_case,
    effective_min_gap_days,
    resolve_client,
    source_workspace_for_client,
)
from app.web.deps import require_local_source_writes
from app.web.co_case_context import (
    _CO_CASE_SOURCE_CACHE,
    _co_stock_refresh_inflight,
    CALCULATE_SNAPSHOT_FRESHNESS_SECONDS,
    CO_CASE_STEP_STATUS_LABELS,
    CO_CASE_WORKFLOW_STEPS,
    ORIGIN_SHEET_STATUS_LABELS,
    SHEET_CURRENCY_MODES,
    SHEET_OPTIMIZATION_MODES,
    _CO_CASE_SOURCE_CACHE_TTL_SECONDS,
    _allocation_line_fx,
    _attach_fob_vnd,
    _calculate_stock_rows_from_snapshot,
    _co_stock_refresh_inflight_lock,
    _co_stock_snapshot_is_fresh,
    _full_refresh,
    _probe_server_time,
    _refresh_co_stock_delta_or_full,
    _schedule_background_co_stock_refresh,
    _try_delta_refresh,
    add_bom_code,
    allocate_material_stock,
    allocation_available_qty,
    allocation_currency_summary,
    allocation_document_ref,
    allocation_line_matches_stock,
    allocation_summary,
    allocation_unit_value_summary,
    allocation_valuation_source,
    apply_existing_origin_product_consumption,
    attach_case_source_summary_snapshot,
    attach_origin_bom_product_codes,
    attach_origin_demo,
    attach_origin_readiness,
    attach_origin_sheet_states,
    bom_code_candidates,
    bom_workspace_from_case_snapshot,
    cached_origin_source_context,
    calculate_lvc_result,
    case_allocation_pool,
    case_export_anchor_date,
    case_tkx_tkn_summary,
    co_case_bom_product_codes,
    co_case_context,
    co_case_hs_codes,
    co_case_light_context,
    co_case_source_context,
    co_case_source_context_cached,
    co_case_step_status,
    co_case_workflow_steps,
    co_stock_allocation_pool,
    co_stock_allocation_sort_key,
    co_stock_has_value,
    co_stock_is_usable,
    co_stock_key_candidates,
    compact_origin_signature_row,
    criterion_mode,
    decimal_text,
    decimal_value,
    declaration_file_count,
    durable_sheet_status,
    enrich_client_with_source_summary,
    enrich_origin_material,
    enrich_origin_product,
    first_decimal_source,
    first_non_empty,
    has_shipment_reference,
    invoice_form_lane_view,
    invoice_match_criteria_rows,
    invoice_match_preview_row,
    invoice_match_summary,
    invoice_preview_from_matches,
    latest_usable_product_version,
    lvc_threshold_from_criterion,
    market_inference_view,
    material_catalog_index,
    material_issue_summary,
    material_summary_row,
    minimal_bom_workspace,
    normalize_threshold,
    normalized_lvc_result,
    numeric_sequence,
    numeric_sort_text,
    order_invoice_matches_for_origin,
    origin_build_signature,
    origin_case_revision,
    origin_lock_actor,
    origin_match_from_existing_product,
    origin_material_count,
    origin_material_from_bom_row,
    origin_product_from_invoice_match,
    origin_product_order,
    origin_product_shell_from_invoice_match,
    origin_product_value,
    origin_sheet_action_error,
    origin_sheet_export_blockers,
    origin_source_context,
    origin_status_details_from_material,
    origin_status_from_material,
    origin_warning_summary,
    prepare_case_origin_product_shells,
    prepare_case_origin_products,
    prepare_case_origin_sheet,
    primary_shipment_reference,
    resolve_bom_product_code,
    selected_bom_rows_by_product,
    sheet_form_recommendation,
    shipment_reference_warnings,
    should_show_origin_demo,
    source_summary_from_case_snapshot,
    stock_allocation_consumption,
    stock_allocation_line,
    stock_allocation_remaining_qty,
    stock_available_qty,
    stock_candidates_for_material,
    stock_consumption_is_before,
    stock_consumption_label,
    stock_for_existing_allocation_line,
    stock_shortage_trace,
    tariff_shift_rule_from_criterion,
    text_list,
    unique_texts,
    usable_bom_product_version,
    valuation_source_label,
    valuation_status_label,
)
from app.web.templating import templates
from app.workbook_io import (
    WorkbookParseError,
    create_dossier_zip,
    create_evidence_workbook,
    create_hq_bang_ke_workbook,
    create_input_workbook,
    parse_input_workbook,
)


ROOT = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if database_url():
        apply_migrations()
    yield


app = FastAPI(title="Barry CO Demo", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount("/portfolio", portfolio_app, name="portfolio")
app.include_router(auth_routes.router)
app.include_router(catalog_routes.router)
app.include_router(customs_fx_routes.router)
app.include_router(settings_routes.router)


@app.exception_handler(CaseClosedError)
async def _case_closed_handler(request: Request, exc: CaseClosedError):
    """Mutating route hit a closed case → 409 with the friendly Vietnamese message."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(SourceBackendUnavailable)
async def _source_backend_unavailable_handler(request: Request, exc: SourceBackendUnavailable):
    """Data Hub is the source of truth but unavailable, and local fallback is not
    allowed → 503 with a clear message instead of a silently-empty page."""
    return PlainTextResponse(str(exc), status_code=503)


@app.exception_handler(httpx.TransportError)
async def _data_hub_unreachable_handler(request: Request, exc: httpx.TransportError):
    """Data Hub is enabled but the API is unreachable (connection refused /
    timeout). Surface a clear 503 instead of a generic 500 so the operator knows
    it's a Data Hub outage, not a CO bug. Only fires for transport errors that
    propagate unhandled — local try/except (e.g. 404 fallbacks) still wins."""
    return PlainTextResponse(
        "Data Hub không phản hồi (kết nối thất bại/timeout). CO không dùng dữ liệu "
        "local backup; kiểm tra Data Hub rồi thử lại.",
        status_code=503,
    )


@app.exception_handler(httpx.HTTPStatusError)
async def _data_hub_error_status_handler(request: Request, exc: httpx.HTTPStatusError):
    """Data Hub returned an error status that no route handled → 502 (bad
    gateway): the upstream source failed, not CO. Routes that intentionally
    handle Data Hub statuses (e.g. 404 → fallback) catch the error themselves
    and never reach this handler."""
    upstream = exc.response.status_code if exc.response is not None else "?"
    return PlainTextResponse(
        f"Data Hub trả lỗi ({upstream}). CO không dùng dữ liệu local backup; "
        "kiểm tra Data Hub rồi thử lại.",
        status_code=502,
    )


async def large_request_form(request: Request):
    try:
        return await request.form(max_fields=100000, max_files=2000)
    except TypeError:
        return await request.form()


def persisted_origin_case(client: dict, case_id: str) -> dict:
    record = get_case_record(client, case_id)
    case = case_from_record(default_client_case(client), client, record)
    case["persisted_case_id"] = case.get("persisted_case_id") or case_id
    return case


def merge_origin_action_payload(case: dict, payload: dict) -> dict:
    if not isinstance(payload, dict):
        return case
    prepared = dict(case)
    order = payload.get("origin_product_order")
    if isinstance(order, str):
        prepared["origin_product_order"] = origin_product_order({"origin_product_order": order})
    elif isinstance(order, list):
        prepared["origin_product_order"] = [str(code).strip() for code in order if str(code).strip()]
    bom_artifact_id = str(payload.get("bom_artifact_id") or payload.get("bom_version_id") or "").strip()
    if bom_artifact_id:
        prepared["bom_artifact_id"] = bom_artifact_id
        prepared["bom_version_id"] = bom_artifact_id
    overrides = dict(prepared.get("bom_product_artifact_overrides") or {})
    legacy_overrides = dict(prepared.get("bom_product_version_overrides") or {})
    incoming_overrides = payload.get("bom_product_artifact_overrides")
    if isinstance(incoming_overrides, dict):
        for code, artifact_id in incoming_overrides.items():
            code = str(code or "").strip()
            artifact_id = str(artifact_id or "").strip()
            if code and artifact_id:
                overrides[code] = artifact_id
                legacy_overrides[code] = artifact_id
    products_by_code = {
        str(product.get("code") or "").strip(): dict(product)
        for product in prepared.get("products", [])
        if str(product.get("code") or "").strip()
    }
    product_sheet_states: dict[str, dict] = {}
    for incoming in payload.get("products") or []:
        if not isinstance(incoming, dict):
            continue
        code = str(incoming.get("code") or incoming.get("product_code") or "").strip()
        if not code:
            continue
        product = products_by_code.get(code, {"code": code})
        for key in [
            "name",
            "finished_hs",
            "quantity",
            "unit",
            "currency",
            "source_declaration_no",
            "source_line_no",
            "invoice_ref",
            "fob",
            "non_origin_value",
            "rvc_threshold",
            "lvc_threshold",
            "bom_product_code",
            "bom_product_artifact_id",
            "bom_product_artifact_no",
            "bom_product_version_id",
            "bom_product_version_no",
            "origin_sheet_status",
            "origin_sheet_status_label",
        ]:
            if key in incoming:
                product[key] = incoming.get(key)
        if isinstance(incoming.get("cost_buildup"), dict):
            existing_cb = product.get("cost_buildup") if isinstance(product.get("cost_buildup"), dict) else {}
            cb_whitelist = {
                "wages", "welfare", "rent", "depreciation", "other_mfg", "transport_storage",
                "profit",
                "labor", "overhead", "other",  # legacy 4-key shape, still accepted
            }
            product["cost_buildup"] = {**existing_cb, **{k: str(v or "") for k, v in incoming["cost_buildup"].items() if k in cb_whitelist}}
        if isinstance(incoming.get("materials"), list):
            product["materials"] = incoming["materials"]
        if incoming.get("origin_sheet_status") or incoming.get("origin_sheet_status_label"):
            durable = durable_sheet_status(incoming.get("origin_sheet_status"))
            product_sheet_states[code] = {
                "status": durable,
                "status_label": ORIGIN_SHEET_STATUS_LABELS.get(
                    durable, str(incoming.get("origin_sheet_status_label") or "").strip()
                ),
            }
        artifact_id = str(
            product.get("bom_product_artifact_id") or product.get("bom_product_version_id") or ""
        ).strip()
        bom_product_code = str(product.get("bom_product_code") or code).strip()
        if artifact_id:
            overrides[code] = artifact_id
            legacy_overrides[code] = artifact_id
            if bom_product_code:
                overrides[bom_product_code] = artifact_id
                legacy_overrides[bom_product_code] = artifact_id
        products_by_code[code] = product
    if products_by_code:
        ordered = origin_product_order(prepared)
        remainder = [code for code in products_by_code if code not in ordered]
        prepared["products"] = [products_by_code[code] for code in ordered + remainder if code in products_by_code]
    sheet_states = payload.get("origin_sheet_states")
    if not isinstance(sheet_states, dict) and product_sheet_states:
        sheet_states = product_sheet_states
    if isinstance(sheet_states, dict):
        existing_states = prepared.get("origin_sheet_states") if isinstance(prepared.get("origin_sheet_states"), dict) else {}
        merged_states: dict[str, dict] = {
            str(code): dict(state)
            for code, state in existing_states.items()
            if isinstance(state, dict)
        }
        for code, state in sheet_states.items():
            if not isinstance(state, dict):
                continue
            previous = existing_states.get(str(code)) if isinstance(existing_states.get(str(code)), dict) else {}
            merged_states[str(code)] = {**previous, **state}
        prepared["origin_sheet_states"] = merged_states
    prepared["bom_product_artifact_overrides"] = overrides
    prepared["bom_product_version_overrides"] = legacy_overrides
    return prepared


async def origin_case_from_request(request: Request, client: dict, case_id: str) -> tuple[dict, dict]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        case = persisted_origin_case(client, case_id)
        expected_revision = str(payload.get("expected_revision") or "").strip()
        if expected_revision and expected_revision != origin_case_revision(case):
            raise HTTPException(status_code=409, detail="Origin case state changed; reload before saving.")
        return merge_origin_action_payload(case, payload), payload
    form = await large_request_form(request)
    case = update_products_from_form({key: str(value) for key, value in form.items()})
    case["persisted_case_id"] = case.get("persisted_case_id") or case_id
    return case, {key: str(value) for key, value in form.items()}


def format_number_display(value, max_decimals: int = 2) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    try:
        decimal = Decimal(text.replace(",", ""))
    except (InvalidOperation, ValueError):
        return text
    if decimal == decimal.to_integral():
        return f"{int(decimal):,}"
    max_decimals = max(0, min(int(max_decimals), 8))
    quant = Decimal("1").scaleb(-max_decimals)
    rounded = decimal.quantize(quant, rounding=ROUND_HALF_UP)
    return f"{rounded:,.{max_decimals}f}".rstrip("0").rstrip(".")


templates.env.filters["number"] = format_number_display


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.middleware("http")
async def require_data_hub_auth(request: Request, call_next):
    redirect = co_auth.guard_response(request)
    if redirect:
        return redirect
    co_auth.load_optional_user(request)
    token_context = None
    user = co_auth.current_user(request)
    if user and user.access_token:
        token_context = set_current_data_hub_token(user.access_token)
    try:
        return await call_next(request)
    finally:
        if token_context:
            reset_current_data_hub_token(token_context)

BCCT_COLUMNS = [
    {"key": "coverage_period", "label": "Kỳ"},
    {"key": "declaration_no", "label": "Tờ khai", "class": "mono"},
    {"key": "line_no", "label": "STT", "class": "mono"},
    {"key": "declaration_type", "label": "LH", "class": "mono"},
    {"key": "direction_label", "label": "Luồng"},
    {"key": "item_code", "label": "Mã hàng", "class": "mono"},
    {"key": "hs_code", "label": "HS", "class": "mono"},
    {"key": "quantity", "label": "Số lượng", "class": "num"},
    {"key": "unit", "label": "ĐVT", "class": "mono"},
    {"key": "customs_value", "label": "Trị giá", "class": "num"},
    {"key": "invoice_ref", "label": "Hóa đơn", "class": "mono"},
]

CO_CASE_WORKFLOW_STEP_KEYS = {step["key"] for step in CO_CASE_WORKFLOW_STEPS}

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

BOM_PRODUCT_COLUMNS = [
    {"key": "product_code", "label": "Mã TP", "class": "mono", "link_key": "view_href"},
    {"key": "product_artifact_no", "label": "TP artifact", "class": "mono"},
    {"key": "row_count", "label": "Dòng BOM", "class": "num"},
    {"key": "status", "label": "Trạng thái"},
    {"key": "version_hash_short", "label": "Hash", "class": "mono"},
]

BOM_LINE_COLUMNS = [
    {"key": "material_code", "label": "Mã NVL", "class": "mono"},
    {"key": "material_name", "label": "Tên NVL"},
    {"key": "qty_per", "label": "Định mức", "class": "num"},
    {"key": "uom", "label": "ĐVT", "class": "mono"},
    {"key": "scrap_rate", "label": "Hao hụt", "class": "num"},
    {"key": "source", "label": "Nguồn"},
    {"key": "row_class", "label": "Trạng thái"},
]




def record_sheet_lock_claims(client_id: str, case_id: str, product_code: str, case: dict) -> int:
    """Persist allocation lines from a locked sheet to the cross-case stock ledger.

    Reads the sheet's products[*].materials[*].allocation_lines and writes one
    claim per (source_row, material_code) so other cases see remaining_qty drop.
    Idempotent: re-locking the same sheet replaces prior claims for it.

    `case` may be the form-rebuilt case (which strips allocation_lines), so
    fall back to the persisted case from disk to get the canonical allocations.
    """
    target = _sheet_with_allocations(client_id, case_id, product_code, case)
    if not target:
        return 0
    allocations: list[dict] = []
    for material_index, material in enumerate(target.get("materials", []) or []):
        material_code = str(material.get("material_code") or material.get("internal_material_code") or "").strip()
        for line in material.get("allocation_lines", []) or []:
            allocations.append({
                "source_row": line.get("source_row", ""),
                "material_code": material_code,
                "material_index": material_index,
                "claimed_qty": line.get("allocated_qty", "0"),
                "declaration_no": line.get("import_declaration_no", ""),
                "line_no": line.get("import_line_no", ""),
                "customs_code": line.get("customs_material_code", "") or line.get("customs_code", ""),
            })
    return co_stock_ledger.record_sheet_lock(client_id, case_id, product_code, allocations)


def _sheet_with_allocations(client_id: str, case_id: str, product_code: str, case: dict) -> dict | None:
    """Pick the product entry, preferring the in-memory case but falling back to
    the persisted record on disk if its materials lack allocation_lines."""

    def _find(case_obj: dict | None) -> dict | None:
        if not case_obj:
            return None
        return next(
            (p for p in case_obj.get("products", []) if str(p.get("code") or "").strip() == product_code),
            None,
        )

    target = _find(case)
    if target and any(material.get("allocation_lines") for material in target.get("materials", []) or []):
        return target
    try:
        client = resolve_client(client_id)
        persisted = persisted_origin_case(client, case_id)
    except Exception:  # noqa: BLE001
        return target
    persisted_target = _find(persisted)
    return persisted_target or target


def invalidate_co_case_source_cache(client_id: str = "", case_id: str = "") -> None:
    """Clear cache entries — call when case mutates (lock, override, etc.)."""
    if not client_id and not case_id:
        _CO_CASE_SOURCE_CACHE.clear()
        return
    keys_to_drop = [
        key for key in _CO_CASE_SOURCE_CACHE
        if (not client_id or key[0] == client_id) and (not case_id or key[1] == case_id)
    ]
    for key in keys_to_drop:
        _CO_CASE_SOURCE_CACHE.pop(key, None)


def invoice_matches_only(client: dict, shipment: dict) -> list[dict]:
    """Lightweight invoice-match lookup for invoice-preview / search dropdown.

    File-store mode: falls through to match_case_bcct_exports (in-memory,
    surfaces invoice/declaration mismatch warnings).
    Data Hub mode: calls invoice_matches adapter directly (~300-500ms),
    avoiding the full materials + BCCT pagination that co_case_source_context
    would otherwise trigger on every keystroke for big clients.
    """
    invoice_no = str(shipment.get("invoice_no") or "").strip()
    declaration_nos = declaration_refs(shipment.get("export_declaration_nos"))
    data_hub = getattr(portfolio_service, "data_hub", None)
    if data_hub is None or not hasattr(data_hub, "invoice_matches"):
        # File-store / test mode: defer to the existing co_case_source_context
        # (in-memory or fake), which surfaces market_hint + reference_warning
        # via the canonical match path.
        try:
            source_context = co_case_source_context(client, {"shipment": shipment})
        except Exception:  # noqa: BLE001
            source_context = {}
        return source_context.get("invoice_matches") or []
    # Data Hub mode: exact-invoice lookup is indexed.
    try:
        client_config = portfolio_service.get_client_config(client) if hasattr(portfolio_service, "get_client_config") else {}
    except Exception:  # noqa: BLE001
        client_config = {}
    relevant_types = list(client_config.get("bcct", {}).get("relevant_export_declaration_types", []))
    matches: list[dict] = []
    if invoice_no:
        try:
            matches = data_hub.invoice_matches(client["id"], invoice_no, relevant_types)
        except Exception:  # noqa: BLE001
            matches = []
    if declaration_nos and not matches:
        for declaration in declaration_nos:
            matches.extend(declaration_invoice_matches(client, declaration, exact=True, include_invoice=False))
    elif declaration_nos and matches:
        wanted = {re.sub(r"[^A-Z0-9]", "", str(decl).upper()) for decl in declaration_nos}
        matches = [
            row for row in matches
            if re.sub(r"[^A-Z0-9]", "", str(row.get("declaration_no") or "").upper()) in wanted
        ] or matches
    return matches


def preload_co_case_origin_context(client_id: str, case_id: str) -> None:
    client = resolve_client(client_id)
    try:
        record = get_case_record(client, case_id)
    except KeyError:
        return
    if record.get("source_snapshot") and record.get("products"):
        return
    context = co_case_context(
        client_id,
        case_id,
        current_step="origin",
        origin_demo_allowed=False,
        force_source_refresh=True,
    )
    if context.get("origin_demo_active"):
        return
    try:
        update_case_record(client, context["case"])
    except KeyError:
        return


def invoice_lookup_payload(client: dict, invoice_no: str, query: str = "", export_declaration_nos: str | list[str] = "") -> dict:
    invoice_no = str(invoice_no or "").strip()
    declaration_nos = declaration_refs(export_declaration_nos)
    query = str(query or invoice_no or (declaration_nos[0] if declaration_nos else "")).strip()
    options = invoice_search_options(client, query)
    if not invoice_no and not declaration_nos:
        return {
            "status": "empty",
            "invoice_no": "",
            "reference_warnings": [],
            "options": options,
            "match_count": 0,
            "matches": [],
            "summary": {},
            "market_inference": market_inference_view({"status": "missing", "destination_market": "", "hints": []}),
            "suggested_forms": [],
        }
    resolved = resolve_shipment_reference(client, invoice_no, declaration_nos)
    lookup_invoice_no = resolved["invoice_no"]
    try:
        # Lightweight match path — invoice-preview only needs invoice_matches.
        # Calling co_case_source_context here would full-paginate materials + BCCT
        # from Data Hub on every keystroke (seconds per request for large clients).
        invoice_matches = invoice_matches_only(client, resolved["shipment"])
    except Exception as exc:
        return {
            "status": "error",
            "invoice_no": lookup_invoice_no,
            "reference_warnings": [],
            "options": options,
            "match_count": 0,
            "matches": [],
            "summary": {},
            "market_inference": market_inference_view({"status": "missing", "destination_market": "", "hints": []}),
            "suggested_forms": [],
            "message": f"Không tra được invoice: {exc}",
        }
    payload = invoice_preview_from_matches(lookup_invoice_no, invoice_matches)
    payload["reference_warnings"] = shipment_reference_warnings(
        resolved["shipment"],
        invoice_matches,
    )
    payload["options"] = options
    if resolved.get("source_reference"):
        payload["source_reference"] = resolved["source_reference"]
        payload["source_reference_type"] = resolved["source_reference_type"]
        payload["reference_label"] = primary_shipment_reference(resolved["shipment"])
        if not payload.get("invoice_no"):
            payload["invoice_no"] = resolved["source_reference"]
    return payload


def resolve_shipment_reference(client: dict, reference: str, export_declaration_nos: str | list[str] = "") -> dict:
    reference = str(reference or "").strip()
    explicit_declarations = declaration_refs(export_declaration_nos)
    if explicit_declarations:
        matches = []
        for declaration in explicit_declarations:
            matches.extend(declaration_invoice_matches(client, declaration, exact=True, include_invoice=False))
        invoice_refs = sorted({row.get("invoice_ref", "") for row in matches if row.get("invoice_ref")})
        invoice_no = reference if reference and not declaration_invoice_matches(client, reference, exact=True, include_invoice=False) else ""
        if len(invoice_refs) == 1:
            invoice_no = invoice_no or invoice_refs[0]
        return {
            "invoice_no": invoice_no,
            "export_declaration_nos": explicit_declarations,
            "source_reference": ", ".join(explicit_declarations),
            "source_reference_type": "declaration",
            "shipment": {"invoice_no": invoice_no, "export_declaration_nos": explicit_declarations},
        }
    if not reference:
        return {
            "invoice_no": "",
            "export_declaration_nos": [],
            "source_reference": "",
            "source_reference_type": "",
            "shipment": {"invoice_no": "", "export_declaration_nos": []},
        }
    matches = declaration_invoice_matches(client, reference, exact=True, include_invoice=False)
    if matches:
        invoice_refs = sorted({row["invoice_ref"] for row in matches if row.get("invoice_ref")})
        invoice_no = invoice_refs[0] if len(invoice_refs) == 1 else ""
        return {
            "invoice_no": invoice_no,
            "export_declaration_nos": [reference],
            "source_reference": reference,
            "source_reference_type": "declaration",
            "shipment": {"invoice_no": invoice_no, "export_declaration_nos": [reference]},
        }
    return {
        "invoice_no": reference,
        "export_declaration_nos": [],
        "source_reference": "",
        "source_reference_type": "",
        "shipment": {"invoice_no": reference, "export_declaration_nos": []},
    }


def resolve_invoice_reference(client: dict, reference: str) -> dict:
    resolved = resolve_shipment_reference(client, reference)
    return {
        "invoice_no": resolved["invoice_no"],
        "source_reference": resolved["source_reference"],
        "source_reference_type": resolved["source_reference_type"],
    }


def invoice_search_options(client: dict, query: str, limit: int = 10) -> list[dict]:
    query = str(query or "").strip()
    if len(query) < 2:
        return []
    # Use Data Hub invoice-matches adapter when available — it's an indexed
    # query (~300-500ms typical) instead of pulling the full BCCT pagination
    # for every keystroke. Falls back to local indexed lookup only when the
    # Data Hub adapter is not present (file-store mode).
    data_hub = getattr(portfolio_service, "data_hub", None)
    if data_hub is not None and hasattr(data_hub, "invoice_matches"):
        try:
            rows = data_hub.invoice_matches(client["id"], query, [])
        except Exception:  # noqa: BLE001
            rows = []
        if not rows and hasattr(data_hub, "list_bcct"):
            # Try declaration-number lookup (declaration_no exact prefix).
            compact = re.sub(r"[^A-Z0-9]", "", query.upper())
            try:
                bcct_rows = data_hub.list_bcct(client["id"], declaration_no=compact, direction="export")
            except TypeError:
                bcct_rows = []
            except Exception:  # noqa: BLE001
                bcct_rows = []
            rows = [row for row in bcct_rows if row.get("review_status") in ("", "reviewed")]
    else:
        rows = declaration_invoice_matches(client, query, exact=False)
    groups: dict[str, dict] = {}
    for row in rows:
        invoice_ref = row.get("invoice_ref", "")
        option_value = invoice_ref or row.get("declaration_no", "")
        group = groups.setdefault(
            option_value,
            {
                "invoice_no": option_value,
                "row_count": 0,
                "declarations": set(),
                "hs_codes": set(),
                "item_codes": set(),
            },
        )
        group["row_count"] += 1
        if row.get("declaration_no"):
            group["declarations"].add(str(row.get("declaration_no")))
        if row.get("hs_code"):
            group["hs_codes"].add(str(row.get("hs_code")))
        if row.get("item_code"):
            group["item_codes"].add(str(row.get("item_code")))
    options = []
    for group in groups.values():
        options.append({
            "invoice_no": group["invoice_no"],
            "row_count": group["row_count"],
            "declaration_count": len(group["declarations"]),
            "declarations": sorted(group["declarations"])[:4],
            "hs_codes": sorted(group["hs_codes"])[:6],
            "item_codes": sorted(group["item_codes"])[:4],
        })
    return sorted(options, key=lambda row: (-int(row["row_count"]), row["invoice_no"]))[:limit]


def declaration_invoice_matches(client: dict, query: str, exact: bool, include_invoice: bool = True) -> list[dict]:
    query = str(query or "").strip()
    if len(query) < 2:
        return []
    # Fast path for Data Hub mode: indexed invoice/declaration lookup, no
    # full-catalog pagination. Falls back to in-memory workspace for file-store
    # / test mode.
    data_hub = getattr(portfolio_service, "data_hub", None)
    if data_hub is not None and hasattr(data_hub, "invoice_matches"):
        try:
            client_config = portfolio_service.get_client_config(client) if hasattr(portfolio_service, "get_client_config") else {}
        except Exception:  # noqa: BLE001
            client_config = {}
        relevant_types_list = list(client_config.get("bcct", {}).get("relevant_export_declaration_types", []))
        rows: list[dict] = []
        if include_invoice:
            try:
                rows = list(data_hub.invoice_matches(client["id"], query, relevant_types_list))
            except Exception:  # noqa: BLE001
                rows = []
        # Declaration lookup — list_bcct accepts declaration_no kwarg on Data Hub.
        if hasattr(data_hub, "list_bcct"):
            compact = re.sub(r"[^A-Z0-9]", "", query.upper())
            try:
                decl_rows = list(data_hub.list_bcct(client["id"], declaration_no=compact, direction="export"))
            except Exception:  # noqa: BLE001
                decl_rows = []
            seen = {(row.get("declaration_no"), row.get("line_no"), row.get("transaction_key")) for row in rows}
            for row in decl_rows:
                key = (row.get("declaration_no"), row.get("line_no"), row.get("transaction_key"))
                if key not in seen:
                    rows.append(row)
                    seen.add(key)
        return rows
    try:
        source_workspace, _source_backend = source_workspace_for_client(client)
    except Exception:
        return []
    client_config = source_workspace.get("client_config", {})
    relevant_types = set(client_config.get("bcct", {}).get("relevant_export_declaration_types", []))
    query_keys = invoice_keys(query)
    query_compact = next(iter(query_keys), re.sub(r"[^A-Z0-9]", "", query.upper()))
    matches = []
    for row in source_workspace.get("bcct", {}).get("published_rows", []):
        if row.get("direction") != "export":
            continue
        if row.get("review_status") not in ("", "reviewed"):
            continue
        if relevant_types and row.get("declaration_type") not in relevant_types:
            continue
        invoice_ref = str(row.get("invoice_ref") or "").strip()
        row_keys = invoice_keys(invoice_ref)
        row_compact = re.sub(r"[^A-Z0-9]", "", invoice_ref.upper())
        declaration_compact = re.sub(r"[^A-Z0-9]", "", str(row.get("declaration_no") or "").upper())
        invoice_matches = include_invoice and query_compact and (query_compact in row_compact or bool(query_keys.intersection(row_keys)))
        declaration_matches = (
            query_compact == declaration_compact
            if exact
            else query_compact and query_compact in declaration_compact
        )
        if not invoice_matches and not declaration_matches:
            continue
        matches.append({**row, "invoice_ref": invoice_ref})
    return matches


def recalculate_origin_sheet_edits(client: dict, case: dict, product_code: str, *, min_gap_days: int | None = None) -> dict:
    """Recompute one sheet from its saved sheet edits, without changing BOM selection."""
    prepared = attach_origin_sheet_states(case)
    products = prepared.get("products", [])
    target_index = next(
        (index for index, product in enumerate(products) if str(product.get("code") or "").strip() == product_code),
        None,
    )
    if target_index is None:
        return prepared
    target = products[target_index]
    overrides = target.get("origin_sheet_material_overrides") or {}
    if not overrides:
        return prepared

    sheet_rows = sheet_edit_bom_rows(target, overrides)
    material_codes = sorted({
        str(row.get("material_code") or "").strip()
        for row in sheet_rows
        if str(row.get("material_code") or "").strip()
    })
    source_context = {"material_rows": [], "stock_rows": []}
    stock_rows: list[dict] = []
    try:
        narrow_rows = portfolio_service.list_bcct_by_codes(client.get("id", ""), material_codes, direction="import")
    except Exception:  # noqa: BLE001
        narrow_rows = []
    if narrow_rows:
        try:
            client_config = portfolio_service.get_client_config(client) if hasattr(portfolio_service, "get_client_config") else {}
            stock_rows = co_stock_rows_from_bcct(narrow_rows, client_config)
        except Exception:  # noqa: BLE001
            stock_rows = []
    if not stock_rows and not co_auth.data_hub_source_mode_enabled():
        try:
            source_context = co_case_source_context_cached(client, prepared)
            stock_rows = source_context.get("stock_rows") or []
        except Exception:  # noqa: BLE001
            source_context = {"material_rows": [], "stock_rows": []}
            stock_rows = []
    material_index = material_catalog_index(source_context.get("material_rows") or [])
    cached_matches = case.get("source_invoice_matches") if isinstance(case.get("source_invoice_matches"), list) else []
    stock_pool = case_allocation_pool(prepared, cached_matches, stock_rows, min_gap_days=min_gap_days)
    for previous in products[:target_index]:
        apply_existing_origin_product_consumption(previous, stock_pool)

    form_lane = recommended_form_lane(
        prioritized_form_lanes(prepared.get("destination_market", ""), [str(target.get("finished_hs") or "")])
    )
    recalculated = origin_product_from_invoice_match(
        origin_match_from_existing_product(target),
        sheet_rows,
        form_lane,
        material_index,
        stock_pool,
        product_sequence=target_index + 1,
        bom_product_code=str(target.get("bom_product_code") or target.get("code") or ""),
    )
    for key in [
        "bom_product_artifact_id",
        "bom_product_artifact_no",
        "bom_product_version_id",
        "bom_product_version_no",
    ]:
        if target.get(key) and not recalculated.get(key):
            recalculated[key] = target.get(key)

    updated_products = [dict(product) for product in products]
    updated_products[target_index] = recalculated
    prepared["products"] = updated_products
    return attach_origin_sheet_states(prepared)


def sheet_edit_bom_rows(product: dict, overrides: dict) -> list[dict]:
    rows: list[dict] = []
    materials = product.get("materials") or []
    for index, material in enumerate(materials):
        override = overrides.get(str(index)) if isinstance(overrides.get(str(index)), dict) else {}
        if override.get("deleted"):
            continue
        replacement_code = str(override.get("material_code") or "").strip()
        original_code = str(material.get("material_code") or material.get("internal_material_code") or "").strip()
        material_code = replacement_code or original_code
        if not material_code:
            continue
        row = {
            "product_code": product.get("bom_product_code") or product.get("code") or "",
            "material_code": material_code,
            "qty_per": str(override.get("norm_per_unit") or material.get("bom_qty_per") or "0"),
            "uom": str(override.get("uom") or material.get("uom") or ""),
            "material_name": str(override.get("name") or ("" if replacement_code else material.get("material_description")) or ""),
            "hs_code": str(override.get("hs_code") or ("" if replacement_code else material.get("hs_code")) or ""),
            "source": material.get("bom_source") or material.get("source_document_ref") or "sheet_edit",
            "row_class": material.get("bom_row_class") or "",
        }
        if not replacement_code:
            row["unit_value"] = material.get("unit_value", "")
        rows.append(row)
    added_items = [
        (key, value)
        for key, value in overrides.items()
        if str(key).startswith("added_") and isinstance(value, dict) and value.get("material_code")
    ]
    added_items.sort(key=lambda item: numeric_sort_text(str(item[0]).split("_", 1)[1] if "_" in str(item[0]) else "0"))
    for _key, value in added_items:
        rows.append({
            "product_code": product.get("bom_product_code") or product.get("code") or "",
            "material_code": str(value.get("material_code") or "").strip(),
            "qty_per": str(value.get("norm_per_unit") or "0"),
            "uom": str(value.get("uom") or ""),
            "material_name": str(value.get("name") or ""),
            "hs_code": str(value.get("hs_code") or ""),
            "source": "sheet_edit_added",
            "row_class": "added",
        })
    return rows


def _hydrate_product_export_declaration_dates(case: dict, client: dict | None = None) -> None:
    """Backfill missing `product.source_declaration_date` from cached matches,
    falling back to Data Hub `list_declarations` for cases saved before
    `enrich_invoice_matches_with_bcct` started forwarding `declaration_date`.

    Read-only patch — operator overrides on `case["products"]` are untouched.
    Cached `case["source_invoice_matches"]` is updated in place so the next
    `update_case_record` call (typically right after export prep) persists the
    backfill, making future renders free.
    """
    products = [p for p in (case.get("products") or []) if not p.get("source_declaration_date")]
    if not products:
        return

    matches = case.get("source_invoice_matches") if isinstance(case.get("source_invoice_matches"), list) else []
    by_decl: dict[str, str] = {}
    for row in matches:
        decl = str(row.get("declaration_no") or "").strip()
        if not decl or decl in by_decl:
            continue
        value = str(row.get("declaration_date") or row.get("registration_date") or "").strip()
        if value:
            by_decl[decl] = value

    missing: list[str] = []
    for product in products:
        decl = str(product.get("source_declaration_no") or "").strip()
        if decl and decl not in by_decl:
            missing.append(decl)

    if missing and client and client.get("id"):
        dates = _fetch_export_declaration_dates(client["id"], sorted(set(missing)))
        by_decl.update({k: v for k, v in dates.items() if v})
        if dates and matches:
            for row in matches:
                decl = str(row.get("declaration_no") or "").strip()
                if decl and not row.get("declaration_date") and dates.get(decl):
                    row["declaration_date"] = dates[decl]

    if not by_decl:
        return
    for product in products:
        decl = str(product.get("source_declaration_no") or "").strip()
        if decl and decl in by_decl:
            product["source_declaration_date"] = by_decl[decl]


def _fetch_export_declaration_dates(client_id: str, declaration_nos: list[str]) -> dict[str, str]:
    """Resolve `earliest_bcct_date` per export declaration_no from Data Hub.

    Returns mapping {declaration_no: "YYYY-MM-DD"}. Empty dict on any error or
    when the active portfolio service doesn't wrap a Data Hub client.
    """
    data_hub = getattr(portfolio_service, "data_hub", None)
    if data_hub is None or not declaration_nos:
        return {}
    try:
        rows = data_hub.list_declarations(
            client_id,
            direction="export",
            declaration_nos=declaration_nos,
        )
    except Exception:  # noqa: BLE001 — best-effort backfill; export must not block
        return {}
    out: dict[str, str] = {}
    for row in rows or []:
        decl = str(row.get("declaration_no") or "").strip()
        date = str(row.get("earliest_bcct_date") or "").strip()
        if decl and date:
            out[decl] = _to_vietnamese_date(date)
    return out


def _to_vietnamese_date(value: str) -> str:
    """Convert "YYYY-MM-DD" (Data Hub ISO) to "DD/MM/YYYY" (bảng kê format)."""
    text = value.strip()
    if not text:
        return ""
    try:
        from datetime import date
        d = date.fromisoformat(text[:10])
        return d.strftime("%d/%m/%Y")
    except ValueError:
        return text


def _hydrate_material_dates_from_stock(case: dict, client: dict) -> None:
    """Backfill missing `import_declaration_date` on materials + allocation lines.

    Materials/allocations saved before `co_stock_rows_from_bcct` started
    copying `registration_date` out of the BCCT payload have empty date
    fields, which leaves col "Ngày" blank on the exported xlsx. Re-running
    Calculate would refresh the snapshot but also wipes operator overrides
    (delete/substitute/norm/added rows), so we look up dates from the
    materialized stock table here instead — read-only, no override loss.
    """
    client_id = str(client.get("id") or "").strip()
    if not client_id:
        return
    rows_to_lookup: set[str] = set()
    for product in case.get("products") or []:
        for material in product.get("materials") or []:
            if not (material.get("import_declaration_date")
                    or material.get("declaration_date")
                    or material.get("registration_date")):
                source_row = str(material.get("source_row") or "").strip()
                if source_row:
                    rows_to_lookup.add(source_row)
            for allocation in material.get("allocation_lines") or []:
                if not (allocation.get("import_declaration_date")
                        or allocation.get("declaration_date")
                        or allocation.get("registration_date")):
                    source_row = str(allocation.get("source_row") or "").strip()
                    if source_row:
                        rows_to_lookup.add(source_row)
    if not rows_to_lookup:
        return
    dates = co_stock_materializer.registration_dates_for_source_rows(client_id, list(rows_to_lookup))
    if not dates:
        return
    for product in case.get("products") or []:
        for material in product.get("materials") or []:
            if not material.get("import_declaration_date"):
                joined = []
                source_row = str(material.get("source_row") or "").strip()
                for piece in [p.strip() for p in source_row.split(",") if p.strip()]:
                    value = dates.get(piece)
                    if value and value not in joined:
                        joined.append(value)
                if joined:
                    material["import_declaration_date"] = ", ".join(joined)
            for allocation in material.get("allocation_lines") or []:
                if not allocation.get("import_declaration_date"):
                    value = dates.get(str(allocation.get("source_row") or "").strip())
                    if value:
                        allocation["import_declaration_date"] = value


def set_origin_sheet_status(case: dict, product_code: str, status: str) -> dict:
    if status not in ORIGIN_SHEET_STATUS_LABELS:
        status = "draft"
    states = dict(case.get("origin_sheet_states") or {})
    previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
    states[product_code] = {
        **previous,
        "status": status,
        "status_label": ORIGIN_SHEET_STATUS_LABELS[status],
    }
    prepared = dict(case)
    prepared["origin_sheet_states"] = states
    return attach_origin_sheet_states(prepared)


def reject_if_sheet_locked(case: dict, product_code: str) -> None:
    """Refuse material/norm mutations on a sheet whose status is `locked`.

    The UI hides the edit buttons when locked (`co_case.html` + JS gate from
    commit `0ca012a`), but those guards can be bypassed by direct POST. Without
    this server check, mutating a locked sheet would leave the ledger holding
    `co_stock_claims` for the old materials while the persisted sheet now lists
    the new ones — a quiet Tồn CO leak. Operator must Mở chốt the sheet first.
    """
    state = (case.get("origin_sheet_states") or {}).get(product_code, {}) or {}
    if state.get("status") == "locked":
        raise HTTPException(
            status_code=409,
            detail=f"Sheet {product_code} đã chốt; mở chốt trước khi sửa NVL.",
        )


def mark_origin_sheets_stale(case: dict, from_index: int) -> dict:
    prepared = attach_origin_sheet_states(case)
    states = dict(prepared.get("origin_sheet_states") or {})
    for index, product in enumerate(prepared.get("products", [])):
        code = str(product.get("code") or "").strip()
        current_status = str(product.get("origin_sheet_status") or "").strip()
        if code and index >= max(from_index, 0) and current_status != "draft":
            previous = states.get(code) if isinstance(states.get(code), dict) else {}
            states[code] = {
                **previous,
                "status": "stale",
                "status_label": ORIGIN_SHEET_STATUS_LABELS["stale"],
            }
    prepared["origin_sheet_states"] = states
    return attach_origin_sheet_states(prepared)


def set_origin_sheet_config_override(
    case: dict, product_code: str, overrides: dict
) -> dict:
    states = dict(case.get("origin_sheet_states") or {})
    previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
    sanitized = {**previous}
    if "form_override" in overrides:
        sanitized["form_override"] = str(overrides.get("form_override") or "").strip()
    if "criteria_override" in overrides:
        sanitized["criteria_override"] = str(overrides.get("criteria_override") or "").strip()
    if "lvc_threshold_override" in overrides:
        sanitized["lvc_threshold_override"] = normalize_threshold(overrides.get("lvc_threshold_override"))
    if "rvc_threshold_override" in overrides:
        sanitized["rvc_threshold_override"] = normalize_threshold(overrides.get("rvc_threshold_override"))
    if "currency_mode" in overrides:
        mode = str(overrides.get("currency_mode") or "").strip().lower()
        sanitized["currency_mode"] = mode if mode in SHEET_CURRENCY_MODES else "native"
    if "optimization_mode" in overrides:
        mode = str(overrides.get("optimization_mode") or "").strip().lower()
        sanitized["optimization_mode"] = mode if mode in SHEET_OPTIMIZATION_MODES else "max_lvc"
    states[product_code] = sanitized
    prepared = dict(case)
    prepared["origin_sheet_states"] = states
    return attach_origin_sheet_states(prepared)


def co_stock_index(stock_rows: list[dict]) -> dict[str, dict]:
    output = {}
    for row in stock_rows:
        for key in co_stock_key_candidates(row):
            existing = output.get(key)
            if existing is None or co_stock_rank(row) > co_stock_rank(existing):
                output[key] = row
    return output


def co_stock_rank(row: dict) -> tuple[bool, bool, bool]:
    return (
        co_stock_is_usable(row),
        decimal_value(row.get("remaining_qty") or row.get("available_qty") or "0") > 0,
        co_stock_has_value(row),
    )


def first_decimal_value(*values) -> Decimal | None:
    for value in values:
        if value not in (None, ""):
            return decimal_value(value)
    return None


def bcct_table_context(request: Request, client_id: str, direction: str | None = None, **extra) -> dict:
    lean = _data_hub_overview_context(client_id, "bcct", dh_path="bcct")
    if lean is not None and not extra.get("bcct_result"):
        lean["bcct_view"] = direction or "all"
        title_by_direction = {"import": "BCCT nhập khẩu", "export": "BCCT xuất khẩu"}
        lean["bcct_title"] = title_by_direction.get(direction, "BCCT nhập khẩu / xuất khẩu")
        return lean
    context = client_context(client_id, "bcct", **extra)
    rows = [bcct_table_row(row) for row in context["source_workspace"]["bcct"]["published_rows"]]
    if direction:
        rows = [row for row in rows if row.get("direction") == direction]
    if direction == "export":
        relevant_types = set(context["client_config"]["bcct"].get("relevant_export_declaration_types", []))
        if relevant_types:
            rows = [row for row in rows if row.get("declaration_type") in relevant_types]
    context["bcct_view"] = direction or "all"
    title_by_direction = {"import": "BCCT nhập khẩu", "export": "BCCT xuất khẩu"}
    context["bcct_title"] = title_by_direction.get(direction, "BCCT nhập khẩu / xuất khẩu")
    context["source_table"] = build_table_view(
        rows,
        columns=BCCT_COLUMNS,
        query=request.query_params,
        filters=[
            {
                "name": "direction",
                "field": "direction",
                "label": "Luồng",
                "options": [
                    {"value": "import", "label": "Nhập khẩu"},
                    {"value": "export", "label": "Xuất khẩu"},
                ],
            },
            {"name": "type", "field": "declaration_type", "label": "Loại hình"},
            {"name": "hs", "field": "hs_code", "label": "HS"},
            {"name": "origin", "field": "origin_country", "label": "Xuất xứ"},
        ],
        summary_fields=[
            {"field": "direction_label", "label": "Luồng"},
            {"field": "declaration_type", "label": "Loại hình"},
        ],
        default_sort="declaration_no",
    )
    return context


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
    return {
        "client": client,
        "active": "co-stock",
        "source_backend": source_backend,
        "client_config": client_config,
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
    # Apply ledger + adjustments only to the visible page.
    if page_rows:
        used_by_lot = co_stock_ledger.used_qty_by_lot(client["id"])
        if used_by_lot:
            page_rows = co_stock_ledger.apply_used_qty(page_rows, used_by_lot)
        adjustments = co_stock_adjustments_store.aggregate_by_lookup_key(client["id"])
        if adjustments:
            page_rows = co_stock_adjustments_store.apply_adjustments(page_rows, adjustments)
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


def bom_context(request: Request, client_id: str, **extra) -> dict:
    lean = _data_hub_overview_context(client_id, "bom", dh_path="bom")
    if lean is not None and not extra.get("message") and not extra.get("error"):
        # DH mode: BOM is read-only; CO renders summary + link rather than
        # paginating the full bom_workspace (which fetches every product
        # version + line over HTTP from Data Hub).
        return lean
    context = client_context(client_id, "bom", **extra)
    workspace = context["bom_workspace"]
    selected_product = selected_bom_product(workspace, request.query_params.get("product", ""))
    product_rows = bom_product_table_rows(workspace, client_id, selected_product)
    line_rows = [
        bom_line_table_row(row)
        for row in workspace.get("latest_rows", [])
        if not selected_product or row.get("product_code") == selected_product
    ]
    product_table = build_table_view(
        product_rows,
        columns=BOM_PRODUCT_COLUMNS,
        query=request.query_params,
        filters=[{"name": "status", "field": "status", "label": "Trạng thái"}],
        summary_fields=[{"field": "status", "label": "Trạng thái"}],
        default_sort="product_code",
        default_per_page=25,
        param_prefix="tp_",
    )
    product_table["search_placeholder"] = "Mã thành phẩm, version, hash..."
    line_table = build_table_view(
        line_rows,
        columns=BOM_LINE_COLUMNS,
        query=request.query_params,
        filters=[
            {"name": "uom", "field": "uom", "label": "ĐVT"},
            {"name": "source", "field": "source", "label": "Nguồn"},
            {"name": "status", "field": "row_class", "label": "Trạng thái"},
        ],
        summary_fields=[
            {"field": "row_class", "label": "Trạng thái"},
            {"field": "uom", "label": "ĐVT"},
        ],
        default_sort="material_code",
        default_per_page=50,
        param_prefix="line_",
    )
    line_table["search_placeholder"] = "Mã NVL, tên NVL, trạng thái..."
    context["selected_bom_product"] = selected_product
    context["selected_bom_product_summary"] = next(
        (row for row in product_rows if row["product_code"] == selected_product),
        {},
    )
    context["bom_product_table"] = product_table
    context["bom_line_table"] = line_table
    return context


def selected_bom_product(workspace: dict, requested_product: str = "") -> str:
    codes = sorted({str(row.get("product_code", "")) for row in workspace.get("product_composition", []) if row.get("product_code")})
    if not codes:
        codes = sorted({str(row.get("product_code", "")) for row in workspace.get("latest_rows", []) if row.get("product_code")})
    requested = str(requested_product or "").strip()
    if requested in codes:
        return requested
    return codes[0] if codes else ""


def bom_product_table_rows(workspace: dict, client_id: str, selected_product: str) -> list[dict]:
    version_index = {
        version.get("product_version_id"): version
        for version in workspace.get("product_versions", [])
        if version.get("product_version_id")
    }
    rows = []
    composition = workspace.get("product_composition", [])
    if not composition:
        composition = [
            {
                "product_code": version.get("product_code", ""),
                "product_version_id": version.get("product_version_id", ""),
                "product_version_no": version.get("product_version_no", ""),
                "row_count": version.get("row_count", 0),
                "status": version.get("status", ""),
                "version_hash": version.get("version_hash", ""),
            }
            for version in workspace.get("product_versions", [])
        ]
    for row in composition:
        version = version_index.get(row.get("product_version_id"), {})
        product_code = str(row.get("product_code", ""))
        version_hash = str(row.get("version_hash") or version.get("version_hash") or "")
        rows.append({
            "product_code": product_code,
            "product_version_no": row.get("product_version_no", version.get("product_version_no", "")),
            "row_count": row.get("row_count", version.get("row_count", 0)),
            "status": row.get("status", version.get("status", "")),
            "version_hash": version_hash,
            "version_hash_short": version_hash[:10],
            "selected": "Đang xem" if product_code == selected_product else "",
            "view_href": f"/clients/{client_id}/bom?product={quote(product_code, safe='')}#bom-lines",
        })
    return rows


def bom_line_table_row(row: dict) -> dict:
    return {
        **row,
        "material_name": row.get("material_name", ""),
        "scrap_rate": row.get("scrap_rate", ""),
        "source": row.get("source", ""),
        "row_class": row.get("row_class", ""),
    }


def config_context(client_id: str, **extra) -> dict:
    # /config only renders client identity + client_config knobs. It does NOT
    # need source_workspace / bom_workspace, so skip the full pagination that
    # client_context triggers (Johnson: ~65k BCCT rows over HTTP per render).
    lean = _data_hub_overview_context(client_id, "config", dh_path="")
    if lean is not None:
        lean.update(extra)
        return lean
    return client_context(client_id, "config", **extra)


def bcct_table_row(row: dict) -> dict:
    direction = row.get("direction", "")
    return {
        **row,
        "direction_label": "Nhập khẩu" if direction == "import" else "Xuất khẩu",
    }


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
    if status == "inactive" and row.get("eligibility_reason") == "excluded_by_declaration_type_config":
        return "Loại hình không active trong config"
    if status == "review_required":
        return row.get("allocation_code_reason") or "Cần review mã phân bổ"
    return row.get("eligibility_reason", "")


@app.get("/", response_class=HTMLResponse)
@app.get("/clients", response_class=HTMLResponse)
async def clients(request: Request):
    clients = portfolio_service.clients()
    if co_auth.auth_required():
        clients = co_auth.filter_visible_clients(clients, co_auth.current_user(request))
    return templates.TemplateResponse(
        request=request,
        name="clients.html",
        context={"clients": clients},
    )


@app.get("/clients/{client_id}", response_class=HTMLResponse)
async def workspace(request: Request, client_id: str):
    # Workspace overview only renders client.counts tiles. Avoid the full
    # source_workspace + bom_service.workspace pagination here — those would
    # paginate every BCCT/material/BOM row from Data Hub on each render.
    return templates.TemplateResponse(
        request=request,
        name="workspace.html",
        context=client_overview_context(client_id),
    )


def client_overview_context(client_id: str) -> dict:
    client = resolve_client(client_id)
    try:
        source_summary, source_backend = portfolio_service.source_summary(client)
    except Exception:  # noqa: BLE001
        source_summary, source_backend = {
            "material_catalog": {"published_row_count": 0},
            "product_catalog": {"published_row_count": 0},
            "bcct": {"published_row_count": 0},
            "co_stock_row_count": 0,
        }, "n/a"
    client = enrich_client_with_source_summary(client, source_summary)
    # Workspace template references client.counts.bom_lines too; surface a
    # zero so the tile renders rather than crashes.
    client["counts"]["bom_lines"] = client["counts"].get("bom_lines", 0)
    return {
        "client": client,
        "case": client_case(client),
        "active": "overview",
        "source_backend": source_backend,
    }


@app.get("/clients/{client_id}/bom", response_class=HTMLResponse)
async def bom(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="bom.html",
        context=bom_context(request, client_id),
    )


@app.post("/clients/{client_id}/bom/config", response_class=HTMLResponse)
async def save_bom_config(request: Request, client_id: str):
    require_local_source_writes()
    client = resolve_client(client_id)
    form = await request.form()
    bom_service.update_config(client, {key: str(value) for key, value in form.items()})
    return templates.TemplateResponse(
        request=request,
        name="bom.html",
        context=bom_context(request, client_id, message="Đã lưu cấu hình BOM cho công ty này."),
    )


@app.get("/clients/{client_id}/config", response_class=HTMLResponse)
async def client_config(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="client_config.html",
        context=config_context(client_id),
    )


@app.post("/clients/{client_id}/config", response_class=HTMLResponse)
async def save_client_config_route(request: Request, client_id: str):
    client = resolve_client(client_id)
    form = await request.form()
    # Identity fields (legal_name / tax_code) are CO-side render metadata, not
    # source data — editable even when Data Hub source-mode is enabled. The
    # `co_stock_min_days_before_export` knob is also CO-side: it controls a
    # local CO eligibility predicate, not anything DH owns, so it persists to
    # the same local overlay without going through `require_local_source_writes`.
    if "legal_name" in form or "tax_code" in form or "co_stock_min_days_before_export" in form:
        client = dict(client)
        if "legal_name" in form:
            client["legal_name"] = str(form.get("legal_name") or "").strip()
        if "tax_code" in form:
            client["tax_code"] = str(form.get("tax_code") or "").strip()
        if "co_stock_min_days_before_export" in form:
            raw = str(form.get("co_stock_min_days_before_export") or "").strip()
            overrides = dict(client.get("co_stock_overrides") or {})
            if raw == "":
                overrides.pop("min_days_before_export", None)
            else:
                try:
                    n = int(raw)
                    if n < 0:
                        n = co_stock_eligibility.DEFAULT_MIN_GAP_DAYS
                except ValueError:
                    n = co_stock_eligibility.DEFAULT_MIN_GAP_DAYS
                overrides["min_days_before_export"] = n
            client["co_stock_overrides"] = overrides
        store = get_app_state_store()
        if store:
            store.upsert_client(client)
    require_local_source_writes()
    config = portfolio_service.get_client_config(client)
    config["co_stock"]["lot_policy"] = str(form.get("co_stock_lot_policy", "line_level"))
    config["allocation_code"]["strategy"] = str(form.get("allocation_code_strategy", "same_as_customs_code"))
    config["allocation_code"]["description_regex"] = str(form.get("description_regex", ""))
    config["allocation_code"]["fallback"] = str(form.get("allocation_code_fallback", "same_as_customs_code"))
    try:
        portfolio_service.save_client_config(client, config)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="client_config.html",
            status_code=400,
            context=config_context(client_id, error=str(exc)),
        )
    portfolio_service.refresh_client_indexes(client)
    return templates.TemplateResponse(
        request=request,
        name="client_config.html",
        context=config_context(client_id, message="Đã lưu cấu hình công ty."),
    )


# ---------- Cost allocation ratios (LVC/RVC cost-buildup auto-fill) ----------


def _decimal_str(value: Decimal) -> str:
    """Render Decimal for the admin form: strip trailing zeros but keep at
    least one digit. Empty for zero (so the placeholder shows)."""
    if value is None or value == 0:
        return ""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _row_for_template(row) -> dict:
    return {
        "product_code": row.product_code,
        "coef_wages_str": _decimal_str(row.coef_wages),
        "coef_welfare_str": _decimal_str(row.coef_welfare),
        "coef_rent_str": _decimal_str(row.coef_rent),
        "coef_depreciation_str": _decimal_str(row.coef_depreciation),
        "coef_other_mfg_str": _decimal_str(row.coef_other_mfg),
        "coef_transport_storage_str": _decimal_str(row.coef_transport_storage),
        "note": row.note,
        "has_value": any([
            row.coef_wages, row.coef_welfare, row.coef_rent,
            row.coef_depreciation, row.coef_other_mfg, row.coef_transport_storage,
            row.note,
        ]),
    }


def _cost_allocation_context(client_id: str, **extra) -> dict:
    """Lightweight context for the cost-allocation admin page.

    Deliberately avoids `client_context()` because that helper pulls the full
    source workspace (BCCT scan ~2.6s on Growatt) which this page does not
    need. We render the nav with no counts; the rest of the template only
    needs client identity + the ratio rows.
    """
    from app import cost_allocation_store
    from app.cost_allocation_store import CostAllocationRow
    client = resolve_client(client_id)
    rows = cost_allocation_store.list_ratios(client_id)
    mode_b = cost_allocation_store.get_mode_b_default(client_id) or CostAllocationRow(product_code="")
    return {
        "client": client,
        "active": "cost-allocation",
        "rows": [_row_for_template(r) for r in sorted(rows, key=lambda r: r.product_code)],
        "mode_b": _row_for_template(mode_b),
        **extra,
    }


def _coef_from_form(form, key: str) -> Decimal:
    raw = str(form.get(key) or "").strip().replace(",", ".")
    if not raw:
        return Decimal(0)
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return Decimal(0)
    return value if value >= 0 else Decimal(0)


@app.get("/clients/{client_id}/cost-allocation", response_class=HTMLResponse)
async def cost_allocation_page(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="cost_allocation.html",
        context=_cost_allocation_context(client_id),
    )


@app.post("/clients/{client_id}/cost-allocation/mode-b", response_class=HTMLResponse)
async def cost_allocation_save_mode_b(request: Request, client_id: str):
    resolve_client(client_id)  # validates client exists
    from app import cost_allocation_store
    form = await request.form()
    row = cost_allocation_store.CostAllocationRow(
        product_code="",
        coef_wages=_coef_from_form(form, "coef_wages"),
        coef_welfare=_coef_from_form(form, "coef_welfare"),
        coef_rent=_coef_from_form(form, "coef_rent"),
        coef_depreciation=_coef_from_form(form, "coef_depreciation"),
        coef_other_mfg=_coef_from_form(form, "coef_other_mfg"),
        coef_transport_storage=_coef_from_form(form, "coef_transport_storage"),
        note=str(form.get("note", "") or "").strip(),
    )
    cost_allocation_store.upsert_ratio(client_id, row)
    return templates.TemplateResponse(
        request=request,
        name="cost_allocation.html",
        context=_cost_allocation_context(client_id, message="Đã lưu hệ số mặc định Mode B."),
    )


@app.post("/clients/{client_id}/cost-allocation/mode-b/delete", response_class=HTMLResponse)
async def cost_allocation_delete_mode_b(request: Request, client_id: str):
    resolve_client(client_id)
    from app import cost_allocation_store
    cost_allocation_store.delete_ratio(client_id, "")
    return templates.TemplateResponse(
        request=request,
        name="cost_allocation.html",
        context=_cost_allocation_context(client_id, message="Đã xóa hệ số mặc định Mode B."),
    )


@app.post("/clients/{client_id}/cost-allocation/row/delete", response_class=HTMLResponse)
async def cost_allocation_delete_row(request: Request, client_id: str, product_code: str = Form(...)):
    resolve_client(client_id)
    from app import cost_allocation_store
    cost_allocation_store.delete_ratio(client_id, product_code.strip())
    return templates.TemplateResponse(
        request=request,
        name="cost_allocation.html",
        context=_cost_allocation_context(client_id, message=f"Đã xóa hệ số cho {product_code}."),
    )


@app.post("/clients/{client_id}/cost-allocation/upload", response_class=HTMLResponse)
async def cost_allocation_upload(request: Request, client_id: str, file: UploadFile = File(...)):
    resolve_client(client_id)
    from app import cost_allocation_store, cost_allocation_importer
    try:
        parsed = cost_allocation_importer.parse_excel(await file.read())
    except Exception as exc:  # noqa: BLE001
        return templates.TemplateResponse(
            request=request,
            name="cost_allocation.html",
            status_code=400,
            context=_cost_allocation_context(client_id, error=f"Không đọc được file: {exc}"),
        )
    diff = cost_allocation_store.replace_all(client_id, parsed)
    return templates.TemplateResponse(
        request=request,
        name="cost_allocation.html",
        context=_cost_allocation_context(
            client_id,
            message=f"Đã import {len(parsed)} dòng từ {file.filename}.",
            upload_diff=diff,
        ),
    )


@app.get("/clients/{client_id}/cost-allocation/template.xlsx")
async def cost_allocation_template(client_id: str):
    resolve_client(client_id)
    from openpyxl import Workbook
    from io import BytesIO
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet3"
    ws["A1"] = "BẢNG PHÂN BỔ TỶ LỆ CHI PHÍ"
    ws["A2"] = "STT"
    ws["B2"] = "Mã SP"
    ws["C2"] = "Lương, thưởng"
    ws["D2"] = "Phúc lợi y tế"
    ws["E2"] = "Phí thuê nhà xưởng"
    ws["F2"] = "Phí khấu hao, BH, BD"
    ws["G2"] = "CP SX chung khác"
    ws["H2"] = "Lợi nhuận (bỏ qua khi import)"
    ws["I2"] = "Vận chuyển, lưu kho, dịch vụ"
    ws["J2"] = "Ghi chú"
    # Row 4 onward = data area.
    ws["A4"] = 1
    buf = BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="cost-allocation-{client_id}-template.xlsx"'},
    )


@app.get("/clients/{client_id}/cost-allocation/resolve")
async def cost_allocation_resolve(client_id: str, product_code: str, fob: str = "0"):
    """JSON endpoint for the 'Áp hệ số' button on the origin product panel.

    Returns the resolved coefficient (Mode A → Mode B fallback) plus the
    multiplied detail values. `found` is false when neither mode matches.
    """
    resolve_client(client_id)
    from app import cost_allocation_store, cost_allocation_importer
    row = cost_allocation_store.get_ratio(client_id, product_code.strip())
    if row is None:
        return JSONResponse({"found": False, "product_code": product_code})
    try:
        fob_dec = Decimal(str(fob).replace(",", "."))
    except (InvalidOperation, ValueError):
        fob_dec = Decimal(0)
    detail = cost_allocation_importer.apply_to_fob(row, fob_dec)
    return JSONResponse({
        "found": True,
        "product_code": product_code,
        "matched_mode": "A" if row.product_code else "B",
        "matched_product_code": row.product_code,
        "fob": str(fob_dec),
        "coefficients": {
            "wages": str(row.coef_wages),
            "welfare": str(row.coef_welfare),
            "rent": str(row.coef_rent),
            "depreciation": str(row.coef_depreciation),
            "other_mfg": str(row.coef_other_mfg),
            "transport_storage": str(row.coef_transport_storage),
        },
        "details": {k: str(v) for k, v in detail.items()},
        "note": row.note,
    })


@app.post("/clients/{client_id}/bom/upload", response_class=HTMLResponse)
async def upload_bom_workbook(
    request: Request,
    client_id: str,
    file: UploadFile = File(...),
    upload_mode: str = Form("direct_bom"),
    upload_scope: str = Form(""),
    accept_review_required: str = Form(""),
):
    require_local_source_writes()
    client = resolve_client(client_id)
    result = bom_service.process_upload(
        client,
        await file.read(),
        file.filename or "bom.xlsx",
        upload_mode,
        upload_scope or None,
        accept_review_required == "on",
    )
    status_code = 400 if result["status"] == "failed" else 200
    return templates.TemplateResponse(
        request=request,
        name="bom.html",
        status_code=status_code,
        context=bom_context(
            request,
            client_id,
            bom_result=result,
            message=result["message"] if status_code == 200 else "",
            error=result["message"] if status_code == 400 else "",
        ),
    )


@app.get("/clients/{client_id}/bom/template.xlsx")
async def download_bom_template(client_id: str):
    try:
        content = bom_service.template(resolve_client(client_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{client_id}-bom-template.xlsx"'},
    )


@app.get("/clients/{client_id}/co-stock", response_class=HTMLResponse)
async def co_stock(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="co_stock.html",
        context=co_stock_table_context(request, client_id),
    )


@app.get("/clients/{client_id}/bcct", response_class=HTMLResponse)
async def bcct(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="bcct.html",
        context=bcct_table_context(request, client_id),
    )


@app.get("/clients/{client_id}/bcct/imports", response_class=HTMLResponse)
async def bcct_imports(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="bcct.html",
        context=bcct_table_context(request, client_id, "import"),
    )


@app.get("/clients/{client_id}/bcct/exports", response_class=HTMLResponse)
async def bcct_exports(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="bcct.html",
        context=bcct_table_context(request, client_id, "export"),
    )


@app.get("/clients/{client_id}/bcct/template.xlsx")
async def download_bcct_template(client_id: str):
    require_local_source_writes()
    content = portfolio_service.bcct_template(resolve_client(client_id))
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{client_id}-bcct-template.xlsx"'},
    )


@app.post("/clients/{client_id}/bcct/upload", response_class=HTMLResponse)
async def upload_bcct_workbook(request: Request, client_id: str, file: UploadFile = File(...)):
    require_local_source_writes()
    client = resolve_client(client_id)
    result = portfolio_service.process_bcct_upload(client, await file.read(), file.filename or "bcct.xlsx")
    status_code = 400 if result["status"] == "failed" else 200
    return templates.TemplateResponse(
        request=request,
        name="bcct.html",
        status_code=status_code,
        context=bcct_table_context(
            request,
            client_id,
            bcct_result=result,
            message=result["message"] if status_code == 200 else "",
            error=result["message"] if status_code == 400 else "",
        ),
    )


@app.post("/clients/{client_id}/co-stock/import")
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


@app.post("/clients/{client_id}/co-stock/refresh")
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


@app.get("/clients/{client_id}/co-stock/lot-history")
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
    return JSONResponse({
        "ok": True,
        "client_id": client["id"],
        "lot": {"declaration_no": declaration_no, "line_no": line_no, "customs_code": customs_code},
        "events": events,
        "count": len(events),
    })


@app.get("/clients/{client_id}/co-stock/export.xlsx")
async def export_co_stock_workbook(client_id: str):
    """Dump effective ton CO state (BCCT opening + ledger + adjustments) into
    a standard template xlsx. Heavy for big clients (full BCCT pagination
    on Data Hub mode); intended for on-demand download.
    """
    client = resolve_client(client_id)
    workspace, _backend = portfolio_service.source_workspace(client)
    stock_rows = [dict(row) for row in workspace.get("co_stock_rows") or []]
    client_id_value = client.get("id", "")
    used_by_lot = co_stock_ledger.used_qty_by_lot(client_id_value)
    if used_by_lot:
        stock_rows = co_stock_ledger.apply_used_qty(stock_rows, used_by_lot)
    adjustments = co_stock_adjustments_store.aggregate_by_lookup_key(client_id_value)
    if adjustments:
        stock_rows = co_stock_adjustments_store.apply_adjustments(stock_rows, adjustments)
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


@app.get("/clients/{client_id}/co-case", response_class=HTMLResponse)
async def co_case(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id),
    )


@app.get("/clients/{client_id}/co-case/invoice-preview")
async def co_case_invoice_preview(client_id: str, invoice_no: str = "", q: str = "", export_declaration_nos: str = ""):
    client = resolve_client(client_id)
    return invoice_lookup_payload(client, invoice_no, q, export_declaration_nos)


@app.post("/clients/{client_id}/co-case/create")
async def create_co_case(request: Request, client_id: str):
    client = resolve_client(client_id)
    form = {key: str(value) for key, value in (await request.form()).items()}
    resolved = resolve_shipment_reference(client, form.get("invoice_no", ""), form.get("export_declaration_nos", ""))
    form["invoice_no"] = resolved["invoice_no"]
    form["export_declaration_nos"] = ", ".join(resolved["export_declaration_nos"])
    record = create_case_record(client, form)
    # Set a short-lived cookie so the case detail page can surface a one-time
    # toast confirming the dossier was created (without changing the redirect
    # URL — many tests + back-references rely on the canonical path).
    response = RedirectResponse(
        f"/clients/{client_id}/co-case/{record['case_id']}",
        status_code=303,
    )
    response.set_cookie(
        "co_case_just_created",
        record["case_id"],
        max_age=60,
        path=f"/clients/{client_id}/co-case/{record['case_id']}",
        httponly=False,
        samesite="lax",
    )
    return response


@app.post("/clients/{client_id}/co-case/{case_id}/delete", response_class=HTMLResponse)
async def delete_co_case(request: Request, client_id: str, case_id: str):
    if not co_auth.can_delete_co_cases(co_auth.current_user(request)):
        raise HTTPException(status_code=403, detail="Không có quyền xoá hồ sơ C/O.")
    client = resolve_client(client_id)
    form = await request.form()
    release_claims = str(form.get("confirm_release_claims") or "").strip() == "1"
    try:
        result = delete_case_record(client, case_id, release_claims=release_claims)
    except KeyError:
        raise HTTPException(status_code=404) from None
    except CaseHasActiveClaimsError as exc:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(client_id, error=str(exc)),
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(client_id, error=str(exc)),
        )
    released = int(result.get("claims_released") or 0)
    flash = (
        f"Đã xoá hồ sơ và nhả {released} dòng tồn về kho."
        if released
        else "Đã xoá hồ sơ."
    )
    redirect = RedirectResponse(f"/clients/{client_id}/co-case", status_code=303)
    # Cookies are latin-1 only; URL-encode the Vietnamese flash text and
    # decode in the template (request.cookies.get(...) | urldecode).
    redirect.set_cookie(
        "co_flash",
        quote(flash, safe=""),
        max_age=15,
        path=f"/clients/{client_id}/co-case",
    )
    return redirect


@app.post("/clients/{client_id}/co-case/{case_id}/shipment")
async def update_co_case_shipment(request: Request, client_id: str, case_id: str):
    form = {key: str(value) for key, value in (await request.form()).items()}
    client = resolve_client(client_id)
    resolved = resolve_shipment_reference(client, form.get("invoice_no", ""), form.get("export_declaration_nos", ""))
    update_case_record(
        client,
        {
            **form,
            "id": case_id,
            "persisted_case_id": case_id,
            "shipment": {
                "invoice_no": resolved["invoice_no"],
                "export_declaration_nos": resolved["export_declaration_nos"],
                "bill_of_lading_no": form.get("bill_of_lading_no", ""),
            },
        },
    )
    return RedirectResponse(f"/clients/{client_id}/co-case/{case_id}", status_code=303)


@app.get("/clients/{client_id}/co-case/{case_id}", response_class=HTMLResponse)
async def co_case_detail(request: Request, client_id: str, case_id: str):
    # Run preload in a thread so the case detail page returns immediately.
    # Preload fetches source_context (BCCT pagination) and persists it to the
    # case record; the next /origin click reads the cached snapshot instead of
    # hitting Data Hub again. Background is fine because the shipment tab
    # doesn't need origin context, and /origin has its own fallback if preload
    # hasn't finished yet.
    asyncio.get_event_loop().run_in_executor(
        None, preload_co_case_origin_context, client_id, case_id
    )
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id, case_id, "shipment"),
    )


# Specific GET routes that share the /clients/{client_id}/co-case/{case_id}/...
# prefix MUST be defined before the catch-all {step} route below — FastAPI's
# router is order-sensitive, and {step} would otherwise swallow any single-
# segment GET (e.g. /export-bang-ke) and 404 it for not being a workflow key.


@app.get("/clients/{client_id}/co-case/{case_id}/export-bang-ke")
async def export_co_case_bang_ke_workbook_get(request: Request, client_id: str, case_id: str):
    return await export_co_case_bang_ke_workbook(request, client_id, case_id)


@app.get("/clients/{client_id}/co-case/{case_id}/{step}", response_class=HTMLResponse)
async def co_case_step(request: Request, client_id: str, case_id: str, step: str):
    if step not in CO_CASE_WORKFLOW_STEP_KEYS:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id, case_id, step),
    )


@app.get("/clients/{client_id}/co-case/{case_id}/origin/calculation-payload")
async def co_case_origin_calculation_payload(client_id: str, case_id: str):
    context = co_case_context(
        client_id,
        case_id,
        current_step="origin",
        origin_demo_allowed=False,
    )
    case = context["case"]
    source_context = context.get("origin_source_context", {})
    return {
        "case_id": case.get("persisted_case_id") or case_id,
        "case_code": case.get("case_code", ""),
        "revision": origin_case_revision(case),
        "source_snapshot": json_safe(case.get("source_snapshot", {})),
        "bom_snapshot": json_safe(case.get("bom_snapshot", {})),
        "origin_snapshot": json_safe(case.get("origin_snapshot", {})),
        "origin_product_order": origin_product_order(case),
        "origin_sheet_states": json_safe(case.get("origin_sheet_states", {})),
        "products": json_safe(case.get("products", [])),
        "form_lane": json_safe(context.get("recommended_form_lane", {})),
        "source": {
            "backend": source_context.get("source_backend", ""),
            "summary": json_safe(source_context.get("source_summary", {})),
            "invoice_matches": json_safe(source_context.get("invoice_matches", [])),
            "material_rows": json_safe(source_context.get("material_rows", [])),
            "stock_rows": json_safe(source_context.get("stock_rows", [])),
        },
    }


@app.post("/clients/{client_id}/co-case/{case_id}/supporting-files")
async def upload_co_case_supporting_file(
    request: Request,
    client_id: str,
    case_id: str,
    file: UploadFile = File(...),
    document_slot: str = Form("other"),
    invoice_no: str = Form(""),
    bill_of_lading_no: str = Form(""),
):
    client = resolve_client(client_id)
    # save_supporting_file bypasses update_case_record's close-state gate;
    # check it explicitly here so closed cases also reject uploads.
    record = get_case_record(client, case_id)
    if record and co_case_is_completed(record):
        raise HTTPException(
            status_code=409,
            detail="Hồ sơ đã đóng — bấm 'Mở lại hồ sơ' ở tab Review & Xuất trước khi upload chứng từ.",
        )
    content = await file.read(MAX_SUPPORTING_FILE_BYTES + 1)
    try:
        save_supporting_file(
            client,
            case_id,
            content,
            file.filename or "supporting-file",
            document_slot,
            invoice_no,
            bill_of_lading_no,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=400,
            context=co_case_context(client_id, case_id, "documents", error=str(exc)),
        )
    return RedirectResponse(f"/clients/{client_id}/co-case/{case_id}/documents", status_code=303)


@app.get("/clients/{client_id}/co-case/{case_id}/supporting-files/{upload_id}")
async def download_co_case_supporting_file(client_id: str, case_id: str, upload_id: str):
    try:
        file_row, path = get_supporting_file(resolve_client(client_id), case_id, upload_id)
    except (KeyError, FileNotFoundError):
        raise HTTPException(status_code=404) from None
    return FileResponse(
        path,
        media_type=file_row.get("mime_type") or file_row.get("content_type") or "application/octet-stream",
        filename=file_row.get("original_filename") or file_row.get("filename") or "supporting-file",
    )


@app.post("/clients/{client_id}/co-case/{case_id}/export")
async def export_co_case_workbook(request: Request, client_id: str, case_id: str):
    content_type = request.headers.get("content-type", "")
    posted_case = None
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await large_request_form(request)
        if form:
            posted_case = update_products_from_form({key: str(value) for key, value in form.items()})
            posted_case["persisted_case_id"] = posted_case.get("persisted_case_id") or case_id
    client = resolve_client(client_id)
    lock_result = acquire_origin_calculation_lock(client, case_id, origin_lock_actor(request))
    if not lock_result["acquired"]:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(
                client_id,
                case_id,
                current_step="origin",
                case=posted_case,
                origin_demo_allowed=False,
                origin_calculation_blocked=True,
                error=f"Chưa thể export: hồ sơ {lock_result['lock'].get('case_code') or lock_result['lock'].get('case_id')} đang giữ phiên tính tồn cho khách hàng này.",
            ),
        )
    context = co_case_context(
        client_id,
        case_id,
        current_step="origin",
        case=posted_case,
        origin_demo_allowed=False,
    )
    blockers = origin_sheet_export_blockers(context["case"])
    should_enforce_sheet_state = bool(posted_case)
    if should_enforce_sheet_state and blockers:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context={
                **context,
                "error": f"Chưa thể export: bảng kê {', '.join(blockers[:5])} cần tính lại hoặc chốt trước.",
            },
        )
    if context["case"].get("persisted_case_id") and not context.get("origin_demo_active"):
        try:
            update_case_record(client, context["case"])
        except KeyError:
            pass
    content = create_case_workbook(
        context["case"],
        context["form_candidates"],
        context["invoice_matches"],
        context["criteria_rows"],
    )
    filename = safe_filename(f"{context['case']['case_code'] or 'co-case'}-dossier.xlsx")
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/clients/{client_id}/co-case/{case_id}/export-bang-ke")
async def export_co_case_bang_ke_workbook(request: Request, client_id: str, case_id: str):
    content_type = request.headers.get("content-type", "")
    posted_case = None
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await large_request_form(request)
        if form:
            posted_case = update_products_from_form({key: str(value) for key, value in form.items()})
            posted_case["persisted_case_id"] = posted_case.get("persisted_case_id") or case_id
    client = resolve_client(client_id)
    case = posted_case or persisted_origin_case(client, case_id)
    # The form-rebuilt case has empty origin_sheet_states (case_from_form starts
    # with {}). Re-hydrate from the persisted DB row so per-sheet overrides
    # (form / criteria / threshold / currency_mode) AND material_overrides
    # (delete / substitute / norm-edit / added rows) are honored by the
    # renderer. Without this, the export ships every material — including
    # ones the operator deleted via Substitute — and always picks the LVC
    # template because effective_criteria is unresolved.
    if posted_case and case_id:
        try:
            persisted = persisted_origin_case(client, case_id)
        except KeyError:
            persisted = None
        if persisted:
            case["origin_sheet_states"] = persisted.get("origin_sheet_states") or {}
    case = attach_origin_sheet_states(case)
    _hydrate_material_dates_from_stock(case, client)
    _hydrate_product_export_declaration_dates(case, client)
    blockers = origin_sheet_export_blockers(case)
    if blockers:
        raise HTTPException(
            status_code=409,
            detail=f"Chưa thể xuất bảng kê: bảng kê {', '.join(blockers[:5])} cần tính lại hoặc chốt trước.",
        )
    if case.get("persisted_case_id"):
        try:
            update_case_record(client, case)
        except KeyError:
            pass
    content = create_hq_bang_ke_workbook(case)
    filename = safe_filename(f"{case['case_code'] or 'co-case'}-bang-ke-hq.xlsx")
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/clients/{client_id}/co-case/{case_id}/export-dossier-zip")
async def export_co_case_dossier_zip(client_id: str, case_id: str):
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    case = attach_origin_sheet_states(case)
    # Hard gate: case must be closed. Close itself already requires every sheet
    # locked, so this implicitly guarantees the TKN summary is complete (it
    # filters to locked sheets — see case_tkx_tkn_summary). Without this gate
    # an operator could ship a dossier whose TKN list silently omits the
    # declarations referenced by half-finished sheets.
    if not co_case_is_completed(case):
        unlocked = [
            str(p.get("code") or "?")
            for p in case.get("products") or []
            if str(p.get("origin_sheet_status") or "").strip() != "locked"
        ]
        if unlocked:
            detail = (
                f"Còn {len(unlocked)} bảng kê chưa chốt: "
                f"{', '.join(unlocked[:5])}{'…' if len(unlocked) > 5 else ''}. "
                "Chốt hết các bảng kê rồi bấm 'Đóng hồ sơ' trước khi xuất file tổng hợp."
            )
        else:
            detail = "Đóng hồ sơ trước khi xuất file tổng hợp (cần khoá để chốt danh sách TKX/TKN)."
        raise HTTPException(status_code=409, detail=detail)
    source_context = co_case_source_context(client, case)
    invoice_matches = source_context.get("invoice_matches") or []
    stock_rows = source_context.get("stock_rows") or []
    summary = case_tkx_tkn_summary(
        case,
        invoice_matches,
        stock_rows,
        source_context.get("declaration_file_counts") or {},
    )
    supporting_files: list[dict] = []
    for file_row in case.get("supporting_files", []):
        upload_id = file_row.get("upload_id") or ""
        if not upload_id:
            continue
        try:
            row, path = get_supporting_file(client, case_id, upload_id)
        except (KeyError, FileNotFoundError):
            continue
        supporting_files.append({
            "slot": row.get("slot", "other"),
            "filename": row.get("filename", "supporting.bin"),
            "content": path.read_bytes(),
        })
    declaration_archives = _try_fetch_declaration_archives(client, case, summary)
    content = create_dossier_zip(
        case,
        supporting_files,
        summary,
        data_hub_base_url=data_hub_link_settings().data_hub_base_url,
        declaration_archives=declaration_archives,
    )
    filename = safe_filename(f"{case.get('case_code') or 'co-case'}-dossier.zip")
    return StreamingResponse(
        iter([content]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _try_fetch_declaration_archives(client: dict, case: dict, tkx_tkn_summary: dict) -> dict[str, bytes]:
    """Probe Data Hub's Bearer-aware download.zip endpoint.

    Until DH ships the endpoint per
    `.ai/api-requests/2026-05-28-bcct-declarations-download-bearer.md`,
    any error (404 / 401 / network) silently falls back to manifest-only
    mode. The dossier ZIP renderer detects the empty dict and only writes
    the README + MANIFEST entries; once DH deploys, this function returns
    populated bytes and create_dossier_zip embeds them directly.

    Keyed by archive path inside the dossier ZIP:
        `TKX/<filename>.zip` and `TKN/<filename>.zip`.
    """
    data_hub = getattr(portfolio_service, "data_hub", None)
    if data_hub is None or not hasattr(data_hub, "download_declarations_zip"):
        return {}
    case_code = (case.get("case_code") or "co-case").strip() or "co-case"
    archives: dict[str, bytes] = {}

    def _fetch(direction: str, entries: list[dict], archive_label: str) -> None:
        nos = sorted({
            str(entry.get("declaration_no") or "").strip()
            for entry in (entries or [])
            if str(entry.get("declaration_no") or "").strip()
        })
        if not nos:
            return
        filename = safe_filename(f"{archive_label}_{case_code}.zip")
        try:
            blob = data_hub.download_declarations_zip(
                client["id"], direction=direction, declaration_nos=nos, filename=filename,
            )
        except Exception:  # noqa: BLE001 — fall back to manifest-only on any failure
            return
        if isinstance(blob, (bytes, bytearray)) and blob:
            archives[f"{archive_label}/{filename}"] = bytes(blob)

    _fetch("export", tkx_tkn_summary.get("tkx") or [], "TKX")
    _fetch("import", tkx_tkn_summary.get("tkn") or [], "TKN")
    return archives


@app.post("/clients/{client_id}/co-case/{case_id}/close")
async def close_co_case(request: Request, client_id: str, case_id: str):
    """Mark the case as completed. Pre-conditions:

    - Every product's origin sheet must be in `locked` status. A case with
      a half-finished bảng kê isn't ready to be filed; we refuse rather
      than silently freezing edits on top of incomplete data.
    - The case must currently be open. (Re-closing a closed case is a
      no-op; the route is idempotent in spirit, but `update_case_record`
      treats it as a normal mutation, so no-op early.)

    After close: every mutating endpoint refuses via CaseClosedError.
    Also releases any origin-calculation lock the case holds."""
    client = resolve_client(client_id)
    try:
        record = get_case_record(client, case_id)
    except KeyError:
        raise HTTPException(status_code=404) from None
    if record is None:
        raise HTTPException(status_code=404)
    case = case_from_record(default_client_case(client), client, record)
    # Idempotent: re-clicking close on a closed case redirects without write.
    if co_case_is_completed(case):
        return RedirectResponse(
            f"/clients/{client_id}/co-case/{case_id}/review",
            status_code=303,
        )
    case = attach_origin_sheet_states(case)
    products = case.get("products") or []
    if not products:
        raise HTTPException(
            status_code=409,
            detail="Chưa có bảng kê nào — không thể đóng hồ sơ rỗng.",
        )
    unlocked = [
        p.get("code") or "?"
        for p in products
        if str(p.get("origin_sheet_status") or "").strip() != "locked"
    ]
    if unlocked:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Còn {len(unlocked)} bảng kê chưa chốt: "
                f"{', '.join(unlocked[:5])}{'…' if len(unlocked) > 5 else ''}. "
                "Chốt tất cả ở tab Bảng kê C/O trước khi đóng hồ sơ."
            ),
        )
    try:
        update_case_record(client, {"id": case_id, "persisted_case_id": case_id, "status": "completed"})
    except KeyError:
        raise HTTPException(status_code=404) from None
    # Best-effort lock release: don't fail the close if no lock is held.
    try:
        existing_lock = active_origin_calculation_lock(client)
        if existing_lock and existing_lock.get("case_id") == case_id:
            release_origin_calculation_lock(client, case_id)
    except Exception:  # noqa: BLE001 — lock release is housekeeping
        pass
    return RedirectResponse(
        f"/clients/{client_id}/co-case/{case_id}/review",
        status_code=303,
    )


@app.post("/clients/{client_id}/co-case/{case_id}/reopen-case")
async def reopen_co_case(request: Request, client_id: str, case_id: str):
    """Re-open a completed case for further edits."""
    client = resolve_client(client_id)
    try:
        update_case_record(client, {"id": case_id, "persisted_case_id": case_id, "status": "open"})
    except KeyError:
        raise HTTPException(status_code=404) from None
    return RedirectResponse(
        f"/clients/{client_id}/co-case/{case_id}/review",
        status_code=303,
    )


@app.post("/clients/{client_id}/co-case/{case_id}/origin-lock/release")
async def release_co_case_origin_lock(client_id: str, case_id: str, next_url: str = Form("")):
    client = resolve_client(client_id)
    try:
        record = get_case_record(client, case_id)
        case = case_from_record(default_client_case(client), client, record)
        case = mark_origin_sheets_stale(case, 0)
        update_case_record(client, case)
    except KeyError:
        pass
    release_origin_calculation_lock(client, case_id)
    redirect_url = next_url if next_url.startswith(f"/clients/{client_id}/co-case") else f"/clients/{client_id}/co-case/{case_id}/origin"
    return RedirectResponse(redirect_url, status_code=303)


@app.post("/clients/{client_id}/co-case/{case_id}/origin/save")
async def save_co_case_origin(request: Request, client_id: str, case_id: str):
    client = resolve_client(client_id)
    case, payload = await origin_case_from_request(request, client, case_id)
    try:
        stale_from_index = int(str(payload.get("stale_from_index", "0") or "0"))
    except ValueError:
        stale_from_index = 0
    if payload.get("mark_stale", True):
        case = mark_origin_sheets_stale(case, stale_from_index)
    else:
        case = attach_origin_sheet_states(case)
    try:
        update_case_record(client, case)
    except KeyError:
        raise HTTPException(status_code=404) from None
    return {
        "status": "ok",
        "revision": origin_case_revision(case),
        "stale_from_index": stale_from_index,
        "origin_product_order": origin_product_order(case),
        "origin_sheet_states": json_safe(case.get("origin_sheet_states", {})),
    }


@app.post("/clients/{client_id}/co-case/{case_id}/origin/autosave")
async def autosave_co_case_origin(request: Request, client_id: str, case_id: str):
    client = resolve_client(client_id)
    case, payload = await origin_case_from_request(request, client, case_id)
    try:
        stale_from_index = int(str(payload.get("stale_from_index", "0") or "0"))
    except ValueError:
        stale_from_index = 0
    case = mark_origin_sheets_stale(case, stale_from_index)
    try:
        update_case_record(client, case)
    except KeyError:
        raise HTTPException(status_code=404) from None
    return {
        "status": "ok",
        "revision": origin_case_revision(case),
        "stale_from_index": stale_from_index,
        "origin_product_order": origin_product_order(case),
        "origin_sheet_states": json_safe(case.get("origin_sheet_states", {})),
    }




@app.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/calculate", response_class=HTMLResponse)
async def calculate_co_case_origin_sheet(request: Request, client_id: str, case_id: str, product_code: str):
    client = resolve_client(client_id)
    case, _payload = await origin_case_from_request(request, client, case_id)
    try:
        persisted = get_case_record(client, case_id)
        if persisted.get("origin_sheet_states"):
            case["origin_sheet_states"] = dict(persisted.get("origin_sheet_states") or {})
    except KeyError:
        pass
    action_error = origin_sheet_action_error(case, product_code, "calculate")
    if action_error:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(
                client_id,
                case_id,
                current_step="origin",
                case=case,
                error=action_error,
                preserve_origin_products=True,
                fast_origin_context=True,
            ),
        )
    lock_result = acquire_origin_calculation_lock(client, case_id, origin_lock_actor(request))
    if not lock_result["acquired"]:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(
                client_id,
                case_id,
                current_step="origin",
                case=case,
                error=f"Chưa thể load BOM vào bảng kê: hồ sơ {lock_result['lock'].get('case_code') or lock_result['lock'].get('case_id')} đang giữ phiên tính tồn cho khách hàng này.",
                origin_calculation_blocked=True,
                preserve_origin_products=True,
            ),
        )
    # Fast path: delta-refresh the materialized stock snapshot (1-2s when
    # the upstream BCCT is quiet, vs 30-45s for a full DH pull every time)
    # and read stock rows from co_stock_rows directly. invoice_matches +
    # material_rows are pulled through the cached snapshot the shipment
    # step already populated. Falls back to the legacy full-pull path when
    # the snapshot is empty (fresh client) or delta refresh errored, so we
    # never silently calculate against stale data.
    snapshot_stock_rows = _calculate_stock_rows_from_snapshot(client)
    if snapshot_stock_rows is not None:
        context = co_case_context(
            client_id,
            case_id,
            current_step="origin",
            case=case,
            message=f"Đã load BOM vào bảng kê {product_code}.",
            preserve_origin_products=True,
            cached_case_context=True,
        )
        source_context = context.get("origin_source_context", {})
        stock_rows = snapshot_stock_rows
    else:
        context = co_case_context(
            client_id,
            case_id,
            current_step="origin",
            case=case,
            message=f"Đã load BOM vào bảng kê {product_code}.",
            preserve_origin_products=True,
            force_source_refresh=True,
        )
        source_context = context.get("origin_source_context", {})
        stock_rows = source_context.get("stock_rows", [])
    try:
        client_config_for_rule = (
            portfolio_service.get_client_config(client)
            if hasattr(portfolio_service, "get_client_config") else {}
        )
    except Exception:  # noqa: BLE001
        client_config_for_rule = {}
    min_gap_days = effective_min_gap_days(client, client_config_for_rule)
    context["case"] = prepare_case_origin_sheet(
        context["case"],
        product_code,
        source_context.get("invoice_matches", []),
        context.get("bom_workspace", minimal_bom_workspace()),
        context.get("recommended_form_lane", {}),
        source_context.get("material_rows", []),
        stock_rows,
        min_gap_days=min_gap_days,
    )
    context["case"] = attach_case_bom_snapshot(context["case"], context.get("bom_workspace", minimal_bom_workspace()))
    context["case"] = attach_origin_bom_product_codes(
        context["case"],
        context.get("bom_workspace", minimal_bom_workspace()),
    )
    context["case"] = attach_origin_readiness(context["case"])
    context["case"] = attach_results(context["case"])
    context["case"] = attach_origin_sheet_states(context["case"])
    context["case"] = set_origin_sheet_status(context["case"], product_code, "calculated")
    target_index = next(
        (
            index
            for index, product in enumerate(context["case"].get("products", []))
            if str(product.get("code") or "").strip() == product_code
        ),
        -1,
    )
    if target_index >= 0:
        context["case"] = mark_origin_sheets_stale(context["case"], target_index + 1)
        context["case"] = set_origin_sheet_status(context["case"], product_code, "calculated")
        states = dict(context["case"].get("origin_sheet_states") or {})
        previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
        if previous.get("material_overrides"):
            states[product_code] = {**previous, "material_overrides": {}}
            context["case"]["origin_sheet_states"] = states
            context["case"] = attach_origin_sheet_states(context["case"])
    context["criteria_rows"] = build_case_criteria_rows(context["case"], context.get("form_candidates", []))
    if context["case"].get("persisted_case_id") and not context.get("origin_demo_active"):
        update_case_record(client, context["case"])
    return templates.TemplateResponse(request=request, name="co_case.html", context=context)


@app.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/lock", response_class=HTMLResponse)
async def lock_co_case_origin_sheet(request: Request, client_id: str, case_id: str, product_code: str):
    client = resolve_client(client_id)
    case, _payload = await origin_case_from_request(request, client, case_id)
    action_error = origin_sheet_action_error(case, product_code, "lock")
    if action_error:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(
                client_id,
                case_id,
                current_step="origin",
                case=case,
                error=action_error,
                preserve_origin_products=True,
                fast_origin_context=True,
            ),
        )
    # Capture allocations from the PERSISTED case BEFORE update_case_record
    # rewrites the disk record. The form-rebuilt `case` may have stripped
    # materials/allocation_lines if the AJAX submitter only sent metadata.
    # The ledger writes claims in a single transaction with an availability
    # pre-check; on any failure we must NOT update case state, otherwise the
    # sheet appears locked while no claim was recorded (the ghost-claim bug
    # this code path used to suffer from silent exception swallowing).
    try:
        record_sheet_lock_claims(client_id, case_id, product_code, case)
    except co_stock_ledger.StockOverclaimError as exc:
        detail_lines = [
            f"{v['source_row']}: cần {v['claimed']}, còn {v['available']}"
            f" (gốc {v['bcct_remaining']} - case khác {v['other_claims']})"
            for v in exc.violations[:5]
        ]
        message = (
            f"Không chốt được bảng kê {product_code} vì vượt tồn ở "
            f"{len(exc.violations)} lot: " + "; ".join(detail_lines)
            + ". Hãy tính lại bảng kê để cập nhật phân bổ theo tồn hiện tại."
        )
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(
                client_id,
                case_id,
                current_step="origin",
                case=case,
                error=message,
                preserve_origin_products=True,
                fast_origin_context=True,
            ),
        )
    case = set_origin_sheet_status(case, product_code, "locked")
    update_case_record(client, case)
    invalidate_co_case_source_cache(client_id, case_id)
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(
            client_id,
            case_id,
            current_step="origin",
            case=case,
            message=f"Đã chốt bảng kê {product_code}.",
            preserve_origin_products=True,
            fast_origin_context=True,
        ),
    )


@app.get("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/substitute-candidates")
async def co_case_origin_sheet_substitute_candidates(
    client_id: str,
    case_id: str,
    product_code: str,
    material_code: str = "",
    row_index: int = -1,
    search: str = "",
    seed_hs: str = "",
    limit: int = 20,
):
    if not material_code and not search:
        raise HTTPException(status_code=400, detail="material_code or search query required")
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    target = next((p for p in case.get("products", []) if str(p.get("code") or "").strip() == product_code), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Sheet {product_code} not found in case")
    sheet_state = (case.get("origin_sheet_states") or {}).get(product_code, {}) or {}
    optimization_mode = sheet_state.get("optimization_mode") or "max_lvc"

    # Empty stock summary placeholder. Stock data is fetched lazily by a
    # separate /substitute-stock endpoint so the recommendation list can
    # render in ~300ms (one Data Hub call) instead of waiting for full
    # BCCT pagination (~30s for Johnson). JS merges stock async.
    def empty_stock_summary() -> dict:
        return {
            "lot_count": 0,
            "usable_lot_count": 0,
            "total_remaining_qty": "0",
            "unit_price_min": "",
            "unit_price_max": "",
            "lots": [],
            "pending": True,
        }

    candidates: list[dict] = []
    error_detail = ""
    candidates_source = "data_hub"
    if material_code:
        try:
            raw, source = portfolio_service.list_material_substitutes(
                client_id, material_code, min_score=0.5, limit=min(limit, 50)
            )
        except Exception as exc:  # noqa: BLE001
            raw, source = [], "error"
            error_detail = str(exc)
        candidates_source = source
        for row in raw:
            code = str(row.get("material_b_code") or row.get("material_code") or "").strip()
            if not code:
                continue
            candidates.append({
                "material_code": code,
                "name": row.get("name", ""),
                "category": row.get("category", ""),
                "hs_code": row.get("hs_code", ""),
                "score": float(row.get("combined_score") or row.get("score") or 0.0),
                "raw_scores": row.get("raw_scores") or {},
                "sources": row.get("sources") or [],
                "confirmed": bool(row.get("confirmed")),
                "stock": empty_stock_summary(),
                "kind": "recommended",
            })
        # Heuristic fallback ONLY when Data Hub had nothing: this still needs
        # the materials catalog (one Data Hub list_materials pagination, but
        # cached). Caller can opt out via ?skip_heuristic=1 to keep first call
        # fast even on substitutes-empty.
        if not candidates:
            try:
                cached_ctx = co_case_source_context_cached(client, case)
                material_rows = cached_ctx.get("material_rows") or []
            except Exception:  # noqa: BLE001
                material_rows = []
            heuristic, hs_seed = compute_substitute_heuristic_candidates(
                client_id, material_code, material_rows, lambda _code: empty_stock_summary(),
                fallback_hs=seed_hs,
            )
            candidates_source = "co_heuristic"
            if source == "data_hub_unauthorized":
                error_detail = (
                    "Data Hub trả 401/403 (token thiếu scope hub:read?) — fallback HS-prefix "
                    f"heuristic từ {len(material_rows)} NVL trong catalog."
                )
            else:
                error_detail = (
                    f"Data Hub không có substitute precomputed cho {material_code or '(no code)'}. "
                    f"Fallback heuristic theo HS={hs_seed or 'n/a'} — {len(heuristic)} ứng viên."
                )
            candidates = heuristic
            candidates.sort(key=lambda item: -item.get("score", 0.0))

    search_results: list[dict] = []
    if search:
        raw_search: list[dict] = []
        search_error = ""
        try:
            raw_search = portfolio_service.search_materials(client_id, search, limit=min(limit, 50))
        except Exception as exc:  # noqa: BLE001
            search_error = str(exc)
        fallback_rows = search_case_material_rows(case, search, limit=min(limit, 50))
        seen_search_codes: set[str] = set()
        for row in [*raw_search, *fallback_rows]:
            code = str(row.get("material_code") or row.get("internal_code") or "").strip()
            if not code or code in seen_search_codes:
                continue
            seen_search_codes.add(code)
            search_results.append({
                "material_code": code,
                "name": row.get("name") or row.get("material_description") or "",
                "category": row.get("category", ""),
                "hs_code": row.get("hs_code", ""),
                "score": 0.0,
                "stock": empty_stock_summary(),
                "kind": "search",
            })
            if len(search_results) >= max(1, min(limit, 50)):
                break
        if not raw_search and fallback_rows and not error_detail:
            error_detail = (
                "Data Hub material catalog search unavailable or empty; showing matching NVL "
                "already present in this dossier."
            )
        elif search_error and not error_detail:
            error_detail = search_error

    # Initial sort by score only — re-sorted client-side once stock arrives.
    candidates.sort(key=lambda item: -item.get("score", 0.0))
    return JSONResponse({
        "ok": True,
        "product_code": product_code,
        "material_code": material_code,
        "row_index": row_index,
        "optimization_mode": optimization_mode,
        "candidates": candidates,
        "candidates_source": candidates_source,
        "search_results": search_results,
        "stock_pending": True,
        "stock_url": (
            f"/clients/{client_id}/co-case/{case_id}/origin/sheet/{quote(product_code, safe='')}/substitute-stock"
        ),
        "error": error_detail,
    })


def search_case_material_rows(case: dict, query: str, limit: int = 20) -> list[dict]:
    if not (query or "").strip():
        return []
    max_rows = max(1, min(limit, 100))
    scored: list[tuple[float, int, dict]] = []
    seen: set[str] = set()
    position = 0
    for product in case.get("products", []) or []:
        for material in product.get("materials", []) or []:
            code = str(
                material.get("material_code")
                or material.get("internal_material_code")
                or material.get("internal_code")
                or ""
            ).strip()
            if not code or code in seen:
                continue
            score = material_search.match_score(query, [
                code,
                material.get("internal_code"),
                material.get("internal_material_code"),
                material.get("material_description"),
                material.get("name"),
                material.get("hs_code") or material.get("import_hs"),
            ])
            if score is None:
                continue
            seen.add(code)
            scored.append((score, position, {
                "material_code": code,
                "internal_code": material.get("internal_code") or material.get("internal_material_code") or code,
                "name": material.get("name") or material.get("material_description") or "",
                "material_description": material.get("material_description") or material.get("name") or "",
                "category": material.get("category", ""),
                "hs_code": material.get("hs_code") or material.get("import_hs") or "",
            }))
            position += 1
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [row for _, _, row in scored[:max_rows]]


@app.get("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/substitute-stock")
async def co_case_origin_sheet_substitute_stock(
    client_id: str,
    case_id: str,
    product_code: str,
    codes: str = "",
):
    """Lazy stock-summary endpoint. Returns stock pool entries for the given
    comma-separated material codes. Prefers Data Hub `bcct/by-codes` for a
    narrow lookup (~500ms); falls back to TTL-cached source_context for the
    file-based service.
    """
    requested = [code.strip() for code in (codes or "").split(",") if code.strip()]
    if not requested:
        return JSONResponse({"ok": True, "stock": {}})
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    sheet_state = (case.get("origin_sheet_states") or {}).get(product_code, {}) or {}
    optimization_mode = sheet_state.get("optimization_mode") or "max_lvc"
    cached_matches = case.get("source_invoice_matches") if isinstance(case.get("source_invoice_matches"), list) else []
    client_config = portfolio_service.get_client_config(client) if hasattr(portfolio_service, "get_client_config") else {}
    min_gap = effective_min_gap_days(client, client_config)
    # Substitute feasibility only needs CO stock (tồn) lots per candidate, not
    # raw BCCT — read solely from the materialized CO-stock snapshot. This is
    # the single source of truth: a flaky Data Hub BCCT call can never blank
    # out the suggestions, and we never silently fall back to file-store or a
    # heavy live DH pull (consistent with the no-silent-local-fallback rule).
    # A candidate code absent from the snapshot simply has no tồn. The snapshot
    # may lag BCCT; the response carries `stock_refreshed_at` so the modal shows
    # how fresh the tồn is (empty when the client has never been materialized).
    requested_set = set(requested)
    snapshot_rows = co_stock_materializer.read_co_stock_rows_cached(client_id)
    candidate_rows = [
        row for row in snapshot_rows
        if any(key in requested_set for key in co_stock_key_candidates(row))
    ]
    stock_pool = case_allocation_pool(case, cached_matches, candidate_rows, min_gap_days=min_gap)
    out: dict[str, dict] = {}
    for code in requested:
        lots = stock_pool.get(code, [])
        usable = [lot for lot in lots if co_stock_is_usable(lot)]
        total_remaining = sum(decimal_value(lot.get("remaining_qty") or lot.get("available_qty") or "0") for lot in lots)
        prices = []
        for lot in lots:
            price = decimal_value(lot.get("unit_value") or lot.get("unit_price") or "0")
            if price > 0:
                prices.append(price)
        unit_price_min = min(prices) if prices else None
        unit_price_max = max(prices) if prices else None
        out[code] = {
            "lot_count": len(lots),
            "usable_lot_count": len(usable),
            "total_remaining_qty": str(total_remaining),
            "unit_price_min": str(unit_price_min) if unit_price_min is not None else "",
            "unit_price_max": str(unit_price_max) if unit_price_max is not None else "",
            "lots": [
                {
                    "source_row": lot.get("source_row", ""),
                    "import_declaration_no": lot.get("import_declaration_no", ""),
                    "line_no": lot.get("line_no", ""),
                    "registration_date": str(lot.get("registration_date") or lot.get("declaration_date") or ""),
                    "remaining_qty": str(lot.get("remaining_qty") or lot.get("available_qty") or "0"),
                    "available_qty": str(lot.get("available_qty") or lot.get("remaining_qty") or "0"),
                    "unit_value": str(lot.get("unit_value") or lot.get("unit_price") or ""),
                    "currency": lot.get("currency", ""),
                    "material_description": lot.get("material_description", ""),
                    "hs_code": lot.get("hs_code", ""),
                    "uom": lot.get("uom", ""),
                    "allocation_code": lot.get("allocation_code", ""),
                    "eligibility_ok": bool(lot.get("_eligibility_ok", True)),
                    "eligibility_reason": str(lot.get("_eligibility_reason", "ok")),
                    "eligibility_label": co_stock_eligibility.REJECTION_LABELS.get(
                        str(lot.get("_eligibility_reason", "ok")), ""
                    ),
                }
                for lot in lots[:50]
            ],
        }
    return JSONResponse({
        "ok": True,
        "optimization_mode": optimization_mode,
        "stock": out,
        "stock_refreshed_at": co_stock_materializer.last_refresh_at(client_id),
    })


def compute_substitute_heuristic_candidates(
    client_id: str,
    seed_material_code: str,
    material_rows: list[dict],
    stock_summary,
    *,
    fallback_hs: str = "",
) -> tuple[list[dict], str]:
    """HS-prefix heuristic fallback when Data Hub substitutes endpoint returns nothing.

    Score = 0.5 base for sharing the 4-digit HS prefix, +0.2 for sharing 6-digit,
    +0.2 if the candidate has any usable CO stock lot. Tagged with source="co_heuristic"
    so the UI shows the explanation banner.

    `fallback_hs` is used when the seed material is not in Data Hub catalog (common
    when BOM uses an internal code that hasn't been catalog-resolved). Pass the
    BOM row's HS code so heuristic still has a search seed.
    """
    seed = next(
        (row for row in material_rows if str(row.get("material_code") or "").strip() == seed_material_code),
        None,
    )
    if not seed:
        try:
            seed = portfolio_service.get_material(client_id, seed_material_code)
        except Exception:  # noqa: BLE001
            seed = {}
    seed_hs = re.sub(r"\D+", "", str(seed.get("hs_code") or fallback_hs or ""))[:6]
    if not seed_hs:
        return [], ""
    seed_category = str(seed.get("category") or "").strip().lower()
    output: list[dict] = []
    for row in material_rows:
        code = str(row.get("material_code") or "").strip()
        if not code or code == seed_material_code:
            continue
        candidate_hs = re.sub(r"\D+", "", str(row.get("hs_code") or ""))[:6]
        if not candidate_hs or candidate_hs[:4] != seed_hs[:4]:
            continue
        if seed_category and str(row.get("category") or "").strip().lower() not in {seed_category, ""}:
            continue
        score = 0.5
        if candidate_hs[:6] == seed_hs[:6]:
            score = 0.7
        stock = stock_summary(code)
        if stock.get("usable_lot_count", 0) > 0:
            score += 0.2
        output.append({
            "material_code": code,
            "name": row.get("name", ""),
            "category": row.get("category", ""),
            "hs_code": row.get("hs_code", ""),
            "score": round(score, 4),
            "raw_scores": {"hs_prefix": score},
            "sources": ["co_heuristic_hs_prefix"],
            "confirmed": False,
            "stock": stock,
            "kind": "heuristic",
        })
    return output[:30], seed_hs


@app.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/substitute-row")
async def co_case_origin_sheet_substitute_row(
    request: Request, client_id: str, case_id: str, product_code: str
):
    payload: dict = {}
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
    else:
        form = await large_request_form(request)
        payload = {key: str(value) for key, value in form.items()}
    row_index = payload.get("row_index")
    new_material_code = str(payload.get("new_material_code") or "").strip()
    new_norm = str(payload.get("new_norm_per_unit") or "").strip()
    new_name = str(payload.get("new_name") or "").strip()
    delete = bool(payload.get("delete"))
    if row_index is None or str(row_index).strip() == "":
        raise HTTPException(status_code=400, detail="row_index required")
    raw_key = str(row_index).strip()
    is_added_key = raw_key.startswith("added_")
    if is_added_key:
        key = raw_key
        row_index_int = -1
    else:
        try:
            row_index_int = int(raw_key)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="row_index must be integer or added_<n>") from exc
        key = str(row_index_int)
    if not delete and not new_material_code:
        raise HTTPException(status_code=400, detail="new_material_code required when not deleting")
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    products = case.get("products", [])
    target_index = next(
        (i for i, p in enumerate(products) if str(p.get("code") or "").strip() == product_code),
        None,
    )
    if target_index is None:
        raise HTTPException(status_code=404, detail=f"Sheet {product_code} not found in case")
    reject_if_sheet_locked(case, product_code)
    states = dict(case.get("origin_sheet_states") or {})
    previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
    overrides = dict(previous.get("material_overrides") or {})
    if delete:
        if is_added_key:
            # added rows aren't part of product.materials; "deletion" = drop the override
            # so the row disappears completely from both UI and export.
            overrides.pop(key, None)
        else:
            overrides[key] = {"deleted": True}
    elif is_added_key:
        existing = overrides.get(key) if isinstance(overrides.get(key), dict) else {}
        overrides[key] = {
            **existing,
            "added": True,
            "material_code": new_material_code,
            "norm_per_unit": new_norm,
            "name": new_name,
        }
    else:
        overrides[key] = {
            "material_code": new_material_code,
            "norm_per_unit": new_norm,
            "name": new_name,
        }
    states[product_code] = {**previous, "material_overrides": overrides, "status": "stale", "status_label": ORIGIN_SHEET_STATUS_LABELS["stale"]}
    case["origin_sheet_states"] = states
    case = mark_origin_sheets_stale(case, target_index)
    update_case_record(client, case)
    return JSONResponse({
        "ok": True,
        "product_code": product_code,
        "row_index": row_index_int if not is_added_key else key,
        "applied_override": overrides.get(key, {"deleted": True}),
        "sheet_status": "stale",
    })


@app.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/propose-bom")
async def co_case_origin_sheet_propose_bom(
    request: Request, client_id: str, case_id: str, product_code: str
):
    payload = await read_json_or_form(request)
    actor = str(payload.get("actor") or "co_system").strip() or "co_system"
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    target = next((p for p in case.get("products", []) if str(p.get("code") or "").strip() == product_code), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Sheet {product_code} not found in case")
    state = (case.get("origin_sheet_states") or {}).get(product_code, {}) or {}
    if state.get("status") != "locked":
        raise HTTPException(status_code=409, detail="Chỉ propose được BOM mới sau khi đã chốt sheet.")
    overrides = state.get("material_overrides") or {}
    if not overrides:
        raise HTTPException(status_code=409, detail="Không có thay đổi BOM so với artifact gốc; không cần propose.")
    parent_artifact_id = str(target.get("bom_product_artifact_id") or target.get("bom_product_version_id") or "").strip()
    if not parent_artifact_id:
        raise HTTPException(status_code=409, detail="Sheet chưa gắn BOM artifact gốc; không thể propose BOM mới.")
    bom_product_code = str(target.get("bom_product_code") or target.get("code") or "").strip()
    rows = build_bom_proposal_rows(target, overrides)
    if not rows:
        raise HTTPException(status_code=409, detail="Không có dòng NVL nào để propose.")
    try:
        result = portfolio_service.submit_bom_proposal(
            client_id,
            bom_product_code,
            parent_artifact_id=parent_artifact_id,
            rows=rows,
            context={
                "case_id": case_id,
                "case_code": case.get("case_code", ""),
                "sheet_product_code": product_code,
                "diff_summary": {
                    "added": state.get("material_diff_added", 0),
                    "removed": state.get("material_diff_removed", 0),
                    "replaced": state.get("material_diff_replaced", 0),
                    "norm_only": state.get("material_diff_norm_only", 0),
                },
            },
            actor=actor,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Data Hub propose failed: {exc}") from exc
    states = dict(case.get("origin_sheet_states") or {})
    previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
    states[product_code] = {
        **previous,
        "proposed_artifact_id": str(result.get("artifact_id") or result.get("proposal_id") or ""),
        "proposed_proposal_id": str(result.get("proposal_id") or ""),
        "proposed_status": str(result.get("status") or "submitted"),
    }
    case["origin_sheet_states"] = states
    update_case_record(client, case)
    return JSONResponse({
        "ok": True, "product_code": product_code,
        "proposal": {
            "artifact_id": result.get("artifact_id"),
            "proposal_id": result.get("proposal_id"),
            "status": result.get("status"),
        },
    })


def build_bom_proposal_rows(product: dict, overrides: dict) -> list[dict]:
    """Shape rows for the Data Hub BOM proposal submission.

    Field names match Data Hub's BOM row contract: qty_per_unit + uom are
    typed columns; everything else lands in the row payload jsonb. CO-internal
    overrides store the qty under `norm_per_unit` (operator-facing "định mức")
    — translate that to `qty_per_unit` at the boundary, never inside DH's
    payload. Sending `norm_per_unit` makes DH read qty as 0, which auto-rejects
    every proposal via `qty_delta_exceeds_tolerance` and leaves the qty cell
    blank in the reviewer UI.
    """
    materials = product.get("materials") or []
    output: list[dict] = []
    for index, material in enumerate(materials):
        override = overrides.get(str(index)) if isinstance(overrides.get(str(index)), dict) else {}
        if override.get("deleted"):
            continue
        material_code = override.get("material_code") or material.get("material_code") or material.get("internal_material_code")
        qty = override.get("norm_per_unit") or material.get("bom_qty_per") or "0"
        output.append({
            "material_code": str(material_code or "").strip(),
            "qty_per_unit": str(qty),
            "scrap_rate": str(material.get("bom_scrap_rate") or "0"),
            "uom": str(material.get("uom") or override.get("uom") or ""),
            "name": str(override.get("name") or material.get("material_description") or ""),
            "hs_code": str(material.get("hs_code") or override.get("hs_code") or ""),
            "source_row_index": index,
        })
    for key, value in overrides.items():
        if not key.startswith("added_") or not isinstance(value, dict):
            continue
        output.append({
            "material_code": str(value.get("material_code") or "").strip(),
            "qty_per_unit": str(value.get("norm_per_unit") or "0"),
            "scrap_rate": "0",
            "uom": str(value.get("uom") or ""),
            "name": str(value.get("name") or ""),
            "hs_code": str(value.get("hs_code") or ""),
            "source_row_index": None,
            "added": True,
        })
    return [row for row in output if row["material_code"]]


@app.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/edit-row")
async def co_case_origin_sheet_edit_row(
    request: Request, client_id: str, case_id: str, product_code: str
):
    payload = await read_json_or_form(request)
    row_index = payload.get("row_index")
    new_norm = str(payload.get("new_norm_per_unit") or "").strip()
    if row_index is None or str(row_index).strip() == "" or not new_norm:
        raise HTTPException(status_code=400, detail="row_index and new_norm_per_unit required")
    try:
        row_index_int = int(row_index)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="row_index must be integer") from exc
    try:
        Decimal(new_norm)
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=400, detail="new_norm_per_unit must be numeric") from exc
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    target_index = next(
        (i for i, p in enumerate(case.get("products", [])) if str(p.get("code") or "").strip() == product_code),
        None,
    )
    if target_index is None:
        raise HTTPException(status_code=404, detail=f"Sheet {product_code} not found in case")
    reject_if_sheet_locked(case, product_code)
    states = dict(case.get("origin_sheet_states") or {})
    previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
    overrides = dict(previous.get("material_overrides") or {})
    key = str(row_index_int)
    existing = overrides.get(key) if isinstance(overrides.get(key), dict) else {}
    overrides[key] = {**existing, "norm_per_unit": new_norm, "norm_edit_only": not existing.get("material_code")}
    states[product_code] = {**previous, "material_overrides": overrides, "status": "stale", "status_label": ORIGIN_SHEET_STATUS_LABELS["stale"]}
    case["origin_sheet_states"] = states
    case = mark_origin_sheets_stale(case, target_index)
    update_case_record(client, case)
    return JSONResponse({
        "ok": True, "product_code": product_code,
        "row_index": row_index_int, "applied_override": overrides[key], "sheet_status": "stale",
    })


@app.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/add-row")
async def co_case_origin_sheet_add_row(
    request: Request, client_id: str, case_id: str, product_code: str
):
    payload = await read_json_or_form(request)
    new_material_code = str(payload.get("new_material_code") or "").strip()
    new_norm = str(payload.get("new_norm_per_unit") or "").strip()
    new_name = str(payload.get("new_name") or "").strip()
    new_uom = str(payload.get("new_uom") or "").strip()
    new_hs = str(payload.get("new_hs_code") or "").strip()
    if not new_material_code:
        raise HTTPException(status_code=400, detail="new_material_code required")
    if new_norm:
        try:
            Decimal(new_norm)
        except (InvalidOperation, ValueError) as exc:
            raise HTTPException(status_code=400, detail="new_norm_per_unit must be numeric") from exc
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    target_index = next(
        (i for i, p in enumerate(case.get("products", [])) if str(p.get("code") or "").strip() == product_code),
        None,
    )
    if target_index is None:
        raise HTTPException(status_code=404, detail=f"Sheet {product_code} not found in case")
    reject_if_sheet_locked(case, product_code)
    states = dict(case.get("origin_sheet_states") or {})
    previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
    overrides = dict(previous.get("material_overrides") or {})
    next_added = 1 + max(
        [int(k.split("_", 1)[1]) for k in overrides if k.startswith("added_") and k.split("_", 1)[1].isdigit()] + [-1]
    )
    key = f"added_{next_added}"
    overrides[key] = {
        "added": True,
        "material_code": new_material_code,
        "norm_per_unit": new_norm,
        "name": new_name,
        "uom": new_uom,
        "hs_code": new_hs,
    }
    states[product_code] = {**previous, "material_overrides": overrides, "status": "stale", "status_label": ORIGIN_SHEET_STATUS_LABELS["stale"]}
    case["origin_sheet_states"] = states
    case = mark_origin_sheets_stale(case, target_index)
    update_case_record(client, case)
    return JSONResponse({
        "ok": True, "product_code": product_code, "added_key": key,
        "applied_override": overrides[key], "sheet_status": "stale",
    })


@app.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/save")
async def co_case_origin_sheet_save(
    request: Request, client_id: str, case_id: str, product_code: str
):
    """Batched persistence of client-side bảng kê edits.

    Accepts a JSON payload with four lists/maps:
      replaces: {row_index: {new_material_code, new_norm_per_unit, new_name, new_hs_code}}
      adds: [{key, new_material_code, new_norm_per_unit, new_name, new_uom, new_hs_code}]
      deletes: {row_index: true}
      norm_edits: {row_index: new_norm}

    Each maps to material_overrides entries the existing render path already
    consumes; the sheet is flipped to "stale" so the next /calculate (now
    "Load BOM vào Bảng Kê") re-runs allocation with these overrides.
    """
    payload = await read_json_or_form(request)
    replaces = payload.get("replaces") or {}
    adds = payload.get("adds") or []
    deletes = payload.get("deletes") or {}
    norm_edits = payload.get("norm_edits") or {}
    if not (replaces or adds or deletes or norm_edits):
        raise HTTPException(status_code=400, detail="empty payload")
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    expected_revision = str(payload.get("expected_revision") or "").strip()
    if expected_revision and expected_revision != origin_case_revision(case):
        raise HTTPException(status_code=409, detail="Origin case state changed; reload before saving.")
    case = merge_origin_action_payload(case, payload)
    target_index = next(
        (i for i, p in enumerate(case.get("products", [])) if str(p.get("code") or "").strip() == product_code),
        None,
    )
    if target_index is None:
        raise HTTPException(status_code=404, detail=f"Sheet {product_code} not found in case")
    reject_if_sheet_locked(case, product_code)
    states = dict(case.get("origin_sheet_states") or {})
    previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
    overrides = dict(previous.get("material_overrides") or {})

    def _parse_row_index(value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    counts = {"replaces": 0, "adds": 0, "deletes": 0, "norm_edits": 0}

    if isinstance(replaces, dict):
        for raw_index, info in replaces.items():
            row_index = _parse_row_index(raw_index)
            if row_index is None or not isinstance(info, dict):
                continue
            new_material_code = str(info.get("new_material_code") or "").strip()
            if not new_material_code:
                continue
            norm = str(info.get("new_norm_per_unit") or "").strip()
            if norm:
                try:
                    Decimal(norm)
                except (InvalidOperation, ValueError):
                    raise HTTPException(status_code=400, detail=f"replaces[{row_index}].new_norm_per_unit must be numeric")
            overrides[str(row_index)] = {
                "material_code": new_material_code,
                "norm_per_unit": norm,
                "name": str(info.get("new_name") or "").strip(),
                "hs_code": str(info.get("new_hs_code") or "").strip(),
                "uom": str(info.get("new_uom") or "").strip(),
            }
            counts["replaces"] += 1

    if isinstance(norm_edits, dict):
        for raw_index, raw_norm in norm_edits.items():
            row_index = _parse_row_index(raw_index)
            if row_index is None:
                continue
            norm = str(raw_norm or "").strip()
            if not norm:
                continue
            try:
                Decimal(norm)
            except (InvalidOperation, ValueError):
                raise HTTPException(status_code=400, detail=f"norm_edits[{row_index}] must be numeric")
            key = str(row_index)
            existing = overrides.get(key) if isinstance(overrides.get(key), dict) else {}
            overrides[key] = {**existing, "norm_per_unit": norm, "norm_edit_only": not existing.get("material_code")}
            counts["norm_edits"] += 1

    if isinstance(deletes, dict):
        for raw_index, flag in deletes.items():
            if not flag:
                continue
            row_index = _parse_row_index(raw_index)
            if row_index is None:
                continue
            overrides[str(row_index)] = {"deleted": True}
            counts["deletes"] += 1

    used_added_ids = [
        int(k.split("_", 1)[1])
        for k in overrides
        if k.startswith("added_") and k.split("_", 1)[1].isdigit()
    ]
    next_added = (max(used_added_ids) + 1) if used_added_ids else 0
    if isinstance(adds, list):
        for entry in adds:
            if not isinstance(entry, dict):
                continue
            new_material_code = str(entry.get("new_material_code") or "").strip()
            if not new_material_code:
                continue
            norm = str(entry.get("new_norm_per_unit") or "").strip()
            if norm:
                try:
                    Decimal(norm)
                except (InvalidOperation, ValueError):
                    raise HTTPException(status_code=400, detail=f"adds[{new_material_code}].new_norm_per_unit must be numeric")
            key = f"added_{next_added}"
            next_added += 1
            overrides[key] = {
                "added": True,
                "material_code": new_material_code,
                "norm_per_unit": norm,
                "name": str(entry.get("new_name") or "").strip(),
                "uom": str(entry.get("new_uom") or "").strip(),
                "hs_code": str(entry.get("new_hs_code") or "").strip(),
            }
            counts["adds"] += 1

    states[product_code] = {
        **previous,
        "material_overrides": overrides,
        "status": "calculated",
        "status_label": ORIGIN_SHEET_STATUS_LABELS["calculated"],
    }
    case["origin_sheet_states"] = states
    try:
        client_config_for_rule = (
            portfolio_service.get_client_config(client)
            if hasattr(portfolio_service, "get_client_config") else {}
        )
    except Exception:  # noqa: BLE001
        client_config_for_rule = {}
    case = recalculate_origin_sheet_edits(
        client, case, product_code,
        min_gap_days=effective_min_gap_days(client, client_config_for_rule),
    )
    case = set_origin_sheet_status(case, product_code, "calculated")
    case = mark_origin_sheets_stale(case, target_index + 1)
    update_case_record(client, case)
    return JSONResponse({
        "ok": True,
        "product_code": product_code,
        "operations": counts,
        "override_count": len(overrides),
        "sheet_status": "calculated",
        "revision": origin_case_revision(case),
        "origin_product_order": origin_product_order(case),
        "origin_sheet_states": json_safe(case.get("origin_sheet_states", {})),
    })


async def read_json_or_form(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            payload = {}
        return payload if isinstance(payload, dict) else {}
    form = await large_request_form(request)
    return {key: str(value) for key, value in form.items()}


@app.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/recommendation-override")
async def co_case_origin_sheet_recommendation_override(
    request: Request, client_id: str, case_id: str, product_code: str
):
    payload: dict = {}
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
    else:
        form = await large_request_form(request)
        payload = {key: str(value) for key, value in form.items()}
    overrides: dict = {}
    if "form_override" in payload:
        form_override = str(payload.get("form_override") or "").strip()
        if form_override and form_override not in {row["form_code"] for row in load_co_form_config().get("forms", [])}:
            raise HTTPException(status_code=400, detail=f"Unknown form_code {form_override}")
        overrides["form_override"] = form_override
    if "criteria_override" in payload:
        overrides["criteria_override"] = str(payload.get("criteria_override") or "").strip()
    if "lvc_threshold_override" in payload:
        overrides["lvc_threshold_override"] = payload.get("lvc_threshold_override")
    if "rvc_threshold_override" in payload:
        overrides["rvc_threshold_override"] = payload.get("rvc_threshold_override")
    if "currency_mode" in payload:
        mode = str(payload.get("currency_mode") or "").strip().lower()
        if mode and mode not in SHEET_CURRENCY_MODES:
            raise HTTPException(status_code=400, detail=f"Unknown currency_mode {mode}")
        overrides["currency_mode"] = mode or "native"
    if "optimization_mode" in payload:
        mode = str(payload.get("optimization_mode") or "").strip().lower()
        if mode and mode not in SHEET_OPTIMIZATION_MODES:
            raise HTTPException(status_code=400, detail=f"Unknown optimization_mode {mode}")
        overrides["optimization_mode"] = mode or "max_lvc"
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    expected_revision = str(payload.get("expected_revision") or "").strip()
    if expected_revision and expected_revision != origin_case_revision(case):
        raise HTTPException(status_code=409, detail="Origin case state changed; reload before saving.")
    case = merge_origin_action_payload(case, payload)
    if not any(str(p.get("code") or "").strip() == product_code for p in case.get("products", [])):
        raise HTTPException(status_code=404, detail=f"Sheet {product_code} not found in case")
    case = set_origin_sheet_config_override(case, product_code, overrides)
    update_case_record(client, case)
    state = (case.get("origin_sheet_states") or {}).get(product_code, {})
    return JSONResponse({
        "ok": True,
        "product_code": product_code,
        "state": {
            "form_override": state.get("form_override", ""),
            "criteria_override": state.get("criteria_override", ""),
            "lvc_threshold_override": state.get("lvc_threshold_override", ""),
            "rvc_threshold_override": state.get("rvc_threshold_override", ""),
            "currency_mode": state.get("currency_mode", "native"),
            "optimization_mode": state.get("optimization_mode", "max_lvc"),
            "effective_form_code": state.get("effective_form_code", ""),
            "effective_criteria_text": state.get("effective_criteria_text", ""),
            "effective_lvc_threshold": state.get("effective_lvc_threshold", ""),
            "effective_rvc_threshold": state.get("effective_rvc_threshold", ""),
        },
    })


@app.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/reopen", response_class=HTMLResponse)
async def reopen_co_case_origin_sheet(request: Request, client_id: str, case_id: str, product_code: str):
    client = resolve_client(client_id)
    case, _payload = await origin_case_from_request(request, client, case_id)
    action_error = origin_sheet_action_error(case, product_code, "reopen")
    if action_error:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(
                client_id,
                case_id,
                current_step="origin",
                case=case,
                error=action_error,
                preserve_origin_products=True,
                fast_origin_context=True,
            ),
        )
    # Release ledger claims BEFORE updating case state so a DB failure leaves
    # the sheet in a consistent locked state (claims still held, sheet still
    # locked). The previous order (case state first, then release) meant a
    # release failure silently leaked the claim while the UI showed unlocked.
    try:
        co_stock_ledger.record_sheet_release(client_id, case_id, product_code)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "reopen failed for %s/%s/%s: %s", client_id, case_id, product_code, exc
        )
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(
                client_id,
                case_id,
                current_step="origin",
                case=case,
                error=f"Không mở chốt được bảng kê {product_code}: ledger lỗi ({exc}). Hãy thử lại.",
                preserve_origin_products=True,
                fast_origin_context=True,
            ),
        )
    case = set_origin_sheet_status(case, product_code, "calculated")
    update_case_record(client, case)
    invalidate_co_case_source_cache(client_id, case_id)
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(
            client_id,
            case_id,
            current_step="origin",
            case=case,
            message=f"Đã mở chốt bảng kê {product_code}.",
            preserve_origin_products=True,
            fast_origin_context=True,
        ),
    )


@app.post("/clients/{client_id}/evaluate", response_class=HTMLResponse)
async def evaluate(request: Request, client_id: str):
    form = await large_request_form(request)
    case = update_products_from_form({key: str(value) for key, value in form.items()})
    case_id = case.get("persisted_case_id", "")
    if case_id:
        client = resolve_client(client_id)
        lock_result = acquire_origin_calculation_lock(client, case_id, origin_lock_actor(request))
        if not lock_result["acquired"]:
            return templates.TemplateResponse(
                request=request,
                name="co_case.html",
                status_code=409,
                context=co_case_context(
                    client_id,
                    case=case,
                    current_step="origin",
                    error=f"Chưa thể tính lại: hồ sơ {lock_result['lock'].get('case_code') or lock_result['lock'].get('case_id')} đang giữ phiên tính tồn cho khách hàng này.",
                    origin_calculation_blocked=True,
                    preserve_origin_products=True,
                ),
            )
    context = co_case_context(
        client_id,
        case=case,
        current_step="origin",
        message="Đã tính lại theo dữ liệu đang sửa.",
        preserve_origin_products=False,
    )
    if context["case"].get("persisted_case_id"):
        try:
            update_case_record(
                resolve_client(client_id),
                case if context.get("origin_demo_active") else context["case"],
            )
        except KeyError:
            pass
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=context,
    )


@app.post("/clients/{client_id}/upload", response_class=HTMLResponse)
async def upload_workbook(request: Request, client_id: str, file: UploadFile = File(...)):
    client = resolve_client(client_id)
    content = await file.read()
    try:
        case = parse_input_workbook(content, source_label=f"Upload: {file.filename}")
    except WorkbookParseError as exc:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=400,
            context=co_case_context(client_id, error=str(exc)),
        )
    case["customer"] = client.get("legal_name") or client["name"]
    case["customer_legal_name"] = client.get("legal_name", "")
    case["customer_tax_code"] = client.get("tax_code", "")
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id, case=case, current_step="origin", message=f"Đã parse {file.filename}."),
    )


@app.get("/clients/{client_id}/demo-input.xlsx")
async def download_demo_input(client_id: str):
    content = create_input_workbook(client_case(resolve_client(client_id)))
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{client_id}-demo-input.xlsx"'},
    )


@app.post("/clients/{client_id}/export")
async def export_evidence(request: Request, client_id: str):
    resolve_client(client_id)
    form = await large_request_form(request)
    case = update_products_from_form({key: str(value) for key, value in form.items()})
    content = create_evidence_workbook(case)
    filename = f"{case['case_code'] or 'co-case'}-evidence.xlsx"
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
