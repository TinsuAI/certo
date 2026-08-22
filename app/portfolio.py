from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.app_state_store import get_app_state_store
from app.client_config_store import get_client_config as load_client_config
from app.client_config_store import save_client_config as persist_client_config
from app.co_case_store import match_case_bcct_exports
from app.data_hub_client import DataHubPortfolioService, current_data_hub_token, data_hub_client_from_env
from app.data_hub_settings import data_hub_link_settings
from app.material_search import rank_matches
from app.demo_data import get_client as seed_get_client
from app.demo_data import get_clients as seed_get_clients
from app.source_index_store import get_source_index_store, rebuild_source_index_if_configured
from app.web.templating import asset_url
from app import version as appver
from app.source_store import (
    _safe_customs_fx_rows,
    co_stock_rows_from_bcct,
    create_bcct_template_workbook,
    create_material_catalog_template_workbook,
    create_product_catalog_template_workbook,
    get_source_workspace,
    load_module_state,
    process_bcct_upload,
    process_catalog_upload,
    source_summary_from_states,
)


ROOT = Path(__file__).resolve().parent
THEME_COOKIE = "co_theme"


def theme_context(request: Request) -> dict[str, str]:
    theme = request.cookies.get(THEME_COOKIE)
    theme = theme if theme in {"light", "dark"} else "light"
    return {
        "theme": theme,
        "next_theme": "light" if theme == "dark" else "dark",
        "app_version": appver.version_info(),
    }


portfolio_templates = Jinja2Templates(directory=ROOT / "templates", context_processors=[theme_context])
portfolio_templates.env.globals["asset_url"] = asset_url


def source_index_accepts_declaration_refs(match_func) -> bool:
    try:
        return "export_declaration_nos" in inspect.signature(match_func).parameters
    except (TypeError, ValueError):
        return False




class SourceBackendUnavailable(RuntimeError):
    """Kept as the name callers catch; there is no local fallback to fall back to."""


def get_portfolio_service() -> DataHubPortfolioService:
    """The one source backend.

    This used to choose between Data Hub and a local file-store implementation
    of the same interface. Two implementations behind one interface is how they
    drift, and the suite exercised the one production never ran — so the local
    one is gone and there is nothing left to select.
    """
    data_hub_client = data_hub_client_from_env(token_provider=current_data_hub_token)
    if data_hub_client is None:
        # SourceBackendUnavailable, not a bare RuntimeError: main.py maps this
        # to a 503 so the operator sees "source unavailable, try again" instead
        # of a 500. The message no longer offers a local fallback because there
        # is not one.
        raise SourceBackendUnavailable(
            "Data Hub chưa được cấu hình (DATA_HUB_ENABLED). "
            "Không có nguồn dữ liệu nào khác — hãy bật Data Hub rồi thử lại."
        )
    return DataHubPortfolioService(data_hub_client)


_PORTFOLIO_SERVICE_CACHE: tuple[tuple, PortfolioService | DataHubPortfolioService] | None = None


def current_portfolio_service() -> PortfolioService | DataHubPortfolioService:
    global _PORTFOLIO_SERVICE_CACHE
    settings = data_hub_link_settings()
    cache_key = (
        settings.source_enabled,
        settings.data_hub_api_base_url,
        settings.api_token,
        settings.request_timeout_seconds,
    )
    if _PORTFOLIO_SERVICE_CACHE and _PORTFOLIO_SERVICE_CACHE[0] == cache_key:
        return _PORTFOLIO_SERVICE_CACHE[1]
    service = get_portfolio_service()
    _PORTFOLIO_SERVICE_CACHE = (cache_key, service)
    return service


class PortfolioServiceProxy:
    def __getattr__(self, name: str):
        return getattr(current_portfolio_service(), name)


portfolio_service = PortfolioServiceProxy()
portfolio_app = FastAPI(title="Barry Source Portfolio")


@portfolio_app.get("/", response_class=HTMLResponse)
async def portfolio_dashboard(request: Request):
    return portfolio_templates.TemplateResponse(
        request=request,
        name="portfolio.html",
        context={"clients": portfolio_service.clients()},
    )


@portfolio_app.get("/api/clients")
async def portfolio_clients() -> dict[str, list[dict]]:
    return {"clients": portfolio_service.clients()}


@portfolio_app.get("/api/clients/{client_id}")
async def portfolio_client(client_id: str) -> dict[str, dict]:
    return {"client": portfolio_service.client_summary(client_id)}


@portfolio_app.get("/api/clients/{client_id}/source-summary")
async def portfolio_source_summary(client_id: str) -> dict[str, Any]:
    client = portfolio_service.client(client_id)
    source_summary, source_backend = portfolio_service.source_summary(client)
    return {
        "client": {
            "id": client["id"],
            "name": client["name"],
            "code": client["code"],
            "tax_code": client.get("tax_code", ""),
        },
        "source_backend": source_backend,
        "source_summary": source_summary,
    }


@portfolio_app.get("/api/clients/{client_id}/source-workspace")
async def portfolio_source_workspace(client_id: str) -> dict[str, Any]:
    client = portfolio_service.client(client_id)
    source_workspace, source_backend = portfolio_service.source_workspace(client)
    return {
        "client": {
            "id": client["id"],
            "name": client["name"],
            "code": client["code"],
            "tax_code": client.get("tax_code", ""),
        },
        "source_backend": source_backend,
        "source_workspace": source_workspace,
    }


@portfolio_app.get("/api/clients/{client_id}/config")
async def portfolio_client_config(client_id: str) -> dict[str, Any]:
    client = portfolio_service.client(client_id)
    return {"client_id": client["id"], "client_config": portfolio_service.get_client_config(client)}


@portfolio_app.put("/api/clients/{client_id}/config")
async def portfolio_save_client_config(client_id: str, config: dict = Body(...)) -> dict[str, Any]:
    client = portfolio_service.client(client_id)
    saved = portfolio_service.save_client_config(client, config)
    portfolio_service.refresh_client_indexes(client)
    return {"client_id": client["id"], "client_config": saved}
