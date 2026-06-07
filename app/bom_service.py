from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
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
# Capped low on purpose: prod Data Hub runs a single uvicorn worker behind a
# public proxy, so it serializes requests. Higher concurrency just queues on
# that one backend worker and the tail latency can exceed the sequential build
# (and breach the client read timeout -> 503). 4 is the stable sweet spot in
# prod benchmarks; raise it only once Data Hub scales out its workers.
BOM_FETCH_MAX_WORKERS = 4
_DATA_HUB_BOM_WORKSPACE_CACHE: dict[tuple[str, str, str, tuple[str, ...], str], tuple[float, dict]] = {}
# Process-local memo of whether a Data Hub backend (keyed by base_url|token)
# serves the batch BOM artifacts endpoint. False once a 404 is seen, so we
# stop probing and use the per-product fallback until the process restarts.
_DATA_HUB_BOM_BATCH_SUPPORTED: dict[str, bool] = {}

PICKER_INTENTS: tuple[str, ...] = (
    "asserted_technical",
    "staff_edit",
    "derived",
    "customs_declared",
    "modified_for_case",
)

# Data Hub owns the shallow/full classification (depth=full filter). This set is
# the CLIENT-SIDE FALLBACK mirror, used only when DH hasn't shipped `depth` yet
# (no `is_shallow` field on items, no `depth` echo in `filter_applied`). A shallow
# flatten stops before exploding sub-assemblies → a structurally incomplete BOM
# that must never reach the picker. `not_applicable` artifacts are never shallow.
_SHALLOW_FLATTEN_STRATEGIES: frozenset[str] = frozenset(
    {"purchased_btp_as_leaf", "mixed_confirmed", "no_strategy"}
)


def _version_is_shallow(version: dict) -> bool:
    """True if an artifact is a shallow/partial flatten.

    Prefers Data Hub's authoritative per-item `is_shallow` boolean when present;
    falls back to the `flatten_strategy` mirror for a pre-depth Data Hub.
    """
    is_shallow = version.get("is_shallow")
    if is_shallow is not None:
        return bool(is_shallow)
    if str(version.get("flatten_status") or "") == "not_applicable":
        return False
    return str(version.get("flatten_strategy") or "") in _SHALLOW_FLATTEN_STRATEGIES


class LocalBomService:
    def workspace(self, client: dict, product_codes: list[str] | None = None, *, case_id: str = "") -> dict:
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

    def list_products(self, client: dict) -> list[dict]:
        """Cheap finished-product list (no per-product line fetch)."""
        composition = self.workspace(client).get("product_composition", [])
        return [{"product_code": code} for code in sorted(
            {str(r.get("product_code", "")) for r in composition if r.get("product_code")}
        )]


class DataHubBomService:
    def __init__(self, data_hub: DataHubClient):
        self.data_hub = data_hub

    def list_products(self, client: dict) -> list[dict]:
        """Cheap finished-product list: one paginated /products call, no
        per-product artifact/line fetch (which workspace() would do)."""
        return self.data_hub.list_bom_products(client["id"])

    def workspace(self, client: dict, product_codes: list[str] | None = None, *, case_id: str = "") -> dict:
        cache_key = data_hub_bom_workspace_cache_key(self.data_hub, client["id"], product_codes, case_id)
        now = monotonic()
        if cache_key[0]:
            cached = _DATA_HUB_BOM_WORKSPACE_CACHE.get(cache_key)
            if cached and now - cached[0] <= DATA_HUB_BOM_WORKSPACE_CACHE_TTL_SECONDS:
                return deepcopy(cached[1])
        workspace = self._build_workspace(client, product_codes, case_id=case_id)
        if cache_key[0]:
            _DATA_HUB_BOM_WORKSPACE_CACHE[cache_key] = (now, deepcopy(workspace))
        return workspace

    def _build_workspace(self, client: dict, product_codes: list[str] | None = None, *, case_id: str = "") -> dict:
        client_id = client["id"]
        product_filter = normalized_product_code_filter(product_codes)
        product_rows = (
            [{"product_code": product_code} for product_code in sorted(product_filter)]
            if product_filter
            else self.data_hub.list_bom_products(client_id)
        )
        product_codes_in_order = [
            code for code in (product_code_from_row(product) for product in product_rows) if code
        ]

        product_versions: list[dict] = []
        latest_rows: list[dict] = []
        variant_conflicts: list[dict] = []
        dh_filter_active = False

        # Prefer the batch endpoint (one round-trip for all products); fall
        # back to the per-product parallel fetch when Data Hub hasn't shipped
        # it. Both produce the same per-product result shape.
        product_results = self._try_batch_results(client_id, product_codes_in_order, case_id=case_id)
        if product_results is None:
            product_results = self._fetch_product_results(client_id, product_codes_in_order, case_id=case_id)
        for result in product_results:
            if result["picker_filter_applied"]:
                dh_filter_active = True
            product_versions.extend(result["product_versions"])
            latest_rows.extend(result["latest_rows"])
            variant_conflicts.extend(result["variant_conflicts"])

        product_versions.sort(
            key=lambda row: (row.get("product_code", ""), row.get("product_version_no", 0))
        )
        latest_rows.sort(key=lambda row: (row.get("product_code", ""), row.get("material_code", "")))
        composition = [composition_entry(row) for row in product_versions if row.get("status") == "current"]
        aggregate = aggregate_version(composition, latest_rows)
        return {
            "backend": "data-hub",
            "read_only": True,
            "dh_picker_filter_active": dh_filter_active,
            "config": {
                "bom_profile": "data_hub",
                "default_import_mode": "data_hub",
                "code_system_mode": "data_hub",
            },
            "versions": [aggregate] if aggregate["version_id"] else [],
            "product_versions": product_versions,
            "product_version_options_by_code": product_version_options_by_code(
                product_versions,
                case_id=case_id,
                trust_server_filter=dh_filter_active,
            ),
            "bom_shallow_only_codes": bom_shallow_only_codes(
                product_versions,
                case_id=case_id,
                trust_server_filter=dh_filter_active,
            ),
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

    def _fetch_product_results(
        self, client_id: str, product_codes: list[str], *, case_id: str = ""
    ) -> list[dict]:
        if not product_codes:
            return []
        if len(product_codes) == 1:
            return [self._build_product_result(client_id, product_codes[0], case_id=case_id)]
        max_workers = min(BOM_FETCH_MAX_WORKERS, len(product_codes))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # A fresh copy_context() per task: a Context object cannot be run
            # by more than one thread concurrently, so each worker gets its own
            # snapshot of the calling thread's contextvars (incl. the DH token).
            futures = [
                executor.submit(
                    copy_context().run,
                    self._build_product_result,
                    client_id,
                    product_code,
                    case_id,
                )
                for product_code in product_codes
            ]
            return [future.result() for future in futures]

    def _try_batch_results(
        self, client_id: str, product_codes: list[str], *, case_id: str = ""
    ) -> list[dict] | None:
        """One batch round-trip -> per-product results, or None to fall back.

        Returns None when the backend lacks the batch endpoint (no adapter,
        or a memoized/observed 404) so the caller uses the per-product
        parallel fetch. On success the per-product result shape matches
        `_build_product_result`.
        """
        if not product_codes:
            return []
        if not hasattr(self.data_hub, "list_bom_artifacts_batch"):
            return None
        identity = data_hub_cache_identity(self.data_hub)
        if _DATA_HUB_BOM_BATCH_SUPPORTED.get(identity) is False:
            return None
        try:
            envelope = self.data_hub.list_bom_artifacts_batch(
                client_id,
                product_codes,
                intents=PICKER_INTENTS,
                lifecycle="active",
                shape="flat",
                depth="full",
                latest_per_variant=True,
                case_id=case_id,
                include_rows=True,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                _DATA_HUB_BOM_BATCH_SUPPORTED[identity] = False
                return None
            raise
        _DATA_HUB_BOM_BATCH_SUPPORTED[identity] = True
        results = envelope.get("results") or {}
        out: list[dict] = []
        for product_code in product_codes:
            product_envelope = results.get(product_code) or {}
            items = product_envelope.get("items") or []
            picker_filter_applied = product_envelope.get("filter_applied") is not None
            if items:
                # Match product_artifact_payloads ordering (artifact_no DESC)
                # so the "current" version selection doesn't depend on the
                # order Data Hub returned the items in.
                ordered = sorted(items, key=lambda it: int(it.get("artifact_no") or 0), reverse=True)
                out.append(
                    self._assemble_from_payloads(
                        product_code,
                        [batch_item_payload(item) for item in ordered],
                        picker_filter_applied,
                    )
                )
            else:
                out.append(
                    {
                        "product_versions": [],
                        "latest_rows": [],
                        "variant_conflicts": [],
                        "picker_filter_applied": picker_filter_applied,
                    }
                )
        return out

    def _assemble_from_payloads(
        self, product_code: str, artifact_payloads: list[dict], picker_filter_applied: bool
    ) -> dict:
        """Build a per-product result from a list of artifact payloads.

        Shared by the per-product (`product_artifact_payloads`) and batch
        paths, so the two cannot drift. `variant_conflicts` is always empty
        here — multiple active artifacts surface as multiple versions, not a
        conflict (the conflict path only exists for the get_bom_latest 409
        fallback below).
        """
        product_versions: list[dict] = []
        latest_rows: list[dict] = []
        current_payload = next(
            (
                payload
                for payload in artifact_payloads
                if (payload.get("artifact") or {}).get("flatten_status") != "non_flattened"
                and payload.get("rows")
            ),
            artifact_payloads[0],
        )
        current_artifact_id = current_payload["artifact"].get("artifact_id", "")
        for payload in artifact_payloads:
            version = normalize_hub_artifact(payload.get("artifact") or {}, product_code)
            rows = [
                normalize_hub_row(row, version)
                for row in payload.get("rows", [])
                if isinstance(row, dict)
            ]
            version["status"] = (
                "current"
                if version.get("product_artifact_id") == current_artifact_id and version.get("flatten_status") != "non_flattened"
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
        return {
            "product_versions": product_versions,
            "latest_rows": latest_rows,
            "variant_conflicts": [],
            "picker_filter_applied": picker_filter_applied,
        }

    def _build_product_result(self, client_id: str, product_code: str, case_id: str = "") -> dict:
        product_versions: list[dict] = []
        latest_rows: list[dict] = []
        variant_conflicts: list[dict] = []

        artifact_payloads, picker_filter_applied = self.product_artifact_payloads(
            client_id, product_code, case_id=case_id
        )
        if artifact_payloads:
            return self._assemble_from_payloads(product_code, artifact_payloads, picker_filter_applied)

        try:
            payload = self.data_hub.get_bom_latest(client_id, product_code)
        except DataHubBomVariantConflict as exc:
            variant_conflicts.append({"product_code": product_code, "variants": exc.variants})
            product_versions.extend(artifact_from_variant(product_code, variant) for variant in exc.variants)
            return {
                "product_versions": product_versions,
                "latest_rows": latest_rows,
                "variant_conflicts": variant_conflicts,
                "picker_filter_applied": picker_filter_applied,
            }
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return {
                    "product_versions": product_versions,
                    "latest_rows": latest_rows,
                    "variant_conflicts": variant_conflicts,
                    "picker_filter_applied": picker_filter_applied,
                }
            raise

        version = normalize_hub_artifact(payload.get("artifact") or {}, product_code)
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
        return {
            "product_versions": product_versions,
            "latest_rows": latest_rows,
            "variant_conflicts": variant_conflicts,
            "picker_filter_applied": picker_filter_applied,
        }

    def product_artifact_payloads(
        self,
        client_id: str,
        product_code: str,
        *,
        case_id: str = "",
    ) -> tuple[list[dict], bool]:
        """Returns (payloads, picker_filter_applied).

        `picker_filter_applied` is True when DH responded to the
        picker-filter contract (`filter_applied` echo present). Callers
        use it to skip duplicate client-side filtering.
        """
        if not hasattr(self.data_hub, "get_bom_artifact"):
            return [], False
        has_filtered = hasattr(self.data_hub, "list_bom_artifacts_filtered")
        has_legacy = hasattr(self.data_hub, "list_bom_artifacts")
        if not (has_filtered or has_legacy):
            return [], False
        picker_filter_applied = False
        try:
            if case_id and has_filtered:
                envelope = self.data_hub.list_bom_artifacts_filtered(
                    client_id,
                    product_code,
                    intents=PICKER_INTENTS,
                    lifecycle="active",
                    shape="flat",
                    depth="full",
                    latest_per_variant=True,
                    case_id=case_id,
                )
                summaries = envelope.get("items", [])
                picker_filter_applied = envelope.get("filter_applied") is not None
            else:
                summaries = self.data_hub.list_bom_artifacts(client_id, product_code)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return [], False
            raise
        if len(summaries) <= 1:
            return [], picker_filter_applied
        payloads = []
        for summary in sorted(summaries, key=lambda row: int(row.get("artifact_no") or 0), reverse=True):
            artifact_id = summary.get("artifact_id", "")
            if not artifact_id:
                continue
            try:
                payload = self.data_hub.get_bom_artifact(client_id, product_code, artifact_id)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    continue
                raise
            payloads.append({
                **payload,
                "artifact": {
                    **summary,
                    **(payload.get("artifact") or {}),
                    "artifact_id": artifact_id,
                    "product_code": product_code,
                },
            })
        return payloads, picker_filter_applied

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


def data_hub_bom_workspace_cache_key(
    data_hub: DataHubClient,
    client_id: str,
    product_codes: list[str] | None,
    case_id: str = "",
) -> tuple[str, str, str, tuple[str, ...], str]:
    return (
        data_hub_cache_identity(data_hub),
        client_id,
        current_data_hub_token(),
        tuple(sorted(normalized_product_code_filter(product_codes))),
        case_id or "",
    )


def data_hub_cache_identity(data_hub: DataHubClient) -> str:
    base_url = getattr(data_hub, "base_url", "")
    token = getattr(data_hub, "token", "")
    if base_url or token:
        return f"{base_url}|{token}"
    return ""


def normalized_product_code_filter(product_codes: list[str] | None) -> set[str]:
    return {str(code or "").strip() for code in product_codes or [] if str(code or "").strip()}


def batch_item_payload(item: dict) -> dict:
    """Reshape a batch `results[pc].items[*]` row (artifact summary fields at
    top level + rows/unresolved/decisions) into the `{artifact, rows,
    unresolved, decisions}` payload shape the per-product path produces."""
    artifact = {key: value for key, value in item.items() if key not in ("rows", "unresolved", "decisions")}
    return {
        "artifact": artifact,
        "rows": item.get("rows") or [],
        "unresolved": item.get("unresolved") or [],
        "decisions": item.get("decisions") or [],
    }


def clear_data_hub_bom_workspace_cache() -> None:
    _DATA_HUB_BOM_WORKSPACE_CACHE.clear()
    _DATA_HUB_BOM_BATCH_SUPPORTED.clear()


def product_code_from_row(row: dict) -> str:
    return str(
        row.get("product_code")
        or row.get("material_code")
        or row.get("customs_code")
        or row.get("internal_code")
        or ""
    ).strip()


def normalize_hub_artifact(artifact: dict, product_code: str) -> dict:
    artifact_id = str(artifact.get("artifact_id", ""))
    artifact_no = int(artifact.get("artifact_no") or 0)
    return {
        **artifact,
        "product_code": artifact.get("product_code") or product_code,
        "product_artifact_id": artifact_id,
        "product_artifact_no": artifact_no,
        "product_version_id": artifact_id,
        "product_version_no": artifact_no,
        "version_hash": artifact.get("normalized_hash", ""),
        "row_count": int(artifact.get("row_count") or 0),
        "status": "current" if artifact.get("flatten_status") != "non_flattened" else "non_flattened",
        "diff_summary": {},
        "source_upload_id": artifact.get("source_upload_id") or artifact.get("source_channel", "data-hub"),
    }


def artifact_from_variant(product_code: str, variant: dict) -> dict:
    return {
        **variant,
        "product_code": product_code,
        "product_artifact_id": variant.get("artifact_id", ""),
        "product_artifact_no": int(variant.get("artifact_no") or 0),
        "product_version_id": variant.get("artifact_id", ""),
        "product_version_no": int(variant.get("artifact_no") or 0),
        "version_hash": "",
        "row_count": int(variant.get("row_count") or 0),
        "status": "variant_conflict",
        "diff_summary": {},
        "source_upload_id": "data-hub",
        "rows": [],
    }


def normalize_hub_row(row: dict, artifact: dict) -> dict:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    product_code = artifact.get("product_code", "")
    qty = row.get("qty_per_unit", row.get("qty_per", ""))
    return {
        **row,
        "product_code": product_code,
        "bom_code": row.get("bom_code") or artifact.get("bom_code") or product_code,
        "bom_variant_id": row.get("bom_variant_id") or artifact.get("bom_variant_id") or "default",
        "material_code": row.get("material_code", ""),
        "material_name": payload.get("material_name") or payload.get("description") or "",
        "hs_code": row.get("hs_code") or payload.get("hs_code") or payload.get("material_hs_code") or "",
        "qty_per": qty,
        "uom": row.get("uom", ""),
        "scrap_rate": payload.get("scrap_rate", ""),
        "source": artifact.get("source_bom_kind", "data_hub"),
        "row_class": artifact.get("flatten_status", "published"),
        "product_artifact_id": artifact.get("product_artifact_id", ""),
        "product_artifact_no": artifact.get("product_artifact_no", 0),
        "product_version_id": artifact.get("product_artifact_id", ""),
        "product_version_no": artifact.get("product_artifact_no", 0),
        "flatten_strategy": artifact.get("flatten_strategy", ""),
    }


def composition_entry(product_version: dict) -> dict:
    return {
        "product_code": product_version["product_code"],
        "product_artifact_id": product_version["product_artifact_id"],
        "product_artifact_no": product_version["product_artifact_no"],
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
            "product_artifact_id": row["product_artifact_id"],
            "product_artifact_no": row["product_artifact_no"],
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


def product_version_options_by_code(
    product_versions: list[dict],
    *,
    case_id: str = "",
    trust_server_filter: bool = False,
) -> dict[str, list[dict]]:
    """Group versions per product_code, applying the picker filter.

    When `trust_server_filter` is True the rows already came through
    Data Hub's `/bom/artifacts` filter contract and pass through as-is.
    Otherwise we apply an equivalent predicate locally so the picker
    behaves the same against legacy DH builds and the LocalBomService.
    """
    output: dict[str, list[dict]] = {}
    for version in product_versions:
        if version.get("status") == "variant_conflict":
            continue
        if version.get("flatten_status") == "non_flattened":
            continue
        if trust_server_filter:
            # DH applied lifecycle/shape/case. It may NOT have applied depth (a
            # pre-`depth` build echoes `filter_applied` but ignores the param), so
            # still drop shallow client-side — a no-op when DH ran depth=full.
            if _version_is_shallow(version):
                continue
        elif not _picker_predicate_keeps(version, case_id, depth="full"):
            continue
        output.setdefault(version["product_code"], []).append(version)
    return output


def bom_shallow_only_codes(
    product_versions: list[dict],
    *,
    case_id: str = "",
    trust_server_filter: bool = False,
) -> list[str]:
    """Product codes whose ONLY pickable flat artifact(s) are shallow.

    These products have a flat BOM but no FULL-depth one, so the depth=full
    picker offers nothing for them — distinct from "no BOM at all". The picker
    surfaces a specific "chỉ có BOM rút gọn" state for these.
    """
    kept: set[str] = set()
    full: set[str] = set()
    for version in product_versions:
        if version.get("status") == "variant_conflict":
            continue
        if version.get("flatten_status") == "non_flattened":
            continue
        if not trust_server_filter and not _picker_predicate_keeps(version, case_id, depth="any"):
            continue
        code = version["product_code"]
        kept.add(code)
        if not _version_is_shallow(version):
            full.add(code)
    return sorted(kept - full)


def _picker_predicate_keeps(version: dict, case_id: str, *, depth: str = "any") -> bool:
    """Mirror of Data Hub's picker filter (`lifecycle=active`, `shape=flat`,
    case-scoped `modified_for_case`, and `depth`). Used when DH didn't echo
    `filter_applied` — keeps CO behaving correctly against legacy DH and
    LocalBomService. `depth="full"` additionally drops shallow flattens.
    """
    if version.get("tombstoned_at"):
        return False
    status = str(version.get("status") or "").lower()
    if status in {"draft", "superseded"}:
        return False
    if str(version.get("flatten_status") or "") not in {"flattened", "not_applicable"}:
        return False
    if depth == "full" and _version_is_shallow(version):
        return False
    intent = str(version.get("intent") or "")
    if intent == "modified_for_case":
        if not case_id:
            return False
        context = version.get("context") if isinstance(version.get("context"), dict) else {}
        if str(context.get("case_id") or "") != case_id:
            return False
    return True
