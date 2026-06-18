from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import httpx
from fastapi import Request
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import co_auth
from app.bom_service import bom_service
from app.co_case_store import CaseClosedError
from app import co_stock_materializer
from app.database import apply_migrations, database_url
from app.data_hub_client import reset_current_data_hub_token, set_current_data_hub_token
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
from app.routers import pages as pages_routes
from app.web.client_context import effective_min_gap_days
from app.web.deps import require_local_source_writes
# Re-export shim: these symbols moved into app.routers.* / app.web.* during the
# main.py split, but tests still import / monkeypatch them via `app.main.X`.
# Kept here for backward compatibility; remove once tests import from source.
from app.routers.co_case import (
    _hydrate_product_export_declaration_dates,
    _to_vietnamese_date,
    invoice_search_options,
    mark_origin_sheets_stale,
    merge_origin_action_payload,
    set_origin_sheet_status,
)
from app.web.co_case_context import (
    _allocation_line_fx,
    _attach_fob_vnd,
    _calculate_stock_rows_from_snapshot,
    _refresh_co_stock_delta_or_full,
    attach_origin_sheet_states,
    case_allocation_pool,
    case_missing_stock_summary,
    case_stock_preview_summary,
    material_row_index,
    case_tkx_tkn_summary,
    co_case_bom_product_codes,
    co_case_source_context,
    co_stock_allocation_pool,
    enrich_origin_product,
    origin_build_signature,
    origin_material_from_bom_row,
    origin_sheet_action_error,
    origin_source_context,
    prepare_case_origin_products,
    prepare_case_origin_sheet,
    selected_bom_rows_by_product,
    stock_allocation_line,
)
from app.web.templating import templates


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
app.include_router(pages_routes.router)


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


