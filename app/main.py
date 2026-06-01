from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import httpx
from fastapi import File, Request, UploadFile
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import co_auth
from app.bom_service import bom_service
from app.co_case_store import CaseClosedError, acquire_origin_calculation_lock, update_case_record
from app import co_stock_eligibility, co_stock_materializer
from app.database import apply_migrations, database_url
from app.data_hub_client import reset_current_data_hub_token, set_current_data_hub_token
from app.demo_data import update_products_from_form
from app.app_state_store import get_app_state_store
from app.portfolio import SourceBackendUnavailable, portfolio_app, portfolio_service
from app.routers import auth as auth_routes
from app.routers import catalog as catalog_routes
from app.routers import co_case as co_case_routes
from app.routers import bcct as bcct_routes
from app.routers import bom as bom_routes
from app.routers import cost_allocation as cost_allocation_routes
from app.routers import co_stock as co_stock_routes
from app.routers import customs_fx as customs_fx_routes
from app.routers import settings as settings_routes
from app.web.client_context import (
    _data_hub_overview_context,
    client_case,
    client_context,
    effective_min_gap_days,
    resolve_client,
)
from app.web.deps import large_request_form, require_local_source_writes
from app.routers.co_case import (
    _hydrate_product_export_declaration_dates,
    _to_vietnamese_date,
    invoice_search_options,
    mark_origin_sheets_stale,
    merge_origin_action_payload,
    resolve_shipment_reference,
    set_origin_sheet_status,
)
from app.web.co_case_context import (
    _allocation_line_fx,
    _attach_fob_vnd,
    _calculate_stock_rows_from_snapshot,
    _refresh_co_stock_delta_or_full,
    attach_origin_sheet_states,
    case_allocation_pool,
    case_tkx_tkn_summary,
    co_case_bom_product_codes,
    co_case_context,
    co_case_source_context,
    co_stock_allocation_pool,
    co_stock_has_value,
    co_stock_is_usable,
    co_stock_key_candidates,
    decimal_value,
    enrich_client_with_source_summary,
    enrich_origin_product,
    origin_build_signature,
    origin_lock_actor,
    origin_material_from_bom_row,
    origin_sheet_action_error,
    origin_source_context,
    prepare_case_origin_products,
    prepare_case_origin_sheet,
    selected_bom_rows_by_product,
    stock_allocation_line,
)
from app.web.templating import templates
from app.workbook_io import (
    WorkbookParseError,
    create_evidence_workbook,
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
app.include_router(co_case_routes.router)
app.include_router(bcct_routes.router)
app.include_router(bom_routes.router)
app.include_router(co_stock_routes.router)
app.include_router(cost_allocation_routes.router)
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


def resolve_invoice_reference(client: dict, reference: str) -> dict:
    resolved = resolve_shipment_reference(client, reference)
    return {
        "invoice_no": resolved["invoice_no"],
        "source_reference": resolved["source_reference"],
        "source_reference_type": resolved["source_reference_type"],
    }


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


def config_context(client_id: str, **extra) -> dict:
    # /config only renders client identity + client_config knobs. It does NOT
    # need source_workspace / bom_workspace, so skip the full pagination that
    # client_context triggers (Johnson: ~65k BCCT rows over HTTP per render).
    lean = _data_hub_overview_context(client_id, "config", dh_path="")
    if lean is not None:
        lean.update(extra)
        return lean
    return client_context(client_id, "config", **extra)


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


# Specific GET routes that share the /clients/{client_id}/co-case/{case_id}/...
# prefix MUST be defined before the catch-all {step} route below — FastAPI's
# router is order-sensitive, and {step} would otherwise swallow any single-
# segment GET (e.g. /export-bang-ke) and 404 it for not being a workflow key.


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
