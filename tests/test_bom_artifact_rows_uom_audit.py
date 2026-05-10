"""Mig 056 — `bom_artifact_rows` UoM audit columns.

Verifies the 3 new typed columns are populated by the refresh path's
convert layer:
- source_uom: raw uom the row started with
- applied_uom_factor: factor multiplied
- applied_uom_source: ConversionMatch.source enum value
"""
from __future__ import annotations

import json

import pytest

from app.database import connect
from app.stores.bom_staleness import refresh_artifact


CLIENT = "_uom_audit_test"


def _seed_client(cur):
    cur.execute(
        "insert into hub.clients (client_id, name) values (%s, %s) "
        "on conflict (client_id) do nothing",
        (CLIENT, "uom audit test"),
    )


def _seed_material(cur, code, category="nvl", uom="kg"):
    cur.execute(
        "insert into hub.materials (client_id, material_code, name, "
        "category, status, uom) values (%s, %s, %s, %s, 'active', %s) "
        "on conflict (client_id, material_code) do update set "
        "category=excluded.category, uom=excluded.uom",
        (CLIENT, code, code, category, uom),
    )


def _insert_raw(cur, artifact_id, product_code, edges):
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, "
        "product_code, artifact_no, status, actor, intent, "
        "context, normalized_hash, row_count, source_bom_kind, "
        "flatten_status, flatten_strategy, source_channel, "
        "bom_variant_id, lineage, flatten_method, "
        "flatten_method_version, published_at) "
        "values (%s, %s, %s, 1, 'published', 'agency_staff', "
        "'asserted_technical', '{}', %s, %s, 'technical_raw', "
        "'non_flattened', 'no_strategy', 'agency_upload', "
        "'default', '{}', 'as_provided', 'v1', now())",
        (artifact_id, CLIENT, product_code, f"h_{artifact_id}", len(edges)),
    )
    for idx, (parent, child, qty, uom) in enumerate(edges):
        cur.execute(
            "insert into hub.bom_edges (artifact_id, row_index, root_code, "
            "parent_code, child_code, qty_per_parent, uom) "
            "values (%s, %s, %s, %s, %s, %s, %s)",
            (artifact_id, idx, product_code, parent, child, qty, uom),
        )


def _insert_derived_stale(cur, artifact_id, product_code, strategy):
    reasons = [{"dim": "catalog_category", "source_table": "hub.materials",
                "source_pk": f"{CLIENT}/seed", "observed_at":
                "2026-05-12T00:00:00Z"}]
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, "
        "product_code, artifact_no, status, actor, intent, "
        "context, normalized_hash, row_count, source_bom_kind, "
        "flatten_status, flatten_strategy, source_channel, "
        "bom_variant_id, lineage, flatten_method, "
        "flatten_method_version, published_at, is_stale, "
        "stale_reasons, stale_first_at) "
        "values (%s, %s, %s, 1, 'published', 'agency_staff', "
        "'derived', '{}', %s, 0, 'technical_flattened', "
        "'flattened', %s, 'migration', 'default', '{}', 'recursive_sql', "
        "'1', now(), true, %s::jsonb, now())",
        (artifact_id, CLIENT, product_code, f"h_{artifact_id}", strategy,
         json.dumps(reasons)),
    )


def _row_audit(cur, artifact_id, material_code):
    cur.execute(
        "select uom, source_uom, applied_uom_factor, applied_uom_source "
        "from hub.bom_artifact_rows "
        "where artifact_id=%s and material_code=%s",
        (artifact_id, material_code),
    )
    r = cur.fetchone()
    return {
        "uom": r[0], "source_uom": r[1],
        "applied_uom_factor": float(r[2]) if r[2] is not None else None,
        "applied_uom_source": r[3],
    }


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        _seed_client(cur)
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
        cur.execute("delete from hub.client_uom_overrides where client_id=%s",
                     (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def test_audit_columns_exist():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            select column_name, data_type, is_nullable
            from information_schema.columns
            where table_schema='hub' and table_name='bom_artifact_rows'
              and column_name in ('source_uom', 'applied_uom_factor',
                                   'applied_uom_source')
            order by column_name
        """)
        cols = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    assert "source_uom" in cols
    assert cols["source_uom"][0] == "text"
    assert cols["source_uom"][1] == "YES"  # nullable
    assert "applied_uom_factor" in cols
    assert cols["applied_uom_factor"][0] == "numeric"
    assert "applied_uom_source" in cols


def test_same_family_audit_global_source():
    """g → kg conversion records source_uom=g, factor=0.001, source=global."""
    raw_id = "ba_audit_same"
    derived_id = "ba_audit_same_d"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP", category="tp", uom="kg")
        _seed_material(cur, "M", category="nvl", uom="kg")
        _insert_raw(cur, raw_id, "TP", [("TP", "M", 2500.0, "g")])
        _insert_derived_stale(cur, derived_id, "TP", "technical_exploded")

    result = refresh_artifact(CLIENT, derived_id)
    new_id = result["new_artifact_ids"][0]
    with connect() as conn, conn.cursor() as cur:
        audit = _row_audit(cur, new_id, "M")

    assert audit["uom"] == "kg"
    assert audit["source_uom"] == "g"
    assert audit["applied_uom_factor"] == pytest.approx(0.001)
    assert audit["applied_uom_source"] == "global"


def test_tier_a_audit_unconfirmed_default():
    """EA → SETS via tier-A: factor=1.0, source=unconfirmed_default."""
    raw_id = "ba_audit_tier_a"
    derived_id = "ba_audit_tier_a_d"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_A", category="tp", uom="SETS")
        _seed_material(cur, "M_A", category="nvl", uom="SETS")
        _insert_raw(cur, raw_id, "TP_A", [("TP_A", "M_A", 4.0, "EA")])
        _insert_derived_stale(cur, derived_id, "TP_A", "technical_exploded")

    result = refresh_artifact(CLIENT, derived_id)
    new_id = result["new_artifact_ids"][0]
    with connect() as conn, conn.cursor() as cur:
        audit = _row_audit(cur, new_id, "M_A")

    assert audit["uom"] == "SETS"
    assert audit["source_uom"] == "EA"
    assert audit["applied_uom_factor"] == pytest.approx(1.0)
    assert audit["applied_uom_source"] == "unconfirmed_default"


def test_client_override_audit_records_client_specific():
    """Override row factor=0.5 → audit factor=0.5 source=client_specific."""
    raw_id = "ba_audit_override"
    derived_id = "ba_audit_override_d"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_O", category="tp", uom="KG")
        _seed_material(cur, "M_O", category="nvl", uom="KG")
        _insert_raw(cur, raw_id, "TP_O", [("TP_O", "M_O", 10.0, "EA")])
        _insert_derived_stale(cur, derived_id, "TP_O", "technical_exploded")
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'M_O', 'EA', 'KG', 0.5, 'supplier_data')",
            (CLIENT,))

    result = refresh_artifact(CLIENT, derived_id)
    new_id = result["new_artifact_ids"][0]
    with connect() as conn, conn.cursor() as cur:
        audit = _row_audit(cur, new_id, "M_O")

    assert audit["applied_uom_factor"] == pytest.approx(0.5)
    assert audit["applied_uom_source"] == "client_specific"
    assert audit["source_uom"] == "EA"
    assert audit["uom"] == "KG"


def test_factor_missing_records_null_factor():
    """Tier B without override: source_uom recorded, factor + source NULL."""
    raw_id = "ba_audit_missing"
    derived_id = "ba_audit_missing_d"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_M", category="tp", uom="KG")
        _seed_material(cur, "M_M", category="nvl", uom="KG")
        _insert_raw(cur, raw_id, "TP_M", [("TP_M", "M_M", 5.0, "EA")])
        _insert_derived_stale(cur, derived_id, "TP_M", "technical_exploded")

    result = refresh_artifact(CLIENT, derived_id)
    new_id = result["new_artifact_ids"][0]
    with connect() as conn, conn.cursor() as cur:
        audit = _row_audit(cur, new_id, "M_M")

    assert audit["source_uom"] == "EA"
    assert audit["uom"] == "EA"  # raw kept
    assert audit["applied_uom_factor"] is None
    assert audit["applied_uom_source"] is None


def test_invalid_source_enum_rejected():
    """Check constraint blocks unknown applied_uom_source values."""
    import psycopg
    raw_id = "ba_audit_bad"
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, "TP_X", category="tp", uom="kg")
        _insert_raw(cur, raw_id, "TP_X", [("TP_X", "Z", 1.0, "kg")])
    with pytest.raises(psycopg.errors.CheckViolation):
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "insert into hub.bom_artifact_rows "
                "(artifact_id, row_index, material_code, qty_per_unit, uom, "
                " applied_uom_source) "
                "values (%s, 0, 'Z', 1, 'kg', 'made_up_source')",
                (raw_id,))
