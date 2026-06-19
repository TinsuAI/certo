"""Route tests: previously-used substitutes pinned/injected in the candidates list.

History is mined from the client's LOCKED dossiers (CO-owned, no Data Hub).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def hist_client(monkeypatch, tmp_path):
    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-cases"))
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    import app.main as main_module
    from app import substitution_history
    substitution_history.invalidate()
    monkeypatch.setattr(main_module, "require_local_source_writes", lambda: None)
    return TestClient(main_module.app)


def _seed(client_id="growatt"):
    from app import co_case_store, substitution_history
    now = co_case_store.now_iso()
    locked_case = {
        "id": "case-locked", "persisted_case_id": "case-locked", "case_id": "case-locked",
        "case_code": "CO-LOCK", "title": "locked", "status": "open",
        "created_at": now, "updated_at": now,
        "origin_product_order": ["SP1"],
        "products": [{"code": "SP1", "name": "SP1", "materials": [{"material_code": "M-OLD"}]}],
        "origin_sheet_states": {"SP1": {
            "status": "locked",
            "material_overrides": {"0": {"material_code": "M-NEW", "name": "NVL Mới"}},
        }},
    }
    query_case = {
        "id": "case-query", "persisted_case_id": "case-query", "case_id": "case-query",
        "case_code": "CO-QUERY", "title": "query", "status": "open",
        "created_at": now, "updated_at": now,
        "origin_product_order": ["SP1"],
        "products": [{"code": "SP1", "name": "SP1", "materials": [{"material_code": "M-OLD"}]}],
    }
    co_case_store.save_state(client_id, {"schema_version": 1, "client_id": client_id, "cases": [locked_case, query_case]})
    substitution_history.invalidate()
    return "case-query"


def _url(case_id, material_code="M-OLD", product="SP1"):
    return (
        f"/clients/growatt/co-case/{case_id}/origin/sheet/{product}"
        f"/substitute-candidates?material_code={material_code}"
    )


def test_previously_used_substitute_injected_when_dh_empty(hist_client):
    case_id = _seed()
    body = hist_client.get(_url(case_id)).json()
    assert body["ok"] is True
    cands = body["candidates"]
    assert cands, "expected the injected history candidate"
    top = cands[0]
    assert top["material_code"] == "M-NEW"
    assert top["previously_used"] is True
    assert top["history_count"] == 1
    assert "co_history" in (top.get("sources") or [])


def test_history_pins_low_score_dh_candidate_above_high_score(hist_client, monkeypatch):
    case_id = _seed()
    from app.routers import co_case

    def fake_subs(client_id, material_code, *, min_score=0.5, limit=20):
        return ([
            {"material_code": "M-HI", "name": "high score", "combined_score": 0.99},
            {"material_code": "M-NEW", "name": "NVL Mới", "combined_score": 0.40},
        ], "data_hub")

    monkeypatch.setattr(co_case.portfolio_service, "list_material_substitutes", fake_subs)
    body = hist_client.get(_url(case_id)).json()
    cands = body["candidates"]
    codes = [c["material_code"] for c in cands]
    # M-NEW (prior-used, low score) pinned ABOVE M-HI (high score, never used).
    assert codes[0] == "M-NEW"
    assert cands[0]["previously_used"] is True
    assert "M-HI" in codes
    hi = next(c for c in cands if c["material_code"] == "M-HI")
    assert not hi.get("previously_used")


def test_no_history_no_pin(hist_client, monkeypatch):
    case_id = _seed()
    from app.routers import co_case

    def fake_subs(client_id, material_code, *, min_score=0.5, limit=20):
        return ([{"material_code": "M-HI", "name": "x", "combined_score": 0.99}], "data_hub")

    monkeypatch.setattr(co_case.portfolio_service, "list_material_substitutes", fake_subs)
    # Query a material that was never substituted.
    body = hist_client.get(_url(case_id, material_code="M-OTHER")).json()
    cands = body["candidates"]
    assert all(not c.get("previously_used") for c in cands)
