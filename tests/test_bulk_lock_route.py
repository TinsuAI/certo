"""Route tests for POST .../origin/bulk-lock (Slice D, #13c — Chốt tất cả).

Locks every origin sheet in product order, committing ledger claims. Sheets
already locked are counted; sheets not yet 'calculated' (or that overclaim) are
skipped — and because locking is sequential, a skipped sheet blocks the ones
after it. The ledger write itself (record_sheet_lock_claims) is stubbed; these
tests cover the lock orchestration + skip-and-report.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def lock_client(monkeypatch, tmp_path):
    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-cases"))
    monkeypatch.setenv("BOM_DEFAULT_CONFIG_ROOT", str(tmp_path / "bom-default"))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    import app.main as main_module
    monkeypatch.setattr(main_module, "require_local_source_writes", lambda: None)
    return TestClient(main_module.app)


def _seed(statuses, client_id="growatt", case_id="case-lock-1"):
    """statuses: list of (code, status)."""
    from app import co_case_store
    now = co_case_store.now_iso()
    case = {
        "id": case_id, "persisted_case_id": case_id, "case_id": case_id,
        "case_code": "CO-LOCK", "title": "Lock test", "customer": "Growatt",
        "destination_market": "Ấn Độ", "status": "open",
        "created_at": now, "updated_at": now,
        "origin_product_order": [c for c, _ in statuses],
        # a covered NVL so the sheet passes the "genuinely ready" lock guard;
        # these tests exercise ordering / overclaim, not emptiness.
        "products": [{"code": c, "name": c, "lvc_status": "pass",
                      "materials": [{"material_code": f"M-{c}", "allocation_status": "covered"}]}
                     for c, _ in statuses],
        "origin_sheet_states": {c: {"status": s, "status_label": s} for c, s in statuses},
    }
    co_case_store.save_state(client_id, {"schema_version": 1, "client_id": client_id, "cases": [case]})
    return case_id


def _stub_claims(monkeypatch, raise_for=None):
    import app.routers.co_case as cc
    from app.co_stock_ledger import StockOverclaimError

    def fake(client_id, case_id, product_code, case):
        if raise_for and product_code == raise_for:
            raise StockOverclaimError([{"source_row": "r1", "claimed": "10", "available": "2"}])
        return 0
    monkeypatch.setattr(cc, "record_sheet_lock_claims", fake)


def _url(case_id):
    return f"/clients/growatt/co-case/{case_id}/origin/bulk-lock"


def test_locks_calculated_sheets_in_order(lock_client, monkeypatch):
    _stub_claims(monkeypatch)
    case_id = _seed([("TP-A", "calculated"), ("TP-B", "calculated")])
    body = lock_client.post(_url(case_id), json={}).json()
    assert body["locked"] == ["TP-A", "TP-B"]
    assert body["skipped"] == []
    from app import co_case_store
    from app.demo_data import get_client
    rec = co_case_store.get_case_record(get_client("growatt"), case_id)
    st = rec["origin_sheet_states"]
    assert st["TP-A"]["status"] == "locked" and st["TP-B"]["status"] == "locked"


def test_uncalculated_skipped_and_blocks_downstream(lock_client, monkeypatch):
    _stub_claims(monkeypatch)
    case_id = _seed([("TP-A", "draft"), ("TP-B", "calculated")])
    body = lock_client.post(_url(case_id), json={}).json()
    assert body["locked"] == []
    skipped_codes = [s["product_code"] for s in body["skipped"]]
    assert skipped_codes == ["TP-A", "TP-B"]   # TP-A not calculated; TP-B blocked by prior


def test_already_locked_counted_not_relocked(lock_client, monkeypatch):
    _stub_claims(monkeypatch)
    case_id = _seed([("TP-A", "locked"), ("TP-B", "calculated")])
    body = lock_client.post(_url(case_id), json={}).json()
    assert body["already_locked"] == ["TP-A"]
    assert body["locked"] == ["TP-B"]


def test_empty_sheet_skipped_not_locked(lock_client, monkeypatch):
    # A "calculated" sheet with no active NVL (empty/no-BOM) must be skipped, not
    # locked — locking would commit an empty bảng kê + 0 claims.
    _stub_claims(monkeypatch)
    from app import co_case_store
    case_id = _seed([("TP-A", "calculated")])
    # strip the seeded material so the sheet is empty
    st = co_case_store.load_state("growatt")
    st["cases"][0]["products"][0]["materials"] = []
    st["cases"][0]["products"][0]["lvc_status"] = "missing_bom"
    co_case_store.save_state("growatt", st)
    body = lock_client.post(_url(case_id), json={}).json()
    assert body["locked"] == []
    assert body["skipped"] and body["skipped"][0]["product_code"] == "TP-A"
    assert "BOM" in body["skipped"][0]["reason"] or "NVL" in body["skipped"][0]["reason"]


def test_overclaim_skips_and_blocks(lock_client, monkeypatch):
    _stub_claims(monkeypatch, raise_for="TP-B")
    case_id = _seed([("TP-A", "calculated"), ("TP-B", "calculated"), ("TP-C", "calculated")])
    body = lock_client.post(_url(case_id), json={}).json()
    assert body["locked"] == ["TP-A"]
    skipped = {s["product_code"]: s["reason"] for s in body["skipped"]}
    assert "TP-B" in skipped and "tồn" in skipped["TP-B"].lower()
    assert "TP-C" in skipped   # blocked because TP-B not locked
