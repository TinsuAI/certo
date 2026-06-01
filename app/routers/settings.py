from __future__ import annotations

import os
import re
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import co_auth
from app.co_form_config_store import (
    co_form_config_path,
    load_co_form_config,
    reset_co_form_config,
    sanitize_co_form_config,
    save_co_form_config,
    unique_text_list,
)
from app.data_hub_client import DataHubClient
from app.data_hub_settings import (
    DATA_HUB_LINK_ENV_KEYS,
    DataHubLinkSettings,
    data_hub_config_path,
    data_hub_link_settings,
    load_data_hub_overrides,
    save_data_hub_overrides,
)
from app.web.templating import THEME_COOKIE, normalize_theme, templates


router = APIRouter()


PSR_STATUS_LABELS = {
    "pending_trong_tin_confirmation": "Chờ Trọng Tín xác nhận",
    "extracted_from_local_corpus_pending_trong_tin_confirmation": "Extract từ corpus, chờ xác nhận",
    "needs_2026_evfta_refresh": "Cần đối chiếu EVFTA 2026",
    "requires_manual_lookup": "Cần tra thủ công",
    "confirmed_by_trong_tin": "Đã xác nhận bởi Trọng Tín",
}


@router.post("/settings/theme")
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
    token_source = (
        "environment"
        if env_values.get("DATA_HUB_SERVICE_TOKEN")
        else "local override"
        if overrides.get("DATA_HUB_SERVICE_TOKEN")
        else "missing"
    )
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
        {"key": "CO_CASE_DELETE_ROLES", "label": "Roles được xoá hồ sơ C/O", "value": ",".join(sorted(settings.co_case_delete_roles)), "type": "text"},
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
            "has_local_override": "DATA_HUB_SERVICE_TOKEN" in overrides,
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
        if key in payload or key in {"DATA_HUB_SERVICE_TOKEN", "CO_FORCE_HTTPS_COOKIE"}:
            continue
        payload[key] = str(form.get(key, "")).strip()
    token = str(form.get("DATA_HUB_SERVICE_TOKEN", "")).strip()
    if token:
        payload["DATA_HUB_SERVICE_TOKEN"] = token
    elif form.get("CLEAR_DATA_HUB_SERVICE_TOKEN") != "1":
        if current_overrides.get("DATA_HUB_SERVICE_TOKEN"):
            payload["DATA_HUB_SERVICE_TOKEN"] = current_overrides["DATA_HUB_SERVICE_TOKEN"]
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


@router.get("/user", response_class=HTMLResponse)
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


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "can_view_technical_settings": co_auth.can_view_technical_settings(co_auth.current_user(request)),
        },
    )


@router.get("/settings/co-forms", response_class=HTMLResponse)
async def co_form_settings_page(request: Request, saved: str = ""):
    return templates.TemplateResponse(
        request=request,
        name="co_form_settings.html",
        context=co_form_settings_context(request, saved=saved == "1"),
    )


@router.post("/settings/co-forms", response_class=HTMLResponse)
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


@router.post("/settings/co-forms/reset")
async def reset_co_form_settings(request: Request):
    reset_co_form_config()
    return RedirectResponse("/settings/co-forms?saved=1", status_code=303)


@router.get("/settings/technical", response_class=HTMLResponse)
@router.get("/settings/data-hub", response_class=HTMLResponse)
async def data_hub_settings_page(request: Request, saved: str = ""):
    require_technical_settings_dev(request)
    return templates.TemplateResponse(
        request=request,
        name="data_hub_settings.html",
        context=data_hub_settings_context(request, saved=saved == "1"),
    )


@router.post("/settings/technical", response_class=HTMLResponse)
@router.post("/settings/data-hub", response_class=HTMLResponse)
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


@router.post("/settings/technical/test", response_class=HTMLResponse)
@router.post("/settings/data-hub/test", response_class=HTMLResponse)
async def test_data_hub_settings(request: Request):
    require_technical_settings_dev(request)
    return templates.TemplateResponse(
        request=request,
        name="data_hub_settings.html",
        context=data_hub_settings_context(request, test_result=data_hub_link_check()),
    )
