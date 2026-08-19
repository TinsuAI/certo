"""Saving a bảng kê's config recalculates it, instead of asking the operator to remember.

The criterion and the threshold decide the LVC pass/fail and the CTC verdict, and both
are stamped on the sheet at Tính — not derived at render. The override route only
persisted them, so a sheet kept reading "Đã tính" with a badge measured against the
PREVIOUS rule and the modal's hint just said "bấm Lưu rồi Tính bảng kê lại".

Cost measured on prod-sized johnson-vn (105-row sheet, warm snapshot): 1.3s per sheet.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def cfg_client(monkeypatch, tmp_path):
    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-cases"))
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    import app.main as main_module
    monkeypatch.setattr(main_module, "require_local_source_writes", lambda: None)
    return TestClient(main_module.app)


def _seed(case_id, statuses):
    from app import co_case_store
    now = co_case_store.now_iso()
    co_case_store.save_state("growatt", {"schema_version": 1, "client_id": "growatt", "cases": [{
        "id": case_id, "persisted_case_id": case_id, "case_id": case_id,
        "case_code": "CO-CFG", "title": "Cfg", "customer": "Growatt",
        "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "origin_product_order": list(statuses),
        "products": [
            {"code": code, "name": code, "fob": "100000", "quantity": "1",
             "finished_hs": "854140", "materials": [{"material_code": "M1", "uom": "kg"}]}
            for code in statuses
        ],
        "origin_sheet_states": {code: {"status": status} for code, status in statuses.items()},
    }]})
    return case_id


def _override_url(case_id, code):
    return f"/clients/growatt/co-case/{case_id}/origin/sheet/{code}/recommendation-override"


def test_changing_the_criterion_recalculates_the_sheet(cfg_client):
    case_id = _seed("case-cfg-crit", {"PV.A": "calculated"})
    body = cfg_client.post(_override_url(case_id, "PV.A"), json={"criteria_override": "RVC 40%"}).json()
    assert body["ok"] is True
    assert body["recalculated"] is True


def test_changing_only_the_currency_does_not_recalculate(cfg_client):
    """Every lot carries both money lanes, so the switch is a display swap."""
    case_id = _seed("case-cfg-cur", {"PV.A": "calculated"})
    body = cfg_client.post(_override_url(case_id, "PV.A"), json={"currency_mode": "vnd"}).json()
    assert body["recalculated"] is False


def test_saving_the_same_values_does_not_recalculate(cfg_client):
    case_id = _seed("case-cfg-same", {"PV.A": "calculated"})
    cfg_client.post(_override_url(case_id, "PV.A"), json={"criteria_override": "CTH"})
    body = cfg_client.post(_override_url(case_id, "PV.A"), json={"criteria_override": "CTH"}).json()
    assert body["recalculated"] is False


def test_a_locked_sheet_is_never_recalculated(cfg_client):
    from app import co_case_store
    from app.demo_data import get_client
    case_id = _seed("case-cfg-locked", {"PV.A": "locked"})
    body = cfg_client.post(_override_url(case_id, "PV.A"), json={"criteria_override": "RVC 40%"}).json()
    assert body["recalculated"] is False
    record = co_case_store.get_case_record(get_client("growatt"), case_id)
    assert record["origin_sheet_states"]["PV.A"]["status"] == "locked"


def test_a_draft_sheet_is_not_dragged_into_a_status_it_never_earned(cfg_client):
    from app import co_case_store
    from app.demo_data import get_client
    case_id = _seed("case-cfg-draft", {"PV.A": "draft"})
    body = cfg_client.post(_override_url(case_id, "PV.A"), json={"criteria_override": "RVC 40%"}).json()
    assert body["recalculated"] is False
    record = co_case_store.get_case_record(get_client("growatt"), case_id)
    assert record["origin_sheet_states"]["PV.A"]["status"] == "draft"


def test_sheets_after_the_edited_one_go_stale(cfg_client):
    """Stock is allocated in sheet order, so a changed allocation on sheet 1 changes
    what is left for sheet 2."""
    from app import co_case_store
    from app.demo_data import get_client
    case_id = _seed("case-cfg-downstream", {"PV.A": "calculated", "PV.B": "calculated"})
    cfg_client.post(_override_url(case_id, "PV.A"), json={"optimization_mode": "min_lvc"})
    record = co_case_store.get_case_record(get_client("growatt"), case_id)
    assert record["origin_sheet_states"]["PV.B"]["status"] == "stale"


def test_choosing_a_case_criterion_recalculates_every_inheriting_sheet(cfg_client):
    case_id = _seed("case-cfg-case-crit", {"PV.A": "calculated", "PV.B": "calculated"})
    body = cfg_client.post(
        f"/clients/growatt/co-case/{case_id}/origin/case-criteria",
        json={"criteria_text": "RVC 40%", "lvc_threshold": "40"},
    ).json()
    assert body["recalculated"] == ["PV.A", "PV.B"]


def test_a_sheet_with_its_own_criterion_is_left_alone(cfg_client):
    from app import co_case_store
    from app.demo_data import get_client
    case_id = _seed("case-cfg-own-crit", {"PV.A": "calculated", "PV.B": "calculated"})
    cfg_client.post(_override_url(case_id, "PV.B"), json={"criteria_override": "CTSH"})
    body = cfg_client.post(
        f"/clients/growatt/co-case/{case_id}/origin/case-criteria",
        json={"criteria_text": "RVC 40%"},
    ).json()
    assert body["recalculated"] == ["PV.A"]
    record = co_case_store.get_case_record(get_client("growatt"), case_id)
    assert record["origin_sheet_states"]["PV.B"]["criteria_override"] == "CTSH"


def test_display_decimals_is_a_display_setting_only(cfg_client):
    """Changing how many decimals the screen shows must not trigger a recalculation —
    the numbers are the same, only the rendering differs."""
    from app import co_case_store
    from app.demo_data import get_client
    case_id = _seed("case-cfg-decimals", {"PV.A": "calculated"})
    body = cfg_client.post(_override_url(case_id, "PV.A"), json={"display_decimals": "2"}).json()
    assert body["recalculated"] is False
    assert body["state"]["display_decimals"] == "2"
    record = co_case_store.get_case_record(get_client("growatt"), case_id)
    assert record["origin_sheet_states"]["PV.A"]["display_decimals"] == "2"


def test_a_bad_display_decimals_value_is_clamped_not_rejected(cfg_client):
    case_id = _seed("case-cfg-decimals-bad", {"PV.A": "calculated"})
    body = cfg_client.post(_override_url(case_id, "PV.A"), json={"display_decimals": "99"}).json()
    assert body["state"]["display_decimals"] == "8"
    body = cfg_client.post(_override_url(case_id, "PV.A"), json={"display_decimals": "abc"}).json()
    assert body["state"]["display_decimals"] == ""
