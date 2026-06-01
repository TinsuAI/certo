from __future__ import annotations

import httpx

from app import co_stock_eligibility
from app.app_state_store import get_app_state_store
from app.client_registry import get_client as registry_get_client
from app.client_registry import get_client_case
from app.demo_data import DEMO_CASE, attach_results, clone_case
from app.portfolio import portfolio_service


# Local CO state uses short client IDs (e.g. "johnson") while Data Hub stores
# them suffixed with a country code (e.g. "johnson-vn"). When the literal
# Data Hub lookup 404s, retry with these suffix variants before falling back
# to the local registry. Edit when new tenants join.
_CLIENT_ID_FALLBACK_SUFFIXES: tuple[str, ...] = ("-vn",)


def resolve_client(client_id: str) -> dict:
    """Resolve a CO client by short ID, mapping to Data Hub's suffix variant.

    Data Hub stores tenants with a country suffix (e.g. `growatt-vn`) while
    CO local state and URLs use the short form (`growatt`). The Data Hub
    client wrapper itself retries 404s on the suffix variant, so the lookup
    succeeds — but the returned record carries the Data Hub ID. Force the
    short ID back onto the result so downstream lookups (`get_case_record`,
    Postgres queries) stay consistent with CO state.

    Identity fields the agency edits in CO (legal_name + tax_code, used on
    the bảng kê HQ render) are stored locally and overlay whatever Data Hub
    returns — Data Hub does not yet expose `legal_name`, and tax_code is
    often "Chưa nhập" upstream.
    """
    service_client = getattr(portfolio_service, "client", None)
    if callable(service_client):
        try:
            resolved = service_client(client_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            return _apply_co_identity_overlay(client_id, registry_get_client(client_id))
        if isinstance(resolved, dict):
            resolved = dict(resolved)
            resolved["id"] = client_id
            resolved["client_id"] = client_id
        return _apply_co_identity_overlay(client_id, resolved)
    return _apply_co_identity_overlay(client_id, registry_get_client(client_id))


def effective_min_gap_days(client: dict | None, client_config: dict | None = None) -> int:
    """Resolve the final 2-day rule threshold for a client.

    1. CO-local `co_stock_overrides.min_days_before_export` wins — it's
       the value the operator set via the CO client-config form.
    2. Falls back to `client_config["co_stock"]["min_days_before_export"]`
       (which today lives in Data Hub when DH source mode is enabled).
    3. Falls back to `DEFAULT_MIN_GAP_DAYS` (2).

    Centralised so the calculate / substitute paths all see the same
    answer without each one re-implementing the lookup.
    """
    if isinstance(client, dict):
        overrides = client.get("co_stock_overrides")
        if isinstance(overrides, dict) and "min_days_before_export" in overrides:
            try:
                value = int(overrides["min_days_before_export"])
                if value >= 0:
                    return value
            except (TypeError, ValueError):
                pass
    return co_stock_eligibility.min_gap_days_from_config(client_config)


def _apply_co_identity_overlay(client_id: str, client: dict) -> dict:
    if not isinstance(client, dict):
        return client
    store = get_app_state_store()
    if not store:
        return client
    try:
        local = store.client(client_id)
    except KeyError:
        return client
    legal_name = str(local.get("legal_name") or "").strip()
    tax_code = str(local.get("tax_code") or "").strip()
    if legal_name:
        client["legal_name"] = legal_name
    if tax_code and tax_code != "Chưa nhập":
        client["tax_code"] = tax_code
    overrides = local.get("co_stock_overrides")
    if isinstance(overrides, dict) and overrides:
        client["co_stock_overrides"] = dict(overrides)
    return client


def default_client_case(client: dict) -> dict:
    case = clone_case(DEMO_CASE)
    case.update(
        {
            "id": f"{client['id']}-empty-co-case",
            "customer": client.get("legal_name") or client["name"],
            "customer_legal_name": client.get("legal_name", ""),
            "customer_tax_code": client.get("tax_code", ""),
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


def source_workspace_for_client(client: dict) -> tuple[dict, str]:
    return portfolio_service.source_workspace(client)
