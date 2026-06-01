from __future__ import annotations

import httpx

from app import co_stock_eligibility
from app.app_state_store import get_app_state_store
from app.bom_service import bom_service
from app.bom_store import attach_case_bom_snapshot
from app.client_registry import get_client as registry_get_client
from app.client_registry import get_client_case
from app.co_case_store import get_case_workspace
from app.co_form_config_store import load_co_form_config
from app.co_forms import (
    COMMON_MARKET_PRESETS,
    common_market_guidance,
    form_candidates_for_market,
    prioritized_form_lanes,
    recommended_form_lane,
)
from app.data_hub_settings import data_hub_link_settings
from app.demo_data import DEMO_CASE, SOURCE_NOTES, attach_results, clone_case
from app.portfolio import portfolio_service
from app.source_store import attach_case_source_snapshot, enrich_client_with_source_workspace


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


def _data_hub_overview_context(
    client_id: str,
    active: str,
    *,
    dh_path: str,
) -> dict | None:
    """Lean context for Data Hub-backed source views (catalog / bom / bcct).

    Returns None when CO is not in Data Hub mode — caller should fall through
    to the full `client_context`. When in DH mode, skips the expensive
    `source_workspace` pagination (which pulls full materials / products /
    BCCT rows over HTTP) and returns only the metadata + counts needed to
    render a summary card + link-out to Data Hub. Pattern mirrors
    `_co_stock_lean_client_context`.

    `dh_path` is the path segment on the Data Hub side
    (catalog / bom / bcct) — composed into a target URL the template can
    render as a "Mở trên Data Hub" button.
    """
    client = resolve_client(client_id)
    try:
        source_summary, source_backend = portfolio_service.source_summary(client)
    except AttributeError:
        # Test shims (FakePortfolioService / FakeSourceIndexStore) may not
        # expose the lean summary call; fall through to the legacy full-
        # workspace path which they do support.
        return None
    if source_backend != "data-hub":
        return None
    client_config = source_summary.get("client_config") or portfolio_service.get_client_config(client)
    bcct_summary = source_summary.get("bcct", {}) or {}
    material_summary = source_summary.get("material_catalog", {}) or {}
    product_summary = source_summary.get("product_catalog", {}) or {}
    bom_summary = source_summary.get("bom", {}) or {}
    counts = {
        **client.get("counts", {}),
        "materials": material_summary.get("published_row_count", 0),
        "products": product_summary.get("published_row_count", 0),
        "bcct": bcct_summary.get("published_row_count", 0),
        "bom_lines": bom_summary.get("published_row_count", client.get("counts", {}).get("bom_lines", 0)),
        "co_stock": source_summary.get("co_stock_row_count", 0),
    }
    client = {**client, "counts": counts}
    dh_base = data_hub_link_settings().data_hub_base_url
    context = {
        "client": client,
        "case": client_case(client),
        "active": active,
        "source_backend": source_backend,
        "client_config": client_config,
        "source_summary": source_summary,
        "data_hub_base_url": dh_base,
    }
    # Only emit a target URL when there is a real DH page to deep-link to.
    # /config passes dh_path="" (no DH page) → omit the field so a "Mở DH"
    # button rendered by a future config-tab template can't point at an
    # empty / bare-client URL.
    if dh_path:
        context["data_hub_target_url"] = (
            f"{dh_base.rstrip('/')}/clients/{client_id}/{dh_path}"
        )
    return context


def case_finished_hs_codes(case: dict) -> list[str]:
    return [
        str(product.get("finished_hs", ""))
        for product in case.get("products", [])
        if str(product.get("finished_hs", "")).strip()
    ]


def client_context(client_id: str, active: str, **extra):
    client = resolve_client(client_id)
    case = extra.pop("case", client_case(client))
    source_workspace, source_backend = source_workspace_for_client(client)
    client = enrich_client_with_source_workspace(client, source_workspace)
    bom_workspace = bom_service.workspace(client)
    case = attach_case_bom_snapshot(case, bom_workspace)
    case = attach_case_source_snapshot(case, source_workspace)
    # Deep-link to the Data Hub page for tabs that have a canonical DH surface.
    # None for everything else (incl. /config) so the template guard hides the
    # "Mở trên Data Hub" button instead of rendering an empty href.
    data_hub_target_url = None
    if source_backend == "data-hub" and active in {"catalog", "bom", "bcct"}:
        dh_base = data_hub_link_settings().data_hub_base_url
        data_hub_target_url = f"{dh_base.rstrip('/')}/clients/{client_id}/{active}"
    return {
        "client": client,
        "case": case,
        "active": active,
        "data_hub_target_url": data_hub_target_url,
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
        "co_form_options": [
            {"form_code": row["form_code"], "display_name": row.get("display_name") or row["form_code"]}
            for row in load_co_form_config().get("forms", [])
            if row.get("enabled")
        ],
        "invoice_matches": extra.pop("invoice_matches", []),
        "invoice_criteria_rows": extra.pop("invoice_criteria_rows", []),
        "criteria_rows": extra.pop("criteria_rows", []),
        "source_notes": SOURCE_NOTES,
        "source_backend": source_backend,
        **extra,
    }
