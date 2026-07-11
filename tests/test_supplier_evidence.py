"""Supplier evidence store + curation flip flow (VN-origin ticket #11).

File-mode suite covers the pure parts (validation, damage/benefit lists from
locked snapshots, route guards, screen rendering); the append-only Postgres
round-trip is DB-gated per the events-store convention.
"""
from __future__ import annotations

import pytest

from app.database import database_url
from app.supplier_evidence import supplier_benefit_list, supplier_damage_list
from app.supplier_evidence_store import EVIDENCE_KINDS, record_flip, store_available


def _case(status="locked", line_status="origin", origin_country="VIETNAM", value="120"):
    return {
        "case_id": "case-1",
        "case_code": "CO-DMG",
        "products": [{
            "code": "TP1",
            "materials": [{
                "material_code": "NVL-1",
                "origin_status": "non_origin",
                "allocation_lines": [{
                    "supplier_key": "CONG TY TNHH MINGJIE VIET NAM",
                    "origin_status": line_status,
                    "origin_country": origin_country,
                    "material_value": value,
                }],
            }],
        }],
        "origin_sheet_states": {"TP1": {"status": status}},
    }


# --- damage list (ON→OFF confirm material) ---

def test_damage_list_finds_locked_sheets_counting_supplier_as_originating():
    hits = supplier_damage_list([_case()], "CONG TY TNHH MINGJIE VIET NAM")
    assert hits == [{
        "case_id": "case-1", "case_code": "CO-DMG",
        "product_code": "TP1", "originating_amount": "120",
    }]


def test_damage_list_ignores_unlocked_sheets_and_other_suppliers():
    assert supplier_damage_list([_case(status="calculated")], "CONG TY TNHH MINGJIE VIET NAM") == []
    assert supplier_damage_list([_case()], "NCC KHAC") == []


def test_damage_list_ignores_non_originating_lines():
    assert supplier_damage_list([_case(line_status="non_origin")], "CONG TY TNHH MINGJIE VIET NAM") == []


# --- benefit list (OFF→ON info) ---

def test_benefit_list_finds_locked_vn_lots_not_counted_originating():
    hits = supplier_benefit_list([_case(line_status="non_origin")], "CONG TY TNHH MINGJIE VIET NAM")
    assert len(hits) == 1
    assert hits[0]["product_code"] == "TP1"


def test_benefit_list_ignores_non_vn_lots_and_already_originating():
    assert supplier_benefit_list([_case(line_status="non_origin", origin_country="CHINA")], "CONG TY TNHH MINGJIE VIET NAM") == []
    assert supplier_benefit_list([_case(line_status="origin")], "CONG TY TNHH MINGJIE VIET NAM") == []


# --- store validation (pure) ---

def test_record_flip_validates_inputs():
    with pytest.raises(ValueError):
        record_flip(client_id="c", supplier_name="X", action="maybe", evidence_kind="phu_luc_x")
    with pytest.raises(ValueError):
        record_flip(client_id="c", supplier_name="X", action="on", evidence_kind="bogus")
    with pytest.raises(ValueError):
        record_flip(client_id="c", supplier_name="  ", action="on", evidence_kind="phu_luc_x")
    assert EVIDENCE_KINDS == {"phu_luc_x", "co_import"}


# --- routes (file-mode: store refuses loudly, screen renders) ---

def test_flip_route_refuses_without_database(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main_module

    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    client = TestClient(main_module.app)
    response = client.post(
        "/clients/growatt/suppliers/flip",
        json={"supplier_name": "CONG TY TNHH MINGJIE VIET NAM", "action": "on", "evidence_kind": "phu_luc_x"},
    )
    assert response.status_code == 503


def test_flip_route_validates_payload(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main_module

    client = TestClient(main_module.app)
    assert client.post("/clients/growatt/suppliers/flip", json={"action": "on"}).status_code == 400
    assert client.post(
        "/clients/growatt/suppliers/flip", json={"supplier_name": "X", "action": "toggle"}
    ).status_code == 400
    assert client.post(
        "/clients/growatt/suppliers/flip",
        json={"supplier_name": "X", "action": "on", "evidence_kind": "bogus"},
    ).status_code == 400


def test_off_flip_returns_damage_list_before_writing(monkeypatch):
    # confirm_required must be computable (and nothing written) even though the
    # store itself is present — patch availability + case source.
    from fastapi.testclient import TestClient
    import app.main as main_module
    from app import supplier_evidence_store
    from app.routers import pages

    monkeypatch.setattr(supplier_evidence_store, "store_available", lambda: True)
    recorded = []
    monkeypatch.setattr(supplier_evidence_store, "record_flip", lambda **kw: recorded.append(kw) or {"event_id": "sev_x", **kw})
    monkeypatch.setattr(pages, "get_case_workspace", lambda client, case_id="": {"cases": [_case()]})

    client = TestClient(main_module.app)
    url = "/clients/growatt/suppliers/flip"
    body = {"supplier_name": "CONG TY TNHH  MINGJIE VIET NAM", "action": "off", "evidence_kind": "phu_luc_x"}

    preview = client.post(url, json=body).json()
    assert preview["confirm_required"] is True
    # the key is normalized with the ONE shared function (double space collapsed)
    assert preview["supplier_key"] == "CONG TY TNHH MINGJIE VIET NAM"
    assert preview["damage_list"][0]["originating_amount"] == "120"
    assert recorded == []  # cancelling writes nothing

    confirmed = client.post(url, json={**body, "confirm": True}).json()
    assert confirmed["ok"] is True
    assert len(recorded) == 1
    assert recorded[0]["action"] == "off"


def test_on_flip_returns_benefit_list(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main_module
    from app import supplier_evidence_store
    from app.routers import pages

    monkeypatch.setattr(supplier_evidence_store, "store_available", lambda: True)
    monkeypatch.setattr(supplier_evidence_store, "record_flip", lambda **kw: {"event_id": "sev_x", **kw})
    monkeypatch.setattr(pages, "get_case_workspace", lambda client, case_id="": {"cases": [_case(line_status="non_origin")]})

    client = TestClient(main_module.app)
    response = client.post(
        "/clients/growatt/suppliers/flip",
        json={"supplier_name": "CONG TY TNHH MINGJIE VIET NAM", "action": "on", "evidence_kind": "phu_luc_x"},
    ).json()
    assert response["ok"] is True
    assert len(response["benefit_list"]) == 1


def test_curation_screen_lists_suppliers_with_counts(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main_module
    from app import co_stock_materializer

    rows = [
        {"consignee_name": "CONG TY TNHH MINGJIE VIET NAM", "declaration_type": "E15", "origin_country": "VIETNAM"},
        {"consignee_name": "MINGJIE INDUSTRIAL (HK) LIMITED", "declaration_type": "E13", "origin_country": "CHINA"},
    ]
    monkeypatch.setattr(co_stock_materializer, "read_co_stock_rows_cached", lambda client_id: list(rows))
    client = TestClient(main_module.app)
    page = client.get("/clients/growatt/suppliers")
    assert page.status_code == 200
    assert "CONG TY TNHH MINGJIE VIET NAM" in page.text
    # the HK namesake stays a DISTINCT row (no auto-merge)
    assert "MINGJIE INDUSTRIAL (HK) LIMITED" in page.text
    assert "data-supplier-flip" in page.text
    # QA #16: search box + per-row lowered haystack for the client-side filter
    assert "data-supplier-search-input" in page.text
    assert 'data-supplier-search="cong ty tnhh mingjie viet nam' in page.text
    # QA #15: name renders through the wrapping class so a 70-char legal name
    # cannot force the table into horizontal scroll
    assert 'class="mono supplier-name"' in page.text


# --- DB round-trip (append-only) ---

@pytest.mark.skipif(not database_url(), reason="needs BARRY_DATABASE_URL")
def test_append_only_round_trip_latest_event_wins():
    from app.database import apply_migrations
    from app.supplier_evidence_store import current_flags, flagged_suppliers, list_events

    apply_migrations()
    assert store_available()
    client_id = "test-evidence-rt"
    record_flip(client_id=client_id, supplier_name="NCC RT", action="on", evidence_kind="phu_luc_x",
                actor_id="u1", actor_email="a@b.c")
    assert flagged_suppliers(client_id).get("NCC RT", {}).get("action") == "on"
    record_flip(client_id=client_id, supplier_name="NCC RT", action="off", evidence_kind="phu_luc_x",
                actor_id="u2", actor_email="d@e.f")
    flags = current_flags(client_id)
    assert flags["NCC RT"]["action"] == "off"
    assert "NCC RT" not in flagged_suppliers(client_id)
    events = list_events(client_id, "NCC RT")
    assert len(events) >= 2
    assert events[0]["action"] == "off"  # newest first
