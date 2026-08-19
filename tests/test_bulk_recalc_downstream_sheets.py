"""A bulk edit must recalculate every sheet it invalidated, not only the edited ones.

Stock is allocated sequentially down the sheet order, so a substitution on sheet 1
changes what is left for sheets 2..N — `mark_origin_sheets_stale` flips all of them to
"Cần tính lại". The bulk routes then recalculated only the sheets they had EDITED, so
the untouched downstream sheets stayed stale while the aggregate panel (which runs a
fresh whole-case preview) reported "Đủ tồn cho tất cả SP — có thể Chốt tất cả".

Reported on johnson-vn VNG26030079 (2026-08-19): one substitution on sheet 1, then
"Tổng hợp NVL" said đủ tồn while sheets 2-5 all read "Cần tính lại" and "Chốt tất cả"
refused them.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

ORDER = ["S1", "S2", "S3", "S4", "S5"]


def _case(states: dict | None = None) -> dict:
    return {"origin_sheet_states": states or {}}


def test_downstream_sheets_are_recalculated_too():
    from app.routers.co_case import origin_codes_to_recalculate
    assert origin_codes_to_recalculate(_case(), ORDER, ["S2"]) == ["S2", "S3", "S4", "S5"]


def test_editing_the_first_sheet_recalculates_the_whole_case():
    from app.routers.co_case import origin_codes_to_recalculate
    assert origin_codes_to_recalculate(_case(), ORDER, ["S1"]) == ORDER


def test_the_lowest_edited_index_sets_the_start():
    from app.routers.co_case import origin_codes_to_recalculate
    assert origin_codes_to_recalculate(_case(), ORDER, ["S4", "S2"]) == ["S2", "S3", "S4", "S5"]


def test_locked_sheets_are_never_recalculated():
    """A lock holds co_stock_claims against the sheet's own allocation lines; the
    snapshot is what was filed."""
    from app.routers.co_case import origin_codes_to_recalculate
    case = _case({"S3": {"status": "locked"}, "S5": {"status": "locked"}})
    assert origin_codes_to_recalculate(case, ORDER, ["S2"]) == ["S2", "S4"]


def test_an_edited_code_outside_the_order_falls_back_to_itself():
    from app.routers.co_case import origin_codes_to_recalculate
    assert origin_codes_to_recalculate(_case(), ORDER, ["GHOST"]) == ["GHOST"]


@pytest.fixture
def bulk_client(monkeypatch, tmp_path):
    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-cases"))
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    import app.main as main_module
    monkeypatch.setattr(main_module, "require_local_source_writes", lambda: None)
    return TestClient(main_module.app)


def _seed_two_sheets(client_id="growatt", case_id="case-downstream-1"):
    from app import co_case_store
    now = co_case_store.now_iso()
    case = {
        "id": case_id, "persisted_case_id": case_id, "case_id": case_id,
        "case_code": "CO-DOWNSTREAM", "title": "Downstream", "customer": "Growatt",
        "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "origin_product_order": ["PV.A", "PV.B"],
        "products": [
            {"code": "PV.A", "name": "SP A", "fob": "100000", "quantity": "1",
             "materials": [{"material_code": "M-OLD", "uom": "kg"}]},
            {"code": "PV.B", "name": "SP B", "fob": "100000", "quantity": "1",
             "materials": [{"material_code": "M-KEEP", "uom": "kg"}]},
        ],
        "origin_sheet_states": {
            "PV.A": {"status": "calculated"},
            "PV.B": {"status": "calculated"},
        },
    }
    co_case_store.save_state(client_id, {"schema_version": 1, "client_id": client_id, "cases": [case]})
    return case_id


def test_bulk_substitute_leaves_no_sheet_resting_at_stale(bulk_client):
    """The untouched downstream sheet must not be left saying "Cần tính lại"."""
    from app import co_case_store
    from app.demo_data import get_client
    case_id = _seed_two_sheets()
    resp = bulk_client.post(
        f"/clients/growatt/co-case/{case_id}/origin/bulk-substitute",
        json={"substitutions": [{"product_code": "PV.A", "material_code": "M-OLD", "substitute_code": "M-NEW"}]},
    )
    assert resp.status_code == 200
    record = co_case_store.get_case_record(get_client("growatt"), case_id)
    statuses = {code: state.get("status") for code, state in record["origin_sheet_states"].items()}
    assert "stale" not in statuses.values(), statuses
