"""End-to-end route tests for /clients/{id}/cost-allocation admin UI.

Use a tmp config root + no BARRY_DATABASE_URL so the store stays on the
JSON fallback path. Each test gets a fresh dir.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


SAMPLE_PATH = Path(".ai/samples/BANG-PHAN-BO-TY-LE-CHI-PHI.xlsx")


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("COST_ALLOCATION_CONFIG_ROOT", str(tmp_path / "cost-allocation"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    # Mock auth gate.
    import app.main as main_module
    monkeypatch.setattr(main_module, "require_local_source_writes", lambda: None)
    return TestClient(main_module.app)


def test_get_page_renders_for_known_client(client):
    resp = client.get("/clients/growatt/cost-allocation")
    assert resp.status_code == 200
    assert "Hệ số phân bổ" in resp.text
    assert "Mặc định cả doanh nghiệp" in resp.text


def test_save_mode_b_default(client):
    resp = client.post(
        "/clients/growatt/cost-allocation/mode-b",
        data={
            "coef_wages": "0.005",
            "coef_welfare": "0.001",
            "coef_rent": "0",
            "coef_depreciation": "0",
            "coef_other_mfg": "0",
            "coef_transport_storage": "0.002",
            "note": "company default",
        },
    )
    assert resp.status_code == 200
    assert "Đã lưu hệ số mặc định Mode B" in resp.text
    # Reload page picks up the saved row.
    page = client.get("/clients/growatt/cost-allocation")
    assert "0.005" in page.text


def test_upload_sample_file_imports_24_rows(client):
    if not SAMPLE_PATH.exists():
        pytest.skip(f"{SAMPLE_PATH} missing")
    with SAMPLE_PATH.open("rb") as fh:
        resp = client.post(
            "/clients/growatt/cost-allocation/upload",
            files={"file": ("sample.xlsx", fh.read(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert resp.status_code == 200
    assert "Đã import 24 dòng" in resp.text
    assert "PV00.0048400" in resp.text


def test_resolve_returns_mode_a_when_product_match(client):
    # Seed via upsert API.
    from app import cost_allocation_store
    from app.cost_allocation_store import CostAllocationRow
    cost_allocation_store.upsert_ratio("growatt", CostAllocationRow(
        product_code="PV.X",
        coef_wages=Decimal("0.01"),
        coef_welfare=Decimal("0.02"),
        coef_rent=Decimal("0.03"),
        coef_depreciation=Decimal("0.04"),
        coef_other_mfg=Decimal("0.05"),
        coef_transport_storage=Decimal("0.06"),
    ))
    resp = client.get("/clients/growatt/cost-allocation/resolve", params={"product_code": "PV.X", "fob": "1000"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["matched_mode"] == "A"
    assert body["details"]["wages"] == "10.00"
    assert body["details"]["transport_storage"] == "60.00"


def test_resolve_falls_back_to_mode_b(client):
    from app import cost_allocation_store
    from app.cost_allocation_store import CostAllocationRow
    cost_allocation_store.upsert_ratio("growatt", CostAllocationRow(
        product_code="",  # Mode B
        coef_wages=Decimal("0.001"),
    ))
    resp = client.get("/clients/growatt/cost-allocation/resolve", params={"product_code": "UNKNOWN.CODE", "fob": "5000"})
    body = resp.json()
    assert body["found"] is True
    assert body["matched_mode"] == "B"
    assert body["details"]["wages"] == "5.00"


def test_resolve_returns_not_found_when_no_match(client):
    resp = client.get("/clients/growatt/cost-allocation/resolve", params={"product_code": "MISSING", "fob": "100"})
    body = resp.json()
    assert body["found"] is False


def test_delete_row(client):
    from app import cost_allocation_store
    from app.cost_allocation_store import CostAllocationRow
    cost_allocation_store.upsert_ratio("growatt", CostAllocationRow(product_code="GONE", coef_wages=Decimal("0.001")))
    resp = client.post(
        "/clients/growatt/cost-allocation/row/delete",
        data={"product_code": "GONE"},
    )
    assert resp.status_code == 200
    assert cost_allocation_store.get_ratio("growatt", "GONE") is None


def test_template_download(client):
    resp = client.get("/clients/growatt/cost-allocation/template.xlsx")
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]
    assert "cost-allocation-growatt-template.xlsx" in resp.headers["content-disposition"]


# ---------- Bulk "Áp hệ số cho tất cả SP" endpoint (Mục 4a) ----------


@pytest.fixture
def bulk_client(monkeypatch, tmp_path):
    monkeypatch.setenv("COST_ALLOCATION_CONFIG_ROOT", str(tmp_path / "cost-allocation"))
    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-cases"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    import app.main as main_module
    monkeypatch.setattr(main_module, "require_local_source_writes", lambda: None)
    return TestClient(main_module.app)


def _seed_bulk_case(client_id="growatt", case_id="case-bulk-1"):
    from app import co_case_store
    now = co_case_store.now_iso()
    case = {
        "id": case_id, "persisted_case_id": case_id, "case_id": case_id,
        "case_code": "CO-TEST", "title": "Bulk test", "customer": "Growatt",
        "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "products": [
            {"code": "PV.A", "fob": "100000", "cost_buildup": {}},
            {"code": "PV.B", "fob": "100000", "cost_buildup": {}},
        ],
        "origin_sheet_states": {
            "PV.A": {"criteria_override": "RVC 35%"},
            "PV.B": {"criteria_override": "RVC 35%"},
        },
    }
    co_case_store.save_state(client_id, {"schema_version": 1, "client_id": client_id, "cases": [case]})
    return case_id


def _seed_ratios():
    from app import cost_allocation_store
    from app.cost_allocation_store import CostAllocationRow
    cost_allocation_store.upsert_ratio("growatt", CostAllocationRow(
        product_code="PV.A", coef_wages=Decimal("0.03"), coef_welfare=Decimal("0.005"),
        coef_rent=Decimal("0.01"), coef_depreciation=Decimal("0.008"),
        coef_other_mfg=Decimal("0.004"), coef_transport_storage=Decimal("0.003"),
    ))
    cost_allocation_store.upsert_ratio("growatt", CostAllocationRow(
        product_code="", coef_wages=Decimal("0.02"),  # Mode B default
    ))


def test_bulk_endpoint_applies_and_persists(bulk_client):
    case_id = _seed_bulk_case()
    _seed_ratios()
    resp = bulk_client.post(f"/clients/growatt/co-case/{case_id}/origin/bulk-apply-cost")
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] == [{"code": "PV.A", "mode": "A"}, {"code": "PV.B", "mode": "B"}]
    # Persisted into the case cost_buildup.
    from app import co_case_store
    from app.demo_data import get_client
    record = co_case_store.get_case_record(get_client("growatt"), case_id)
    by_code = {p["code"]: p for p in record["products"]}
    assert by_code["PV.A"]["cost_buildup"]["wages"] == "3000.00"   # 0.03 × 100000
    assert by_code["PV.B"]["cost_buildup"]["wages"] == "2000.00"   # Mode B 0.02 × 100000


def test_bulk_endpoint_skips_filled_unless_overwrite(bulk_client):
    from app import co_case_store
    from app.demo_data import get_client
    case_id = _seed_bulk_case()
    _seed_ratios()
    # Pre-fill PV.A by hand.
    state = co_case_store.load_state("growatt")
    state["cases"][0]["products"][0]["cost_buildup"] = {"wages": "777"}
    co_case_store.save_state("growatt", state)

    body = bulk_client.post(f"/clients/growatt/co-case/{case_id}/origin/bulk-apply-cost").json()
    assert body["skipped_filled"] == ["PV.A"]
    assert [a["code"] for a in body["applied"]] == ["PV.B"]
    record = co_case_store.get_case_record(get_client("growatt"), case_id)
    assert {p["code"]: p for p in record["products"]}["PV.A"]["cost_buildup"]["wages"] == "777"

    # overwrite=1 recomputes PV.A.
    body2 = bulk_client.post(
        f"/clients/growatt/co-case/{case_id}/origin/bulk-apply-cost", data={"overwrite": "1"}
    ).json()
    assert {a["code"] for a in body2["applied"]} == {"PV.A", "PV.B"}
    record2 = co_case_store.get_case_record(get_client("growatt"), case_id)
    assert {p["code"]: p for p in record2["products"]}["PV.A"]["cost_buildup"]["wages"] == "3000.00"
