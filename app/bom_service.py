from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from time import monotonic

import httpx

from app.bom_store import (
    BOM_PROFILE_OPTIONS,
    CODE_SYSTEM_OPTIONS,
    UPLOAD_MODE_OPTIONS,
    UPLOAD_SCOPE_OPTIONS,
    create_bom_template_workbook,
    get_bom_workspace,
    process_bom_upload,
    update_bom_config,
)
from app.data_hub_client import (
    DataHubBomVariantConflict,
    DataHubClient,
    current_data_hub_token,
    data_hub_client_from_env,
)

DATA_HUB_BOM_WORKSPACE_CACHE_TTL_SECONDS = 60.0
_DATA_HUB_BOM_WORKSPACE_CACHE: dict[tuple[str, str, str, tuple[str, ...]], tuple[float, dict]] = {}


class LocalBomService:
    def workspace(self, client: dict, product_codes: list[str] | None = None) -> dict:
        workspace = get_bom_workspace(client)
        workspace["backend"] = "local"
        workspace["read_only"] = False
        return workspace

    def update_config(self, client: dict, form: dict[str, str]) -> dict:
        return update_bom_config(client, form)

    def process_upload(
        self,
        client: dict,
        content: bytes,
        filename: str,
        upload_mode: str,
        upload_scope: str | None,
        accept_review_required: bool,
    ) -> dict:
        return process_bom_upload(
            client,
            content,
            filename,
            upload_mode,
            upload_scope,
            accept_review_required,
        )

    def template(self, client: dict) -> bytes:
        return create_bom_template_workbook(client)


class DataHubBomService:
    def __init__(self, data_hub: DataHubClient):
        self.data_hub = data_hub

    def workspace(self, client: dict, product_codes: list[str] | None = None) -> dict:
        cache_key = data_hub_bom_workspace_cache_key(self.data_hub, client["id"], product_codes)
        now = monotonic()
        cached = _DATA_HUB_BOM_WORKSPACE_CACHE.get(cache_key)
        if cached and now - cached[0] <= DATA_HUB_BOM_WORKSPACE_CACHE_TTL_SECONDS:
            return deepcopy(cached[1])
        workspace = self._build_workspace(client, product_codes)
        _DATA_HUB_BOM_WORKSPACE_CACHE[cache_key] = (now, deepcopy(workspace))
        return workspace

    def _build_workspace(self, client: dict, product_codes: list[str] | None = None) -> dict:
        client_id = client["id"]
        product_filter = normalized_product_code_filter(product_codes)
        product_rows = self.data_hub.list_bom_products(client_id)
        if product_filter:
            product_rows = [
                product
                for product in product_rows
                if product_code_from_row(product) in product_filter
            ]
        product_versions: list[dict] = []
        latest_rows: list[dict] = []
        variant_conflicts: list[dict] = []

        for product in product_rows:
            product_code = product_code_from_row(product)
            if not product_code:
                continue
            version_payloads = self.product_version_payloads(client_id, product_code)
            if version_payloads:
                current_version_id = version_payloads[0]["version"].get("version_id", "")
                for payload in version_payloads:
                    version = normalize_hub_version(payload.get("version") or {}, product_code)
                    rows = [
                        normalize_hub_row(row, version)
                        for row in payload.get("rows", [])
                        if isinstance(row, dict)
                    ]
                    version["status"] = (
                        "current"
                        if version.get("product_version_id") == current_version_id and version.get("flatten_status") != "non_flattened"
                        else "non_flattened"
                        if version.get("flatten_status") == "non_flattened"
                        else "published"
                    )
                    version["rows"] = rows
                    version["row_count"] = version.get("row_count") or len(rows)
                    version["unresolved"] = payload.get("unresolved", [])
                    version["decisions"] = payload.get("decisions", [])
                    product_versions.append(version)
                    if version["status"] == "current":
                        latest_rows.extend(rows)
                continue
            try:
                payload = self.data_hub.get_bom_latest(client_id, product_code)
            except DataHubBomVariantConflict as exc:
                variant_conflicts.append({"product_code": product_code, "variants": exc.variants})
                product_versions.extend(version_from_variant(product_code, variant) for variant in exc.variants)
                continue
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    continue
                raise

            version = normalize_hub_version(payload.get("version") or {}, product_code)
            rows = [
                normalize_hub_row(row, version)
                for row in payload.get("rows", [])
                if isinstance(row, dict)
            ]
            version["rows"] = rows
            version["row_count"] = version.get("row_count") or len(rows)
            version["unresolved"] = payload.get("unresolved", [])
            version["decisions"] = payload.get("decisions", [])
            product_versions.append(version)
            latest_rows.extend(rows)

        product_versions.sort(
            key=lambda row: (row.get("product_code", ""), row.get("product_version_no", 0))
        )
        latest_rows.sort(key=lambda row: (row.get("product_code", ""), row.get("material_code", "")))
        composition = [composition_entry(row) for row in product_versions if row.get("status") == "current"]
        aggregate = aggregate_version(composition, latest_rows)
        return {
            "backend": "data-hub",
            "read_only": True,
            "config": {
                "bom_profile": "data_hub",
                "default_import_mode": "data_hub",
                "code_system_mode": "data_hub",
            },
            "versions": [aggregate] if aggregate["version_id"] else [],
            "product_versions": product_versions,
            "product_version_options_by_code": product_version_options_by_code(product_versions),
            "product_composition": composition,
            "uploads": [],
            "audit": [],
            "latest_version": aggregate,
            "latest_rows": latest_rows,
            "profile_options": BOM_PROFILE_OPTIONS,
            "upload_mode_options": UPLOAD_MODE_OPTIONS,
            "upload_scope_options": UPLOAD_SCOPE_OPTIONS,
            "code_system_options": CODE_SYSTEM_OPTIONS,
            "variant_conflicts": variant_conflicts,
        }

    def product_version_payloads(self, client_id: str, product_code: str) -> list[dict]:
        if not hasattr(self.data_hub, "list_bom_versions") or not hasattr(self.data_hub, "get_bom_version"):
            return []
        try:
            summaries = self.data_hub.list_bom_versions(client_id, product_code)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return []
            raise
        if len(summaries) <= 1:
            return []
        payloads = []
        for summary in sorted(summaries, key=lambda row: int(row.get("version_no") or 0), reverse=True):
            version_id = summary.get("version_id", "")
            if not version_id:
                continue
            try:
                payload = self.data_hub.get_bom_version(client_id, product_code, version_id)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    continue
                raise
            payloads.append({
                **payload,
                "version": {
                    **summary,
                    **(payload.get("version") or {}),
                    "version_id": version_id,
                    "product_code": product_code,
                },
            })
        return payloads

    def update_config(self, *_args, **_kwargs) -> dict:
        raise RuntimeError("Canonical BOM config must be managed in Data Hub.")

    def process_upload(self, *_args, **_kwargs) -> dict:
        raise RuntimeError("Canonical BOM uploads must be handled in Data Hub.")

    def template(self, *_args, **_kwargs) -> bytes:
        raise RuntimeError("Canonical BOM templates must be downloaded from Data Hub.")


def current_bom_service() -> LocalBomService | DataHubBomService:
    data_hub_client = data_hub_client_from_env(token_provider=current_data_hub_token)
    if data_hub_client:
        return DataHubBomService(data_hub_client)
    return LocalBomService()


class BomServiceProxy:
    def __getattr__(self, name: str):
        return getattr(current_bom_service(), name)


bom_service = BomServiceProxy()


def data_hub_bom_workspace_cache_key(data_hub: DataHubClient, client_id: str, product_codes: list[str] | None) -> tuple[str, str, str, tuple[str, ...]]:
    return (
        data_hub_cache_identity(data_hub),
        client_id,
        current_data_hub_token(),
        tuple(sorted(normalized_product_code_filter(product_codes))),
    )


def data_hub_cache_identity(data_hub: DataHubClient) -> str:
    base_url = getattr(data_hub, "base_url", "")
    token = getattr(data_hub, "token", "")
    if base_url or token:
        return f"{base_url}|{token}"
    return f"object:{id(data_hub)}"


def normalized_product_code_filter(product_codes: list[str] | None) -> set[str]:
    return {str(code or "").strip() for code in product_codes or [] if str(code or "").strip()}


def clear_data_hub_bom_workspace_cache() -> None:
    _DATA_HUB_BOM_WORKSPACE_CACHE.clear()


def product_code_from_row(row: dict) -> str:
    return str(row.get("product_code") or row.get("customs_code") or row.get("internal_code") or "").strip()


def normalize_hub_version(version: dict, product_code: str) -> dict:
    version_id = str(version.get("version_id", ""))
    version_no = int(version.get("version_no") or 0)
    return {
        **version,
        "product_code": version.get("product_code") or product_code,
        "product_version_id": version_id,
        "product_version_no": version_no,
        "version_hash": version.get("normalized_hash", ""),
        "row_count": int(version.get("row_count") or 0),
        "status": "current" if version.get("flatten_status") != "non_flattened" else "non_flattened",
        "diff_summary": {},
        "source_upload_id": version.get("source_upload_id") or version.get("source_channel", "data-hub"),
    }


def version_from_variant(product_code: str, variant: dict) -> dict:
    return {
        **variant,
        "product_code": product_code,
        "product_version_id": variant.get("version_id", ""),
        "product_version_no": int(variant.get("version_no") or 0),
        "version_hash": "",
        "row_count": int(variant.get("row_count") or 0),
        "status": "variant_conflict",
        "diff_summary": {},
        "source_upload_id": "data-hub",
        "rows": [],
    }


def normalize_hub_row(row: dict, version: dict) -> dict:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    product_code = version.get("product_code", "")
    qty = row.get("qty_per_unit", row.get("qty_per", ""))
    return {
        **row,
        "product_code": product_code,
        "bom_code": row.get("bom_code") or version.get("bom_code") or product_code,
        "bom_variant_id": row.get("bom_variant_id") or version.get("bom_variant_id") or "default",
        "material_code": row.get("material_code", ""),
        "material_name": payload.get("material_name") or payload.get("description") or "",
        "hs_code": row.get("hs_code") or payload.get("hs_code") or payload.get("material_hs_code") or "",
        "qty_per": qty,
        "uom": row.get("uom", ""),
        "scrap_rate": payload.get("scrap_rate", ""),
        "source": version.get("source_bom_kind", "data_hub"),
        "row_class": version.get("flatten_status", "published"),
        "product_version_id": version.get("product_version_id", ""),
        "product_version_no": version.get("product_version_no", 0),
        "flatten_strategy": version.get("flatten_strategy", ""),
    }


def composition_entry(product_version: dict) -> dict:
    return {
        "product_code": product_version["product_code"],
        "product_version_id": product_version["product_version_id"],
        "product_version_no": product_version["product_version_no"],
        "version_hash": product_version.get("version_hash", ""),
        "row_count": product_version.get("row_count", 0),
        "status": product_version.get("status", "current"),
    }


def aggregate_version(composition: list[dict], rows: list[dict]) -> dict:
    if not composition:
        return {
            "version_no": 0,
            "version_id": "",
            "rows": [],
            "row_count": 0,
            "product_versions": [],
        }
    payload = [
        {
            "product_code": row["product_code"],
            "product_version_id": row["product_version_id"],
            "product_version_no": row["product_version_no"],
            "version_hash": row.get("version_hash", ""),
        }
        for row in composition
    ]
    version_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return {
        "version_no": 1,
        "version_id": f"dhagg-{version_hash[:16]}",
        "version_hash": version_hash,
        "status": "published",
        "row_count": len(rows),
        "rows": rows,
        "product_versions": composition,
        "diff_summary": {},
        "published_at": "",
    }


def product_version_options_by_code(product_versions: list[dict]) -> dict[str, list[dict]]:
    output: dict[str, list[dict]] = {}
    for version in product_versions:
        if version.get("status") == "variant_conflict":
            continue
        output.setdefault(version["product_code"], []).append(version)
    return output
