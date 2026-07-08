"""Cross-dossier correctness for the substitute-modal stock endpoint.

Finding D (2026-07-08 batch cross-dossier review): the substitute picker's tồn
comes from GET .../origin/sheet/{code}/substitute-stock, which reads the raw
materialized snapshot (`read_co_stock_rows_cached`) and reports `remaining_qty`
directly. It must ALSO subtract live ledger claims held by OTHER dossiers of the
same client (`used_qty_by_lot`), exactly like the calculate path
(`_calculate_stock_rows_from_snapshot` -> `apply_used_qty`). Otherwise dossier B
sees a lot as fully available while dossier A has already locked most of it —
misleading the operator into picking a substitute that is actually claimed.

This is a preview/advisory surface (no ledger write), so we only assert the
displayed tồn is NET of other dossiers' locked claims.
"""
from __future__ import annotations

from decimal import Decimal

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


def _seed_case(client_id="growatt", case_id="case-sub-stock-1"):
    from app import co_case_store
    now = co_case_store.now_iso()
    case = {
        "id": case_id, "persisted_case_id": case_id, "case_id": case_id,
        "case_code": "CO-SUBSTOCK", "title": "Substitute stock test", "customer": "Growatt",
        "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "products": [{"code": "PV.A", "fob": "100000"}],
    }
    co_case_store.save_state(client_id, {"schema_version": 1, "client_id": client_id, "cases": [case]})
    return case_id


def _lot(remaining="1000") -> dict:
    """One eligible CO-stock lot of material A1, gross `remaining` on the snapshot."""
    return {
        "material_code": "A1",
        "allocation_code": "A1",
        "allocation_code_status": "resolved",
        "available_qty": remaining,
        "remaining_qty": remaining,
        "eligibility_status": "active",
        "unit_value": "5",
        "currency": "USD",
        "source_row": "S1",
        "import_declaration_no": "IMP1",
        "line_no": "1",
    }


def test_substitute_stock_nets_other_dossier_locked_claims(sub_client, monkeypatch):
    """Lot S1 has 1000 gross tồn; another dossier holds a locked claim of 800 on
    it. The substitute endpoint must report 200 available (net), not 1000 gross."""
    from app import co_stock_ledger, co_stock_materializer
    case_id = _seed_case()

    monkeypatch.setattr(
        co_stock_materializer, "read_co_stock_rows_cached", lambda client_id: [_lot("1000")]
    )
    # A DIFFERENT dossier of this client has locked 800 of lot S1.
    monkeypatch.setattr(
        co_stock_ledger, "used_qty_by_lot", lambda client_id: {"S1": Decimal("800")}
    )

    resp = sub_client.get(
        "/clients/growatt/co-case/%s/origin/sheet/PV.A/substitute-stock?codes=A1" % case_id
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    a1 = body["stock"]["A1"]
    # NET of the other dossier's 800 locked claim, not the raw 1000.
    assert Decimal(a1["total_remaining_qty"]) == Decimal("200")
    assert a1["lots"], "expected the lot to be listed"
    assert Decimal(a1["lots"][0]["remaining_qty"]) == Decimal("200")


def test_substitute_stock_gross_when_no_claims(sub_client, monkeypatch):
    """Positive control: no ledger claims -> full 1000 shown (overlay is a no-op)."""
    from app import co_stock_ledger, co_stock_materializer
    case_id = _seed_case(case_id="case-sub-stock-2")

    monkeypatch.setattr(
        co_stock_materializer, "read_co_stock_rows_cached", lambda client_id: [_lot("1000")]
    )
    monkeypatch.setattr(co_stock_ledger, "used_qty_by_lot", lambda client_id: {})

    resp = sub_client.get(
        "/clients/growatt/co-case/%s/origin/sheet/PV.A/substitute-stock?codes=A1" % case_id
    )
    assert resp.status_code == 200
    a1 = resp.json()["stock"]["A1"]
    assert Decimal(a1["total_remaining_qty"]) == Decimal("1000")
