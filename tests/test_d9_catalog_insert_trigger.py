"""Mig 058 — D9 catalog-insert trigger.

Order-independence invariant: BOM uploaded before catalog row exists →
when catalog later gains the code, derived artifacts referencing it
must go stale (so refresh picks up the new UoM).
"""
from __future__ import annotations

import json

import pytest

from app.database import connect


CLIENT = "_d9_test"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict do nothing", (CLIENT, "d9 test"))
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
        cur.execute("delete from hub.bom_artifacts where client_id=%s",
                     (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s",
                     (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _insert_artifact(cur, artifact_id, product_code, strategy, source_kind,
                      rows: list[tuple] = (),
                      edges: list[tuple] = ()):
    flatten_status = ("non_flattened" if source_kind == "technical_raw"
                       else ("not_applicable"
                             if strategy == "manual_flat_as_provided"
                             else "flattened"))
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
         len(rows), source_kind, flatten_status, strategy))
    for idx, (mat, qty, uom) in enumerate(rows):
        cur.execute(
            "insert into hub.bom_artifact_rows (artifact_id, row_index, "
            "material_code, qty_per_unit, uom) values (%s, %s, %s, %s, %s)",
            (artifact_id, idx, mat, qty, uom))
    for idx, (parent, child, qty, uom) in enumerate(edges):
        cur.execute(
            "insert into hub.bom_edges (artifact_id, row_index, root_code, "
            "parent_code, child_code, qty_per_parent, uom) "
            "values (%s, %s, %s, %s, %s, %s, %s)",
            (artifact_id, idx, product_code, parent, child, qty, uom))


def test_d9_marks_derived_artifact_stale_on_catalog_insert():
    """BOM ingested first (no catalog row); catalog INSERT fires D9."""
    with connect() as conn, conn.cursor() as cur:
        _insert_artifact(cur, "ba_d9_der", "TP1", "technical_exploded",
                          source_kind="technical_flattened",
                          rows=[("M_LATE", 3.0, "kg")])
        cur.execute(
            "select is_stale from hub.bom_artifacts "
            "where artifact_id='ba_d9_der'")
        assert cur.fetchone()[0] is False, "no stale before catalog INSERT"

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, status, uom) values (%s, 'M_LATE', 'M_LATE', "
            "'nvl', 'active', 'kg')", (CLIENT,))

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select is_stale, stale_reasons from hub.bom_artifacts "
            "where artifact_id='ba_d9_der'")
        is_stale, reasons = cur.fetchone()
    assert is_stale is True
    dims = sorted({r["dim"] for r in reasons})
    assert "catalog_inserted" in dims


def test_d9_marks_manual_flat_uom_drift_when_uom_set():
    """manual_flat artifact + catalog INSERT with uom set → has_uom_drift."""
    with connect() as conn, conn.cursor() as cur:
        _insert_artifact(cur, "ba_d9_mf", "P_MF", "manual_flat_as_provided",
                          source_kind="technical_flattened",
                          rows=[("M_MF", 1.0, "kg")])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, status, uom) values (%s, 'M_MF', 'M_MF', "
            "'nvl', 'active', 'g')", (CLIENT,))
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select has_uom_drift from hub.bom_artifacts "
                    "where artifact_id='ba_d9_mf'")
        assert cur.fetchone()[0] is True


def test_d9_skips_catalog_insert_with_null_uom_for_source():
    """Catalog INSERT without uom → no UoM to convert against, skip
    source-artifact drift signal (still marks derived as stale because
    catalog appearance itself is the trigger event)."""
    with connect() as conn, conn.cursor() as cur:
        _insert_artifact(cur, "ba_d9_no_uom", "P_NU",
                          "manual_flat_as_provided",
                          source_kind="technical_flattened",
                          rows=[("M_NU", 1.0, "kg")])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, status) values (%s, 'M_NU', 'M_NU', "
            "'nvl', 'active')", (CLIENT,))
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select has_uom_drift from hub.bom_artifacts "
                    "where artifact_id='ba_d9_no_uom'")
        assert cur.fetchone()[0] is False


def test_d9_marks_raw_graph_artifact_via_bom_edges():
    """raw_graph artifact (rows in bom_edges, not bom_artifact_rows) +
    catalog INSERT → has_uom_drift via bom_edges.child_code path."""
    with connect() as conn, conn.cursor() as cur:
        _insert_artifact(cur, "ba_d9_raw", "P_RAW", "no_strategy",
                          source_kind="technical_raw",
                          edges=[("P_RAW", "M_RAW_LATE", 1.0, "kg")])
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, status, uom) values (%s, 'M_RAW_LATE', 'M_RAW_LATE', "
            "'nvl', 'active', 'g')", (CLIENT,))
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select has_uom_drift from hub.bom_artifacts "
                    "where artifact_id='ba_d9_raw'")
        assert cur.fetchone()[0] is True


def test_d9_does_not_cross_clients():
    """D9 must scope by client_id (no cross-tenant ripple)."""
    other = "_d9_test_other"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict do nothing", (other, "other"))
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, status, actor, intent, "
            "context, normalized_hash, row_count, source_bom_kind, "
            "flatten_status, flatten_strategy, source_channel, "
            "bom_variant_id, lineage, flatten_method, "
            "flatten_method_version, published_at) values "
            "('ba_d9_other', %s, 'P_OTHER', 1, 'published', 'agency_staff', "
            "'asserted_technical', '{}', 'h_other', 1, "
            "'technical_flattened', 'flattened', 'technical_exploded', "
            "'agency_upload', 'default', '{}', 'as_provided', 'v1', now())",
            (other,))
        cur.execute(
            "insert into hub.bom_artifact_rows (artifact_id, row_index, "
            "material_code, qty_per_unit, uom) values "
            "('ba_d9_other', 0, 'M_SHARED', 1.0, 'kg')")
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "insert into hub.materials (client_id, material_code, name, "
                "category, status, uom) values (%s, 'M_SHARED', 'm', "
                "'nvl', 'active', 'kg')", (CLIENT,))
        with connect() as conn, conn.cursor() as cur:
            cur.execute("select is_stale from hub.bom_artifacts "
                        "where artifact_id='ba_d9_other'")
            assert cur.fetchone()[0] is False, "cross-client must not ripple"
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "delete from hub.bom_artifact_rows "
                "where artifact_id='ba_d9_other'")
            cur.execute(
                "delete from hub.bom_artifacts where artifact_id='ba_d9_other'")
            cur.execute("delete from hub.clients where client_id=%s", (other,))
