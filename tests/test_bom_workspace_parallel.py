from __future__ import annotations

import threading

import httpx
import pytest

from app.bom_service import DataHubBomService
from app.data_hub_client import (
    DataHubBomVariantConflict,
    current_data_hub_token,
    set_current_data_hub_token,
    reset_current_data_hub_token,
)


def _artifact_row(material_code: str = "NVL-1") -> dict:
    return {"material_code": material_code, "qty_per_unit": 1, "uom": "PCS", "payload": {}}


def _latest_payload(product_code: str, artifact_no: int = 1) -> dict:
    return {
        "artifact": {
            "artifact_id": f"{product_code}-bv{artifact_no}",
            "product_code": product_code,
            "artifact_no": artifact_no,
            "row_count": 1,
            "flatten_status": "flattened",
        },
        "rows": [_artifact_row(f"NVL-{product_code}")],
    }


class _SingleArtifactDH:
    """Every product resolves through the get_bom_latest fallback (<=1 summary)."""

    def __init__(self, product_codes: list[str], *, on_fetch=None):
        self._product_codes = product_codes
        self._on_fetch = on_fetch

    def list_bom_products(self, _client_id):
        return [{"product_code": code} for code in self._product_codes]

    def list_bom_artifacts_filtered(self, _client_id, _product_code, **_kw):
        return {"items": [], "filter_applied": {"case_id": "c"}}

    def list_bom_artifacts(self, _client_id, _product_code):
        return []

    def get_bom_artifact(self, *_a, **_k):  # pragma: no cover - not reached
        raise AssertionError("single-artifact products use get_bom_latest")

    def get_bom_latest(self, _client_id, product_code):
        if self._on_fetch is not None:
            self._on_fetch(product_code)
        return _latest_payload(product_code)


def test_build_workspace_fetches_products_concurrently():
    """With N independent products the per-product fetches must overlap.

    A barrier of width N only releases when all N worker threads arrive at
    once. If _build_workspace were sequential the barrier would never fill and
    BrokenBarrierError (via timeout) would surface.
    """
    product_codes = ["TP-1", "TP-2", "TP-3", "TP-4"]
    barrier = threading.Barrier(len(product_codes), timeout=5)

    def on_fetch(_product_code):
        barrier.wait()

    service = DataHubBomService(_SingleArtifactDH(product_codes, on_fetch=on_fetch))
    workspace = service._build_workspace({"id": "growatt-vn"}, product_codes=product_codes)

    assert {v["product_code"] for v in workspace["product_versions"]} == set(product_codes)


def test_build_workspace_propagates_data_hub_token_to_worker_threads():
    """The DH bearer token lives in a contextvar that worker threads do not
    inherit automatically. Each parallel fetch must observe the token that was
    set in the calling thread, or every fetch would 401."""
    product_codes = ["TP-1", "TP-2", "TP-3"]
    seen: dict[str, str] = {}
    lock = threading.Lock()

    def on_fetch(product_code):
        with lock:
            seen[product_code] = current_data_hub_token()

    token = set_current_data_hub_token("worker-token-xyz")
    try:
        service = DataHubBomService(_SingleArtifactDH(product_codes, on_fetch=on_fetch))
        service._build_workspace({"id": "growatt-vn"}, product_codes=product_codes)
    finally:
        reset_current_data_hub_token(token)

    assert seen == {code: "worker-token-xyz" for code in product_codes}


def test_build_workspace_output_is_deterministic_regardless_of_fetch_order():
    """Completion order must not affect the assembled workspace: product
    versions and latest rows are sorted, variant conflicts surfaced, 404s
    skipped — identical to the sequential result."""

    release = {code: threading.Event() for code in ("TP-1", "TP-2", "TP-3", "TP-404")}

    class FakeDH:
        def list_bom_products(self, _client_id):
            return [{"product_code": c} for c in ("TP-1", "TP-2", "TP-3", "TP-404")]

        def list_bom_artifacts_filtered(self, _client_id, product_code, **_kw):
            if product_code == "TP-1":
                # two artifacts -> payloads path
                return {
                    "items": [
                        {
                            "artifact_id": "TP-1-bv1",
                            "artifact_no": 1,
                            "row_count": 1,
                            "flatten_status": "flattened",
                            "status": "published",
                            "intent": "staff_edit",
                            "tombstoned_at": None,
                        },
                        {
                            "artifact_id": "TP-1-bv2",
                            "artifact_no": 2,
                            "row_count": 1,
                            "flatten_status": "flattened",
                            "status": "published",
                            "intent": "staff_edit",
                            "tombstoned_at": None,
                        },
                    ],
                    "filter_applied": {"case_id": "c"},
                }
            return {"items": [], "filter_applied": {"case_id": "c"}}

        def get_bom_artifact(self, _client_id, product_code, artifact_id):
            return {
                "artifact": {
                    "artifact_id": artifact_id,
                    "product_code": product_code,
                    "artifact_no": int(artifact_id[-1]),
                    "row_count": 1,
                    "flatten_status": "flattened",
                },
                "rows": [_artifact_row(f"NVL-{artifact_id}")],
            }

        def get_bom_latest(self, _client_id, product_code):
            # Force completion order opposite to input order: TP-3 returns
            # immediately, TP-2 waits for TP-3 to finish first.
            if product_code == "TP-2":
                release["TP-3"].wait(timeout=5)
            if product_code == "TP-3":
                release["TP-3"].set()
            if product_code == "TP-404":
                raise httpx.HTTPStatusError(
                    "not found",
                    request=httpx.Request("GET", "https://hub.test"),
                    response=httpx.Response(404),
                )
            return _latest_payload(product_code)

    workspace = DataHubBomService(FakeDH()).workspace(
        {"id": "growatt-vn"},
        product_codes=["TP-1", "TP-2", "TP-3", "TP-404"],
        case_id="co-case-x",
    )

    # product_versions sorted by (product_code, version_no); TP-404 skipped
    assert [(v["product_code"], v["product_version_no"]) for v in workspace["product_versions"]] == [
        ("TP-1", 1),
        ("TP-1", 2),
        ("TP-2", 1),
        ("TP-3", 1),
    ]
    # latest_rows sorted by (product_code, material_code)
    codes = [r["product_code"] for r in workspace["latest_rows"]]
    assert codes == sorted(codes)
    assert "TP-404" not in {r["product_code"] for r in workspace["latest_rows"]}


def test_build_workspace_surfaces_variant_conflict_under_parallel_fetch():
    class FakeDH:
        def list_bom_products(self, _client_id):
            return [{"product_code": c} for c in ("TP-1", "TP-2")]

        def list_bom_artifacts_filtered(self, _client_id, _product_code, **_kw):
            return {"items": [], "filter_applied": {"case_id": "c"}}

        def get_bom_artifact(self, *_a, **_k):  # pragma: no cover
            raise AssertionError("unused")

        def get_bom_latest(self, _client_id, product_code):
            if product_code == "TP-2":
                raise DataHubBomVariantConflict(
                    product_code,
                    {"variants": [{"artifact_id": "v-a", "artifact_no": 1}, {"artifact_id": "v-b", "artifact_no": 2}]},
                )
            return _latest_payload(product_code)

    workspace = DataHubBomService(FakeDH()).workspace(
        {"id": "growatt-vn"}, product_codes=["TP-1", "TP-2"], case_id="co-case-x"
    )

    assert [c["product_code"] for c in workspace["variant_conflicts"]] == ["TP-2"]
    assert {v["product_code"] for v in workspace["product_versions"]} == {"TP-1", "TP-2"}
