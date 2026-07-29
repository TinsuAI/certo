"""BOM-proposal re-POST guard — backlog M1, sub-bug 2 (server half).

The "Đã propose ✓" button must not file a duplicate proposal. The client half is
a JS guard in `co_case.html` (`initOriginProposeBom` skips wiring the POST and
hard-disables the button when `data-proposed-artifact-id` is set). The server
half, tested here, is that any material_overrides WRITE clears the prior proposal
stamp via `override_state_stamp`, so a genuinely changed BOM re-renders the button
as "Lưu BOM mới" and a fresh proposal is allowed — while an unchanged, already
proposed sheet stays inert.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.routers.co_case import override_state_stamp


def test_override_state_stamp_clears_prior_proposal():
    stamp = override_state_stamp({"bom_product_artifact_id": "bv-9"})
    assert stamp["overrides_artifact_id"] == "bv-9"
    assert stamp["proposed_artifact_id"] == ""
    assert stamp["proposed_proposal_id"] == ""
    assert stamp["proposed_status"] == ""


def test_override_write_pattern_drops_proposed_stamp():
    # A sheet locked + proposed (proposed_* set), then edited: the write pattern
    # every override endpoint uses is {**previous, ..., **override_state_stamp}.
    previous = {
        "status": "locked",
        "material_overrides": {"row-1": {"deleted": True}},
        "proposed_artifact_id": "art-1",
        "proposed_proposal_id": "prop-1",
        "proposed_status": "submitted",
    }
    product = {"bom_product_artifact_id": "bv-9"}
    new_state = {
        **previous,
        "material_overrides": {"row-1": {"deleted": True}, "row-2": {"added": True}},
        **override_state_stamp(product),
        "status": "stale",
    }
    assert new_state["proposed_artifact_id"] == ""
    assert new_state["proposed_proposal_id"] == ""
    assert new_state["proposed_status"] == ""
    # The edit itself is preserved; only the proposal reference is dropped.
    assert new_state["overrides_artifact_id"] == "bv-9"
    assert "row-2" in new_state["material_overrides"]


# --- server half: the propose-bom route itself rejects a duplicate POST ---
# The client guard hard-disables the button, but a second browser tab (opened
# before the first render) or a direct curl can still re-POST. The route must
# 409 before calling submit_bom_proposal so no duplicate proposal reaches Data
# Hub — the mutating external side effect.


@pytest.fixture
def propose_client(monkeypatch, tmp_path):
    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-cases"))
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    import app.main as main_module
    monkeypatch.setattr(main_module, "require_local_source_writes", lambda: None)
    return TestClient(main_module.app)


def _spy_submit(monkeypatch):
    """Stub portfolio_service.submit_bom_proposal, recording every call."""
    from app.portfolio import portfolio_service
    calls: list[tuple] = []

    def fake(client_id, product_code, **kwargs):
        calls.append((client_id, product_code, kwargs))
        return {"artifact_id": "art-new", "proposal_id": "prop-new", "status": "submitted"}

    monkeypatch.setattr(portfolio_service, "submit_bom_proposal", fake)
    return calls


def _seed_locked_sheet(client_id="growatt", case_id="case-propose-1", *, proposed_artifact_id=""):
    from app import co_case_store
    now = co_case_store.now_iso()
    state = {
        "status": "locked",
        "status_label": "locked",
        "material_overrides": {"added_0": {"added": True, "material_code": "NEW-1", "norm_per_unit": "2"}},
    }
    if proposed_artifact_id:
        state["proposed_artifact_id"] = proposed_artifact_id
        state["proposed_proposal_id"] = "prop-old"
        state["proposed_status"] = "submitted"
    case = {
        "id": case_id, "persisted_case_id": case_id, "case_id": case_id,
        "case_code": "CO-PROPOSE", "title": "Propose test", "customer": "Growatt",
        "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "origin_product_order": ["TP-A"],
        "products": [{"code": "TP-A", "name": "TP-A", "bom_product_artifact_id": "bv-9",
                      "bom_product_code": "TP-A", "materials": []}],
        "origin_sheet_states": {"TP-A": state},
    }
    co_case_store.save_state(client_id, {"schema_version": 1, "client_id": client_id, "cases": [case]})
    return case_id


def _url(case_id):
    return f"/clients/growatt/co-case/{case_id}/origin/sheet/TP-A/propose-bom"


def test_first_propose_calls_data_hub(propose_client, monkeypatch):
    # sanity: a locked sheet not yet proposed does reach submit_bom_proposal.
    calls = _spy_submit(monkeypatch)
    case_id = _seed_locked_sheet()
    resp = propose_client.post(_url(case_id), json={})
    assert resp.status_code == 200
    assert len(calls) == 1


def test_second_propose_on_proposed_sheet_returns_409_and_skips_data_hub(propose_client, monkeypatch):
    # already-proposed sheet: the route must 409 and NOT re-invoke Data Hub.
    calls = _spy_submit(monkeypatch)
    case_id = _seed_locked_sheet(proposed_artifact_id="art-existing")
    resp = propose_client.post(_url(case_id), json={})
    assert resp.status_code == 409
    assert "propose" in resp.json()["detail"].lower()
    assert calls == []
