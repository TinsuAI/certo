"""Mig 057 — manual_flat UoM drift signal.

Verifies:
- has_uom_drift column exists with proper default + index
- bom_mark_uom_drift helper marks only source artifacts
- D7 trigger extension fires on manual_flat when materials.uom edits
- Derived artifacts use is_stale, not has_uom_drift (separation)
- @> dedup prevents duplicate reasons
"""
from __future__ import annotations

import json

import pytest

from app.database import connect


CLIENT = "_uom_drift_test"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict do nothing",
            (CLIENT, "uom drift test"))
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.bom_artifact_rows where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (CLIENT,))
        cur.execute(
            "delete from hub.bom_edges where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (CLIENT,))
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _seed_material(cur, code, uom):
    cur.execute(
        "insert into hub.materials (client_id, material_code, name, "
        "category, status, uom) values (%s, %s, %s, 'nvl', 'active', %s) "
        "on conflict (client_id, material_code) do update set "
        "uom=excluded.uom",
        (CLIENT, code, code, uom))


def _insert_artifact(cur, artifact_id, product_code, strategy, source_kind,
                      rows: list[tuple] = ()):
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, "
        "product_code, artifact_no, status, actor, intent, "
        "context, normalized_hash, row_count, source_bom_kind, "
        "flatten_status, flatten_strategy, source_channel, "
        "bom_variant_id, lineage, flatten_method, "
        "flatten_method_version, published_at) "
        "values (%s, %s, %s, 1, 'published', 'agency_staff', "
        "'asserted_technical', '{}', %s, %s, %s, %s, %s, "
        "'agency_upload', 'default', '{}', 'as_provided', 'v1', now())",
        (artifact_id, CLIENT, product_code, f"h_{artifact_id}",
         len(rows), source_kind,
         "not_applicable" if strategy == "manual_flat_as_provided"
            else ("non_flattened" if source_kind == "technical_raw"
                  else "flattened"),
         strategy))
    for idx, (mat, qty, uom) in enumerate(rows):
        cur.execute(
            "insert into hub.bom_artifact_rows (artifact_id, row_index, "
            "material_code, qty_per_unit, uom) values (%s, %s, %s, %s, %s)",
            (artifact_id, idx, mat, qty, uom))


# ── Schema ────────────────────────────────────────────────────────────


def test_has_uom_drift_column_exists():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            select column_name, data_type, column_default
            from information_schema.columns
            where table_schema='hub' and table_name='bom_artifacts'
              and column_name in ('has_uom_drift', 'uom_drift_reasons',
                                   'uom_drift_first_at',
                                   'uom_drift_resolved_at')
            order by column_name
        """)
        cols = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    assert "has_uom_drift" in cols and cols["has_uom_drift"][0] == "boolean"
    assert "uom_drift_reasons" in cols and cols["uom_drift_reasons"][0] == "jsonb"
    assert "uom_drift_first_at" in cols
    assert "uom_drift_resolved_at" in cols


def test_index_on_has_uom_drift_exists():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            select indexname from pg_indexes
            where schemaname='hub' and tablename='bom_artifacts'
              and indexname='idx_bom_artifacts_has_uom_drift'
        """)
        assert cur.fetchone() is not None


# ── Helper bom_mark_uom_drift filters by strategy ────────────────────


def test_helper_marks_manual_flat():
    with connect() as conn, conn.cursor() as cur:
        _insert_artifact(cur, "ba_mf", "P1", "manual_flat_as_provided",
                          source_kind="technical_flattened",
                          rows=[("M1", 1.0, "kg")])
        cur.execute(
            "select hub.bom_mark_uom_drift(%s::text[], %s, %s, %s, %s)",
            (["ba_mf"], "materials_uom", "hub.materials",
             f"{CLIENT}/M1", "M1"))
        cur.execute("select has_uom_drift, uom_drift_reasons "
                    "from hub.bom_artifacts where artifact_id='ba_mf'")
        flag, reasons = cur.fetchone()
    assert flag is True
    dims = sorted({r["dim"] for r in reasons})
    assert "materials_uom" in dims


def test_helper_does_not_mark_derived():
    with connect() as conn, conn.cursor() as cur:
        _insert_artifact(cur, "ba_der", "P1", "technical_exploded",
                          source_kind="technical_flattened",
                          rows=[("M1", 1.0, "kg")])
        cur.execute(
            "select hub.bom_mark_uom_drift(%s::text[], %s, %s, %s, %s)",
            (["ba_der"], "materials_uom", "hub.materials",
             f"{CLIENT}/M1", "M1"))
        cur.execute("select has_uom_drift from hub.bom_artifacts "
                    "where artifact_id='ba_der'")
        flag = cur.fetchone()[0]
    assert flag is False, \
        "derived artifacts use is_stale, not has_uom_drift"


def test_helper_dedups_same_reason():
    """@> dedup: same dim + material_code → single reason entry."""
    with connect() as conn, conn.cursor() as cur:
        _insert_artifact(cur, "ba_dd", "P1", "manual_flat_as_provided",
                          source_kind="technical_flattened",
                          rows=[("M1", 1.0, "kg")])
        for _ in range(3):
            cur.execute(
                "select hub.bom_mark_uom_drift(%s::text[], %s, %s, %s, %s)",
                (["ba_dd"], "materials_uom", "hub.materials",
                 f"{CLIENT}/M1", "M1"))
        cur.execute("select uom_drift_reasons from hub.bom_artifacts "
                    "where artifact_id='ba_dd'")
        reasons = cur.fetchone()[0]
    assert len(reasons) == 1, f"expected 1 deduped reason, got {len(reasons)}"


# ── Trigger D7 extension fires on materials.uom edit ────────────────


def test_d7_marks_manual_flat_on_uom_edit():
    """Editing materials.uom marks the manual_flat artifact has_uom_drift."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_TRIGGER", uom="kg")
        _insert_artifact(cur, "ba_trig_mf", "P_T", "manual_flat_as_provided",
                          source_kind="technical_flattened",
                          rows=[("M_TRIGGER", 5.0, "kg")])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set uom='lb' "
            "where client_id=%s and material_code='M_TRIGGER'",
            (CLIENT,))
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select has_uom_drift from hub.bom_artifacts "
            "where artifact_id='ba_trig_mf'")
        assert cur.fetchone()[0] is True


def test_d7_does_not_mark_manual_flat_on_category_only_edit():
    """Editing materials.category alone does NOT mark uom drift."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_CAT", uom="kg")
        _insert_artifact(cur, "ba_trig_cat", "P_C", "manual_flat_as_provided",
                          source_kind="technical_flattened",
                          rows=[("M_CAT", 1.0, "kg")])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set category='btp_sx' "
            "where client_id=%s and material_code='M_CAT'", (CLIENT,))
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select has_uom_drift from hub.bom_artifacts "
            "where artifact_id='ba_trig_cat'")
        assert cur.fetchone()[0] is False


def test_d7_skips_tombstoned_artifacts():
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "M_TS", uom="kg")
        _insert_artifact(cur, "ba_trig_ts", "P_TS", "manual_flat_as_provided",
                          source_kind="technical_flattened",
                          rows=[("M_TS", 1.0, "kg")])
        cur.execute(
            "update hub.bom_artifacts set tombstoned_at=now(), "
            "tombstone_reason='test-tombstone' where artifact_id='ba_trig_ts'")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set uom='lb' "
            "where client_id=%s and material_code='M_TS'", (CLIENT,))
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select has_uom_drift from hub.bom_artifacts "
            "where artifact_id='ba_trig_ts'")
        assert cur.fetchone()[0] is False
