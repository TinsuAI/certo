from __future__ import annotations

import hashlib
import json
import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import quote

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
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
    get_supporting_file,
    invoice_keys,
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
from app.co_form_config_store import (
    co_form_config_path,
    load_co_form_config,
    reset_co_form_config,
    sanitize_co_form_config,
    save_co_form_config,
    unique_text_list,
)
from app.co_market_hints import infer_market_from_invoice_matches
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


PSR_STATUS_LABELS = {
    "pending_trong_tin_confirmation": "Chờ Trọng Tín xác nhận",
    "extracted_from_local_corpus_pending_trong_tin_confirmation": "Extract từ corpus, chờ xác nhận",
    "needs_2026_evfta_refresh": "Cần đối chiếu EVFTA 2026",
    "requires_manual_lookup": "Cần tra thủ công",
    "confirmed_by_trong_tin": "Đã xác nhận bởi Trọng Tín",
}

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
        "description": "Lập bảng kê LVC từ invoice, BCCT và BOM snapshot.",
    },
    {
        "key": "review",
        "label": "Review & xuất",
        "short_label": "6",
        "description": "Kiểm tra dossier và xuất workbook.",
    },
]
CO_CASE_WORKFLOW_STEP_KEYS = {step["key"] for step in CO_CASE_WORKFLOW_STEPS}
CO_CASE_STEP_STATUS_LABELS = {
    "ready": "Đủ",
    "todo": "Thiếu",
    "review": "Cần soát",
    "preview": "Preview",
}

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


def co_form_settings_context(request: Request, *, saved: bool = False, error: str = "") -> dict:
    config = load_co_form_config()
    display_config = {
        **config,
        "forms": [
            {
                **form,
                "verification_status_label": co_form_status_label(form.get("verification_status", "")),
            }
            for form in config.get("forms", [])
        ],
    }
    form_codes = [row["form_code"] for row in config["forms"] if row.get("enabled")]
    psr_rule_counts = {
        form_code: len([rule for rule in config.get("psr_rules", []) if rule.get("form_code") == form_code])
        for form_code in form_codes
    }
    active_tab = request.query_params.get("tab") or "overview"
    if active_tab not in {"overview", "forms", "markets", "psr"}:
        active_tab = "overview"
    psr_selected_form = request.query_params.get("psr_form") or (form_codes[0] if form_codes else "")
    psr_query = str(request.query_params.get("psr_query") or "").strip()
    psr_status = str(request.query_params.get("psr_status") or "").strip()
    psr_filtered_rules = filter_psr_rules(config.get("psr_rules", []), psr_selected_form, psr_query, psr_status)
    psr_status_values = [
        str(rule.get("status") or "")
        for rule in config.get("psr_rules", [])
        if rule.get("status")
    ]
    form_status_values = [
        str(form.get("verification_status") or "")
        for form in config.get("forms", [])
        if form.get("verification_status")
    ]
    return {
        "saved": saved,
        "error": error,
        "config": display_config,
        "config_path": str(co_form_config_path()),
        "form_codes": form_codes,
        "psr_rule_counts": psr_rule_counts,
        "active_tab": active_tab,
        "settings_tabs": [
            {"id": "overview", "label": "Overview"},
            {"id": "forms", "label": "Forms"},
            {"id": "markets", "label": "Markets"},
            {"id": "psr", "label": "HS Criteria"},
        ],
        "enabled_form_count": len([row for row in config["forms"] if row.get("enabled")]),
        "enabled_market_count": len([row for row in config["market_presets"] if row.get("enabled")]),
        "picker_market_count": len([row for row in config["market_presets"] if row.get("enabled") and row.get("show_in_picker")]),
        "psr_selected_form": psr_selected_form,
        "psr_query": psr_query,
        "psr_status": psr_status,
        "psr_filtered_count": len(psr_filtered_rules),
        "psr_visible_rules": [with_co_form_status_label(rule) for rule in psr_filtered_rules[:120]],
        "form_status_options": co_form_status_options(form_status_values),
        "psr_status_options": co_form_status_options(psr_status_values),
    }


def co_form_config_from_form(form) -> dict:
    current = load_co_form_config()
    source_note = current.get("source_note", "")
    if "source_note" in form:
        source_note = form.get("source_note", source_note)
    form_priority = current.get("form_priority", [])
    if "form_priority" in form:
        form_priority = unique_text_list(form.get("form_priority", ""))

    forms = current.get("forms", [])
    if "form_count" in form:
        form_count = int(str(form.get("form_count") or "0") or "0")
        forms = []
        for index in range(form_count):
            form_code = str(form.get(f"form_{index}_form_code") or "").strip()
            if not form_code:
                continue
            forms.append({
                "form_code": form_code,
                "display_name": form.get(f"form_{index}_display_name", ""),
                "agreement": form.get(f"form_{index}_agreement", ""),
                "instrument": form.get(f"form_{index}_instrument", ""),
                "instrument_note": form.get(f"form_{index}_instrument_note", ""),
                "source_label": form.get(f"form_{index}_source_label", ""),
                "source_url": form.get(f"form_{index}_source_url", ""),
                "verification_status": form.get(f"form_{index}_verification_status", ""),
                "enabled": form.get(f"form_{index}_enabled") == "1",
            })

    market_presets = current.get("market_presets", [])
    if "market_count" in form:
        market_count = int(str(form.get("market_count") or "0") or "0")
        market_presets = []
        for index in range(market_count + 1):
            market = str(form.get(f"market_{index}_market") or "").strip()
            form_code = str(form.get(f"market_{index}_form_code") or "").strip()
            if not market or not form_code:
                continue
            market_presets.append({
                "market": market,
                "label": form.get(f"market_{index}_label", ""),
                "form_code": form_code,
                "aliases": unique_text_list(form.get(f"market_{index}_aliases", "")),
                "selection_reason": form.get(f"market_{index}_selection_reason", ""),
                "source_label": form.get(f"market_{index}_source_label", ""),
                "enabled": form.get(f"market_{index}_enabled") == "1",
                "show_in_picker": form.get(f"market_{index}_show_in_picker") == "1",
            })

    psr_rules = current.get("psr_rules", [])
    if "psr_count" in form:
        psr_count = int(str(form.get("psr_count") or "0") or "0")
        psr_rules = []
        for index in range(psr_count + 1):
            form_code = str(form.get(f"psr_{index}_form_code") or "").strip()
            hs_scope = str(form.get(f"psr_{index}_hs_scope") or "").strip()
            criteria = str(form.get(f"psr_{index}_criteria") or "").strip()
            if not form_code or not hs_scope or not criteria:
                continue
            psr_rules.append({
                "form_code": form_code,
                "hs_scope": hs_scope,
                "criteria": criteria,
                "source_reference": form.get(f"psr_{index}_source_reference", ""),
                "note": form.get(f"psr_{index}_note", ""),
                "status": form.get(f"psr_{index}_status", ""),
                "enabled": form.get(f"psr_{index}_enabled") == "1",
            })
    elif "psr_visible_count" in form:
        psr_rules = list(psr_rules)
        psr_visible_count = int(str(form.get("psr_visible_count") or "0") or "0")
        for index in range(psr_visible_count + 1):
            form_code = str(form.get(f"psr_{index}_form_code") or "").strip()
            hs_scope = str(form.get(f"psr_{index}_hs_scope") or "").strip()
            criteria = str(form.get(f"psr_{index}_criteria") or "").strip()
            if not form_code or not hs_scope or not criteria:
                continue
            rule = {
                "form_code": form_code,
                "hs_scope": hs_scope,
                "criteria": criteria,
                "source_reference": form.get(f"psr_{index}_source_reference", ""),
                "note": form.get(f"psr_{index}_note", ""),
                "status": form.get(f"psr_{index}_status", ""),
                "enabled": form.get(f"psr_{index}_enabled") == "1",
            }
            original_index = str(form.get(f"psr_{index}_original_index") or "").strip()
            if original_index.isdigit() and int(original_index) < len(psr_rules):
                psr_rules[int(original_index)] = rule
            else:
                psr_rules.append(rule)

    return sanitize_co_form_config({
        **current,
        "source_note": source_note,
        "form_priority": form_priority,
        "forms": forms,
        "market_presets": market_presets,
        "psr_rules": psr_rules,
    })


def filter_psr_rules(rules: list[dict], form_code: str, query: str, status: str) -> list[dict]:
    query_key = co_form_filter_key(query)
    output = []
    for index, rule in enumerate(rules):
        if form_code and rule.get("form_code") != form_code:
            continue
        if status and rule.get("status") != status:
            continue
        if query_key:
            haystack = co_form_filter_key(" ".join([
                str(rule.get("hs_scope") or ""),
                str(rule.get("criteria") or ""),
                str(rule.get("source_reference") or ""),
                str(rule.get("note") or ""),
                str(rule.get("status") or ""),
                co_form_status_label(str(rule.get("status") or "")),
            ]))
            if query_key not in haystack:
                continue
        output.append({**rule, "original_index": index})
    return output


def with_co_form_status_label(row: dict) -> dict:
    status = str(row.get("status") or "")
    return {**row, "status_label": co_form_status_label(status)}


def co_form_status_options(statuses: list[str]) -> list[dict]:
    output = []
    seen = set()
    for status in list(PSR_STATUS_LABELS) + sorted(set(statuses)):
        if not status or status in seen:
            continue
        output.append({"value": status, "label": co_form_status_label(status)})
        seen.add(status)
    return output


def co_form_status_label(status: str) -> str:
    if not status:
        return ""
    return PSR_STATUS_LABELS.get(status, status.replace("_", " ").strip().capitalize())


def co_form_filter_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


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


@app.get("/settings/co-forms", response_class=HTMLResponse)
async def co_form_settings_page(request: Request, saved: str = ""):
    return templates.TemplateResponse(
        request=request,
        name="co_form_settings.html",
        context=co_form_settings_context(request, saved=saved == "1"),
    )


@app.post("/settings/co-forms", response_class=HTMLResponse)
async def save_co_form_settings(request: Request):
    form = await request.form()
    active_tab = str(form.get("active_tab") or "").strip()
    try:
        save_co_form_config(co_form_config_from_form(form))
    except Exception as exc:
        return templates.TemplateResponse(
            request=request,
            name="co_form_settings.html",
            context=co_form_settings_context(request, error=str(exc)),
            status_code=400,
        )
    suffix = f"&tab={quote(active_tab)}" if active_tab else ""
    return RedirectResponse(f"/settings/co-forms?saved=1{suffix}", status_code=303)


@app.post("/settings/co-forms/reset")
async def reset_co_form_settings(request: Request):
    reset_co_form_config()
    return RedirectResponse("/settings/co-forms?saved=1", status_code=303)


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
    origin_demo_allowed = extra.pop("origin_demo_allowed", True)
    preserve_origin_products = extra.pop("preserve_origin_products", False)
    client = enrich_client_with_source_summary(client, source_summary)
    case = attach_case_source_summary_snapshot(case, source_summary)
    if current_step == "origin":
        selected_lane = recommended_form_lane(
            prioritized_form_lanes(case.get("destination_market", ""), co_case_hs_codes(case, invoice_matches))
        )
        material_rows = source_context.get("material_rows") or client.get("material_catalog", [])
        stock_rows = source_context.get("stock_rows") or client.get("co_stock", [])
        case = prepare_case_origin_products(
            case,
            invoice_matches,
            bom_workspace,
            selected_lane,
            material_rows,
            stock_rows,
            preserve_existing=preserve_origin_products,
        )
        case = attach_case_bom_snapshot(case, bom_workspace)
        if case.get("products"):
            case = attach_results(case)
            criteria_rows = build_case_criteria_rows(case, form_candidates)
    origin_demo_active = origin_demo_allowed and should_show_origin_demo(current_step, case, invoice_matches)
    if origin_demo_active:
        case = attach_origin_demo(case)
        criteria_rows = build_case_criteria_rows(case, form_candidates)
    form_lanes = prioritized_form_lanes(case.get("destination_market", ""), co_case_hs_codes(case, invoice_matches))
    selected_form_lane = recommended_form_lane(form_lanes)
    invoice_criteria_rows = invoice_match_criteria_rows(invoice_matches, selected_form_lane)
    invoice_lookup_preview = invoice_preview_from_matches(
        case.get("shipment", {}).get("invoice_no", ""),
        invoice_matches,
    )
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
        "invoice_lookup_preview": invoice_lookup_preview,
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
    context["co_case_steps"] = co_case_workflow_steps(
        client_id,
        context["case"],
        current_step,
        invoice_matches=invoice_matches,
        criteria_rows=criteria_rows,
        origin_demo_active=origin_demo_active,
    )
    return context


def co_case_source_context(client: dict, case: dict) -> dict:
    return portfolio_service.co_case_source_context(client, case)


def invoice_lookup_payload(client: dict, invoice_no: str, query: str = "") -> dict:
    invoice_no = str(invoice_no or "").strip()
    query = str(query or invoice_no or "").strip()
    options = invoice_search_options(client, query)
    if not invoice_no:
        return {
            "status": "empty",
            "invoice_no": "",
            "options": options,
            "match_count": 0,
            "matches": [],
            "summary": {},
            "market_inference": market_inference_view({"status": "missing", "destination_market": "", "hints": []}),
            "suggested_forms": [],
        }
    try:
        source_context = co_case_source_context(client, {"shipment": {"invoice_no": invoice_no}})
    except Exception as exc:
        return {
            "status": "error",
            "invoice_no": invoice_no,
            "options": options,
            "match_count": 0,
            "matches": [],
            "summary": {},
            "market_inference": market_inference_view({"status": "missing", "destination_market": "", "hints": []}),
            "suggested_forms": [],
            "message": f"Không tra được invoice: {exc}",
        }
    payload = invoice_preview_from_matches(invoice_no, source_context.get("invoice_matches", []))
    payload["options"] = options
    return payload


def invoice_preview_from_matches(invoice_no: str, invoice_matches: list[dict]) -> dict:
    invoice_no = str(invoice_no or "").strip()
    inference = infer_market_from_invoice_matches(invoice_matches)
    hs_codes = co_case_hs_codes({"shipment": {"invoice_no": invoice_no}}, invoice_matches)
    suggested_forms = []
    if inference.get("status") == "ready":
        suggested_forms = [
            invoice_form_lane_view(row)
            for row in prioritized_form_lanes(inference["destination_market"], hs_codes)
        ]
    summary = invoice_match_summary(invoice_matches)
    return {
        "status": "found" if invoice_matches else "not_found" if invoice_no else "empty",
        "invoice_no": invoice_no,
        "match_count": len(invoice_matches),
        "matches": [invoice_match_preview_row(row) for row in invoice_matches[:12]],
        "summary": summary,
        "market_inference": market_inference_view(inference),
        "suggested_forms": suggested_forms,
        "options": [],
    }


def invoice_search_options(client: dict, query: str, limit: int = 10) -> list[dict]:
    query = str(query or "").strip()
    if len(query) < 2:
        return []
    try:
        source_workspace, _source_backend = source_workspace_for_client(client)
    except Exception:
        return []
    client_config = source_workspace.get("client_config", {})
    relevant_types = set(client_config.get("bcct", {}).get("relevant_export_declaration_types", []))
    query_keys = invoice_keys(query)
    query_compact = next(iter(query_keys), re.sub(r"[^A-Z0-9]", "", query.upper()))
    groups: dict[str, dict] = {}
    for row in source_workspace.get("bcct", {}).get("published_rows", []):
        if row.get("direction") != "export":
            continue
        if row.get("review_status") not in ("", "reviewed"):
            continue
        if relevant_types and row.get("declaration_type") not in relevant_types:
            continue
        invoice_ref = str(row.get("invoice_ref") or "").strip()
        if not invoice_ref:
            continue
        row_keys = invoice_keys(invoice_ref)
        row_compact = re.sub(r"[^A-Z0-9]", "", invoice_ref.upper())
        if query_compact and query_compact not in row_compact and not query_keys.intersection(row_keys):
            continue
        group = groups.setdefault(
            invoice_ref,
            {
                "invoice_no": invoice_ref,
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
            "hs_codes": sorted(group["hs_codes"])[:6],
            "item_codes": sorted(group["item_codes"])[:4],
        })
    return sorted(options, key=lambda row: (-int(row["row_count"]), row["invoice_no"]))[:limit]


def invoice_match_summary(invoice_matches: list[dict]) -> dict:
    declarations = sorted({
        str(row.get("declaration_no") or "")
        for row in invoice_matches
        if row.get("declaration_no")
    })
    hs_codes = sorted({
        str(row.get("hs_code") or "")
        for row in invoice_matches
        if row.get("hs_code")
    })
    item_codes = sorted({
        str(row.get("item_code") or "")
        for row in invoice_matches
        if row.get("item_code")
    })
    invoice_refs = sorted({
        str(row.get("invoice_ref") or "")
        for row in invoice_matches
        if row.get("invoice_ref")
    })
    return {
        "declaration_count": len(declarations),
        "declarations": declarations[:8],
        "hs_codes": hs_codes[:12],
        "item_codes": item_codes[:8],
        "invoice_refs": invoice_refs[:4],
    }


def invoice_match_preview_row(row: dict) -> dict:
    return {
        "declaration_no": row.get("declaration_no", ""),
        "line_no": row.get("line_no", ""),
        "declaration_type": row.get("declaration_type", ""),
        "item_code": row.get("item_code", ""),
        "description": row.get("description", ""),
        "hs_code": row.get("hs_code", ""),
        "quantity": row.get("quantity", ""),
        "unit": row.get("unit", ""),
        "customs_value": row.get("customs_value") or row.get("total_value", ""),
        "value_currency": row.get("value_currency") or row.get("currency", ""),
        "invoice_ref": row.get("invoice_ref", ""),
        "unloading_location": row.get("unloading_location") or row.get("destination_location_name", ""),
        "consignee_name": row.get("consignee_name", ""),
    }


def market_inference_view(inference: dict) -> dict:
    status = inference.get("status", "missing")
    hints = inference.get("hints", [])
    if status == "ready" and hints:
        hint = hints[0]
        source_field = str(hint.get("source_field") or "market_hint")
        source_value = str(hint.get("source_value") or hint.get("country_name") or hint.get("country_code") or "")
        explanation = (
            f"Gợi ý từ {source_field} = {source_value}. "
            "Các dòng invoice chỉ có một quốc gia đích đủ độ tin cậy cao."
        )
        action_label = f"Dùng thị trường {inference.get('destination_market', '')}"
    elif status == "conflict":
        markets = ", ".join(
            str(hint.get("country_name") or hint.get("country_code") or "")
            for hint in hints
            if hint.get("country_name") or hint.get("country_code")
        )
        explanation = f"Không tự chọn vì invoice có nhiều gợi ý thị trường: {markets}."
        action_label = ""
    else:
        explanation = "Chưa có market hint đủ tin cậy từ dữ liệu invoice; cần chọn thị trường thủ công."
        action_label = ""
    return {
        **inference,
        "explanation": explanation,
        "action_label": action_label,
    }


def invoice_form_lane_view(row: dict) -> dict:
    return {
        "form_code": row.get("form_code", ""),
        "display_name": row.get("display_name", ""),
        "agreement": row.get("agreement", ""),
        "instrument": row.get("instrument", ""),
        "reason": row.get("reason", ""),
        "recommended": bool(row.get("recommended")),
        "criteria_preview": row.get("criteria_preview", [])[:4],
    }


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


def prepare_case_origin_products(
    case: dict,
    invoice_matches: list[dict],
    bom_workspace: dict,
    form_lane: dict,
    material_rows: list[dict],
    stock_rows: list[dict],
    *,
    preserve_existing: bool = False,
) -> dict:
    if not invoice_matches:
        return case

    bom_rows_by_product = selected_bom_rows_by_product(case, bom_workspace)
    build_signature = origin_build_signature(invoice_matches, bom_rows_by_product, material_rows, stock_rows, form_lane)
    if (
        case.get("products")
        and (
            preserve_existing
            or case.get("origin_snapshot", {}).get("build_signature") == build_signature
        )
    ):
        return case

    material_index = material_catalog_index(material_rows)
    stock_index = co_stock_index(stock_rows)
    products = []
    for match in invoice_matches:
        product_code = str(match.get("item_code", "")).strip()
        if not product_code:
            continue
        product_rows = bom_rows_by_product.get(product_code, [])
        products.append(origin_product_from_invoice_match(
            match,
            product_rows,
            form_lane,
            material_index,
            stock_index,
        ))
    if not products:
        return case

    prepared = dict(case)
    prepared["products"] = products
    prepared["mode"] = "Invoice + BCCT + BOM snapshot"
    prepared["mode_note"] = "Sản phẩm lấy từ BCCT xuất khẩu khớp invoice; NVL lấy từ BOM snapshot hiện hành. Đơn giá NVL ưu tiên từ tồn CO/BCCT nhập, nếu thiếu mới fallback danh mục NVL."
    prepared["origin_snapshot"] = {
        "source": "invoice_bcct_bom",
        "build_signature": build_signature,
        "invoice_no": prepared.get("shipment", {}).get("invoice_no", ""),
        "invoice_match_count": len(invoice_matches),
        "product_count": len(products),
        "material_count": sum(len(product.get("materials", [])) for product in products),
        "stock_row_count": len(stock_rows),
    }
    return prepared


def origin_build_signature(
    invoice_matches: list[dict],
    bom_rows_by_product: dict[str, list[dict]],
    material_rows: list[dict],
    stock_rows: list[dict],
    form_lane: dict,
) -> str:
    payload = {
        "form": {
            "form_code": form_lane.get("form_code", ""),
            "display_name": form_lane.get("display_name", ""),
        },
        "invoice_matches": [
            compact_origin_signature_row(
                row,
                [
                    "transaction_key",
                    "declaration_no",
                    "line_no",
                    "item_code",
                    "hs_code",
                    "quantity",
                    "unit",
                    "customs_value",
                    "foreign_currency_value",
                    "total_value",
                    "currency",
                    "value_currency",
                    "invoice_ref",
                ],
            )
            for row in invoice_matches
        ],
        "bom_rows": [
            compact_origin_signature_row(
                row,
                [
                    "product_code",
                    "product_version_id",
                    "product_version_no",
                    "material_code",
                    "qty_per",
                    "uom",
                    "hs_code",
                    "unit_value",
                    "unit_price",
                ],
            )
            for product_code in sorted(bom_rows_by_product)
            for row in bom_rows_by_product[product_code]
        ],
        "materials": [
            compact_origin_signature_row(
                row,
                ["customs_code", "internal_code", "origin_default", "origin_status", "unit_price", "taxable_unit_price"],
            )
            for row in material_rows
        ],
        "stock_rows": [
            compact_origin_signature_row(
                row,
                [
                    "material_code",
                    "allocation_code",
                    "customs_item_code",
                    "remaining_qty",
                    "available_qty",
                    "customs_value",
                    "currency",
                    "value_currency",
                    "unit_value",
                    "unit_price",
                    "taxable_unit_price",
                    "eligibility_status",
                ],
            )
            for row in stock_rows
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def compact_origin_signature_row(row: dict, fields: list[str]) -> dict:
    return {field: str(row.get(field, "")) for field in fields if row.get(field, "") not in (None, "")}


def selected_bom_rows_by_product(case: dict, bom_workspace: dict) -> dict[str, list[dict]]:
    selected_version_id = case.get("bom_version_id") or bom_workspace.get("latest_version", {}).get("version_id", "")
    aggregate = next(
        (version for version in bom_workspace.get("versions", []) if version.get("version_id") == selected_version_id),
        bom_workspace.get("latest_version", {}),
    )
    rows = aggregate.get("rows")
    if rows is None:
        rows = bom_workspace.get("latest_rows", [])
    output: dict[str, list[dict]] = {}
    for row in rows or []:
        product_code = str(row.get("product_code", "")).strip()
        if product_code:
            output.setdefault(product_code, []).append(dict(row))

    version_index = {
        version.get("product_version_id", ""): version
        for version in bom_workspace.get("product_versions", [])
        if version.get("product_version_id")
    }
    composition_by_product = {
        row.get("product_code", ""): row.get("product_version_id", "")
        for row in aggregate.get("product_versions", [])
    }
    overrides = dict(case.get("bom_product_version_overrides", {}))
    for product in case.get("products", []):
        product_code = str(product.get("code", "")).strip()
        selected_product_version_id = (
            product.get("bom_product_version_id")
            or overrides.get(product_code)
            or composition_by_product.get(product_code, "")
        )
        selected_product_version = version_index.get(selected_product_version_id)
        if product_code and selected_product_version and selected_product_version.get("rows") is not None:
            output[product_code] = [dict(row) for row in selected_product_version.get("rows", [])]
    return output


def material_catalog_index(material_rows: list[dict]) -> dict[str, dict]:
    output = {}
    for row in material_rows:
        for key in [row.get("customs_code", ""), row.get("internal_code", "")]:
            if str(key).strip():
                output[str(key).strip()] = row
    return output


def co_stock_index(stock_rows: list[dict]) -> dict[str, dict]:
    output = {}
    for row in stock_rows:
        for key in co_stock_key_candidates(row):
            existing = output.get(key)
            if existing is None or co_stock_rank(row) > co_stock_rank(existing):
                output[key] = row
    return output


def co_stock_key_candidates(row: dict) -> list[str]:
    keys = []
    for value in [row.get("material_code"), row.get("allocation_code"), row.get("customs_item_code")]:
        key = str(value or "").strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def co_stock_rank(row: dict) -> tuple[bool, bool, bool]:
    return (
        row.get("eligibility_status") == "active",
        decimal_value(row.get("remaining_qty") or row.get("available_qty") or "0") > 0,
        bool(first_non_empty([
            row.get("unit_value", ""),
            row.get("unit_price", ""),
            row.get("taxable_unit_price", ""),
            row.get("customs_value", ""),
        ])),
    )


def origin_product_from_invoice_match(
    match: dict,
    bom_rows: list[dict],
    form_lane: dict,
    material_index: dict[str, dict],
    stock_index: dict[str, dict],
) -> dict:
    product_code = str(match.get("item_code", "")).strip()
    finished_hs = str(match.get("hs_code", "")).strip()
    preview = criteria_preview_for_hs(form_lane.get("form_code", ""), finished_hs) if form_lane else {}
    criterion = preview.get("criteria") or "Cần tra cứu PSR theo HS"
    threshold = lvc_threshold_from_criterion(criterion)
    quantity = decimal_value(match.get("quantity", "0"))
    product_value = origin_product_value(match)
    fob = product_value["value"]
    materials = [
        origin_material_from_bom_row(row, quantity, material_index, stock_index)
        for row in bom_rows
    ]
    vnm = sum(
        decimal_value(material.get("non_origin_cif_value"))
        for material in materials
    )
    missing_material_values = any(
        material.get("origin_status") == "non_origin" and material.get("unit_value_missing")
        for material in materials
    )
    lvc = calculate_lvc_result(fob, vnm, threshold, missing_material_values)
    return {
        "code": product_code,
        "name": match.get("description") or product_code,
        "finished_hs": finished_hs,
        "quantity": decimal_text(quantity),
        "unit": match.get("unit", ""),
        "currency": product_value["currency"],
        "declared_currency": match.get("currency", ""),
        "value_source": product_value["source"],
        "source_declaration_no": match.get("declaration_no", ""),
        "source_line_no": match.get("line_no", ""),
        "invoice_ref": match.get("invoice_ref", ""),
        "fob": decimal_text(fob) if fob is not None else "",
        "non_origin_value": decimal_text(vnm) if materials else "",
        "rvc_threshold": decimal_text(threshold) if threshold is not None else "",
        "documented_result": criterion,
        "lvc_percentage": lvc["percentage"],
        "lvc_status": lvc["status"],
        "lvc_status_label": lvc["status_label"],
        "lvc_threshold": decimal_text(threshold) if threshold is not None else "",
        "vnm_value": decimal_text(vnm) if materials else "",
        "bom_product_version_id": first_non_empty(row.get("product_version_id", "") for row in bom_rows),
        "bom_product_version_no": first_non_empty(row.get("product_version_no", "") for row in bom_rows),
        "materials": materials,
    }


def origin_product_value(match: dict) -> dict:
    value_sources = [
        ("fob_value", match.get("fob_value"), match.get("fob_currency") or match.get("value_currency") or match.get("currency", "")),
        ("customs_value", match.get("customs_value"), match.get("value_currency") or "VND"),
        ("total_value", match.get("total_value"), match.get("value_currency") or "VND"),
        ("foreign_currency_value", match.get("foreign_currency_value"), match.get("currency", "")),
        ("invoice_value", match.get("invoice_value"), match.get("currency", "")),
    ]
    for source, value, currency in value_sources:
        if value not in (None, ""):
            return {"value": decimal_value(value), "currency": currency, "source": source}
    return {"value": None, "currency": "", "source": ""}


def origin_material_from_bom_row(
    row: dict,
    export_quantity: Decimal,
    material_index: dict[str, dict],
    stock_index: dict[str, dict],
) -> dict:
    material_code = str(row.get("material_code", "")).strip()
    material = material_index.get(material_code, {})
    stock = stock_index.get(material_code, {})
    qty_per = decimal_value(row.get("qty_per", "0"))
    consumed_qty = export_quantity * qty_per
    origin_status = origin_status_from_material(material)
    unit_value = first_decimal_value(
        row.get("unit_value"),
        row.get("unit_price"),
        stock.get("unit_value"),
        stock.get("unit_price"),
        stock.get("taxable_unit_price"),
        material.get("unit_price"),
        material.get("taxable_unit_price"),
    )
    material_value = consumed_qty * unit_value if unit_value is not None else None
    vnm_value = material_value if origin_status == "non_origin" and material_value is not None else None
    return {
        "source_row": stock.get("source_row") or f"BOM:{row.get('source', '')}",
        "import_declaration_no": stock.get("import_declaration_no", ""),
        "import_line_no": stock.get("line_no", ""),
        "material_code": material_code,
        "customs_material_code": material.get("customs_code") or material_code,
        "internal_material_code": material.get("internal_code") or material_code,
        "material_description": row.get("material_name") or material.get("name", ""),
        "hs_code": row.get("hs_code") or material.get("hs_code", ""),
        "origin_status": origin_status,
        "available_qty": decimal_value(stock.get("remaining_qty") or stock.get("available_qty") or "0"),
        "consumed_qty": consumed_qty,
        "unit_value": decimal_text(unit_value) if unit_value is not None else "",
        "currency": stock.get("value_currency") or stock.get("currency") or material.get("value_currency") or material.get("currency", ""),
        "material_value": decimal_text(material_value) if material_value is not None else "",
        "non_origin_cif_value": decimal_text(vnm_value) if vnm_value is not None else "",
        "unit_value_missing": unit_value is None,
        "bom_qty_per": decimal_text(qty_per),
        "bom_scrap_rate": row.get("scrap_rate", ""),
        "bom_source": row.get("source", ""),
        "bom_row_class": row.get("row_class", ""),
        "uom": row.get("uom", ""),
        "source_document_ref": row.get("source") or row.get("product_version_id", ""),
    }


def origin_status_from_material(material: dict) -> str:
    value = str(material.get("origin_default") or material.get("origin_status") or "").lower()
    if "không" in value or "khong" in value or value == "non_origin":
        return "non_origin"
    if "có" in value or value == "origin":
        return "origin"
    return "non_origin"


def lvc_threshold_from_criterion(criterion: str) -> Decimal | None:
    if not criterion:
        return None
    match = re.search(r"(?:LVC|RVC|AIFTA)[^\d]*(\d+(?:[.,]\d+)?)\s*%", criterion, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:FOB|LVC|RVC)", criterion, flags=re.IGNORECASE)
    return decimal_value(match.group(1)) if match else None


def calculate_lvc_result(
    fob: Decimal | None,
    vnm: Decimal,
    threshold: Decimal | None,
    missing_material_values: bool,
) -> dict:
    if fob is None or fob <= 0:
        return {"percentage": "", "status": "missing_value", "status_label": "Thiếu FOB"}
    if missing_material_values:
        return {"percentage": "", "status": "missing_value", "status_label": "Thiếu đơn giá NVL"}
    percentage = ((fob - vnm) / fob * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    percentage_text = f"{percentage:.2f}"
    if threshold is None:
        return {"percentage": percentage_text, "status": "review", "status_label": "Thiếu ngưỡng"}
    if percentage >= threshold:
        return {"percentage": percentage_text, "status": "pass", "status_label": "Đạt LVC"}
    return {"percentage": percentage_text, "status": "fail", "status_label": "Không đạt LVC"}


def first_non_empty(values) -> str:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return ""


def first_decimal_value(*values) -> Decimal | None:
    for value in values:
        if value not in (None, ""):
            return decimal_value(value)
    return None


def decimal_value(value) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", "").strip() or "0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def decimal_text(value: Decimal | str) -> str:
    if isinstance(value, str):
        return value
    if value == value.to_integral():
        return str(value.quantize(Decimal("1")))
    return str(value)


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
    case_was_supplied = "case" in extra
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
    if case.get("products") and current_step != "origin":
        case = attach_results(case)
    if case_was_supplied and current_step == "origin":
        extra.setdefault("preserve_origin_products", True)
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


def co_case_workflow_steps(
    client_id: str,
    case: dict,
    current_step: str,
    invoice_matches: list[dict] | None = None,
    criteria_rows: list[dict] | None = None,
    origin_demo_active: bool = False,
) -> list[dict]:
    case_id = case.get("persisted_case_id", "")
    base_url = f"/clients/{client_id}/co-case/{case_id}" if case_id else ""
    steps = []
    for step in CO_CASE_WORKFLOW_STEPS:
        href = base_url if step["key"] == "shipment" else f"{base_url}/{step['key']}"
        status = co_case_step_status(
            case,
            step["key"],
            invoice_matches=invoice_matches or [],
            criteria_rows=criteria_rows or [],
            origin_demo_active=origin_demo_active,
        )
        steps.append({
            **step,
            "href": href,
            "active": current_step == step["key"],
            "status": status,
            "status_label": CO_CASE_STEP_STATUS_LABELS.get(status, status),
        })
    return steps


def co_case_step_status(
    case: dict,
    step_key: str,
    invoice_matches: list[dict] | None = None,
    criteria_rows: list[dict] | None = None,
    origin_demo_active: bool = False,
) -> str:
    invoice_matches = invoice_matches or []
    criteria_rows = criteria_rows or []
    shipment = case.get("shipment", {})
    has_invoice = bool(shipment.get("invoice_no"))
    has_market = bool(case.get("destination_market") and case.get("destination_market") != "Chưa nhập")
    has_products = bool(case.get("products") or criteria_rows)
    has_bom_snapshot = bool(case.get("bom_snapshot", {}).get("composition"))
    if step_key == "shipment":
        return "ready" if has_invoice and has_market else "todo"
    if step_key == "documents":
        return "ready" if case.get("supporting_files") else "todo"
    if step_key == "exports":
        if not has_invoice:
            return "todo"
        return "ready" if invoice_matches else "review"
    if step_key == "guidance":
        if not has_market:
            return "todo"
        return "ready" if invoice_matches else "preview"
    if step_key == "origin":
        if origin_demo_active:
            return "preview"
        if invoice_matches and has_products and has_bom_snapshot:
            return "review"
        if has_products or invoice_matches:
            return "preview"
        return "todo"
    if step_key == "review":
        if has_invoice and invoice_matches and has_products:
            return "ready"
        return "preview" if has_products else "todo"
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


@app.get("/clients/{client_id}/co-case/invoice-preview")
async def co_case_invoice_preview(client_id: str, invoice_no: str = "", q: str = ""):
    client = resolve_client(client_id)
    return invoice_lookup_payload(client, invoice_no, q)


@app.post("/clients/{client_id}/co-case/create")
async def create_co_case(request: Request, client_id: str):
    client = resolve_client(client_id)
    form = {key: str(value) for key, value in (await request.form()).items()}
    record = create_case_record(client, form)
    return RedirectResponse(f"/clients/{client_id}/co-case/{record['case_id']}", status_code=303)


@app.post("/clients/{client_id}/co-case/{case_id}/shipment")
async def update_co_case_shipment(request: Request, client_id: str, case_id: str):
    form = {key: str(value) for key, value in (await request.form()).items()}
    client = resolve_client(client_id)
    update_case_record(
        client,
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
        form = await request.form()
        if form:
            posted_case = update_products_from_form({key: str(value) for key, value in form.items()})
            posted_case["persisted_case_id"] = posted_case.get("persisted_case_id") or case_id
    context = co_case_context(
        client_id,
        case_id,
        current_step="origin",
        case=posted_case,
        origin_demo_allowed=False,
    )
    if context["case"].get("persisted_case_id") and not context.get("origin_demo_active"):
        try:
            update_case_record(resolve_client(client_id), context["case"])
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


@app.post("/clients/{client_id}/evaluate", response_class=HTMLResponse)
async def evaluate(request: Request, client_id: str):
    form = await request.form()
    case = update_products_from_form({key: str(value) for key, value in form.items()})
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
