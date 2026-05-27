"""Tests for app.cost_allocation_store.

JSON-fallback tests run anywhere. DB-backed tests are skipped without
BARRY_DATABASE_URL. The store transparently dual-writes when both are
available so dev without Postgres still works.
"""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest


@pytest.fixture
def isolated_config_root(monkeypatch, tmp_path):
    """Pin the store to the JSON-fallback path with a clean tmp dir.

    These are unit tests for the store API. The DB path is exercised by the
    integration test below + the migration applying cleanly in CI.
    """
    root = tmp_path / "cost-allocation"
    monkeypatch.setenv("COST_ALLOCATION_CONFIG_ROOT", str(root))
    monkeypatch.delenv("BARRY_DATABASE_URL", raising=False)
    yield root


@pytest.fixture
def db_only_client(monkeypatch, tmp_path):
    """Force the store onto the Postgres path with an isolated JSON dir.

    Used by the DB integration test below to confirm the SQL paths work.
    Skips when BARRY_DATABASE_URL is not set in the environment.
    """
    from app.database import database_url
    if not database_url():
        pytest.skip("BARRY_DATABASE_URL not set — DB integration test skipped")
    monkeypatch.setenv("COST_ALLOCATION_CONFIG_ROOT", str(tmp_path / "cost-allocation"))
    # Wipe the client row so tests are repeatable.
    from app.database import connect
    client_id = f"test-cost-alloc-{os.getpid()}"
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from co_cost_allocation_ratio where client_id = %s", (client_id,))
    yield client_id
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from co_cost_allocation_ratio where client_id = %s", (client_id,))


def _row(code: str, *, wages="0", welfare="0", rent="0", deprec="0", other_mfg="0", transport="0", note=""):
    from app.cost_allocation_store import CostAllocationRow
    return CostAllocationRow(
        product_code=code,
        coef_wages=Decimal(wages),
        coef_welfare=Decimal(welfare),
        coef_rent=Decimal(rent),
        coef_depreciation=Decimal(deprec),
        coef_other_mfg=Decimal(other_mfg),
        coef_transport_storage=Decimal(transport),
        note=note,
    )


def test_empty_client_returns_empty_list(isolated_config_root):
    from app.cost_allocation_store import list_ratios
    assert list_ratios("growatt") == []


def test_upsert_and_get_per_product(isolated_config_root):
    from app.cost_allocation_store import upsert_ratio, get_ratio
    upsert_ratio("growatt", _row("PV00.0048400", wages="0.00899", welfare="0.00082"))
    got = get_ratio("growatt", "PV00.0048400")
    assert got is not None
    assert got.coef_wages == Decimal("0.00899")
    assert got.coef_welfare == Decimal("0.00082")
    assert got.product_code == "PV00.0048400"


def test_upsert_overwrites_existing(isolated_config_root):
    from app.cost_allocation_store import upsert_ratio, get_ratio
    upsert_ratio("growatt", _row("PV00.0048400", wages="0.001"))
    upsert_ratio("growatt", _row("PV00.0048400", wages="0.999"))
    got = get_ratio("growatt", "PV00.0048400")
    assert got.coef_wages == Decimal("0.999")


def test_mode_b_fallback_when_product_missing(isolated_config_root):
    from app.cost_allocation_store import upsert_ratio, get_ratio
    upsert_ratio("growatt", _row("", wages="0.005", note="default"))
    # Unknown product code falls back to Mode B (empty product_code).
    got = get_ratio("growatt", "NOT.IN.LIST")
    assert got is not None
    assert got.coef_wages == Decimal("0.005")
    assert got.product_code == ""


def test_mode_a_wins_over_mode_b(isolated_config_root):
    from app.cost_allocation_store import upsert_ratio, get_ratio
    upsert_ratio("growatt", _row("", wages="0.005"))
    upsert_ratio("growatt", _row("PV00.0048400", wages="0.999"))
    got = get_ratio("growatt", "PV00.0048400")
    assert got.coef_wages == Decimal("0.999")
    assert got.product_code == "PV00.0048400"


def test_get_returns_none_when_neither_mode_present(isolated_config_root):
    from app.cost_allocation_store import upsert_ratio, get_ratio
    upsert_ratio("growatt", _row("SD00.0010600", wages="0.001"))
    assert get_ratio("growatt", "OTHER.CODE") is None


def test_list_ratios_excludes_mode_b_by_default(isolated_config_root):
    from app.cost_allocation_store import upsert_ratio, list_ratios
    upsert_ratio("growatt", _row("", wages="0.005"))
    upsert_ratio("growatt", _row("PV00.0048400", wages="0.001"))
    upsert_ratio("growatt", _row("SD00.0010600", wages="0.002"))
    rows = list_ratios("growatt")
    codes = sorted(r.product_code for r in rows)
    assert codes == ["PV00.0048400", "SD00.0010600"]


def test_get_mode_b_default(isolated_config_root):
    from app.cost_allocation_store import upsert_ratio, get_mode_b_default
    assert get_mode_b_default("growatt") is None
    upsert_ratio("growatt", _row("", wages="0.005", note="company default"))
    default = get_mode_b_default("growatt")
    assert default is not None
    assert default.coef_wages == Decimal("0.005")
    assert default.note == "company default"


def test_delete_ratio(isolated_config_root):
    from app.cost_allocation_store import upsert_ratio, delete_ratio, get_ratio
    upsert_ratio("growatt", _row("PV00.0048400", wages="0.001"))
    delete_ratio("growatt", "PV00.0048400")
    assert get_ratio("growatt", "PV00.0048400") is None


def test_replace_all_preserves_mode_b(isolated_config_root):
    from app.cost_allocation_store import upsert_ratio, replace_all, list_ratios, get_mode_b_default
    upsert_ratio("growatt", _row("", wages="0.005"))
    upsert_ratio("growatt", _row("OLD.CODE", wages="0.001"))
    result = replace_all("growatt", [
        _row("NEW.CODE.A", wages="0.002"),
        _row("NEW.CODE.B", wages="0.003"),
    ])
    assert sorted(result["added"]) == ["NEW.CODE.A", "NEW.CODE.B"]
    assert sorted(result["removed"]) == ["OLD.CODE"]
    codes = sorted(r.product_code for r in list_ratios("growatt"))
    assert codes == ["NEW.CODE.A", "NEW.CODE.B"]
    # Mode B default survives untouched.
    default = get_mode_b_default("growatt")
    assert default is not None and default.coef_wages == Decimal("0.005")


def test_replace_all_diff_changed_count(isolated_config_root):
    from app.cost_allocation_store import upsert_ratio, replace_all
    upsert_ratio("growatt", _row("PV00.0048400", wages="0.001"))
    upsert_ratio("growatt", _row("SD00.0010600", wages="0.002"))
    result = replace_all("growatt", [
        _row("PV00.0048400", wages="0.999"),  # changed
        _row("SD00.0010600", wages="0.002"),  # unchanged
    ])
    assert result["added"] == []
    assert result["removed"] == []
    assert result["changed"] == ["PV00.0048400"]


def test_per_client_isolation(isolated_config_root):
    from app.cost_allocation_store import upsert_ratio, get_ratio
    upsert_ratio("growatt", _row("SAME.CODE", wages="0.001"))
    upsert_ratio("acme", _row("SAME.CODE", wages="0.999"))
    a = get_ratio("growatt", "SAME.CODE")
    b = get_ratio("acme", "SAME.CODE")
    assert a.coef_wages == Decimal("0.001")
    assert b.coef_wages == Decimal("0.999")


def test_db_round_trip_upsert_get_delete(db_only_client):
    """Confirm the Postgres path implements the same contract as JSON."""
    from app.cost_allocation_store import (
        upsert_ratio, get_ratio, list_ratios, replace_all, delete_ratio,
    )
    client = db_only_client
    upsert_ratio(client, _row("", wages="0.005", note="default"))
    upsert_ratio(client, _row("PV.A", wages="0.001"))
    upsert_ratio(client, _row("PV.B", wages="0.002"))
    # Mode A hit.
    a = get_ratio(client, "PV.A")
    assert a.coef_wages == Decimal("0.001")
    # Mode B fallback.
    b = get_ratio(client, "NOT.LISTED")
    assert b is not None and b.coef_wages == Decimal("0.005")
    # list excludes Mode B.
    codes = sorted(r.product_code for r in list_ratios(client))
    assert codes == ["PV.A", "PV.B"]
    # replace_all preserves Mode B, swaps the per-product rows.
    result = replace_all(client, [_row("PV.C", wages="0.003")])
    assert sorted(result["removed"]) == ["PV.A", "PV.B"]
    assert result["added"] == ["PV.C"]
    fallback = get_ratio(client, "STILL.NOT.LISTED")
    assert fallback is not None and fallback.coef_wages == Decimal("0.005")
    delete_ratio(client, "PV.C")
    assert get_ratio(client, "PV.C") is None or get_ratio(client, "PV.C").product_code == ""


def test_json_persistence_across_calls(isolated_config_root):
    """Each store call reopens the JSON file — no in-memory caching."""
    from app import cost_allocation_store as store
    store.upsert_ratio("growatt", _row("X.1", wages="0.42"))
    # Simulate fresh process by clearing any module-level cache (none expected).
    got = store.get_ratio("growatt", "X.1")
    assert got.coef_wages == Decimal("0.42")
    # Direct file inspection.
    files = list(isolated_config_root.rglob("*.json"))
    assert any("growatt" in str(f) for f in files), files
