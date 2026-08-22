from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import httpx
from fastapi import Request
from fastapi import FastAPI
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

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
# Phase 1: the Data Hub half runs inside this app, not a second service. Mounted
# under a prefix because both halves own top-level /clients and /healthz;
# Starlette sets root_path="/hub" on the sub-app, which hub templates read as
# `url_prefix` so their URLs resolve in both the mounted and standalone shapes.
from hub.app.main import app as hub_app  # noqa: E402

app.mount("/hub", hub_app, name="hub")
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
from app.design_gallery import router as design_gallery_router; app.include_router(design_gallery_router)  # /design — component gallery (redesign 2026-08-20)


_ERROR_TITLES = {
    400: "Yêu cầu không hợp lệ",
    401: "Cần đăng nhập",
    403: "Không có quyền truy cập",
    404: "Không tìm thấy trang",
    409: "Chưa thực hiện được",
    413: "Dữ liệu quá lớn",
    422: "Dữ liệu không hợp lệ",
    503: "Dịch vụ tạm thời không khả dụng",
}


def _prefers_html_error(request: Request) -> bool:
    """True for a real browser navigation (native form submit / link click), False
    for an AJAX/fetch call. Browser navigations get a styled error page; fetch/XHR
    clients keep getting JSON so the existing in-page toast handling still works."""
    if request.headers.get("x-requested-with"):
        return False
    dest = request.headers.get("sec-fetch-dest")
    if dest:
        return dest == "document"
    return "text/html" in request.headers.get("accept", "")


def error_response(request: Request, status_code: int, detail: str, headers=None):
    """JSON for AJAX, a styled page for browser navigation — so an operator never
    sees a raw {"detail": …} blob after a native form submit / page load."""
    if _prefers_html_error(request):
        title = _ERROR_TITLES.get(
            status_code, "Lỗi máy chủ" if status_code >= 500 else "Đã xảy ra lỗi"
        )
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={"status_code": status_code, "title": title, "detail": detail},
            status_code=status_code,
        )
    return JSONResponse(status_code=status_code, content={"detail": detail}, headers=headers)


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Catch-all for HTTPException (404/403/409/…): render a friendly page for
    browsers, JSON for fetch. Replaces the default raw-JSON-everywhere handler."""
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail else "Đã xảy ra lỗi."
    return error_response(request, exc.status_code, detail, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError):
    """Bad request params: a styled page for browsers; the standard FastAPI 422
    JSON (with its error list) for fetch, so API clients see the field details."""
    if _prefers_html_error(request):
        return error_response(
            request, 422,
            "Dữ liệu gửi lên không hợp lệ. Kiểm tra lại các trường rồi thử lại.",
        )
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(CaseClosedError)
async def _case_closed_handler(request: Request, exc: CaseClosedError):
    """Mutating route hit a closed case → 409 with the friendly Vietnamese message."""
    return error_response(request, 409, str(exc))


@app.exception_handler(SourceBackendUnavailable)
async def _source_backend_unavailable_handler(request: Request, exc: SourceBackendUnavailable):
    """Data Hub is the source of truth but unavailable, and local fallback is not
    allowed → 503 with a clear message instead of a silently-empty page."""
    return error_response(request, 503, str(exc))


@app.exception_handler(httpx.TransportError)
async def _data_hub_unreachable_handler(request: Request, exc: httpx.TransportError):
    """Data Hub is enabled but the API is unreachable (connection refused /
    timeout). Surface a clear 503 instead of a generic 500 so the operator knows
    it's a Data Hub outage, not a CO bug. Only fires for transport errors that
    propagate unhandled — local try/except (e.g. 404 fallbacks) still wins."""
    return error_response(
        request, 503,
        "Data Hub không phản hồi (kết nối thất bại/timeout). CO không dùng dữ liệu "
        "local backup; kiểm tra Data Hub rồi thử lại.",
    )


@app.exception_handler(httpx.HTTPStatusError)
async def _data_hub_error_status_handler(request: Request, exc: httpx.HTTPStatusError):
    """Data Hub returned an error status that no route handled → 502 (bad
    gateway): the upstream source failed, not CO. Routes that intentionally
    handle Data Hub statuses (e.g. 404 → fallback) catch the error themselves
    and never reach this handler."""
    upstream = exc.response.status_code if exc.response is not None else "?"
    return error_response(
        request, 502,
        f"Data Hub trả lỗi ({upstream}). CO không dùng dữ liệu local backup; "
        "kiểm tra Data Hub rồi thử lại.",
    )


from app import money_display


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
# Money cells carry their own decimal rule (VND has no đồng fractions on a filed
# bảng kê, a USD đơn giá does) — see app/money_display.py.
templates.env.filters["money"] = money_display.format_money


@app.middleware("http")
async def require_data_hub_auth(request: Request, call_next):
    redirect = co_auth.guard_response(request)
    if redirect:
        return redirect
    co_auth.load_optional_user(request)
    # Publish the operator for the duration of the request so in-process Data
    # Hub reads can scope to them. This used to publish an access token for the
    # other service to verify; there is no other service.
    user_context = co_auth.CURRENT_CO_USER.set(co_auth.current_user(request))
    try:
        return await call_next(request)
    finally:
        co_auth.CURRENT_CO_USER.reset(user_context)


