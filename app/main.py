from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import co_auth
from app.bom_store import attach_case_bom_snapshot
from app.bom_service import bom_service
from app.co_case_store import (
    MAX_SUPPORTING_FILE_BYTES,
    build_case_criteria_rows,
    case_from_record,
    create_case_record,
    create_case_workbook,
    get_case_record,
    get_case_workspace,
    safe_filename,
    save_supporting_file,
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
from app.client_registry import get_client as registry_get_client
from app.client_registry import get_client_case
from app.customs_fx_store import CUSTOMS_FX_CLIENT_ID, get_customs_fx_store, refresh_customs_exchange_rates
from app.data_hub_client import DataHubClient, reset_current_data_hub_token, set_current_data_hub_token
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
from app.portfolio import portfolio_app, portfolio_service
from app.source_store import (
    attach_case_source_snapshot,
    enrich_client_with_source_workspace,
)
from app.table_view import build_table_view
from app.workbook_io import (
    WorkbookParseError,
    create_evidence_workbook,
    create_input_workbook,
    parse_input_workbook,
)

ROOT = Path(__file__).resolve().parent

THEME_COOKIE = "co_theme"
SUPPORTED_THEMES = {"light", "dark"}


def normalize_theme(value: str | None) -> str:
    return value if value in SUPPORTED_THEMES else "light"


def theme_context(request: Request) -> dict[str, str]:
    theme = normalize_theme(request.cookies.get(THEME_COOKIE))
    user = co_auth.current_user(request)
    return {
        "theme": theme,
        "next_theme": "light" if theme == "dark" else "dark",
        "co_user": user,
        "auth_required": co_auth.auth_required(),
        "show_login": (co_auth.auth_required() or co_auth.data_hub_source_mode_enabled()) and request.url.path != "/auth/logout",
        "can_view_technical_settings": co_auth.can_view_technical_settings(user),
    }


app = FastAPI(title="Barry CO Demo")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount("/portfolio", portfolio_app, name="portfolio")

templates = Jinja2Templates(directory=ROOT / "templates", context_processors=[theme_context])


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

CATALOG_VIEWS = {
    "materials": {
        "module": "material_catalog",
        "title": "DS NVL DK HQ",
        "subtitle": "Nguyên vật liệu theo danh mục đăng ký hải quan.",
        "template_url": "material-template.xlsx",
        "template_label": "Tải template DS NVL",
        "columns": [
            {"key": "customs_code", "label": "Mã HQ", "class": "mono"},
            {"key": "name", "label": "Tên"},
            {"key": "unit", "label": "ĐVT", "class": "mono"},
            {"key": "hs_code", "label": "HS", "class": "mono"},
            {"key": "purpose", "label": "Mục đích"},
            {"key": "origin_default", "label": "Xuất xứ mặc định"},
            {"key": "status", "label": "Trạng thái"},
        ],
        "filters": [
            {"name": "status", "field": "status", "label": "Trạng thái"},
            {"name": "unit", "field": "unit", "label": "ĐVT"},
            {"name": "hs", "field": "hs_code", "label": "HS"},
            {"name": "purpose", "field": "purpose", "label": "Mục đích"},
        ],
        "summary_fields": [
            {"field": "status", "label": "Trạng thái"},
            {"field": "unit", "label": "ĐVT"},
        ],
        "default_sort": "customs_code",
    },
    "products": {
        "module": "product_catalog",
        "title": "DS SP DK HQ",
        "subtitle": "Thành phẩm theo danh mục đăng ký hải quan.",
        "template_url": "product-template.xlsx",
        "template_label": "Tải template DS SP",
        "columns": [
            {"key": "product_code", "label": "Mã SP", "class": "mono"},
            {"key": "name", "label": "Tên"},
            {"key": "unit", "label": "ĐVT", "class": "mono"},
            {"key": "hs_code", "label": "HS", "class": "mono"},
            {"key": "purpose", "label": "Mục đích"},
            {"key": "status", "label": "Trạng thái"},
        ],
        "filters": [
            {"name": "status", "field": "status", "label": "Trạng thái"},
            {"name": "unit", "field": "unit", "label": "ĐVT"},
            {"name": "hs", "field": "hs_code", "label": "HS"},
            {"name": "purpose", "field": "purpose", "label": "Mục đích"},
        ],
        "summary_fields": [
            {"field": "status", "label": "Trạng thái"},
            {"field": "unit", "label": "ĐVT"},
        ],
        "default_sort": "product_code",
    },
}

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

CO_CASE_WORKFLOW_STEPS = [
    {
        "key": "shipment",
        "label": "Lô hàng",
        "short_label": "1",
        "description": "Thông tin shipment, invoice, B/L và thị trường.",
    },
    {
        "key": "documents",
        "label": "Chứng từ",
        "short_label": "2",
        "description": "Upload invoice, vận đơn, packing list và bằng chứng kèm theo.",
    },
    {
        "key": "exports",
        "label": "Tờ khai xuất",
        "short_label": "3",
        "description": "Đối chiếu tờ khai xuất đã review theo invoice.",
    },
    {
        "key": "guidance",
        "label": "Form & PSR",
        "short_label": "4",
        "description": "Gợi ý form, thông tư và trạng thái tra cứu quy tắc.",
    },
    {
        "key": "origin",
        "label": "Xuất xứ",
        "short_label": "5",
        "description": "Chạy RVC/CTSH và xem preview phân bổ.",
    },
    {
        "key": "review",
        "label": "Review & xuất",
        "short_label": "6",
        "description": "Kiểm tra dossier và xuất workbook.",
    },
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
]

CUSTOMS_FX_COLUMNS = [
    {"key": "currency_code", "label": "Nguyên tệ", "class": "mono"},
    {"key": "currency_name", "label": "Tên ngoại tệ"},
    {"key": "effective_date", "label": "Ngày hiệu lực", "class": "mono"},
    {"key": "rate_display", "label": "Tỷ giá", "class": "num", "sortable": False},
    {"key": "source_endpoint", "label": "Nguồn API", "class": "mono"},
    {"key": "fetched_at", "label": "Lần lấy", "class": "mono"},
]

BOM_PRODUCT_COLUMNS = [
    {"key": "product_code", "label": "Mã TP", "class": "mono", "link_key": "view_href"},
    {"key": "product_version_no", "label": "TP version", "class": "mono"},
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


@app.post("/settings/theme")
async def set_theme(theme: str = Form("light"), next_url: str = Form("/clients")):
    target = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/clients"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        THEME_COOKIE,
        normalize_theme(theme),
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="lax",
    )
    return response


def require_technical_settings_dev(request: Request) -> None:
    if not co_auth.can_view_technical_settings(co_auth.current_user(request)):
        raise HTTPException(status_code=403, detail="Technical settings require a dev Data Hub session.")


def mask_secret(value: str) -> str:
    if not value:
        return "Chưa cấu hình"
    return f"Đã cấu hình ({len(value)} ký tự)"


def data_hub_settings_context(request: Request, *, saved: bool = False, error: str = "", test_result: dict | None = None) -> dict:
    settings = data_hub_link_settings()
    overrides = load_data_hub_overrides()
    env_values = os.environ
    token_source = "environment" if env_values.get("DATA_HUB_API_TOKEN") else "local override" if "DATA_HUB_API_TOKEN" in overrides else "missing"
    rows = [
        {"key": "DATA_HUB_ENABLED", "label": "Dùng Data Hub cho source/master data", "value": "1" if settings.source_enabled else "0", "type": "checkbox"},
        {"key": "CO_AUTH_REQUIRED", "label": "Bắt buộc Data Hub SSO cho CO", "value": "1" if settings.auth_required else "0", "type": "checkbox"},
        {"key": "DATA_HUB_BASE_URL", "label": "Data Hub browser URL", "value": settings.data_hub_base_url, "type": "url"},
        {"key": "DATA_HUB_API_BASE_URL", "label": "Data Hub API URL", "value": settings.data_hub_api_base_url, "type": "url"},
        {"key": "DATA_HUB_ISSUER_URL", "label": "JWT issuer", "value": settings.issuer_url, "type": "url"},
        {"key": "DATA_HUB_JWKS_URL", "label": "JWKS URL", "value": settings.jwks_url, "type": "url"},
        {"key": "CO_PUBLIC_BASE_URL", "label": "CO public URL", "value": settings.co_public_base_url, "type": "url"},
        {"key": "CO_FORCE_HTTPS_COOKIE", "label": "Secure cookie HTTPS", "value": "1" if settings.force_https_cookie else "0", "type": "checkbox"},
        {"key": "DATA_HUB_REQUEST_TIMEOUT_SECONDS", "label": "Request timeout seconds", "value": str(settings.request_timeout_seconds), "type": "number"},
        {"key": "DATA_HUB_CLIENT_CLAIM_KEYS", "label": "Client claim keys", "value": ",".join(settings.client_claim_keys), "type": "text"},
        {"key": "DATA_HUB_ADMIN_ROLES", "label": "Admin roles", "value": ",".join(sorted(settings.admin_roles)), "type": "text"},
    ]
    for row in rows:
        row["source"] = "environment" if row["key"] in env_values else "local override" if row["key"] in overrides else "default"
    return {
        "saved": saved,
        "error": error,
        "settings": settings,
        "rows": rows,
        "token": {
            "configured": bool(settings.api_token),
            "masked": mask_secret(settings.api_token),
            "source": token_source,
            "has_local_override": "DATA_HUB_API_TOKEN" in overrides,
        },
        "config_path": str(data_hub_config_path()),
        "test_result": test_result,
    }


def data_hub_override_payload(form, current_overrides: dict[str, str]) -> dict[str, str]:
    payload: dict[str, str] = {
        "DATA_HUB_ENABLED": "1" if form.get("DATA_HUB_ENABLED") == "1" else "0",
        "CO_AUTH_REQUIRED": "1" if form.get("CO_AUTH_REQUIRED") == "1" else "0",
        "CO_FORCE_HTTPS_COOKIE": "1" if form.get("CO_FORCE_HTTPS_COOKIE") == "1" else "0",
    }
    for key in DATA_HUB_LINK_ENV_KEYS:
        if key in payload or key in {"DATA_HUB_API_TOKEN", "CO_FORCE_HTTPS_COOKIE"}:
            continue
        payload[key] = str(form.get(key, "")).strip()
    token = str(form.get("DATA_HUB_API_TOKEN", "")).strip()
    if token:
        payload["DATA_HUB_API_TOKEN"] = token
    elif form.get("CLEAR_DATA_HUB_API_TOKEN") != "1" and current_overrides.get("DATA_HUB_API_TOKEN"):
        payload["DATA_HUB_API_TOKEN"] = current_overrides["DATA_HUB_API_TOKEN"]
    return payload


def data_hub_link_check() -> dict:
    settings = data_hub_link_settings()
    checks: list[dict] = []
    try:
        jwks = co_auth.fetch_data_hub_jwks(settings.jwks_url)
        key_count = len(jwks.get("keys", [])) if isinstance(jwks, dict) else 0
        checks.append({"name": "JWKS", "status": "success", "detail": f"{key_count} signing keys"})
    except Exception as exc:
        checks.append({"name": "JWKS", "status": "error", "detail": str(exc)})

    if not settings.source_enabled:
        checks.append({"name": "Source API", "status": "warning", "detail": "DATA_HUB_ENABLED đang tắt"})
    elif not settings.api_token:
        checks.append({"name": "Source API", "status": "error", "detail": "DATA_HUB_API_TOKEN chưa cấu hình"})
    else:
        client = DataHubClient(
            base_url=settings.data_hub_api_base_url,
            token=settings.api_token,
            timeout=settings.request_timeout_seconds,
        )
        try:
            clients = client.list_clients()
            checks.append({"name": "Source API", "status": "success", "detail": f"{len(clients)} clients"})
        except Exception as exc:
            checks.append({"name": "Source API", "status": "error", "detail": str(exc)})
        finally:
            client.close()
    return {"ok": all(check["status"] != "error" for check in checks), "checks": checks}


@app.get("/user", response_class=HTMLResponse)
async def user_page(request: Request, logged_out: str = ""):
    user = co_auth.current_user(request)
    return templates.TemplateResponse(
        request=request,
        name="user.html",
        context={
            "user": user,
            "logged_out": logged_out == "1",
            "visible_clients": sorted(co_auth.visible_client_ids(user) or []) if user and co_auth.visible_client_ids(user) is not None else [],
            "all_clients": bool(user and co_auth.visible_client_ids(user) is None),
        },
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "can_view_technical_settings": co_auth.can_view_technical_settings(co_auth.current_user(request)),
        },
    )


@app.get("/settings/technical", response_class=HTMLResponse)
@app.get("/settings/data-hub", response_class=HTMLResponse)
async def data_hub_settings_page(request: Request, saved: str = ""):
    require_technical_settings_dev(request)
    return templates.TemplateResponse(
        request=request,
        name="data_hub_settings.html",
        context=data_hub_settings_context(request, saved=saved == "1"),
    )


@app.post("/settings/technical", response_class=HTMLResponse)
@app.post("/settings/data-hub", response_class=HTMLResponse)
async def save_data_hub_settings(request: Request):
    require_technical_settings_dev(request)
    form = await request.form()
    payload = data_hub_override_payload(form, load_data_hub_overrides())
    try:
        DataHubLinkSettings.from_env(payload)
        DataHubLinkSettings.from_env({**payload, **os.environ})
    except RuntimeError as exc:
        return templates.TemplateResponse(
            request=request,
            name="data_hub_settings.html",
            context=data_hub_settings_context(request, error=str(exc)),
            status_code=400,
        )
    save_data_hub_overrides(payload)
    return RedirectResponse("/settings/technical?saved=1", status_code=303)


@app.post("/settings/technical/test", response_class=HTMLResponse)
@app.post("/settings/data-hub/test", response_class=HTMLResponse)
async def test_data_hub_settings(request: Request):
    require_technical_settings_dev(request)
    return templates.TemplateResponse(
        request=request,
        name="data_hub_settings.html",
        context=data_hub_settings_context(request, test_result=data_hub_link_check()),
    )


@app.get("/auth/login")
async def auth_login(request: Request, next: str = "/clients"):
    redirect_uri = f"{co_auth.co_public_base_url(request)}/auth/callback"
    return RedirectResponse(
        co_auth.data_hub_authorize_url(redirect_uri=redirect_uri, state=next),
        status_code=303,
    )


@app.post("/auth/logout")
async def auth_logout(request: Request, next_url: str = Form("/clients")):
    next_path = co_auth.safe_next_path(next_url)
    if co_auth.auth_required():
        request.state.co_user = None
        response = templates.TemplateResponse(
            request=request,
            name="sso_logout.html",
            context={
                "data_hub_logout_url": co_auth.data_hub_logout_url(),
                "next_path": next_path,
            },
        )
        co_auth.clear_session_cookie(response)
        return response
    target = f"{next_path}?logged_out=1" if next_path == "/user" else next_path
    response = RedirectResponse(target, status_code=303)
    co_auth.clear_session_cookie(response)
    return response


@app.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request, code: str = "", state: str = "/clients"):
    next_url = co_auth.safe_next_path(state)
    if not code:
        return RedirectResponse(f"/auth/login?next={quote(next_url, safe='/')}", status_code=303)
    redirect_uri = f"{co_auth.co_public_base_url(request)}/auth/callback"
    try:
        payload = co_auth.exchange_data_hub_sso_code(code, redirect_uri=redirect_uri)
        token = str(payload["access_token"])
        verifier = co_auth.DataHubTokenVerifier(
            issuer=co_auth.data_hub_issuer_urls(),
            jwks_provider=lambda: co_auth.fetch_data_hub_jwks(co_auth.data_hub_jwks_url()),
        )
        verifier.verify(token)
    except Exception:
        response = PlainTextResponse(
            "Data Hub login failed. Check Technical Settings for issuer/JWKS and Data Hub SSO config.",
            status_code=401,
        )
        co_auth.clear_session_cookie(response)
        return response
    response = RedirectResponse(next_url, status_code=303)
    co_auth.set_session_cookie(response, token, int(payload.get("expires_in") or 600))
    return response


def require_local_source_writes() -> None:
    if co_auth.data_hub_source_mode_enabled():
        raise HTTPException(
            status_code=409,
            detail="Shared source data is read-only in CO when DATA_HUB_ENABLED is active. Use Data Hub for source changes.",
        )


def resolve_client(client_id: str) -> dict:
    service_client = getattr(portfolio_service, "client", None)
    if callable(service_client):
        return service_client(client_id)
    return registry_get_client(client_id)


def default_client_case(client: dict) -> dict:
    case = clone_case(DEMO_CASE)
    case.update(
        {
            "id": f"{client['id']}-empty-co-case",
            "customer": client["name"],
            "case_code": "Chưa tạo",
            "title": f"Hồ sơ C/O {client['name']}",
            "destination_market": "Chưa nhập",
            "agreement": "Chưa nhập",
            "co_form_type": "Chưa nhập",
            "source_label": "Chưa có dữ liệu C/O",
            "products": [],
        }
    )
    return attach_results(case)


def client_case(client: dict) -> dict:
    try:
        return get_client_case(client["id"])
    except KeyError:
        return default_client_case(client)


def client_context(client_id: str, active: str, **extra):
    client = resolve_client(client_id)
    case = extra.pop("case", client_case(client))
    source_workspace, source_backend = source_workspace_for_client(client)
    client = enrich_client_with_source_workspace(client, source_workspace)
    bom_workspace = bom_service.workspace(client)
    case = attach_case_bom_snapshot(case, bom_workspace)
    case = attach_case_source_snapshot(case, source_workspace)
    return {
        "client": client,
        "case": case,
        "active": active,
        "bom_workspace": bom_workspace,
        "source_workspace": source_workspace,
        "client_config": source_workspace["client_config"],
        "case_workspace": extra.pop("case_workspace", get_case_workspace(client)),
        "form_candidates": extra.pop("form_candidates", form_candidates_for_market(case.get("destination_market", ""))),
        "form_lanes": prioritized_form_lanes(case.get("destination_market", ""), case_finished_hs_codes(case)),
        "recommended_form_lane": recommended_form_lane(
            prioritized_form_lanes(case.get("destination_market", ""), case_finished_hs_codes(case))
        ),
        "common_market_presets": COMMON_MARKET_PRESETS,
        "common_market_guidance": common_market_guidance(),
        "invoice_matches": extra.pop("invoice_matches", []),
        "invoice_criteria_rows": extra.pop("invoice_criteria_rows", []),
        "criteria_rows": extra.pop("criteria_rows", []),
        "source_notes": SOURCE_NOTES,
        "source_backend": source_backend,
        **extra,
    }


def source_workspace_for_client(client: dict) -> tuple[dict, str]:
    return portfolio_service.source_workspace(client)


def co_case_light_context(client_id: str, case: dict, current_step: str, **extra) -> dict:
    client = resolve_client(client_id)
    source_context = co_case_source_context(client, case)
    source_summary = source_context["source_summary"]
    invoice_matches = source_context["invoice_matches"]
    case_workspace = extra.pop("case_workspace")
    form_candidates = extra.pop("form_candidates")
    criteria_rows = extra.pop("criteria_rows")
    bom_workspace = bom_service.workspace(client) if current_step == "origin" else minimal_bom_workspace()
    client = enrich_client_with_source_summary(client, source_summary)
    case = attach_case_source_summary_snapshot(case, source_summary)
    if current_step == "origin":
        case = attach_case_bom_snapshot(case, bom_workspace)
    origin_demo_active = should_show_origin_demo(current_step, case, invoice_matches)
    if origin_demo_active:
        case = attach_origin_demo(case)
        criteria_rows = build_case_criteria_rows(case, form_candidates)
    form_lanes = prioritized_form_lanes(case.get("destination_market", ""), co_case_hs_codes(case, invoice_matches))
    selected_form_lane = recommended_form_lane(form_lanes)
    invoice_criteria_rows = invoice_match_criteria_rows(invoice_matches, selected_form_lane)
    if not criteria_rows and invoice_criteria_rows:
        criteria_rows = invoice_criteria_rows
    context = {
        "client": client,
        "case": case,
        "active": "co-case",
        "bom_workspace": bom_workspace,
        "source_workspace": {},
        "client_config": source_summary["client_config"],
        "case_workspace": case_workspace,
        "form_candidates": form_candidates,
        "form_lanes": form_lanes,
        "recommended_form_lane": selected_form_lane,
        "common_market_presets": COMMON_MARKET_PRESETS,
        "common_market_guidance": common_market_guidance(),
        "invoice_matches": invoice_matches,
        "invoice_criteria_rows": invoice_criteria_rows,
        "criteria_rows": criteria_rows,
        "origin_demo_active": origin_demo_active,
        "origin_demo_material_count": origin_material_count(case) if origin_demo_active else 0,
        "source_notes": SOURCE_NOTES,
        "source_backend": source_context["source_backend"],
        **extra,
    }
    context["co_case_active_step"] = current_step
    context["co_case_steps"] = co_case_workflow_steps(client_id, context["case"], current_step)
    return context


def co_case_source_context(client: dict, case: dict) -> dict:
    return portfolio_service.co_case_source_context(client, case)


def should_show_origin_demo(current_step: str, case: dict, invoice_matches: list[dict]) -> bool:
    return current_step == "origin" and not case.get("products") and not invoice_matches


def attach_origin_demo(case: dict) -> dict:
    demo = attach_results(clone_case(DEMO_CASE))
    case = dict(case)
    case["products"] = demo["products"]
    if not case.get("documents"):
        case["documents"] = demo["documents"]
    case["summary"] = demo["summary"]
    case["mode"] = "Demo tự nạp trong tab Xuất xứ"
    case["mode_note"] = "Dùng khi hồ sơ chưa có đủ invoice/BCCT/BOM để tính thật; không ghi vào hồ sơ lưu."
    return case


def origin_material_count(case: dict) -> int:
    return sum(len(product.get("materials", [])) for product in case.get("products", []))


def case_finished_hs_codes(case: dict) -> list[str]:
    return [
        str(product.get("finished_hs", ""))
        for product in case.get("products", [])
        if str(product.get("finished_hs", "")).strip()
    ]


def co_case_hs_codes(case: dict, invoice_matches: list[dict]) -> list[str]:
    product_hs = case_finished_hs_codes(case)
    if product_hs:
        return product_hs
    return [
        str(row.get("hs_code", ""))
        for row in invoice_matches
        if str(row.get("hs_code", "")).strip()
    ]


def invoice_match_criteria_rows(invoice_matches: list[dict], form_lane: dict) -> list[dict]:
    if not form_lane:
        return []
    rows = []
    seen = set()
    for row in invoice_matches:
        hs_code = str(row.get("hs_code", "")).strip()
        product_code = str(row.get("item_code", "")).strip()
        key = (product_code, hs_code, str(row.get("declaration_no", "")), str(row.get("line_no", "")))
        if not hs_code or key in seen:
            continue
        seen.add(key)
        preview = criteria_preview_for_hs(form_lane["form_code"], hs_code)
        rows.append({
            "product_code": product_code,
            "product_name": row.get("description", ""),
            "finished_hs": hs_code,
            "form": form_lane["display_name"],
            "agreement": form_lane["agreement"],
            "instrument": form_lane["instrument"],
            "rule": preview["criteria"],
            "rule_note": preview["note"],
            "source_reference": preview["source_reference"],
            "rvc_percentage": "",
            "tariff_shift_status": "Chờ BOM",
            "material_code": "",
            "material_name": "",
            "material_hs": "",
            "origin_status": "BCCT invoice",
            "non_origin_cif_value": "",
            "declaration_no": row.get("declaration_no", ""),
            "line_no": row.get("line_no", ""),
            "quantity": row.get("quantity", ""),
            "unit": row.get("unit", ""),
            "invoice_ref": row.get("invoice_ref", ""),
        })
    return rows


def enrich_client_with_source_summary(client: dict, source_summary: dict) -> dict:
    client["counts"] = {
        **client.get("counts", {}),
        "materials": source_summary["material_catalog"]["published_row_count"],
        "products": source_summary["product_catalog"]["published_row_count"],
        "bcct": source_summary["bcct"]["published_row_count"],
        "co_stock": source_summary["co_stock_row_count"],
    }
    return client


def attach_case_source_summary_snapshot(case: dict, source_summary: dict) -> dict:
    material = source_summary["material_catalog"].get("latest_version") or {}
    product = source_summary["product_catalog"].get("latest_version") or {}
    bcct = source_summary["bcct"].get("latest_version") or {}
    case["source_snapshot"] = {
        "material_catalog_version_id": material.get("version_id", ""),
        "material_catalog_version_no": material.get("version_no", ""),
        "product_catalog_version_id": product.get("version_id", ""),
        "product_catalog_version_no": product.get("version_no", ""),
        "bcct_version_id": bcct.get("version_id", ""),
        "bcct_version_no": bcct.get("version_no", ""),
        "bcct_reviewed_row_count": source_summary["bcct"].get("reviewed_row_count", 0),
        "correction_candidate_count": source_summary["bcct"].get("correction_candidate_count", 0),
        "client_config_version": source_summary["client_config"].get("config_version", ""),
        "client_config_hash": source_summary["client_config"].get("config_hash", ""),
    }
    return case


def minimal_bom_workspace() -> dict:
    return {
        "versions": [],
        "product_versions": [],
        "product_version_options_by_code": {},
        "latest_version": {},
    }


def catalog_table_context(request: Request, client_id: str, view_name: str, **extra) -> dict:
    view = CATALOG_VIEWS[view_name]
    context = client_context(client_id, "catalog", **extra)
    rows = context["source_workspace"][view["module"]]["published_rows"]
    context["catalog_view"] = {**view, "name": view_name}
    context["source_table"] = build_table_view(
        rows,
        columns=view["columns"],
        query=request.query_params,
        filters=view["filters"],
        summary_fields=view["summary_fields"],
        default_sort=view["default_sort"],
    )
    return context


def bcct_table_context(request: Request, client_id: str, direction: str | None = None, **extra) -> dict:
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


def co_stock_table_context(request: Request, client_id: str) -> dict:
    context = client_context(client_id, "co-stock")
    rows = [co_stock_table_row(row) for row in context["client"]["co_stock"]]
    context["source_table"] = build_table_view(
        rows,
        columns=CO_STOCK_COLUMNS,
        query=request.query_params,
        filters=[
            {
                "name": "status",
                "field": "status",
                "label": "Trạng thái",
                "options": [
                    {"value": "available", "label": "Khả dụng"},
                    {"value": "review_required", "label": "Cần review"},
                    {"value": "inactive", "label": "Không dùng"},
                    {"value": "depleted", "label": "Hết tồn"},
                ],
            }
        ],
        summary_fields=[
            {"field": "status_label", "label": "Trạng thái"},
            {"field": "declaration_type", "label": "Loại hình"},
        ],
        default_sort="import_declaration_no",
    )
    return context


def customs_exchange_rate_context(request: Request, **extra) -> dict:
    context = dict(extra)
    store = get_customs_fx_store()
    rows = store.rows(CUSTOMS_FX_CLIENT_ID)
    query = dict(request.query_params)
    if "sort" not in query:
        query["sort"] = "effective_date"
        query["dir"] = "desc"
    context["customs_fx_scope"] = CUSTOMS_FX_CLIENT_ID
    context["customs_fx_summary"] = store.summary(CUSTOMS_FX_CLIENT_ID)
    context["source_table"] = build_table_view(
        rows,
        columns=CUSTOMS_FX_COLUMNS,
        query=query,
        filters=[
            {"name": "currency", "field": "currency_code", "label": "Nguyên tệ"},
            {"name": "endpoint", "field": "source_endpoint", "label": "Nguồn API"},
        ],
        summary_fields=[
            {"field": "currency_code", "label": "Nguyên tệ"},
            {"field": "source_endpoint", "label": "Nguồn API"},
        ],
        default_sort="effective_date",
    )
    return context


def bom_context(request: Request, client_id: str, **extra) -> dict:
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


def co_case_context(client_id: str, case_id: str = "", current_step: str = "index", **extra) -> dict:
    client = resolve_client(client_id)
    case = extra.pop("case", None)
    effective_case_id = case_id or (case or {}).get("persisted_case_id", "")
    workspace = get_case_workspace(client, effective_case_id)
    record = get_case_record(client, effective_case_id) if effective_case_id else None
    if case is None:
        case = client_case(client)
        if record:
            case = case_from_record(case, client, record)
    elif record:
        case.setdefault("persisted_case_id", record["case_id"])
        case["supporting_files"] = [dict(file_row) for file_row in record.get("supporting_files", [])]
    case.setdefault("persisted_case_id", "")
    case.setdefault("shipment", {"invoice_no": "", "bill_of_lading_no": ""})
    case["shipment"].setdefault("invoice_no", "")
    case["shipment"].setdefault("bill_of_lading_no", "")
    case.setdefault("supporting_files", [])
    form_candidates = form_candidates_for_market(case.get("destination_market", ""))
    criteria_rows = build_case_criteria_rows(case, form_candidates)
    return co_case_light_context(
        client_id,
        case=case,
        current_step=current_step,
        case_workspace=workspace,
        form_candidates=form_candidates,
        criteria_rows=criteria_rows,
        **extra,
    )


def co_case_workflow_steps(client_id: str, case: dict, current_step: str) -> list[dict]:
    case_id = case.get("persisted_case_id", "")
    base_url = f"/clients/{client_id}/co-case/{case_id}" if case_id else ""
    steps = []
    for step in CO_CASE_WORKFLOW_STEPS:
        href = base_url if step["key"] == "shipment" else f"{base_url}/{step['key']}"
        steps.append({
            **step,
            "href": href,
            "active": current_step == step["key"],
            "status": co_case_step_status(case, step["key"]),
        })
    return steps


def co_case_step_status(case: dict, step_key: str) -> str:
    shipment = case.get("shipment", {})
    if step_key == "shipment":
        return "ready" if shipment.get("invoice_no") and case.get("destination_market") else "todo"
    if step_key == "documents":
        return "ready" if case.get("supporting_files") else "todo"
    if step_key == "exports":
        return "review"
    if step_key == "guidance":
        return "review"
    if step_key == "origin":
        return "preview"
    return "todo"


def config_context(client_id: str, **extra) -> dict:
    context = client_context(client_id, "config", **extra)
    return context


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
    return templates.TemplateResponse(
        request=request,
        name="workspace.html",
        context=client_context(client_id, "overview"),
    )


@app.get("/clients/{client_id}/catalog", response_class=HTMLResponse)
async def catalog(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="catalog.html",
        context=client_context(client_id, "catalog"),
    )


@app.get("/clients/{client_id}/catalog/materials", response_class=HTMLResponse)
async def material_catalog(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="catalog_table.html",
        context=catalog_table_context(request, client_id, "materials"),
    )


@app.get("/clients/{client_id}/catalog/products", response_class=HTMLResponse)
async def product_catalog(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="catalog_table.html",
        context=catalog_table_context(request, client_id, "products"),
    )


@app.get("/clients/{client_id}/catalog/material-template.xlsx")
async def download_material_catalog_template(client_id: str):
    require_local_source_writes()
    content = portfolio_service.material_catalog_template(resolve_client(client_id))
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{client_id}-ds-nvl-template.xlsx"'},
    )


@app.get("/clients/{client_id}/catalog/product-template.xlsx")
async def download_product_catalog_template(client_id: str):
    require_local_source_writes()
    content = portfolio_service.product_catalog_template(resolve_client(client_id))
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{client_id}-ds-sp-template.xlsx"'},
    )


@app.post("/clients/{client_id}/catalog/upload", response_class=HTMLResponse)
async def upload_catalog_workbook(
    request: Request,
    client_id: str,
    file: UploadFile = File(...),
    catalog_type: str = Form("material"),
    upload_scope: str = Form("full_catalog"),
):
    require_local_source_writes()
    client = resolve_client(client_id)
    result = portfolio_service.process_catalog_upload(
        client,
        catalog_type,
        await file.read(),
        file.filename or "catalog.xlsx",
        upload_scope,
    )
    status_code = 400 if result["status"] == "failed" else 200
    view_name = "products" if catalog_type == "product" else "materials"
    return templates.TemplateResponse(
        request=request,
        name="catalog_table.html",
        status_code=status_code,
        context=catalog_table_context(
            request,
            client_id,
            view_name,
            catalog_result=result,
            message=result["message"] if status_code == 200 else "",
            error=result["message"] if status_code == 400 else "",
        ),
    )


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
    require_local_source_writes()
    client = resolve_client(client_id)
    form = await request.form()
    config = portfolio_service.get_client_config(client)
    config["bcct"]["eligible_import_declaration_types"] = str(form.get("eligible_import_declaration_types", ""))
    config["bcct"]["relevant_export_declaration_types"] = str(form.get("relevant_export_declaration_types", ""))
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


@app.get("/customs-exchange-rates", response_class=HTMLResponse)
async def customs_exchange_rates(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="customs_exchange_rates.html",
        context=customs_exchange_rate_context(request),
    )


@app.post("/customs-exchange-rates/refresh", response_class=HTMLResponse)
async def refresh_customs_exchange_rates_route(request: Request):
    require_local_source_writes()
    try:
        result = refresh_customs_exchange_rates(client_id=CUSTOMS_FX_CLIENT_ID)
    except Exception as exc:
        return templates.TemplateResponse(
            request=request,
            name="customs_exchange_rates.html",
            status_code=502,
            context=customs_exchange_rate_context(
                request,
                error=f"Không cập nhật được tỷ giá hải quan: {exc}",
            ),
        )
    return templates.TemplateResponse(
        request=request,
        name="customs_exchange_rates.html",
        context=customs_exchange_rate_context(
            request,
            customs_fx_result=result,
            message=(
                f"Đã cập nhật {result['fetched_row_count']} dòng tỷ giá hải quan; "
                f"đang lưu {result['saved_row_count']} dòng."
            ),
        ),
    )


@app.get("/clients/{client_id}/customs-exchange-rates")
async def client_customs_exchange_rates_redirect(client_id: str):
    return RedirectResponse("/customs-exchange-rates", status_code=303)


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


@app.get("/clients/{client_id}/co-case", response_class=HTMLResponse)
async def co_case(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id),
    )


@app.post("/clients/{client_id}/co-case/create")
async def create_co_case(request: Request, client_id: str):
    client = resolve_client(client_id)
    form = await request.form()
    record = create_case_record(client, {key: str(value) for key, value in form.items()})
    return RedirectResponse(f"/clients/{client_id}/co-case/{record['case_id']}", status_code=303)


@app.post("/clients/{client_id}/co-case/{case_id}/shipment")
async def update_co_case_shipment(request: Request, client_id: str, case_id: str):
    form = {key: str(value) for key, value in (await request.form()).items()}
    update_case_record(
        resolve_client(client_id),
        {
            **form,
            "id": case_id,
            "persisted_case_id": case_id,
            "shipment": {
                "invoice_no": form.get("invoice_no", ""),
                "bill_of_lading_no": form.get("bill_of_lading_no", ""),
            },
        },
    )
    return RedirectResponse(f"/clients/{client_id}/co-case/{case_id}", status_code=303)


@app.get("/clients/{client_id}/co-case/{case_id}", response_class=HTMLResponse)
async def co_case_detail(request: Request, client_id: str, case_id: str):
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id, case_id, "shipment"),
    )


@app.get("/clients/{client_id}/co-case/{case_id}/{step}", response_class=HTMLResponse)
async def co_case_step(request: Request, client_id: str, case_id: str, step: str):
    if step not in CO_CASE_WORKFLOW_STEP_KEYS:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id, case_id, step),
    )


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


@app.post("/clients/{client_id}/co-case/{case_id}/export")
async def export_co_case_workbook(client_id: str, case_id: str):
    context = co_case_context(client_id, case_id)
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


@app.post("/clients/{client_id}/evaluate", response_class=HTMLResponse)
async def evaluate(request: Request, client_id: str):
    form = await request.form()
    case = update_products_from_form({key: str(value) for key, value in form.items()})
    if case.get("persisted_case_id"):
        try:
            update_case_record(resolve_client(client_id), case)
        except KeyError:
            pass
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id, case=case, current_step="origin", message="Đã tính lại theo dữ liệu đang sửa."),
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
    case["customer"] = client["name"]
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
    form = await request.form()
    case = update_products_from_form({key: str(value) for key, value in form.items()})
    content = create_evidence_workbook(case)
    filename = f"{case['case_code'] or 'co-case'}-evidence.xlsx"
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
