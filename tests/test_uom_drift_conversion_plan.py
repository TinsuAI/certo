"""Phase 2 step 5 — `compute_uom_drifts` returns conversion plan.

Each drift entry now carries a `conversion` block:
  {factor, source, target_uom, would_block}

so the preview UI can show the converted value or a 'thiếu hệ số'
prompt + 'Add factor' link.
"""
from __future__ import annotations

import pytest

from app.database import connect
from app.stores.uom_drift import compute_uom_drifts


CLIENT = "_drift_plan_test"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict do nothing", (CLIENT, "drift plan test"))
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, status, uom) values "
            "(%s, 'M_MASS', 'mass mat', 'nvl', 'active', 'kg'), "
            "(%s, 'M_TIER_A', 'tier-a mat', 'nvl', 'active', 'SETS'), "
            "(%s, 'M_TIER_B', 'tier-b mat', 'nvl', 'active', 'KG')",
            (CLIENT, CLIENT, CLIENT))
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.client_uom_overrides where client_id=%s",
                     (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def test_same_family_drift_emits_conversion_plan_with_factor():
    rows = [{"material_code": "M_MASS", "uom": "g"}]
    drifts = compute_uom_drifts(CLIENT, rows)
    assert len(drifts) == 1
    conv = drifts[0]["conversion"]
    assert conv is not None
    assert conv["target_uom"] == "kg"
    assert conv["source"] == "global"
    assert conv["factor"] == "0.001"
    assert conv["would_block"] is False


def test_tier_a_drift_emits_unconfirmed_default_plan():
    rows = [{"material_code": "M_TIER_A", "uom": "EA"}]
    drifts = compute_uom_drifts(CLIENT, rows)
    assert len(drifts) == 1
    conv = drifts[0]["conversion"]
    assert conv is not None
    assert conv["target_uom"] == "SETS"
    assert conv["source"] == "unconfirmed_default"
    assert conv["factor"] == "1"
    assert conv["would_block"] is False


def test_tier_b_drift_without_override_would_block():
    rows = [{"material_code": "M_TIER_B", "uom": "EA"}]
    drifts = compute_uom_drifts(CLIENT, rows)
    assert len(drifts) == 1
    conv = drifts[0]["conversion"]
    assert conv is not None
    assert conv["target_uom"] == "KG"
    assert conv["factor"] is None
    assert conv["source"] is None
    assert conv["would_block"] is True


def test_tier_b_with_override_would_not_block():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'M_TIER_B', 'EA', 'KG', 0.5, 'supplier_data')",
            (CLIENT,))
    rows = [{"material_code": "M_TIER_B", "uom": "EA"}]
    drifts = compute_uom_drifts(CLIENT, rows)
    assert len(drifts) == 1
    conv = drifts[0]["conversion"]
    assert conv is not None
    assert float(conv["factor"]) == pytest.approx(0.5)
    assert conv["source"] == "client_specific"
    assert conv["would_block"] is False
