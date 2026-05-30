"""Lightweight non-origin case context: skip the 65k-row materials/BCCT pull.

Guards the perf fix for the ~21s case detail load. Non-origin steps
(shipment/documents/exports/review) only need source_summary + invoice_matches,
so `skip_heavy_context=True` must avoid paginating /v1/hub/materials and
/v1/hub/bcct. Export-declaration cases still need the full BCCT pull to match,
so they fall through to the heavy path even when skip_heavy_context is set.

See .ai/sessions (2026-05-30 case-detail perf) and STATUS next-step #1.
"""
from __future__ import annotations

import httpx

from app.data_hub_client import DataHubClient, DataHubPortfolioService

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


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/v1/hub/dncxs/acme/source-summary":
        return httpx.Response(200, json=SOURCE_SUMMARY_PAYLOAD)
    if path == "/v1/hub/bcct/invoice-matches":
        return httpx.Response(
            200,
            json={"items": [{"declaration_no": "EX-1", "line_no": 1, "item_code": "MAT-1"}]},
        )
    if path == "/v1/hub/materials":
        return httpx.Response(200, json={"items": [{"material_code": "MAT-1", "category": "nvl"}]})
    if path == "/v1/hub/bcct":
        return httpx.Response(
            200,
            json={"items": [{"direction": "export", "declaration_no": "EX-1", "line_no": 1, "item_code": "MAT-1"}]},
        )
    return httpx.Response(200, json={"items": []})


def test_skip_heavy_context_avoids_materials_and_bcct_pagination():
    service, seen = _service(_handler)
    context = service.co_case_source_context(
        {"id": "acme"}, {"shipment": {"invoice_no": "INV-1"}}, skip_heavy_context=True
    )

    # Lightweight: invoice matches come from the dedicated endpoint...
    assert [row["declaration_no"] for row in context["invoice_matches"]] == ["EX-1"]
    assert "/v1/hub/bcct/invoice-matches" in seen
    # ...and the expensive full catalogs are never paginated.
    assert "/v1/hub/materials" not in seen
    assert "/v1/hub/bcct" not in seen
    assert context["material_rows"] == []
    assert context["stock_rows"] == []


def test_skip_heavy_context_still_paginates_for_export_declaration_cases():
    """Export-declaration matching needs the full BCCT pull — no shortcut."""
    service, seen = _service(_handler)
    context = service.co_case_source_context(
        {"id": "acme"},
        {"shipment": {"export_declaration_nos": ["EX-1"]}},
        skip_heavy_context=True,
    )

    # Falls through to the heavy path: BCCT is paginated to compute matches.
    assert "/v1/hub/bcct" in seen
    assert context["material_rows"] != [] or context["stock_rows"] != [] or context["invoice_matches"] is not None


def test_heavy_path_default_paginates_materials_and_bcct():
    """Default (origin step) keeps fetching the full catalogs."""
    service, seen = _service(_handler)
    service.co_case_source_context({"id": "acme"}, {"shipment": {"invoice_no": "INV-1"}})

    assert "/v1/hub/materials" in seen
    assert "/v1/hub/bcct" in seen
