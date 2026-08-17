"""Route tests for POST .../origin/bulk-substitute (Slice C, #13b).

Verifies the bug-prone wiring: a substitution becomes a material_override at the
matched row index, persisted under origin_sheet_states; bad entries are
skipped-and-reported; the response carries the override-aware preview summary.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def sub_client(monkeypatch, tmp_path):
    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-cases"))
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    import app.main as main_module
    monkeypatch.setattr(main_module, "require_local_source_writes", lambda: None)
    return TestClient(main_module.app)


def _seed(client_id="growatt", case_id="case-sub-1"):
    from app import co_case_store
    now = co_case_store.now_iso()
    case = {
        "id": case_id, "persisted_case_id": case_id, "case_id": case_id,
        "case_code": "CO-SUB", "title": "Sub test", "customer": "Growatt",
        "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "origin_product_order": ["PV.A"],
        "products": [{
            "code": "PV.A", "name": "SP A", "fob": "100000", "quantity": "1",
            "materials": [
                {"material_code": "M-KEEP", "uom": "kg"},
                {"material_code": "M-OLD", "uom": "kg"},
            ],
        }],
    }
    co_case_store.save_state(client_id, {"schema_version": 1, "client_id": client_id, "cases": [case]})
    return case_id


def _url(case_id):
    return f"/clients/growatt/co-case/{case_id}/origin/bulk-substitute"


def test_substitution_persists_override_at_matched_row(sub_client):
    from app import co_case_store
    from app.demo_data import get_client
    case_id = _seed()
    resp = sub_client.post(_url(case_id), json={
        "substitutions": [{"product_code": "PV.A", "material_code": "M-OLD", "substitute_code": "M-NEW"}]
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] == [{"product_code": "PV.A", "material_code": "M-OLD", "substitute_code": "M-NEW"}]
    assert body["skipped"] == []
    record = co_case_store.get_case_record(get_client("growatt"), case_id)
    overrides = record["origin_sheet_states"]["PV.A"]["material_overrides"]
    # M-OLD is the 2nd material → material_sequence key "2"
    assert overrides["2"]["material_code"] == "M-NEW"


def test_unknown_material_is_skipped(sub_client):
    case_id = _seed()
    body = sub_client.post(_url(case_id), json={
        "substitutions": [{"product_code": "PV.A", "material_code": "NOPE", "substitute_code": "X"}]
    }).json()
    assert body["applied"] == []
    assert body["skipped"] == [{"product_code": "PV.A", "material_code": "NOPE", "reason": "material_not_found"}]


def test_incomplete_entry_is_skipped(sub_client):
    case_id = _seed()
    body = sub_client.post(_url(case_id), json={
        "substitutions": [{"product_code": "PV.A", "material_code": "M-OLD"}]
    }).json()
    assert body["applied"] == []
    assert body["skipped"][0]["reason"] == "incomplete"


def test_empty_payload_rejected(sub_client):
    case_id = _seed()
    resp = sub_client.post(_url(case_id), json={"substitutions": []})
    assert resp.status_code == 400


def _seed_with_unmatched(client_id="growatt", case_id="case-sub-unm"):
    from app import co_case_store
    now = co_case_store.now_iso()
    case = {
        "id": case_id, "persisted_case_id": case_id, "case_id": case_id,
        "case_code": "CO-SUB-UNM", "title": "Sub test", "customer": "Growatt",
        "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "origin_product_order": ["PV.A"],
        "products": [{
            "code": "PV.A", "name": "SP A", "fob": "100000", "quantity": "1",
            "materials": [
                {"material_code": "M-OLD", "uom": "kg", "customs_relevance": "declarable"},
                {"material_code": "M-UNM", "uom": "kg", "customs_relevance": "declarable_unmatched"},
            ],
        }],
    }
    co_case_store.save_state(client_id, {"schema_version": 1, "client_id": client_id, "cases": [case]})
    return case_id


def test_persisted_status_reflects_the_remaining_block(sub_client):
    """Substituting one NVL leaves PV.A with a declarable_unmatched row, so the sheet
    is NOT lockable. The route must persist the DERIVED status (`bom_loaded`), not a
    hardcoded "calculated" — otherwise the sheet list reads "Đã tính" while "Chốt tất
    cả" skips it, and the block only surfaces after a reload."""
    from app import co_case_store
    from app.demo_data import get_client
    case_id = _seed_with_unmatched()
    resp = sub_client.post(
        f"/clients/growatt/co-case/{case_id}/origin/bulk-substitute",
        json={"substitutions": [{"product_code": "PV.A", "material_code": "M-OLD", "substitute_code": "M-NEW"}]},
    )
    assert resp.status_code == 200
    rec = co_case_store.get_case_record(get_client("growatt"), case_id)
    assert rec["origin_sheet_states"]["PV.A"]["status"] == "bom_loaded"
