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
    # Severity stays warn_cross_family — families ARE different.
    # `resolved_by_override` flag indicates that the difference is
    # bridged by an explicit factor (UI shows green check, no block).
    assert drifts[0]["severity"] == "warn_cross_family"
    assert drifts[0]["resolved_by_override"] is True


def test_tier_a_severity_stays_warn_when_unconfirmed_default():
    """Tier-A 1:1 default is a guess, not a confirmation. Severity must
    stay warn_cross_family until staff inserts an explicit override."""
    rows = [{"material_code": "M_TIER_A", "uom": "EA"}]
    drifts = compute_uom_drifts(CLIENT, rows)
    assert len(drifts) == 1
    assert drifts[0]["severity"] == "warn_cross_family"
    assert drifts[0]["conversion"]["source"] == "unconfirmed_default"


def test_has_blocking_drift_respects_conversion_path():
    """has_blocking_drift only blocks when there's no conversion path.
    Tier-B without override → blocks. Tier-A default → allows. Override
    row → allows."""
    from app.stores.uom_drift import has_blocking_drift
    # Tier-B without override.
    drifts_b = compute_uom_drifts(
        CLIENT, [{"material_code": "M_TIER_B", "uom": "EA"}])
    assert has_blocking_drift(drifts_b) is True
    # Tier-A: default 1:1 path exists, doesn't block (but stays warn).
    drifts_a = compute_uom_drifts(
        CLIENT, [{"material_code": "M_TIER_A", "uom": "EA"}])
    assert has_blocking_drift(drifts_a) is False
    # Override row added → tier-B no longer blocks.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'M_TIER_B', 'EA', 'KG', 0.5, 'supplier_data')",
            (CLIENT,))
    drifts_b2 = compute_uom_drifts(
        CLIENT, [{"material_code": "M_TIER_B", "uom": "EA"}])
    assert has_blocking_drift(drifts_b2) is False
