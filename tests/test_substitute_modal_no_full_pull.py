"""Substitute modal must NOT trigger the full ~104s BCCT pull.

`co_case_origin_sheet_substitute_candidates` only needs the material catalog
(material_rows) for its heuristic-fallback and search candidates. It used to get
that via `co_case_source_context_cached`, which paginates the full list_materials
+ list_bcct catalogs (~125s cold for Johnson → Cloudflare 524, and it blocks the
event loop). It now uses `co_case_material_catalog_cached` (materials-only, cached
per client). These tests guard that the full BCCT pull never runs on that path.
"""
from __future__ import annotations

import asyncio

import httpx

import app.routers.co_case as co_case
import app.web.co_case_context as ctx
from app.data_hub_client import DataHubClient, DataHubPortfolioService


class StubTransport(httpx.BaseTransport):
    def __init__(self, handler):
        self._handler = handler

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._handler(request)


def _service(handler) -> tuple[DataHubPortfolioService, list[str]]:
    seen: list[str] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return handler(request)

    client = DataHubClient(
        base_url="https://hub.test", token="t", transport=StubTransport(wrapped)
    )
    return DataHubPortfolioService(client), seen


SOURCE_SUMMARY_PAYLOAD = {
    "material_catalog": {"published_row_count": 1, "latest_version": {"version_no": 3}},
    "product_catalog": {"published_row_count": 1, "latest_version": {"version_no": 2}},
    "bcct": {"published_row_count": 1, "latest_version": {"version_no": 5}},
    "co_stock_row_count": 7,
    "client_config": {
        "preset_key": "data_hub",
        "eligible_import_declaration_types": ["A11", "A12"],
        "relevant_export_declaration_types": ["B11", "E62"],
    },
}


def _full_handler(request: httpx.Request) -> httpx.Response:
    """Serves every endpoint the heavy co_case_source_context path calls."""
    p = request.url.path
    if p == "/v1/hub/dncxs/acme/source-summary":
        return httpx.Response(200, json=SOURCE_SUMMARY_PAYLOAD)
    if p == "/v1/hub/materials":
        return httpx.Response(200, json={"items": [
            {"material_code": "NVL-1", "category": "nvl", "name": "A", "hs_code": "8501"},
            {"material_code": "NVL-2", "category": "nvl", "name": "B", "hs_code": "8502"},
            {"material_code": "TP-1", "category": "tp", "name": "C", "hs_code": "8501"},
        ]})
    if p == "/v1/hub/bcct":
        return httpx.Response(200, json={"items": [
            {"direction": "export", "declaration_no": "D1", "line_no": 1, "item_code": "NVL-1"},
        ]})
    if p == "/v1/hub/bcct/invoice-matches":
        return httpx.Response(200, json={"items": []})
    return httpx.Response(200, json={"items": []})


def test_material_catalog_equals_heavy_path_material_rows():
    """Core correctness invariant: material_catalog() returns byte-identical
    material_rows to the full co_case_source_context heavy pull. The substitute
    modal only ever read material_rows from that pull (BCCT/stock were fetched and
    discarded at the call sites), so its candidates/catalog are unchanged — only
    the ~104s BCCT pagination is gone. Guards against the two paths drifting."""
    service, _ = _service(_full_handler)
    catalog = service.material_catalog({"id": "acme"})
    heavy = service.co_case_source_context(
        {"id": "acme"}, {"shipment": {"invoice_no": "INV-1"}}
    )["material_rows"]

    assert catalog == heavy
    assert [r.get("material_code") for r in catalog] == ["NVL-1", "NVL-2"]  # 'tp' dropped both sides


def test_material_catalog_fetches_materials_only_not_bcct():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/hub/materials":
            return httpx.Response(200, json={"items": [
                {"material_code": "NVL-1", "category": "nvl"},
                {"material_code": "TP-1", "category": "tp"},   # finished product — dropped
            ]})
        if request.url.path == "/v1/hub/bcct":
            return httpx.Response(200, json={"items": [{"_full_pull": "must-not-be-called"}]})
        return httpx.Response(200, json={"items": []})

    service, seen = _service(handler)
    rows = service.material_catalog({"id": "acme"})

    assert "/v1/hub/materials" in seen
    assert "/v1/hub/bcct" not in seen            # the ~104s killer never runs
    assert len(rows) == 1                          # the 'tp' row is filtered out
    assert all(r.get("category") != "tp" for r in rows)


def test_co_case_material_catalog_cached_uses_catalog_and_caches(monkeypatch):
    ctx._CO_MATERIAL_CATALOG_CACHE.clear()
    calls = {"catalog": 0, "heavy": 0}

    class _PF:
        def material_catalog(self, client):
            calls["catalog"] += 1
            return [{"material_code": "NVL-1", "category": "nvl"}]

        def co_case_source_context(self, *a, **k):   # the heavy full pull
            calls["heavy"] += 1
            raise AssertionError("substitute catalog must not run the heavy source context")

    monkeypatch.setattr(ctx, "portfolio_service", _PF())

    client, case = {"id": "acme"}, {"shipment": {}}
    first = ctx.co_case_material_catalog_cached(client, case)
    second = ctx.co_case_material_catalog_cached(client, case)

    assert [r["material_code"] for r in first] == ["NVL-1"]
    assert second == first
    assert calls["catalog"] == 1     # second call served from cache
    assert calls["heavy"] == 0       # never the full BCCT pull


def _drive_substitute_heuristic(monkeypatch) -> dict:
    """Drive the material_code heuristic-fallback path and report which catalog
    accessor the endpoint used."""
    calls = {"heavy": 0, "narrow": 0}

    def heavy_spy(client, case):
        calls["heavy"] += 1
        return {"material_rows": [], "stock_rows": []}

    def narrow_spy(client, case):
        calls["narrow"] += 1
        return [{"material_code": "NVL-2", "category": "nvl", "name": "x", "hs_code": "8501"}]

    monkeypatch.setattr(co_case, "resolve_client", lambda cid: {"id": cid})
    monkeypatch.setattr(
        co_case, "persisted_origin_case",
        lambda client, case_id: {"products": [{"code": "P1"}], "origin_sheet_states": {}},
    )
    # Data Hub has no precomputed substitute → heuristic fallback (the path that
    # needs the material catalog).
    monkeypatch.setattr(
        co_case.portfolio_service, "list_material_substitutes",
        lambda *a, **k: ([], "data_hub"),
    )
    monkeypatch.setattr(
        co_case, "compute_substitute_heuristic_candidates",
        lambda *a, **k: ([], "8501"),
    )
    monkeypatch.setattr(co_case.substitution_history, "get_substitution_history", lambda client: {})
    monkeypatch.setattr(co_case, "co_case_source_context_cached", heavy_spy)
    monkeypatch.setattr(co_case, "co_case_material_catalog_cached", narrow_spy)

    resp = asyncio.run(
        co_case.co_case_origin_sheet_substitute_candidates(
            "johnson-vn", "case-1", product_code="P1", material_code="NVL-1"
        )
    )
    assert resp.status_code == 200
    return calls


def test_substitute_modal_heuristic_uses_narrow_catalog_not_full_pull(monkeypatch):
    calls = _drive_substitute_heuristic(monkeypatch)
    assert calls["heavy"] == 0, "substitute modal must not call the heavy full-BCCT source context"
    assert calls["narrow"] >= 1
