"""Route tests for POST .../origin/bulk-delete-rac.

"Xoá NVL rác hàng loạt" from the aggregate / per-sheet: soft-deletes folded rác rows
of ONE kind (customs_relevance = declarable_unmatched | excluded_non_material) for the
selected codes across non-locked sheets. Optional product_code scopes to one sheet.
The server filters by customs_relevance itself, so kinds never bleed into each other.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def del_client(monkeypatch, tmp_path):
    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-cases"))
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    import app.main as main_module
    monkeypatch.setattr(main_module, "require_local_source_writes", lambda: None)
    return TestClient(main_module.app)


def _seed(case_id="case-rac-1", *, lock_b=False, client_id="growatt"):
    from app import co_case_store
    now = co_case_store.now_iso()
    case = {
        "id": case_id, "persisted_case_id": case_id, "case_id": case_id,
        "case_code": "CO-RAC", "title": "Rac test", "customer": "Growatt",
        "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "origin_product_order": ["PV.A", "PV.B"],
        "products": [
            {"code": "PV.A", "name": "SP A", "fob": "100000", "quantity": "1",
             "materials": [
                 {"material_code": "M-UNM", "uom": "kg", "customs_relevance": "declarable_unmatched"},   # không có trong BCCT
                 {"material_code": "M-PHI", "uom": "kg", "customs_relevance": "excluded_non_material"},   # phi vật tư
                 {"material_code": "M-OK", "uom": "kg", "customs_relevance": "declarable"},               # hàng thật
             ]},
            {"code": "PV.B", "name": "SP B", "fob": "50000", "quantity": "1",
             "materials": [
                 {"material_code": "M-UNM", "uom": "kg", "customs_relevance": "declarable_unmatched"},
             ]},
        ],
    }
    if lock_b:
        case["origin_sheet_states"] = {"PV.B": {"status": "locked", "status_label": "Đã chốt"}}
    co_case_store.save_state(client_id, {"schema_version": 1, "client_id": client_id, "cases": [case]})
    return case_id


def _url(case_id):
    return f"/clients/growatt/co-case/{case_id}/origin/bulk-delete-rac"


def test_deletes_only_the_chosen_kind_across_sheets(del_client):
    from app import co_case_store
    from app.demo_data import get_client
    case_id = _seed()
    body = del_client.post(_url(case_id), json={"kind": "declarable_unmatched", "material_codes": ["M-UNM"]}).json()

    deleted = {(d["product_code"], d["material_code"]) for d in body["deleted"]}
    assert deleted == {("PV.A", "M-UNM"), ("PV.B", "M-UNM")}

    rec = co_case_store.get_case_record(get_client("growatt"), case_id)
    over_a = rec["origin_sheet_states"]["PV.A"]["material_overrides"]
    assert over_a["1"]["deleted"] is True                          # M-UNM = 1st row → key "1"
    assert "2" not in over_a or not over_a["2"].get("deleted")     # M-PHI (other kind) untouched
    assert "3" not in over_a or not over_a["3"].get("deleted")     # M-OK (declarable) untouched


def test_kinds_do_not_bleed(del_client):
    case_id = _seed()
    # send BOTH codes but kind=excluded_non_material → only the phi-vật-tư row goes.
    body = del_client.post(_url(case_id), json={"kind": "excluded_non_material", "material_codes": ["M-PHI", "M-UNM"]}).json()
    deleted = {(d["product_code"], d["material_code"]) for d in body["deleted"]}
    assert deleted == {("PV.A", "M-PHI")}


def test_no_kind_deletes_any_folded_rac_mixed(del_client):
    from app import co_case_store
    from app.demo_data import get_client
    case_id = _seed()
    # omit kind → mixed selection: both folded kinds go; the declarable row is safe.
    body = del_client.post(_url(case_id), json={"material_codes": ["M-UNM", "M-PHI", "M-OK"]}).json()
    deleted = {(d["product_code"], d["material_code"]) for d in body["deleted"]}
    assert deleted == {("PV.A", "M-UNM"), ("PV.A", "M-PHI"), ("PV.B", "M-UNM")}
    rec = co_case_store.get_case_record(get_client("growatt"), case_id)
    over_a = rec["origin_sheet_states"]["PV.A"]["material_overrides"]
    assert "3" not in over_a or not over_a["3"].get("deleted")   # M-OK (declarable) never deleted


def test_product_code_scopes_to_one_sheet(del_client):
    case_id = _seed()
    body = del_client.post(_url(case_id), json={
        "kind": "declarable_unmatched", "material_codes": ["M-UNM"], "product_code": "PV.A"}).json()
    deleted = {(d["product_code"], d["material_code"]) for d in body["deleted"]}
    assert deleted == {("PV.A", "M-UNM")}                          # PV.B not touched (scoped)


def test_locked_sheet_skipped_and_reported(del_client):
    case_id = _seed("case-rac-lock", lock_b=True)
    body = del_client.post(_url(case_id), json={"kind": "declarable_unmatched", "material_codes": ["M-UNM"]}).json()
    deleted = {(d["product_code"], d["material_code"]) for d in body["deleted"]}
    assert deleted == {("PV.A", "M-UNM")}
    assert {"product_code": "PV.B", "material_code": "M-UNM"} in body["skipped_locked"]


def test_bad_kind_rejected(del_client):
    case_id = _seed()
    assert del_client.post(_url(case_id), json={"kind": "bogus", "material_codes": ["M-UNM"]}).status_code == 400


def test_empty_codes_rejected(del_client):
    case_id = _seed()
    assert del_client.post(_url(case_id), json={"kind": "declarable_unmatched", "material_codes": []}).status_code == 400


def test_persisted_status_reflects_the_remaining_block(del_client):
    """Deleting only the phi-vật-tư row leaves PV.A with a declarable_unmatched NVL,
    so the sheet is NOT lockable. The route must persist the status DERIVED from the
    recalculated sheet (`bom_loaded`), not a hardcoded "calculated" — otherwise the
    sheet list reads "Đã tính" while "Chốt tất cả" silently skips it, and the real
    state only appears after F5."""
    from app import co_case_store
    from app.demo_data import get_client
    case_id = _seed()
    del_client.post(_url(case_id), json={"kind": "excluded_non_material", "material_codes": ["M-PHI"]})
    rec = co_case_store.get_case_record(get_client("growatt"), case_id)
    assert rec["origin_sheet_states"]["PV.A"]["status"] == "bom_loaded"
