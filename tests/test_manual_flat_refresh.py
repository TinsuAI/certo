"""Phase 2 round 3 — manual_flat refresh re-applies UoM conversion.

User feedback: "khong refresh duoc la sao? Nghia la mot khi da parse
thi co them he so vao cung chiu?"

Manual_flat artifacts now refresh by reconstructing originals from
source_uom audit columns + re-running convert with current state.
Hash diff tombstones original (immutable principle), same hash dedups.
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.database import connect
from app.stores.bom import create_artifact
from app.stores.bom_staleness import (
    _reconstruct_originals_from_artifact,
    refresh_artifact,
)


CLIENT = "_mf_refresh_test"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict do nothing", (CLIENT, "manual_flat refresh test"))
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, status, uom) values "
            "(%s, 'TP_MF', 'TP', 'tp', 'active', 'KG'), "
            "(%s, 'M_MF', 'NVL', 'nvl', 'active', 'KG')",
            (CLIENT, CLIENT))
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.bom_artifact_rows where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (CLIENT,))
        cur.execute("delete from hub.bom_artifacts where client_id=%s",
                     (CLIENT,))
        cur.execute("delete from hub.client_uom_overrides where client_id=%s",
                     (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _make_manual_flat_artifact(rows: list[dict]) -> str:
    """Create a manual_flat artifact via the public store API. Goes
    through the convert layer if rows lack audit columns; preserves
    audit columns when present."""
    return create_artifact(
        client_id=CLIENT, product_code="TP_MF", rows=rows,
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None,
        context={"channel": "agency_upload", "profile": "manual_flat"},
        source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="not_applicable",
        flatten_strategy="manual_flat_as_provided",
        source_channel="agency_upload",
        flatten_method="manual_flat", flatten_method_version="1",
    )


# ── _reconstruct_originals_from_artifact ────────────────────────────


def test_reconstruct_with_factor_inverts_conversion():
    """Row stored as 4 ST with source_uom=SETS, factor=4. Reconstruct
    should give back qty=1 SETS."""
    aid = _make_manual_flat_artifact(rows=[{
        "material_code": "M_MF",
        "qty_per_unit": 4.0, "uom": "ST",
        "source_uom": "SETS",
        "applied_uom_factor": 4.0,
        "applied_uom_source": "client_specific",
    }])
    with connect() as conn, conn.cursor() as cur:
        originals = _reconstruct_originals_from_artifact(cur, aid)
    assert len(originals) == 1
    o = originals[0]
    assert o["material_code"] == "M_MF"
    assert o["uom"] == "SETS"
    assert o["qty_per_unit"] == pytest.approx(1.0)


def test_reconstruct_alias_keeps_qty():
    """Alias source (factor=1) keeps qty as-is. orig_uom=source_uom."""
    aid = _make_manual_flat_artifact(rows=[{
        "material_code": "M_MF",
        "qty_per_unit": 5.0, "uom": "ST",
        "source_uom": "PCS",
        "applied_uom_factor": 1.0,
        "applied_uom_source": "alias",
    }])
    with connect() as conn, conn.cursor() as cur:
        originals = _reconstruct_originals_from_artifact(cur, aid)
    o = originals[0]
    assert o["uom"] == "PCS"
    assert o["qty_per_unit"] == pytest.approx(5.0)


def test_reconstruct_no_audit_keeps_uom_qty():
    """Pre-Phase-2 rows without audit columns: source_uom NULL.
    Reconstruct treats current uom + qty as the original."""
    aid = _make_manual_flat_artifact(rows=[{
        "material_code": "M_MF",
        "qty_per_unit": 7.0, "uom": "kg",
        # No source_uom / applied_uom_factor / applied_uom_source
    }])
    with connect() as conn, conn.cursor() as cur:
        originals = _reconstruct_originals_from_artifact(cur, aid)
    o = originals[0]
    assert o["uom"] == "kg"
    assert o["qty_per_unit"] == pytest.approx(7.0)


# ── refresh_artifact for manual_flat ────────────────────────────────


def test_refresh_manual_flat_applies_new_factor():
    """User flow: ingested manual_flat with no factor → row stored raw
    with factor_missing drift. Add factor → refresh → row converts +
    drift clears."""
    # Initial ingest: factor missing for EA→KG cross-family.
    aid = _make_manual_flat_artifact(rows=[{
        "material_code": "M_MF",
        "qty_per_unit": 10.0, "uom": "EA",  # raw kept
        "source_uom": "EA",
        "applied_uom_factor": None,
        "applied_uom_source": None,
    }])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.bom_artifacts set has_uom_drift=true, "
            "uom_drift_reasons=%s::jsonb, uom_drift_first_at=now() "
            "where artifact_id=%s",
            (json.dumps([{"dim": "factor_missing",
                          "source_table": "hub.client_uom_overrides",
                          "source_pk": "M_MF",
                          "material_code": "M_MF",
                          "observed_at": "2026-05-12T00:00:00Z"}]),
             aid))

    # Add factor.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'M_MF', 'EA', 'KG', 0.5, 'supplier_data')",
            (CLIENT,))

    # Refresh manual_flat.
    result = refresh_artifact(CLIENT, aid)
    assert result["new_artifact_ids"], "refresh should mint or return artifact"
    new_id = result["new_artifact_ids"][0]
    assert new_id != aid, "factor-changed → diff hash → new artifact"

    # Verify new row converted; old artifact tombstoned.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select uom, qty_per_unit::text, source_uom, "
            "applied_uom_factor::text, applied_uom_source "
            "from hub.bom_artifact_rows where artifact_id=%s", (new_id,))
        new_row = cur.fetchone()
        cur.execute(
            "select tombstoned_at, tombstone_reason from hub.bom_artifacts "
            "where artifact_id=%s", (aid,))
        tomb_at, tomb_reason = cur.fetchone()
        cur.execute(
            "select has_uom_drift from hub.bom_artifacts where artifact_id=%s",
            (new_id,))
        new_drift = cur.fetchone()[0]

    assert new_row[0] == "KG"
    assert float(new_row[1]) == pytest.approx(5.0)  # 10 EA × 0.5 = 5 KG
    assert new_row[2] == "EA"  # source_uom preserved
    assert float(new_row[3]) == pytest.approx(0.5)
    assert new_row[4] == "client_specific"
    assert tomb_at is not None
    assert tomb_reason == f"superseded_by_refresh:{new_id}"
    assert new_drift is False, \
        "no remaining drift on new artifact after factor applied"


def test_refresh_manual_flat_same_state_no_supersede():
    """Refresh without state change → same hash → returns existing
    artifact id, no tombstone, just clears flag."""
    aid = _make_manual_flat_artifact(rows=[{
        "material_code": "M_MF",
        "qty_per_unit": 2.0, "uom": "KG",
        "source_uom": "KG",
        "applied_uom_factor": 1.0,
        "applied_uom_source": "alias",
    }])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.bom_artifacts set has_uom_drift=true, "
            "uom_drift_reasons='[]'::jsonb, uom_drift_first_at=now() "
            "where artifact_id=%s", (aid,))

    result = refresh_artifact(CLIENT, aid)
    assert result["new_artifact_ids"] == [aid], \
        "same state should return original id (hash dedup)"

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select tombstoned_at, has_uom_drift from hub.bom_artifacts "
            "where artifact_id=%s", (aid,))
        tomb, drift = cur.fetchone()
    assert tomb is None
    assert drift is False


def test_refresh_manual_flat_with_remaining_drift_keeps_flag():
    """If after refresh there's still drift (e.g. catalog UoM still
    null, factor still missing), the new artifact keeps has_uom_drift
    until the underlying issue resolves."""
    aid = _make_manual_flat_artifact(rows=[{
        "material_code": "M_MF",
        "qty_per_unit": 3.0, "uom": "EA",  # cross-family with KG; no factor
        "source_uom": "EA",
        "applied_uom_factor": None,
        "applied_uom_source": None,
    }])
    # No override added → tier-B factor_missing remains.
    result = refresh_artifact(CLIENT, aid)
    new_id = result["new_artifact_ids"][0]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select has_uom_drift, uom_drift_reasons "
            "from hub.bom_artifacts where artifact_id=%s", (new_id,))
        drift, reasons = cur.fetchone()
    assert drift is True
    dims = sorted({r["dim"] for r in reasons})
    assert "factor_missing" in dims
