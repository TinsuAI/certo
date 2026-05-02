from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Callable

import httpx

from app.client_config_store import default_config, migrate_config
from app.data_hub_settings import data_hub_link_settings
from app.source_store import (
    co_stock_rows_from_bcct,
)

CURRENT_DATA_HUB_TOKEN: ContextVar[str] = ContextVar("current_data_hub_token", default="")


def set_current_data_hub_token(token: str) -> Token[str]:
    return CURRENT_DATA_HUB_TOKEN.set(token)


def reset_current_data_hub_token(token: Token[str]) -> None:
    CURRENT_DATA_HUB_TOKEN.reset(token)


def current_data_hub_token() -> str:
    return CURRENT_DATA_HUB_TOKEN.get()


class DataHubClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        token_provider: Callable[[], str] | None = None,
        timeout: float = 20,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.token_provider = token_provider
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
        )

    def list_clients(self) -> list[dict]:
        return [normalize_client(row) for row in self._get_all("/v1/hub/dncxs")]

    def get_client(self, client_id: str) -> dict:
        return normalize_client(self._get(f"/v1/hub/dncxs/{client_id}"))

    def list_materials(self, client_id: str, **query) -> list[dict]:
        return self._get_all("/v1/hub/materials", {"client_id": client_id, **query})

    def list_bcct(self, client_id: str, **query) -> list[dict]:
        return self._get_all("/v1/hub/bcct", {"client_id": client_id, **query})

    def list_code_mappings(self, client_id: str) -> list[dict]:
        return self._get_all("/v1/hub/code-mappings", {"client_id": client_id})

    def list_products(self, client_id: str) -> list[dict]:
        return self._get_all("/v1/hub/products", {"client_id": client_id})

    def get_co_config(self, client_id: str) -> dict:
        return self._get(f"/v1/hub/dncxs/{client_id}/co-config")

    def source_summary(self, client_id: str) -> dict:
        return self._get(f"/v1/hub/dncxs/{client_id}/source-summary")

    def invoice_matches(self, client_id: str, invoice_no: str, declaration_types: list[str]) -> list[dict]:
        return items(self._get(
            "/v1/hub/bcct/invoice-matches",
            {
                "client_id": client_id,
                "invoice_no": invoice_no,
                "declaration_types": ",".join(declaration_types),
            },
        ))

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        params = {key: value for key, value in (params or {}).items() if value not in (None, "")}
        response = self._client.get(path, params=params, headers=self._auth_headers())
        response.raise_for_status()
        return response.json()

    def _get_all(self, path: str, params: dict[str, Any] | None = None) -> list[dict]:
        params = dict(params or {})
        params.setdefault("limit", 1000)
        cursor = ""
        seen_cursors: set[str] = set()
        rows: list[dict] = []
        while True:
            page_params = {**params, "cursor": cursor} if cursor else params
            payload = self._get(path, page_params)
            rows.extend(items(payload))
            cursor = next_cursor(payload)
            if not cursor or cursor in seen_cursors:
                return rows
            seen_cursors.add(cursor)

    def _auth_headers(self) -> dict[str, str]:
        token = self.token_provider() if self.token_provider else ""
        return {"Authorization": f"Bearer {token or self.token}"}

    def close(self) -> None:
        self._client.close()


class DataHubPortfolioService:
    def __init__(self, client: DataHubClient):
        self.data_hub = client

    def clients(self) -> list[dict]:
        return [self.client_summary(row["id"]) for row in self.data_hub.list_clients()]

    def client(self, client_id: str) -> dict:
        return self.data_hub.get_client(client_id)

    def client_summary(self, client_id: str) -> dict:
        client = self.client(client_id)
        source_summary, source_backend = self.source_summary(client)
        return {
            **client,
            "counts": {
                **client.get("counts", {}),
                "materials": source_summary["material_catalog"]["published_row_count"],
                "products": source_summary["product_catalog"]["published_row_count"],
                "bcct": source_summary["bcct"]["published_row_count"],
                "co_stock": source_summary["co_stock_row_count"],
            },
            "source_backend": source_backend,
            "source_versions": {
                "material_catalog": source_summary["material_catalog"].get("latest_version") or {},
                "product_catalog": source_summary["product_catalog"].get("latest_version") or {},
                "bcct": source_summary["bcct"].get("latest_version") or {},
            },
        }

    def get_client_config(self, client: dict) -> dict:
        config = self.data_hub.get_co_config(client["id"])
        return migrate_config({**default_config(client), **config}, client)

    def save_client_config(self, client: dict, config: dict) -> dict:
        raise RuntimeError("Client config is read-only from CO while DATA_HUB_ENABLED is active.")

    def refresh_client_indexes(self, client: dict) -> None:
        return None

    def source_summary(self, client: dict) -> tuple[dict, str]:
        summary = self.data_hub.source_summary(client["id"])
        summary["client_config"] = migrate_config(summary.get("client_config") or {}, client)
        return summary, "data-hub"

    def source_workspace(self, client: dict) -> tuple[dict, str]:
        states, client_config = self._source_states(client)
        return {
            "client_config": client_config,
            "material_catalog": module_workspace(states["material_catalog"]),
            "product_catalog": module_workspace(states["product_catalog"]),
            "bcct": module_workspace(states["bcct"]),
            "co_stock_rows": co_stock_rows_from_bcct(states["bcct"]["published_rows"], client_config),
        }, "data-hub"

    def co_case_source_context(self, client: dict, case: dict) -> dict:
        source_summary, source_backend = self.source_summary(client)
        client_config = source_summary["client_config"]
        invoice_no = case.get("shipment", {}).get("invoice_no", "")
        relevant_types = client_config.get("bcct", {}).get("relevant_export_declaration_types", [])
        return {
            "source_backend": source_backend,
            "source_summary": source_summary,
            "invoice_matches": self.data_hub.invoice_matches(client["id"], invoice_no, relevant_types),
        }

    def process_catalog_upload(self, *_args, **_kwargs) -> dict:
        raise RuntimeError("Catalog uploads must be handled in Data Hub.")

    def process_bcct_upload(self, *_args, **_kwargs) -> dict:
        raise RuntimeError("BCCT uploads must be handled in Data Hub.")

    def material_catalog_template(self, *_args, **_kwargs) -> bytes:
        raise RuntimeError("Catalog templates must be handled in Data Hub.")

    def product_catalog_template(self, *_args, **_kwargs) -> bytes:
        raise RuntimeError("Catalog templates must be handled in Data Hub.")

    def bcct_template(self, *_args, **_kwargs) -> bytes:
        raise RuntimeError("BCCT templates must be handled in Data Hub.")

    def _source_states(self, client: dict) -> tuple[dict[str, dict], dict]:
        client_id = client["id"]
        client_config = self.get_client_config(client)
        materials = self.data_hub.list_materials(client_id)
        bcct_rows = [normalize_bcct_row(row) for row in self.data_hub.list_bcct(client_id)]
        product_rows = [normalize_product_row(row) for row in materials if row.get("category") == "tp"]
        if not product_rows:
            product_rows = [normalize_product_row(row) for row in self.data_hub.list_products(client_id)]
        material_rows = [normalize_material_row(row) for row in materials if row.get("category") != "tp"]
        return {
            "material_catalog": source_state_from_workspace("material_catalog", material_rows),
            "product_catalog": source_state_from_workspace("product_catalog", product_rows),
            "bcct": source_state_from_workspace("bcct", bcct_rows),
        }, client_config


def data_hub_client_from_env(token_provider: Callable[[], str] | None = None) -> DataHubClient | None:
    settings = data_hub_link_settings()
    if not settings.source_enabled:
        return None
    settings.require_source_config()
    return DataHubClient(
        base_url=settings.data_hub_api_base_url,
        token=settings.api_token,
        token_provider=token_provider,
        timeout=settings.request_timeout_seconds,
    )


def items(payload: dict) -> list[dict]:
    values = payload.get("items", payload.get("clients", []))
    return values if isinstance(values, list) else []


def next_cursor(payload: dict) -> str:
    for key in ("next_cursor", "nextCursor"):
        value = payload.get(key)
        if value:
            return str(value)
    pagination = payload.get("pagination")
    if isinstance(pagination, dict) and pagination.get("next_cursor"):
        return str(pagination["next_cursor"])
    return ""


def normalize_client(row: dict) -> dict:
    client_id = row.get("id") or row.get("client_id") or row.get("dncx_id") or ""
    return {
        "id": client_id,
        "name": row.get("name", client_id),
        "code": row.get("code") or client_id,
        "tax_code": row.get("tax_code", ""),
        "status": row.get("status", "active"),
        "contact": row.get("contact", ""),
    }


def normalize_material_row(row: dict) -> dict:
    return {
        "customs_code": row.get("customs_code", ""),
        "internal_code": row.get("internal_code", ""),
        "name": row.get("name", ""),
        "category": row.get("category", ""),
        "unit": row.get("unit", ""),
        "hs_code": row.get("hs_code", ""),
        "status": row.get("status", "active"),
    }


def normalize_product_row(row: dict) -> dict:
    code = row.get("product_code") or row.get("customs_code") or row.get("internal_code", "")
    return {
        "product_code": code,
        "customs_code": row.get("customs_code", code),
        "name": row.get("name", code),
        "unit": row.get("unit", ""),
        "hs_code": row.get("hs_code", ""),
        "status": row.get("status", "active"),
    }


def normalize_bcct_row(row: dict) -> dict:
    item_code = row.get("item_code") or row.get("internal_code") or row.get("customs_code", "")
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    transaction_key = row.get("transaction_key") or "||".join([
        row.get("direction", ""),
        row.get("declaration_no", ""),
        str(row.get("line_no", "")),
        item_code,
    ])
    invoice_ref = first_value(
        row.get("invoice_ref"),
        row.get("invoice_no"),
        row.get("invoice_number"),
        row.get("commercial_invoice_no"),
        payload.get("invoice_ref"),
        payload.get("so_hoa_don"),
        payload.get("hoa_don"),
    )
    return {
        **row,
        "transaction_key": transaction_key,
        "item_code": item_code,
        "description": row.get("description") or row.get("goods_name", ""),
        "origin_country": row.get("origin_country") or row.get("origin", ""),
        "customs_value": row.get("customs_value") or row.get("total_value", ""),
        "invoice_ref": invoice_ref,
        "review_status": row.get("review_status", "reviewed"),
    }


def first_value(*values) -> str:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return ""


def source_state_from_workspace(module: str, rows: list[dict]) -> dict:
    return {
        "module": module,
        "published_rows": [dict(row) for row in rows],
        "latest_version": {},
        "versions": [],
        "uploads": [],
        "correction_candidates": [],
        "audit_events": [],
    }


def module_workspace(state: dict) -> dict:
    return {
        "module": state["module"],
        "published_rows": [dict(row) for row in state["published_rows"]],
        "latest_version": dict(state.get("latest_version") or {}),
        "versions": [dict(row) for row in state.get("versions", [])],
        "uploads": [dict(row) for row in state.get("uploads", [])],
        "correction_candidates": [dict(row) for row in state.get("correction_candidates", [])],
        "audit_events": [dict(row) for row in state.get("audit_events", [])],
    }
