"""Converged origin tab-load: eliminate the ~40s full BCCT pull.

The origin tab-load used to call the heavy co_case_source_context, whose
dominant cost is list_bcct(include_material_identity=true) paginating the
client's entire customs history (65k+ rows / ~40s for Johnson). Every consumer
has a narrow/snapshot replacement:

- stock_rows -> materialized co_stock snapshot (same source /calculate uses)
- invoice_matches (invoice case) -> invoice_matches endpoint + narrow by-codes
- invoice_matches (export-decl case) -> per-declaration list_bcct(declaration_no=)
- material_rows -> [] (unused at tab render; substitute modal self-fetches)

These tests guard that the narrow path never paginates the full /v1/hub/bcct
or /v1/hub/materials catalogs. Real-data parity (old heavy vs converged on
Johnson) lives in the Postgres-gated e2e test below.

Brief: .ai/features/2026-05-31-origin-narrow-bcct-fetch.md
"""
from __future__ import annotations

import httpx

from app.data_hub_client import DataHubClient, DataHubPortfolioService

CLIENT_CONFIG = {"bcct": {"relevant_export_declaration_types": ["B11", "E62"]}}


class StubTransport(httpx.BaseTransport):
    def __init__(self, handler):
        self._handler = handler

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._handler(request)


def _service(handler):
    seen: list[httpx.URL] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return handler(request)

    client = DataHubClient(
        base_url="https://hub.test", token="t", transport=StubTransport(wrapped)
    )
    return DataHubPortfolioService(client), seen


def _full_bcct_pulled(seen: list[httpx.URL]) -> bool:
    """A full catalog pull = GET /v1/hub/bcct with NO declaration_no filter
    (the narrow export-decl fetch shares the path but always carries one)."""
    return any(
        url.path == "/v1/hub/bcct" and "declaration_no" not in url.params
        for url in seen
    )


def _invoice_only_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/v1/hub/bcct/invoice-matches":
        return httpx.Response(200, json={"items": [
            {"declaration_no": "EX-1", "line_no": 1, "item_code": "MAT-1",
             "transaction_key": "TX-1"},
        ]})
    if path.endswith("/bcct/by-codes"):
        # Narrow export rows that supply the values enrichment fills in.
        return httpx.Response(200, json={"items": [
            {"direction": "export", "transaction_key": "TX-1", "declaration_no": "EX-1",
             "line_no": 1, "item_code": "MAT-1", "customs_value": "500", "currency": "USD"},
        ]})
    if path == "/v1/hub/bcct":
        return httpx.Response(200, json={"items": [{"_full_pull": "must-not-be-called"}]})
    if path == "/v1/hub/materials":
        return httpx.Response(200, json={"items": [{"_materials": "must-not-be-called"}]})
    return httpx.Response(200, json={"items": []})


def _export_decl_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/v1/hub/bcct" and request.url.params.get("declaration_no"):
        # Narrow, declaration-filtered fetch: only the requested declaration.
        return httpx.Response(200, json={"items": [
            {"direction": "export", "review_status": "reviewed", "declaration_type": "B11",
             "declaration_no": "EX-1", "line_no": 1, "item_code": "MAT-1",
             "invoice_ref": "INV-1", "transaction_key": "TX-1", "customs_value": "900"},
        ]})
    if path == "/v1/hub/bcct":
        return httpx.Response(200, json={"items": [{"_full_pull": "must-not-be-called"}]})
    if path == "/v1/hub/materials":
        return httpx.Response(200, json={"items": [{"_materials": "must-not-be-called"}]})
    return httpx.Response(200, json={"items": []})


def test_invoice_only_case_uses_narrow_fetch_not_full_pull():
    service, seen = _service(_invoice_only_handler)
    matches = service.origin_invoice_matches(
        {"id": "acme"}, {"shipment": {"invoice_no": "INV-1"}}, CLIENT_CONFIG
    )
    # Enriched from the narrow by-codes export rows, not the full catalog.
    assert [m["item_code"] for m in matches] == ["MAT-1"]
    assert matches[0]["customs_value"] == "500"
    # Narrow endpoints hit...
    assert any(u.path == "/v1/hub/bcct/invoice-matches" for u in seen)
    assert any(u.path.endswith("/bcct/by-codes") for u in seen)
    # ...and the ~40s killers are never touched.
    assert not _full_bcct_pulled(seen)
    assert not any(u.path == "/v1/hub/materials" for u in seen)


def test_export_declaration_case_uses_declaration_filter_not_full_pull():
    service, seen = _service(_export_decl_handler)
    matches = service.origin_invoice_matches(
        {"id": "acme"}, {"shipment": {"export_declaration_nos": ["EX-1"]}}, CLIENT_CONFIG
    )
    assert [m["declaration_no"] for m in matches] == ["EX-1"]
    # The declaration-filtered fetch carried the singular declaration_no param.
    assert any(
        u.path == "/v1/hub/bcct" and u.params.get("declaration_no") == "EX-1"
        for u in seen
    )
    # No unfiltered full pull, no materials pagination.
    assert not _full_bcct_pulled(seen)
    assert not any(u.path == "/v1/hub/materials" for u in seen)


def test_empty_shipment_returns_no_matches_without_any_fetch():
    service, seen = _service(_invoice_only_handler)
    matches = service.origin_invoice_matches({"id": "acme"}, {"shipment": {}}, CLIENT_CONFIG)
    assert matches == []
    assert not _full_bcct_pulled(seen)
    assert not any(u.path == "/v1/hub/materials" for u in seen)


# --- origin_source_context orchestration (main.py) --------------------------
# Stock comes from the CO materializer snapshot (which the DH adapter can't
# reach), so the helper lives in main.py and is exercised with the snapshot
# function + portfolio_service stubbed.

import pytest  # noqa: E402


class _FakePortfolio:
    # Presence of a `data_hub` attribute marks Data-Hub mode (the file-store
    # PortfolioService has none); origin_source_context only engages the
    # snapshot path in DH mode.
    data_hub = object()

    def __init__(self, calls: dict, narrow_matches: list[dict]):
        self._calls = calls
        self._narrow = narrow_matches

    def source_summary(self, client):
        return (
            {"client_config": {"bcct": {"relevant_export_declaration_types": ["B11"]}}},
            "data-hub",
        )

    def origin_invoice_matches(self, client, case, client_config):
        self._calls["origin_invoice_matches"] = self._calls.get("origin_invoice_matches", 0) + 1
        return list(self._narrow)

    def declaration_file_counts(self, client_id, case, invoice_matches):
        return {"export": {}, "import": {}}


def test_origin_source_context_cold_reads_snapshot_and_narrow_matches(monkeypatch):
    import app.main as main

    snapshot = [{"material_code": "MAT-1", "remaining_qty": "10"}]
    calls: dict = {}
    monkeypatch.setattr(main, "_calculate_stock_rows_from_snapshot", lambda client: snapshot)
    monkeypatch.setattr("app.web.co_case_context._calculate_stock_rows_from_snapshot", lambda client: snapshot)
    _fake_pf = _FakePortfolio(calls, narrow_matches=[{"item_code": "MAT-1", "declaration_no": "EX-1"}])
    monkeypatch.setattr(main, "portfolio_service", _fake_pf)
    monkeypatch.setattr("app.web.client_context.portfolio_service", _fake_pf)
    monkeypatch.setattr("app.web.co_case_context.portfolio_service", _fake_pf)
    _fail_heavy = lambda *a, **k: pytest.fail("heavy full-BCCT path must not run when snapshot exists")
    monkeypatch.setattr(main, "co_case_source_context", _fail_heavy)
    monkeypatch.setattr("app.web.co_case_context.co_case_source_context", _fail_heavy)

    ctx = main.origin_source_context({"id": "johnson-vn"}, {"shipment": {"invoice_no": "INV-1"}})

    assert ctx["stock_rows"] == snapshot          # netted snapshot, not a live full pull
    assert ctx["material_rows"] == []             # unused at tab render
    assert ctx["invoice_matches"] == [{"item_code": "MAT-1", "declaration_no": "EX-1"}]
    assert ctx["source_backend"] == "data-hub"
    assert ctx["declaration_file_counts"] == {"export": {}, "import": {}}
    assert calls["origin_invoice_matches"] == 1   # cold load did the narrow fetch


def test_origin_source_context_cold_always_refetches_not_stale_case_matches(monkeypatch):
    import app.main as main

    # The cold path must NOT reuse case["source_invoice_matches"]: warm reuse is
    # handled upstream (cached_origin_source_context). Reaching origin_source_context
    # with cached matches present means force_source_refresh bypassed the cache,
    # so the operator asked for fresh data — re-fetch, don't serve the stale list.
    snapshot = [{"material_code": "MAT-1", "remaining_qty": "10"}]
    calls: dict = {}
    monkeypatch.setattr(main, "_calculate_stock_rows_from_snapshot", lambda client: snapshot)
    monkeypatch.setattr("app.web.co_case_context._calculate_stock_rows_from_snapshot", lambda client: snapshot)
    _fake_pf = _FakePortfolio(calls, narrow_matches=[{"item_code": "FRESH", "declaration_no": "EX-1"}])
    monkeypatch.setattr(main, "portfolio_service", _fake_pf)
    monkeypatch.setattr("app.web.client_context.portfolio_service", _fake_pf)
    monkeypatch.setattr("app.web.co_case_context.portfolio_service", _fake_pf)

    case = {
        "shipment": {"invoice_no": "INV-1"},
        "source_invoice_matches": [{"item_code": "STALE", "declaration_no": "EX-9"}],
    }
    ctx = main.origin_source_context({"id": "johnson-vn"}, case)

    assert ctx["invoice_matches"] == [{"item_code": "FRESH", "declaration_no": "EX-1"}]
    assert ctx["stock_rows"] == snapshot
    assert calls["origin_invoice_matches"] == 1   # cold path always re-fetches


def test_origin_source_context_falls_back_to_heavy_when_snapshot_unusable(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "_calculate_stock_rows_from_snapshot", lambda client: None)
    monkeypatch.setattr("app.web.co_case_context._calculate_stock_rows_from_snapshot", lambda client: None)
    sentinel = {
        "source_backend": "data-hub",
        "source_summary": {},
        "invoice_matches": [],
        "material_rows": [],
        "stock_rows": [{"legacy_full_pull": True}],
        "declaration_file_counts": {"export": {}, "import": {}},
    }
    called: dict = {}

    def fake_heavy(client, case, **kwargs):
        called["heavy"] = True
        return sentinel

    monkeypatch.setattr(main, "co_case_source_context", fake_heavy)
    monkeypatch.setattr("app.web.co_case_context.co_case_source_context", fake_heavy)
    monkeypatch.setattr(main, "portfolio_service", _FakePortfolio({}, narrow_matches=[]))
    monkeypatch.setattr("app.web.client_context.portfolio_service", _FakePortfolio({}, narrow_matches=[]))
    monkeypatch.setattr("app.web.co_case_context.portfolio_service", _FakePortfolio({}, narrow_matches=[]))

    ctx = main.origin_source_context({"id": "johnson-vn"}, {"shipment": {"invoice_no": "INV-1"}})

    # Empty/unusable snapshot must never serve an empty stock preview — it
    # falls back to the legacy full pull so the operator always sees real data.
    assert called.get("heavy") is True
    assert ctx is sentinel


# --- real-Johnson parity e2e (opt-in) ---------------------------------------
# Authoritative guard for the high-risk RVC/export parity: the converged path
# must produce the SAME invoice_matches and stock coverage as the legacy full
# BCCT pull on real data. Opt-in (needs the local Data Hub :8754 + materialized
# co_stock snapshot for johnson-vn), so it is skipped in CI. Run with:
#   set -a; . ./.env; set +a
#   RUN_ORIGIN_PARITY_E2E=1 PYTHONPATH=. .venv/bin/python -m pytest \
#       tests/test_origin_narrow_source_context.py -k parity_e2e -q
import os  # noqa: E402

JOHNSON = "johnson-vn"
JOHNSON_INVOICE = "VNG25120047"  # local invoice-only case co-case-ec000d03522e


@pytest.mark.skipif(
    not os.environ.get("RUN_ORIGIN_PARITY_E2E"),
    reason="opt-in real-Data-Hub parity (set RUN_ORIGIN_PARITY_E2E=1 with local DH + snapshot)",
)
def test_origin_parity_e2e_converged_matches_full_pull_on_real_johnson():
    import json
    import app.main as main
    from app.portfolio import current_portfolio_service

    svc = current_portfolio_service()
    if getattr(svc, "data_hub", None) is None:
        pytest.skip("Data Hub not configured (DATA_HUB_ENABLED off)")
    if main.co_stock_materializer.row_count(JOHNSON) <= 0:
        pytest.skip(f"no materialized co_stock snapshot for {JOHNSON}")

    client = svc.client(JOHNSON)
    case = {"shipment": {"invoice_no": JOHNSON_INVOICE}}

    old = svc.co_case_source_context(client, case)            # legacy full BCCT pull
    new = main.origin_source_context(client, case)            # converged snapshot path

    def _norm(rows):
        return [json.dumps(r, sort_keys=True, ensure_ascii=False, default=str) for r in rows]

    # Export side (the high-risk parity): byte-identical invoice_matches.
    assert _norm(new["invoice_matches"]) == _norm(old["invoice_matches"])

    # Stock: the snapshot is the materialized output of the same derivation the
    # full pull runs live, so material coverage is identical (netting aside).
    old_codes = {str(r.get("material_code") or "") for r in old["stock_rows"]}
    new_codes = {str(r.get("material_code") or "") for r in new["stock_rows"]}
    assert new_codes == old_codes
    assert new["stock_rows"]                                   # never an empty preview
    assert new["material_rows"] == []                         # dropped (unused at tab render)

    # Signature stability across reloads (Risk #3): same inputs -> same hash.
    sig1 = main.origin_build_signature(new["invoice_matches"], {}, new["material_rows"], new["stock_rows"], {})
    again = main.origin_source_context(client, case)
    sig2 = main.origin_build_signature(again["invoice_matches"], {}, again["material_rows"], again["stock_rows"], {})
    assert sig1 == sig2


def test_cached_origin_source_context_carries_declaration_file_counts(monkeypatch):
    """The cached (warm) path feeds the exports/review TKX/TKN file-status panel.
    Without declaration_file_counts every declaration falsely reads
    "Thiếu tờ khai" even when Data Hub has the file (regression)."""
    import app.web.co_case_context as ctx

    sentinel = {"export": {"EX-1": 1}, "import": {"IM-1": 1}}

    class _PF:
        data_hub = object()

        def declaration_file_counts(self, client_id, case, invoice_matches):
            return sentinel

    monkeypatch.setattr("app.web.co_case_context.portfolio_service", _PF())

    case = {
        "source_invoice_matches": [{"item_code": "MAT-1", "declaration_no": "EX-1"}],
        "products": [],
    }
    out = ctx.cached_origin_source_context({"id": "johnson-vn"}, case)
    assert out["source_backend"] == "case-snapshot"
    assert out["declaration_file_counts"] == sentinel
