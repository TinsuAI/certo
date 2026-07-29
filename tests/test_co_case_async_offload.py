"""H2 async-offload (CO-524): async case handlers must run their blocking sync
Data Hub pulls OFF the event loop via asyncio.to_thread, not on the loop thread.

Before this fix co_case_detail / co_case_step / substitute-candidates were
`async def` but called sync DH pulls directly, blocking the event loop (residual
~15s first-open stall; one slow request stalled others). This asserts the pulls
execute on a worker thread while the handler still returns the same result.
"""
from __future__ import annotations

import asyncio
import json
import threading

from app.routers import co_case


def test_substitute_candidates_offloads_blocking_pulls_to_thread(monkeypatch):
    ran_on: dict[str, str] = {}

    def record(name: str) -> None:
        ran_on[name] = threading.current_thread().name

    monkeypatch.setattr(co_case, "resolve_client", lambda client_id: {"id": client_id})

    def fake_persisted_origin_case(client, case_id):
        record("persisted_origin_case")
        return {"products": [{"code": "P1"}], "origin_sheet_states": {}}

    monkeypatch.setattr(co_case, "persisted_origin_case", fake_persisted_origin_case)

    def fake_search_materials(client_id, query, limit=20):
        record("search_materials")
        return [{"material_code": "MAT-9", "name": "Widget", "hs_code": "1234"}]

    monkeypatch.setattr(
        co_case.portfolio_service, "search_materials", fake_search_materials
    )

    def fake_read_stock(client_id):
        record("read_co_stock_rows_cached")
        return []

    monkeypatch.setattr(
        co_case.co_stock_materializer, "read_co_stock_rows_cached", fake_read_stock
    )

    def fake_catalog(client, case):
        record("co_case_material_catalog_cached")
        return []

    monkeypatch.setattr(co_case, "co_case_material_catalog_cached", fake_catalog)

    resp = asyncio.run(
        co_case.co_case_origin_sheet_substitute_candidates(
            client_id="acme", case_id="C1", product_code="P1", search="widget"
        )
    )

    body = json.loads(resp.body)
    assert body["ok"] is True
    assert body["product_code"] == "P1"
    assert any(row["material_code"] == "MAT-9" for row in body["search_results"])

    main = threading.main_thread().name
    assert ran_on, "expected the offloaded pulls to run"
    # Every offloaded pull must have executed on a worker thread, not the loop's.
    for name, thread_name in ran_on.items():
        assert thread_name != main, f"{name} ran on the event-loop thread ({thread_name})"
