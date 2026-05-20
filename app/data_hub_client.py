from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Callable
from urllib.parse import quote

import httpx

from app.client_config_store import default_config, migrate_config
from app.co_case_store import match_case_bcct_exports
from app.data_hub_settings import data_hub_link_settings
from app.source_store import (
    co_stock_rows_from_bcct,
)

CURRENT_DATA_HUB_TOKEN: ContextVar[str] = ContextVar("current_data_hub_token", default="")
HUB_BOM_PATH = "/v1/hub/products/{product_code}/bom"
HUB_BOM_LATEST_PATH = "/v1/hub/products/{product_code}/bom/latest"
HUB_BOM_PROPOSALS_PATH = "/v1/hub/products/{product_code}/bom/proposals"
HUB_BOM_ARTIFACTS_PATH = "/v1/hub/products/{product_code}/bom/artifacts"
HUB_PROPOSAL_PATH = "/v1/hub/proposals/{proposal_id}"


class DataHubBomVariantConflict(RuntimeError):
    def __init__(self, product_code: str, payload: dict):
        super().__init__(payload.get("message") or f"Multiple BOM variants exist for {product_code}.")
        self.product_code = product_code
        self.payload = payload
        self.variants = items(payload)
        if not self.variants and isinstance(payload.get("variants"), list):
            self.variants = payload["variants"]
        self.variants = [normalize_bom_artifact(row) for row in self.variants]


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

    def list_bcct_by_codes(
        self,
        client_id: str,
        codes: list[str],
        *,
        direction: str = "import",
        include_material_identity: bool = False,
    ) -> list[dict]:
        if not codes:
            return []
        return self._get_all(
            f"/v1/hub/clients/{hub_path_part(client_id)}/bcct/by-codes",
            {
                "codes": ",".join(codes[:100]),
                "direction": direction,
                "include_material_identity": "true" if include_material_identity else "false",
            },
        )

    def list_declarations(
        self,
        client_id: str,
        *,
        direction: str | None = None,
        declaration_nos: list[str] | None = None,
        has_files: str | None = None,
    ) -> list[dict]:
        return self._get_all(
            f"/v1/hub/clients/{hub_path_part(client_id)}/declarations",
            {
                "direction": direction,
                "declaration_nos": ",".join((declaration_nos or [])[:500]),
                "has_files": has_files,
            },
        )

    def list_products(self, client_id: str) -> list[dict]:
        return self._get_all("/v1/hub/products", {"client_id": client_id})

    def list_bom_products(self, client_id: str) -> list[dict]:
        return self._get_all("/v1/hub/products", {"client_id": client_id})

    def list_bom_artifacts(self, client_id: str, product_code: str, **query) -> list[dict]:
        return [
            normalize_bom_artifact(row)
            for row in self._get_all(
                hub_bom_path(HUB_BOM_ARTIFACTS_PATH, product_code),
                {"client_id": client_id, **query},
            )
        ]

    def get_bom_latest(self, client_id: str, product_code: str) -> dict:
        try:
            return normalize_bom_payload(
                self._get(hub_bom_path(HUB_BOM_LATEST_PATH, product_code), {"client_id": client_id})
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                raise DataHubBomVariantConflict(product_code, exc.response.json()) from exc
            raise

    def get_bom_artifact(self, client_id: str, product_code: str, artifact_id: str) -> dict:
        return normalize_bom_payload(
            self._get(
                hub_bom_path(HUB_BOM_PATH, product_code),
                {"client_id": client_id, "artifact_id": artifact_id},
            )
        )

    def submit_bom_proposal(
        self,
        client_id: str,
        product_code: str,
        *,
        parent_artifact_id: str,
        rows: list[dict],
        context: dict | None = None,
        actor: str = "co_system",
        intent: str = "modified_for_case",
    ) -> dict:
        return self._post(
            hub_bom_path(HUB_BOM_PROPOSALS_PATH, product_code),
            {
                "client_id": client_id,
                "actor": actor,
                "intent": intent,
                "parent_artifact_id": parent_artifact_id,
                "context": context or {},
                "rows": rows,
            },
        )

    def get_bom_proposal(self, proposal_id: str) -> dict:
        return self._get(HUB_PROPOSAL_PATH.format(proposal_id=hub_path_part(proposal_id)))

    def get_client_config(self, client_id: str) -> dict:
        return self._get(f"/v1/hub/dncxs/{client_id}/client-config")

    def source_summary(self, client_id: str) -> dict:
        return self._get(f"/v1/hub/dncxs/{client_id}/source-summary")

    def list_material_substitutes(
        self,
        client_id: str,
        material_code: str,
        *,
        min_score: float = 0.5,
        limit: int = 20,
        include_rejected: bool = False,
    ) -> tuple[list[dict], str]:
        # Bearer-aware mirror per Data Hub sister-app note 2026-05-13.
        # Same response shape as the legacy cookie-only /api/v1 route, but
        # this one accepts service-token Bearer (scope hub:read).
        path = f"/v1/hub/clients/{hub_path_part(client_id)}/materials/{hub_path_part(material_code)}/substitutes"
        params = {
            "min_score": min_score,
            "limit": min(max(int(limit), 1), 100),
            "include_rejected": "true" if include_rejected else "false",
        }
        try:
            payload = self._get(path, params)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return [], "data_hub"
            # 401/403 surface as unauthorized so the UI can render a useful
            # banner (token missing scope or expired). The HS-prefix heuristic
            # in main.py kicks in as a soft fallback so operators are not blocked.
            if exc.response.status_code in (401, 403):
                return [], "data_hub_unauthorized"
            raise
        return list(payload.get("items") or []), "data_hub"

    def get_material(self, client_id: str, material_code: str) -> dict:
        try:
            return normalize_material_row(
                self._get(f"/v1/hub/materials/{hub_path_part(material_code)}", {"client_id": client_id})
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return {}
            raise

    def invoice_matches(self, client_id: str, invoice_no: str, declaration_types: list[str]) -> list[dict]:
        if not invoice_no.strip():
            return []
        return items(self._get(
            "/v1/hub/bcct/invoice-matches",
            {
                "client_id": client_id,
                "invoice_no": invoice_no,
                "declaration_types": ",".join(declaration_types),
                "include_market_hint": "true",
                "include_material_identity": "true",
            },
        ))

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        params = {key: value for key, value in (params or {}).items() if value not in (None, "")}
        response = self._client.get(path, params=params, headers=self._auth_headers())
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, payload: dict[str, Any]) -> dict:
        response = self._client.post(path, json=payload, headers=self._auth_headers())
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
        effective_token = token or self.token
        return {"Authorization": f"Bearer {effective_token}"} if effective_token else {}

    def close(self) -> None:
        self._client.close()


class DataHubPortfolioService:
    def __init__(self, client: DataHubClient):
        self.data_hub = client

    def clients(self) -> list[dict]:
        return [self._client_summary(row) for row in self.data_hub.list_clients()]

    def client(self, client_id: str) -> dict:
        return self.data_hub.get_client(client_id)

    def client_summary(self, client_id: str) -> dict:
        return self._client_summary(self.client(client_id))

    def _client_summary(self, client: dict) -> dict:
        source_summary, source_backend = self.source_summary(client)
        return {
            **client,
            "counts": {
                **client.get("counts", {}),
                "materials": source_summary["material_catalog"]["published_row_count"],
                "products": source_summary["product_catalog"]["published_row_count"],
                "bcct": source_summary["bcct"]["published_row_count"],
                "co_stock": source_summary.get("co_stock_row_count", 0),
            },
            "source_backend": source_backend,
            "source_versions": {
                "material_catalog": source_summary["material_catalog"].get("latest_version") or {},
                "product_catalog": source_summary["product_catalog"].get("latest_version") or {},
                "bcct": source_summary["bcct"].get("latest_version") or {},
            },
        }

    def get_client_config(self, client: dict) -> dict:
        config = self.data_hub.get_client_config(client["id"])
        return migrate_config({**default_config(client), **config}, client)

    def save_client_config(self, client: dict, config: dict) -> dict:
        raise RuntimeError("Client config is read-only from CO while DATA_HUB_ENABLED is active.")

    def refresh_client_indexes(self, client: dict) -> None:
        return None

    def source_summary(self, client: dict) -> tuple[dict, str]:
        summary = self.data_hub.source_summary(client["id"])
        summary["client_config"] = normalize_data_hub_client_config(summary.get("client_config") or {}, client)
        # Never paginate the full import-direction BCCT just to compute co_stock_row_count.
        # On big clients (Johnson: 65k+ rows) that's the difference between a snappy
        # /clients home and a 30-60s page load. If Data Hub didn't include the count
        # in source-summary, surface 0 — the dashboard tile is informational.
        summary["co_stock_row_count"] = int(summary.get("co_stock_row_count") or 0)
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

    def submit_bom_proposal(
        self,
        client_id: str,
        product_code: str,
        *,
        parent_artifact_id: str,
        rows: list[dict],
        context: dict | None = None,
        actor: str = "co_system",
        intent: str = "modified_for_case",
    ) -> dict:
        if not hasattr(self.data_hub, "submit_bom_proposal"):
            raise RuntimeError("Data Hub backend does not expose submit_bom_proposal")
        return self.data_hub.submit_bom_proposal(
            client_id,
            product_code,
            parent_artifact_id=parent_artifact_id,
            rows=rows,
            context=context,
            actor=actor,
            intent=intent,
        )

    def list_material_substitutes(
        self,
        client_id: str,
        material_code: str,
        *,
        min_score: float = 0.5,
        limit: int = 20,
        include_rejected: bool = False,
    ) -> tuple[list[dict], str]:
        if not hasattr(self.data_hub, "list_material_substitutes"):
            return [], "no_data_hub"
        result = self.data_hub.list_material_substitutes(
            client_id,
            material_code,
            min_score=min_score,
            limit=limit,
            include_rejected=include_rejected,
        )
        if isinstance(result, tuple):
            return result
        return list(result), "data_hub"

    def get_material(self, client_id: str, material_code: str) -> dict:
        if not hasattr(self.data_hub, "get_material"):
            return {}
        return self.data_hub.get_material(client_id, material_code)

    def list_bcct_by_codes(
        self,
        client_id: str,
        codes: list[str],
        *,
        direction: str = "import",
    ) -> list[dict]:
        if not codes or not hasattr(self.data_hub, "list_bcct_by_codes"):
            return []
        rows = self.data_hub.list_bcct_by_codes(client_id, codes, direction=direction)
        return [normalize_bcct_row(row) for row in rows]

    def list_declarations(
        self,
        client_id: str,
        *,
        direction: str | None = None,
        declaration_nos: list[str] | None = None,
    ) -> list[dict]:
        if not hasattr(self.data_hub, "list_declarations"):
            return []
        return self.data_hub.list_declarations(
            client_id,
            direction=direction,
            declaration_nos=declaration_nos,
        )

    def search_materials(self, client_id: str, query: str, limit: int = 20) -> list[dict]:
        if not hasattr(self.data_hub, "list_materials"):
            return []
        rows = []
        for row in self.data_hub.list_materials(client_id):
            normalized = normalize_material_row(row)
            haystack = " ".join([
                str(normalized.get("material_code") or ""),
                str(normalized.get("internal_code") or ""),
                str(normalized.get("name") or ""),
                str(normalized.get("hs_code") or ""),
            ]).lower()
            if not query or query.lower() in haystack:
                rows.append(normalized)
                if len(rows) >= max(1, min(limit, 100)):
                    break
        return rows

    def co_case_source_context(self, client: dict, case: dict) -> dict:
        source_summary, source_backend = self.source_summary(client)
        client_config = source_summary["client_config"]
        shipment = case.get("shipment", {})
        invoice_no = str(shipment.get("invoice_no", "") or "").strip()
        export_declaration_nos = shipment.get("export_declaration_nos", []) or []
        has_products = bool(case.get("products"))
        # Short-circuit: empty case (no shipment, no products) only needs source_summary.
        # Without this, opening the /co-case index page paginates the full materials +
        # BCCT catalogs from Data Hub on every render — seconds-to-minutes for big clients.
        if not invoice_no and not export_declaration_nos and not has_products:
            return {
                "source_backend": source_backend,
                "source_summary": source_summary,
                "invoice_matches": [],
                "material_rows": [],
                "stock_rows": [],
                "declaration_file_counts": {"export": {}, "import": {}},
            }
        relevant_types = client_config.get("bcct", {}).get("relevant_export_declaration_types", [])
        material_rows = []
        if hasattr(self.data_hub, "list_materials"):
            material_rows = [
                normalize_material_row(row)
                for row in self.data_hub.list_materials(client["id"])
                if row.get("category") != "tp"
            ]
        bcct_rows = []
        if hasattr(self.data_hub, "list_bcct"):
            bcct_rows = [
                normalize_bcct_row(row)
                for row in self.data_hub.list_bcct(client["id"], include_material_identity="true")
            ]
        if export_declaration_nos:
            invoice_matches = match_case_bcct_exports(
                case,
                {"bcct": {"published_rows": bcct_rows}},
                client_config,
            )
        else:
            invoice_matches = self.data_hub.invoice_matches(client["id"], invoice_no, relevant_types) if invoice_no else []
            invoice_matches = enrich_invoice_matches_with_bcct(invoice_matches, bcct_rows)
        stock_rows = co_stock_rows_from_bcct(bcct_rows, client_config)
        declaration_file_counts = self.declaration_file_counts(client["id"], case, invoice_matches)
        return {
            "source_backend": source_backend,
            "source_summary": source_summary,
            "invoice_matches": invoice_matches,
            "material_rows": material_rows,
            "stock_rows": stock_rows,
            "declaration_file_counts": declaration_file_counts,
        }

    def declaration_file_counts(self, client_id: str, case: dict, invoice_matches: list[dict]) -> dict:
        counts: dict[str, dict[str, int]] = {"export": {}, "import": {}}
        if not hasattr(self.data_hub, "list_declarations"):
            return counts
        shipment_export_declarations = case.get("shipment", {}).get("export_declaration_nos", []) or []
        matched_export_declarations = [
            row.get("declaration_no")
            for row in invoice_matches or []
        ]
        export_declarations = sorted({
            str(value or "").strip()
            for value in [*shipment_export_declarations, *matched_export_declarations]
            if str(value or "").strip()
        })
        import_declarations = sorted({
            str(line.get("import_declaration_no") or "").strip()
            for product in case.get("products", []) or []
            if str(product.get("origin_sheet_status") or "").strip() == "locked"
            for material in product.get("materials", []) or []
            for line in material.get("allocation_lines", []) or []
            if str(line.get("import_declaration_no") or "").strip()
        })
        try:
            if export_declarations:
                for row in self.list_declarations(client_id, direction="export", declaration_nos=export_declarations):
                    declaration_no = str(row.get("declaration_no") or "").strip()
                    if declaration_no:
                        counts["export"][declaration_no] = int(row.get("file_count") or 0)
            if import_declarations:
                for row in self.list_declarations(client_id, direction="import", declaration_nos=import_declarations):
                    declaration_no = str(row.get("declaration_no") or "").strip()
                    if declaration_no:
                        counts["import"][declaration_no] = int(row.get("file_count") or 0)
        except Exception:  # noqa: BLE001
            return {"export": {}, "import": {}}
        return counts

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


def normalize_bom_artifact(row: dict) -> dict:
    artifact_id = row.get("artifact_id") or ""
    artifact_no = row.get("artifact_no") or 0
    return {
        **row,
        "artifact_id": artifact_id,
        "artifact_no": artifact_no,
    }


def normalize_bom_payload(payload: dict) -> dict:
    output = dict(payload)
    if isinstance(output.get("artifact"), dict):
        output["artifact"] = normalize_bom_artifact(output["artifact"])
    if isinstance(output.get("variants"), list):
        output["variants"] = [normalize_bom_artifact(row) for row in output["variants"]]
    return output


def material_identity(row: dict) -> dict:
    identity = row.get("material_identity")
    if not isinstance(identity, dict):
        return {}
    return identity


def material_identity_display_code(row: dict) -> str:
    identity = material_identity(row)
    return str(
        identity.get("resolved_code")
        or identity.get("internal_code")
        or identity.get("customs_code")
        or ""
    ).strip()


def bom_product_code_from_material_identity(row: dict) -> str:
    identity = material_identity(row)
    if not identity:
        return ""
    if identity.get("resolution_status") not in ("resolved", "resolved_pending_review"):
        return ""
    if identity.get("product_kind") not in ("", None, "tp"):
        return ""
    return str(identity.get("bom_product_code") or "").strip()


def normalize_client(row: dict) -> dict:
    client_id = row.get("id") or row.get("client_id") or row.get("dncx_id") or ""
    counts = dict(row.get("counts") or {})
    if "n_bom" in row:
        counts["bom_lines"] = row.get("n_bom") or 0
    return {
        "id": client_id,
        "name": row.get("name", client_id),
        "code": row.get("code") or client_id,
        "tax_code": row.get("tax_code", ""),
        "status": row.get("status", "active"),
        "contact": row.get("contact", ""),
        "counts": counts,
    }


def normalize_data_hub_client_config(payload: dict, client: dict) -> dict:
    if "bcct" in payload:
        return migrate_config(payload, client)
    config = {
        "schema_version": payload.get("schema_version", 1),
        "client_id": payload.get("client_id") or client["id"],
        "config_version": payload.get("config_version", 1),
        "config_hash": payload.get("config_hash", ""),
        "bcct": {
            "declaration_type_preset": payload.get("preset_key", "data_hub"),
            "eligible_import_declaration_types": payload.get("eligible_import_declaration_types", []),
            "relevant_export_declaration_types": payload.get("relevant_export_declaration_types", []),
        },
    }
    return migrate_config(config, client)


def normalize_material_row(row: dict) -> dict:
    code = row.get("material_code") or row.get("customs_code", "")
    normalized = {key: value for key, value in row.items() if key != "unit"}
    return {
        **normalized,
        "customs_code": code,
        "internal_code": row.get("internal_code") or code,
        "material_code": code,
        "name": row.get("name", ""),
        "category": row.get("category", ""),
        "uom": row.get("uom") or row.get("unit", ""),
        "hs_code": row.get("hs_code", ""),
        "unit_price": row.get("unit_price") or row.get("taxable_unit_price") or "",
        "status": row.get("status", "active"),
    }


def normalize_product_row(row: dict) -> dict:
    code = row.get("product_code") or row.get("material_code") or row.get("customs_code") or row.get("internal_code", "")
    normalized = {key: value for key, value in row.items() if key != "unit"}
    return {
        **normalized,
        "product_code": code,
        "customs_code": row.get("customs_code") or row.get("material_code") or code,
        "name": row.get("name", code),
        "uom": row.get("uom") or row.get("unit", ""),
        "hs_code": row.get("hs_code", ""),
        "status": row.get("status", "active"),
    }


def normalize_bcct_row(row: dict) -> dict:
    item_code = material_identity_display_code(row) or row.get("item_code") or row.get("internal_code") or row.get("customs_code", "")
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
    customs_value = first_value(
        row.get("customs_value"),
        row.get("total_value"),
        payload.get("customs_value"),
        payload.get("total_value"),
        payload.get("tri_gia"),
        payload.get("tong_tri_gia"),
    )
    foreign_currency_value = first_value(
        row.get("foreign_currency_value"),
        row.get("total_value_nt"),
        payload.get("foreign_currency_value"),
        payload.get("tri_gia_nt"),
    )
    currency = first_value(row.get("currency"), row.get("currency_nt"), payload.get("currency"), payload.get("don_vi_tien_te"))
    return {
        **row,
        "transaction_key": transaction_key,
        "item_code": item_code,
        "description": row.get("description") or row.get("goods_name", ""),
        "origin_country": row.get("origin_country") or row.get("origin", ""),
        "customs_value": customs_value,
        "taxable_unit_price": first_value(
            row.get("taxable_unit_price"),
            row.get("unit_price"),
            payload.get("taxable_unit_price"),
            payload.get("unit_price"),
            payload.get("don_gia_tinh_thue"),
            payload.get("don_gia"),
        ),
        "total_value": first_value(row.get("total_value"), payload.get("total_value"), payload.get("tong_tri_gia")),
        "foreign_currency_value": foreign_currency_value,
        "currency": currency,
        "value_currency": "VND" if customs_value else currency if foreign_currency_value else "",
        "invoice_ref": invoice_ref,
        "review_status": row.get("review_status", "reviewed"),
    }


def enrich_invoice_matches_with_bcct(invoice_matches: list[dict], bcct_rows: list[dict]) -> list[dict]:
    by_transaction = {
        str(row.get("transaction_key", "")): row
        for row in bcct_rows
        if row.get("direction") == "export" and row.get("transaction_key")
    }
    by_line = {
        bcct_line_key(row): row
        for row in bcct_rows
        if row.get("direction") == "export"
    }
    output = []
    for match in invoice_matches:
        source = by_transaction.get(str(match.get("transaction_key", ""))) or by_line.get(bcct_line_key(match)) or {}
        output.append({
            **match,
            "material_identity": match.get("material_identity") if isinstance(match.get("material_identity"), dict) else source.get("material_identity", {}),
            "customs_value": first_value(match.get("customs_value"), source.get("customs_value")),
            "total_value": first_value(match.get("total_value"), source.get("total_value")),
            "foreign_currency_value": first_value(match.get("foreign_currency_value"), source.get("foreign_currency_value")),
            "currency": first_value(match.get("currency"), source.get("currency")),
            "value_currency": first_value(match.get("value_currency"), source.get("value_currency")),
            "incoterms": first_value(match.get("incoterms"), source.get("incoterms")),
            "origin_country": first_value(match.get("origin_country"), source.get("origin_country")),
            "invoice_date": first_value(match.get("invoice_date"), source.get("invoice_date")),
            "departure_date": first_value(match.get("departure_date"), source.get("departure_date")),
            "consignee_name": first_value(match.get("consignee_name"), source.get("consignee_name")),
            "exporter_name": first_value(match.get("exporter_name"), source.get("exporter_name")),
            "unloading_location": first_value(match.get("unloading_location"), source.get("unloading_location")),
            "destination_location_code": first_value(
                match.get("destination_location_code"),
                source.get("destination_location_code"),
            ),
            "destination_location_name": first_value(
                match.get("destination_location_name"),
                source.get("destination_location_name"),
            ),
            "market_hint": match.get("market_hint") if isinstance(match.get("market_hint"), dict) else source.get("market_hint"),
        })
    return output


def bcct_line_key(row: dict) -> tuple[str, str, str, str]:
    return (
        str(row.get("declaration_no", "")),
        str(row.get("line_no", "")),
        str(row.get("item_code") or row.get("internal_code") or row.get("customs_code") or ""),
        str(row.get("invoice_ref", "")),
    )


def first_value(*values) -> str:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return ""


def hub_path_part(value: str) -> str:
    return quote(str(value), safe="")


def hub_bom_path(template: str, product_code: str) -> str:
    return template.format(product_code=hub_path_part(product_code))


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
