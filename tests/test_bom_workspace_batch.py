from __future__ import annotations

import httpx
import pytest

from app.bom_service import (
    DataHubBomService,
    PICKER_INTENTS,
    clear_data_hub_bom_workspace_cache,
)
from app.data_hub_client import DataHubClient, HUB_BOM_ARTIFACTS_BATCH_PATH


@pytest.fixture(autouse=True)
def _clear_caches():
    clear_data_hub_bom_workspace_cache()
    yield
    clear_data_hub_bom_workspace_cache()


def _artifact(product_code, no, *, variant="default", strategy="manual_flat_as_provided", material="NVL"):
    return {
        "artifact_id": f"{product_code}-bv{no}",
        "artifact_no": no,
        "product_code": product_code,
        "client_id": "johnson-vn",
        "status": "published",
        "tombstoned_at": None,
        "intent": "staff_edit",
        "flatten_status": "flattened",
        "flatten_strategy": strategy,
        "bom_variant_id": variant,
        "bom_code": product_code,
        "row_count": 1,
        "normalized_hash": f"h-{product_code}-{no}",
        "published_at": f"2026-05-2{no}T00:00:00Z",
        "context": {"case_id": None},
        "rows": [{"material_code": f"{material}-{product_code}", "qty_per_unit": "1.5", "uom": "PCS", "payload": {}}],
        "unresolved": [],
        "decisions": [],
    }


# Shared fixture: artifacts per product. Both the per-product endpoints AND
# the batch endpoint are served from THIS dict, so the only thing under test
# is whether CO's two code paths consume the same data into the same workspace.
ARTIFACTS = {
    "TP-1": [_artifact("TP-1", 1, strategy="leaf"), _artifact("TP-1", 2, strategy="exploded")],  # multi
    "TP-2": [_artifact("TP-2", 5)],   # single -> per-product path uses get_bom_latest
    "TP-3": [],                       # none -> missing
}
FILTER_APPLIED = {
    "lifecycle": "active", "shape": "flat",
    "intents": sorted(PICKER_INTENTS), "latest_per_variant": True, "case_id": "co-case-x",
}


def _summary(artifact):
    return {k: v for k, v in artifact.items() if k not in ("rows", "unresolved", "decisions")}


def _payload(artifact):
    return {
        "artifact": _summary(artifact),
        "rows": artifact["rows"],
        "unresolved": artifact["unresolved"],
        "decisions": artifact["decisions"],
    }


class PerProductFakeDH:
    """Serves only the per-product picker endpoints (no batch method, so CO
    falls back). Records which surface was hit."""

    def __init__(self):
        self.calls = {"batch": 0, "filtered": 0, "get_artifact": 0, "get_latest": 0}

    def list_bom_products(self, _client_id):
        return [{"product_code": c} for c in ARTIFACTS]

    def list_bom_artifacts_filtered(self, _client_id, product_code, **_kw):
        self.calls["filtered"] += 1
        return {"items": [_summary(a) for a in ARTIFACTS.get(product_code, [])], "filter_applied": FILTER_APPLIED}

    def get_bom_artifact(self, _client_id, product_code, artifact_id):
        self.calls["get_artifact"] += 1
        art = next(a for a in ARTIFACTS[product_code] if a["artifact_id"] == artifact_id)
        return _payload(art)

    def get_bom_latest(self, _client_id, product_code):
        self.calls["get_latest"] += 1
        arts = ARTIFACTS.get(product_code, [])
        if not arts:
            raise httpx.HTTPStatusError(
                "nf", request=httpx.Request("GET", "https://h"), response=httpx.Response(404)
            )
        # newest artifact_no wins (mirrors /latest semantics)
        return _payload(max(arts, key=lambda a: a["artifact_no"]))


class BatchFakeDH(PerProductFakeDH):
    """Adds the batch endpoint on top of the per-product surface, from the
    same fixture — so the two CO paths can be compared for parity."""

    def list_bom_artifacts_batch(self, _client_id, product_codes, **_kw):
        self.calls["batch"] += 1
        results = {}
        missing = []
        for pc in product_codes:
            arts = ARTIFACTS.get(pc, [])
            if arts:
                results[pc] = {"items": [dict(a) for a in arts], "filter_applied": FILTER_APPLIED}
            else:
                missing.append(pc)
        return {"results": results, "missing": missing}


CODES = ["TP-1", "TP-2", "TP-3"]


def test_workspace_uses_batch_when_available_and_skips_per_product_calls():
    dh = BatchFakeDH()
    ws = DataHubBomService(dh).workspace({"id": "johnson-vn"}, product_codes=CODES, case_id="co-case-x")
    assert dh.calls["batch"] == 1
    # batch path must NOT touch the per-product endpoints
    assert dh.calls["filtered"] == 0 and dh.calls["get_artifact"] == 0 and dh.calls["get_latest"] == 0
    assert {v["product_code"] for v in ws["product_versions"]} == {"TP-1", "TP-2"}
    assert ws["dh_picker_filter_active"] is True


def test_batch_path_workspace_matches_per_product_path_byte_for_byte():
    """The core parity guarantee: same data, both CO code paths -> same workspace."""
    import json

    batch_ws = DataHubBomService(BatchFakeDH()).workspace(
        {"id": "johnson-vn"}, product_codes=CODES, case_id="co-case-x"
    )
    clear_data_hub_bom_workspace_cache()
    fallback_ws = DataHubBomService(PerProductFakeDH()).workspace(
        {"id": "johnson-vn"}, product_codes=CODES, case_id="co-case-x"
    )
    assert json.dumps(batch_ws, sort_keys=True, default=str) == json.dumps(fallback_ws, sort_keys=True, default=str)


def test_falls_back_to_per_product_when_batch_404_and_memoizes():
    class NotFoundBatch(PerProductFakeDH):
        def list_bom_artifacts_batch(self, _client_id, product_codes, **_kw):
            self.calls["batch"] += 1
            raise httpx.HTTPStatusError(
                "nf", request=httpx.Request("POST", "https://h"), response=httpx.Response(404)
            )

    dh = NotFoundBatch()
    svc = DataHubBomService(dh)
    ws1 = svc.workspace({"id": "johnson-vn"}, product_codes=CODES, case_id="co-case-x")
    assert dh.calls["batch"] == 1
    # fell back to the per-product path
    assert dh.calls["filtered"] > 0
    assert {v["product_code"] for v in ws1["product_versions"]} == {"TP-1", "TP-2"}

    # Clear only the workspace cache, keep the batch-support memo: the next
    # build must NOT re-probe the now-known-404 endpoint.
    from app.bom_service import _DATA_HUB_BOM_WORKSPACE_CACHE
    _DATA_HUB_BOM_WORKSPACE_CACHE.clear()
    svc.workspace({"id": "johnson-vn"}, product_codes=CODES, case_id="co-case-x")
    assert dh.calls["batch"] == 1  # not re-probed


def test_adapter_posts_batch_body_and_merges_paginated_results():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content)
        seen.append(body)
        if request.url.path != "/v1/hub/products/bom/artifacts:batch":
            return httpx.Response(404)
        if not body.get("cursor"):
            return httpx.Response(200, json={
                "results": {"TP-1": {"items": [_summary(ARTIFACTS["TP-1"][0])], "filter_applied": FILTER_APPLIED}},
                "missing": ["TP-3"],
                "next_cursor": "pc:TP-1",
            })
        return httpx.Response(200, json={
            "results": {"TP-2": {"items": [_summary(ARTIFACTS["TP-2"][0])], "filter_applied": FILTER_APPLIED}},
            "missing": [],
            "next_cursor": None,
        })

    client = DataHubClient(base_url="https://hub.test", token="tok", transport=httpx.MockTransport(handler))
    envelope = client.list_bom_artifacts_batch(
        "johnson-vn", ["TP-2", "TP-1", "TP-1", "", "TP-3"],
        intents=PICKER_INTENTS, case_id="co-case-x",
    )
    # request body: deduped (client passes through; server dedupes too) + filters
    first = seen[0]
    assert first["client_id"] == "johnson-vn"
    assert first["lifecycle"] == "active" and first["shape"] == "flat"
    assert first["latest_per_variant"] is True and first["include_rows"] is True
    assert first["case_id"] == "co-case-x"
    assert set(first["intents"]) == set(PICKER_INTENTS)
    assert "" not in first["product_codes"]
    # paginated results merged across both pages
    assert set(envelope["results"]) == {"TP-1", "TP-2"}
    assert envelope["missing"] == ["TP-3"]
    assert len(seen) == 2  # followed next_cursor once
