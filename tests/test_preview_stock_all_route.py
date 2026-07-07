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
    assert body["rollup"] == {"materials": [], "material_count": 0}
