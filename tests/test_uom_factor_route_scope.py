"""POST .../origin/uom-factor — the confirmation's SCOPE.

A ĐVT pair like EA → CAY is usually the same answer for every material declared
under it (johnson-vn: "1 EA = 1 CAY, synonym in Johnson context", applied to 90
catalog codes). `uom_factor_store` has always supported a client-wide row
(`material_code = ""`), but the row control posted `scope: "material"`
unconditionally, so the operator re-answered the same question per code. The modal
now offers both, and this pins that the route honours the choice.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def uom_client(monkeypatch, tmp_path):
    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-cases"))
    monkeypatch.setenv("CO_UOM_FACTOR_ROOT", str(tmp_path / "uom-factors"))
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    import app.main as main_module
    monkeypatch.setattr(main_module, "require_local_source_writes", lambda: None)
    return TestClient(main_module.app)


def _seed(case_id="case-uom-scope"):
    from app import co_case_store
    now = co_case_store.now_iso()
    co_case_store.save_state("growatt", {"schema_version": 1, "client_id": "growatt", "cases": [{
        "id": case_id, "persisted_case_id": case_id, "case_id": case_id,
        "case_code": "CO-UOM", "title": "Uom", "customer": "Growatt",
        "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "products": [{"code": "PV.A", "materials": [{"material_code": "M1", "uom": "EA"}]}],
    }]})
    return case_id


def _post(client, case_id, scope):
    return client.post(
        f"/clients/growatt/co-case/{case_id}/origin/uom-factor",
        json={"material_code": "M1", "bom_uom": "EA", "lot_uom": "CAY",
              "factor": "1", "scope": scope},
    )


def test_material_scope_writes_a_row_for_that_code_only(uom_client):
    from app import uom_factor_store
    case_id = _seed("case-uom-material")
    assert _post(uom_client, case_id, "material").status_code == 200
    # The store canonicalises spellings on write (EA is PIECES), which is also how
    # resolve_uom_factor looks the pair up.
    keys = {row.key() for row in uom_factor_store.list_factors("growatt")}
    assert keys == {("PIECES", "CAY", "M1")}


def test_client_scope_writes_the_pair_for_every_material(uom_client):
    from app import uom_factor_store
    from app.uom_conversion import resolve_uom_factor
    case_id = _seed("case-uom-client")
    assert _post(uom_client, case_id, "client").status_code == 200
    keys = {row.key() for row in uom_factor_store.list_factors("growatt")}
    assert keys == {("PIECES", "CAY")}
    # A material the operator never touched now resolves through the same pair.
    factor, source = resolve_uom_factor(
        "EA", "CAY", confirmed=uom_factor_store.factor_map("growatt"), material_code="M-OTHER",
    )
    assert source == "operator_confirmed"
    assert str(factor) == "1"


def test_a_zero_factor_is_refused(uom_client):
    case_id = _seed("case-uom-zero")
    resp = uom_client.post(
        f"/clients/growatt/co-case/{case_id}/origin/uom-factor",
        json={"material_code": "M1", "bom_uom": "EA", "lot_uom": "CAY",
              "factor": "0", "scope": "material"},
    )
    assert resp.status_code == 400
