"""Route smoke for POST .../origin/preview-stock-all (Slice B).

File-mode has no BCCT/BOM/stock source, so the summary is empty — this proves
the endpoint is wired, returns the JSON summary shape, runs side-effect-free
(no persistence/ledger), and never 500s. The shortage logic itself is covered
by test_stock_preview_pipeline.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def preview_client(monkeypatch, tmp_path):
    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-cases"))
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    import app.main as main_module
    monkeypatch.setattr(main_module, "require_local_source_writes", lambda: None)
    return TestClient(main_module.app)


def _seed_case(client_id="growatt", case_id="case-preview-1"):
    from app import co_case_store
    now = co_case_store.now_iso()
    case = {
        "id": case_id, "persisted_case_id": case_id, "case_id": case_id,
        "case_code": "CO-PREVIEW", "title": "Preview test", "customer": "Growatt",
        "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "products": [{"code": "PV.A", "fob": "100000"}],
    }
    co_case_store.save_state(client_id, {"schema_version": 1, "client_id": client_id, "cases": [case]})
    return case_id


def test_preview_stock_all_returns_summary_shape(preview_client):
    case_id = _seed_case()
    resp = preview_client.post(
        f"/clients/growatt/co-case/{case_id}/origin/preview-stock-all", json={}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["products"] == []
    assert body["missing_codes"] == []
    assert body["missing_code_count"] == 0
    assert body["product_count"] == 0
    # material-centric rollup (M3) rides alongside the product-centric summary
    assert body["rollup"]["materials"] == []
    assert body["rollup"]["material_count"] == 0
    assert "no_bom_products" in body["rollup"]  # no-BOM sheets are flagged, not counted as covered


def test_calculate_all_returns_shape_and_persists(preview_client):
    # calculate-all is committing (persists calculated sheets); file-mode has no BOM
    # so nothing loads, but it must wire, return the rollup+revision shape, and 200.
    case_id = _seed_case(case_id="case-calc-all-1")
    resp = preview_client.post(
        f"/clients/growatt/co-case/{case_id}/origin/calculate-all", json={}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "revision" in body
    assert body["rollup"]["material_count"] == 0
    assert body["rollup"]["no_bom_products"] == ["PV.A"]  # seeded product has no BOM in file-mode


def test_calculate_all_never_reopens_a_locked_sheet(preview_client):
    """`allocate_whole_case_preview` rebuilds EVERY product, so persisting its output
    as-is rewrote a locked sheet's snapshot and re-stamped its status from
    `calculated_sheet_status` — silently unlocking it while the ledger still held
    co_stock_claims against the old allocation lines."""
    from app import co_case_store
    from app.demo_data import get_client

    case_id = "case-calc-all-locked"
    now = co_case_store.now_iso()
    co_case_store.save_state("growatt", {"schema_version": 1, "client_id": "growatt", "cases": [{
        "id": case_id, "persisted_case_id": case_id, "case_id": case_id,
        "case_code": "CO-LOCKED", "title": "Locked", "customer": "Growatt",
        "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "origin_product_order": ["PV.A", "PV.B"],
        "products": [
            {"code": "PV.A", "fob": "100000", "materials": [{"material_code": "M-FILED", "uom": "kg"}]},
            {"code": "PV.B", "fob": "100000", "materials": []},
        ],
        "origin_sheet_states": {"PV.A": {"status": "locked"}, "PV.B": {"status": "calculated"}},
    }]})

    resp = preview_client.post(f"/clients/growatt/co-case/{case_id}/origin/calculate-all", json={})
    assert resp.status_code == 200

    record = co_case_store.get_case_record(get_client("growatt"), case_id)
    assert record["origin_sheet_states"]["PV.A"]["status"] == "locked"
    filed = next(p for p in record["products"] if p["code"] == "PV.A")
    assert [m["material_code"] for m in filed["materials"]] == ["M-FILED"]
