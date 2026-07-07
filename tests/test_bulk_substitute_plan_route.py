"""Route smoke for POST .../origin/bulk-substitute-plan (M2 planner).

File-mode has no BCCT/BOM/stock source, so the allocated case is empty and the
plan targets nothing — this proves the endpoint is wired, returns the
{substitutions, summary} shape, runs side-effect-free, and never 500s. The
expansion logic (only_short / everywhere / locked) is covered by
test_substitution_plan.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def plan_client(monkeypatch, tmp_path):
    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-cases"))
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    import app.main as main_module
    monkeypatch.setattr(main_module, "require_local_source_writes", lambda: None)
    return TestClient(main_module.app)


def _seed_case(client_id="growatt", case_id="case-plan-1"):
    from app import co_case_store
    now = co_case_store.now_iso()
    case = {
        "id": case_id, "persisted_case_id": case_id, "case_id": case_id,
        "case_code": "CO-PLAN", "title": "Plan test", "customer": "Growatt",
        "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "products": [{"code": "PV.A", "fob": "100000"}],
    }
    co_case_store.save_state(client_id, {"schema_version": 1, "client_id": client_id, "cases": [case]})
    return case_id


def test_plan_route_returns_plan_shape(plan_client):
    case_id = _seed_case()
    resp = plan_client.post(
        f"/clients/growatt/co-case/{case_id}/origin/bulk-substitute-plan",
        json={"material_code": "A", "substitute_code": "A-SUB", "mode": "only_short"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["substitutions"] == []  # file-mode: no materials → nothing to target
    assert body["summary"]["material_code"] == "A"
    assert body["summary"]["substitute_code"] == "A-SUB"
    assert body["summary"]["mode"] == "only_short"
    assert body["summary"]["target_count"] == 0


def test_plan_route_requires_codes(plan_client):
    case_id = _seed_case()
    resp = plan_client.post(
        f"/clients/growatt/co-case/{case_id}/origin/bulk-substitute-plan",
        json={"material_code": "A"},
    )
    assert resp.status_code == 400
