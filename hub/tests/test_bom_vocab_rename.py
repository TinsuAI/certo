"""Vocab rename pass: schema guarantees.

Locks in the canonical rename (mig 031, 2026-05-07):
- bom_versions → bom_artifacts
- bom_resolution_profiles → bom_presets
- column renames per .ai/GLOSSARY.md

URL alias 308 redirects (D10) lived through 2026-05-28 then were
dropped per BACKLOG.md C.3 removal trigger; redirect tests removed
with the handlers.
"""
from __future__ import annotations

import pytest

from hub.app.database import connect


CLIENT = "vocab_rename_test"


@pytest.fixture(autouse=True)
def setup_client():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "vocab rename test"),
        )
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id = %s", (CLIENT,))


# ─────────────────────────────────────────────────────────────────────
# Schema — new names exist, old names don't
# ─────────────────────────────────────────────────────────────────────


def test_bom_artifacts_table_exists_with_new_columns():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema='hub' and table_name='bom_artifacts'"
        )
        cols = {r[0] for r in cur.fetchall()}
    assert "artifact_id" in cols
    assert "artifact_no" in cols
    assert "parent_artifact_id" in cols
    # Old names gone
    assert "version_id" not in cols
    assert "version_no" not in cols
    assert "parent_version_id" not in cols


def test_bom_presets_table_exists_with_renamed_columns():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema='hub' and table_name='bom_presets'"
        )
        cols = {r[0] for r in cur.fetchall()}
    assert cols, "bom_presets table missing"
    assert "preset_id" in cols
    assert "artifact_id" in cols
    assert "profile_id" not in cols
    assert "bom_version_id" not in cols


def test_old_table_names_dropped():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema='hub' and table_name in "
            "('bom_versions', 'bom_version_rows', 'bom_resolution_profiles')"
        )
        survivors = [r[0] for r in cur.fetchall()]
    assert survivors == [], f"old table names still in schema: {survivors}"


def test_bcct_rows_artifact_id_column():
    """bcct_rows.bom_version_id renamed to artifact_id (mig 031 §9b)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema='hub' and table_name='bcct_rows' "
            "and column_name in ('artifact_id', 'bom_version_id')"
        )
        names = {r[0] for r in cur.fetchall()}
    assert "artifact_id" in names
    assert "bom_version_id" not in names


# ─────────────────────────────────────────────────────────────────────
# ID prefix — new artifacts mint with ba_ (D8)
# ─────────────────────────────────────────────────────────────────────


def test_new_artifact_ids_use_ba_prefix():
    """Forward-only: existing bv_* ids untouched, new rows minted ba_*."""
    from hub.app.stores import bom as bom_store
    bom_store.create_artifact(
        client_id=CLIENT, product_code="VOCAB_PROD",
        rows=[{"material_code": "MAT_X", "qty_per_unit": 1, "uom": "kg"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy="technical_exploded",
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select artifact_id from hub.bom_artifacts "
            "where client_id=%s and product_code=%s",
            (CLIENT, "VOCAB_PROD"),
        )
        ids = [r[0] for r in cur.fetchall()]
    assert ids, "no artifact created"
    assert all(i.startswith("ba_") for i in ids), ids
