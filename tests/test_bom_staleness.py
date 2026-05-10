"""Track D Phase 1 — BOM dependency staleness (4 dimensions).

Mig 053 adds:
- `hub.bom_artifacts.is_stale BOOLEAN NOT NULL DEFAULT false`
- `hub.bom_artifacts.stale_reasons JSONB NOT NULL DEFAULT '[]'`
- `hub.bom_artifacts.stale_first_at TIMESTAMPTZ`
- `hub.bom_artifacts.stale_resolved_at TIMESTAMPTZ`
- Partial index `(client_id, is_stale) WHERE is_stale = true`
- Trigger D1: AFTER UPDATE materials.category → mark dependent
  derived artifacts stale, dim='catalog_category'.
- Trigger D7: AFTER UPDATE materials.uom → dim='materials_uom'.
- Trigger D8: AFTER UPDATE materials.btp_sourcing → dim='btp_sourcing'.
- Trigger D2: AFTER INSERT bom_artifacts WHERE source_bom_kind=
  'technical_raw' on a btp_sx product → mark parents that reference
  this product_code in their bom_artifact_rows as stale,
  dim='btp_bom_added'.
- Trigger D2-symmetric: AFTER UPDATE bom_artifacts.tombstoned_at
  on raw artifact → dim='btp_bom_tombstoned'.

Spec: `.ai/features/2026-05-11-bom-staleness-track-d/brief.md`.
"""
from __future__ import annotations

import pytest

from app.database import connect


CLIENT = "track_d_test"
OTHER_CLIENT = "track_d_other"
DERIVED_STRATEGIES = (
    "technical_exploded",
    "purchased_btp_as_leaf",
    "self_produced_btp_exploded",
    "mixed_confirmed",
)


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        for c in (CLIENT, OTHER_CLIENT):
            cur.execute(
                "insert into hub.clients (client_id, name) "
                "values (%s, %s) on conflict (client_id) do nothing",
                (c, f"track D test {c}"),
            )
    yield
    with connect() as conn, conn.cursor() as cur:
        for c in (CLIENT, OTHER_CLIENT):
            cur.execute(
                "delete from hub.bom_artifact_rows where artifact_id in "
                "(select artifact_id from hub.bom_artifacts where client_id=%s)",
                (c,),
            )
            cur.execute(
                "delete from hub.bom_artifacts where client_id=%s", (c,)
            )
            cur.execute(
                "delete from hub.materials where client_id=%s", (c,)
            )
            cur.execute(
                "delete from hub.clients where client_id=%s", (c,)
            )


def _insert_material(
    client_id: str,
    material_code: str,
    *,
    category: str = "nvl",
    uom: str = "pcs",
    btp_sourcing: str | None = None,
    name: str | None = None,
) -> None:
    name = name or f"M-{material_code}"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            "category, uom, unit, btp_sourcing, status, source) "
            "values (%s, %s, %s, %s, %s, %s, %s, 'active', 'client_declared')",
            (client_id, material_code, name, category, uom, uom, btp_sourcing),
        )
        conn.commit()


def _insert_artifact(
    client_id: str,
    product_code: str,
    artifact_id: str,
    artifact_no: int,
    *,
    parent_artifact_id: str | None = None,
    bom_variant_id: str = "default",
    flatten_status: str = "flattened",
    flatten_strategy: str = "technical_exploded",
    source_bom_kind: str = "technical_flattened",
    rows: list[tuple[str, float, str]] | None = None,
) -> None:
    """Insert one artifact + optional bom_artifact_rows.
    `rows` is list of (material_code, qty, uom).
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, status, actor, intent, "
            "parent_artifact_id, context, normalized_hash, row_count, "
            "source_bom_kind, flatten_status, flatten_strategy, "
            "source_channel, bom_variant_id, lineage, flatten_method, "
            "flatten_method_version, published_at) "
            "values (%s, %s, %s, %s, 'published', 'agency_staff', "
            "'asserted_technical', %s, '{}', %s, %s, %s, %s, %s, "
            "'staff_form', %s, '{}', 'as_provided', 'v1', now())",
            (
                artifact_id, client_id, product_code, artifact_no,
                parent_artifact_id, f"h_{artifact_id}",
                len(rows or []), source_bom_kind, flatten_status,
                flatten_strategy, bom_variant_id,
            ),
        )
        for i, (mat, qty, uom) in enumerate(rows or [], start=1):
            cur.execute(
                "insert into hub.bom_artifact_rows (artifact_id, "
                "row_index, material_code, bom_code, bom_variant_id, "
                "qty_per_unit, uom, payload) values "
                "(%s, %s, %s, %s, %s, %s, %s, '{}')",
                (artifact_id, i, mat, mat, bom_variant_id, qty, uom),
            )
        conn.commit()


def _stale_state(artifact_id: str) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select is_stale, stale_reasons, stale_first_at, "
            "stale_resolved_at from hub.bom_artifacts "
            "where artifact_id=%s",
            (artifact_id,),
        )
        row = cur.fetchone()
    return {
        "is_stale": row[0],
        "stale_reasons": row[1],
        "stale_first_at": row[2],
        "stale_resolved_at": row[3],
    }


# ────────────────────────────────────────────────────────────────────
# Schema — columns + index exist with correct nullability/defaults.
# ────────────────────────────────────────────────────────────────────


def test_is_stale_column_exists_not_null_default_false():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select is_nullable, column_default, data_type "
            "from information_schema.columns "
            "where table_schema='hub' and table_name='bom_artifacts' "
            "and column_name='is_stale'"
        )
        row = cur.fetchone()
    assert row is not None, "bom_artifacts.is_stale missing"
    assert row[0] == "NO", f"is_stale must be NOT NULL, got {row[0]!r}"
    assert row[1] is not None and "false" in row[1].lower()
    assert row[2] == "boolean"


def test_stale_reasons_column_jsonb_default_empty_array():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select is_nullable, column_default, data_type "
            "from information_schema.columns "
            "where table_schema='hub' and table_name='bom_artifacts' "
            "and column_name='stale_reasons'"
        )
        row = cur.fetchone()
    assert row is not None, "bom_artifacts.stale_reasons missing"
    assert row[0] == "NO"
    assert row[1] is not None and "[]" in row[1]
    assert row[2] == "jsonb"


def test_stale_timestamps_columns_nullable():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select column_name, is_nullable, data_type "
            "from information_schema.columns "
            "where table_schema='hub' and table_name='bom_artifacts' "
            "and column_name in ('stale_first_at','stale_resolved_at') "
            "order by column_name"
        )
        rows = cur.fetchall()
    names = {r[0] for r in rows}
    assert names == {"stale_first_at", "stale_resolved_at"}, (
        f"missing timestamp columns: {names}"
    )
    for r in rows:
        assert r[1] == "YES", f"{r[0]} must be nullable"
        assert "timestamp" in r[2]


def test_partial_index_on_is_stale_exists():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select indexdef from pg_indexes "
            "where schemaname='hub' and tablename='bom_artifacts' "
            "and indexdef ilike '%is_stale%'"
        )
        rows = cur.fetchall()
    assert rows, "no index references is_stale"
    assert any("where" in r[0].lower() and "is_stale" in r[0].lower()
               for r in rows), (
        f"no partial index on is_stale=true; got: {[r[0] for r in rows]}"
    )


# ────────────────────────────────────────────────────────────────────
# Trigger D1: materials.category UPDATE → marks dependent artifacts.
# ────────────────────────────────────────────────────────────────────


def test_d1_category_update_marks_dependent_derived_artifact_stale():
    _insert_material(CLIENT, "M_D1_A", category="nvl")
    _insert_artifact(
        CLIENT, "P_D1", "ba_d1_derived", 1,
        flatten_strategy="technical_exploded",
        rows=[("M_D1_A", 1.0, "pcs")],
    )
    # Trigger fires here.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set category='btp_sx' "
            "where client_id=%s and material_code='M_D1_A'",
            (CLIENT,),
        )
        conn.commit()

    s = _stale_state("ba_d1_derived")
    assert s["is_stale"] is True
    dims = [r["dim"] for r in s["stale_reasons"]]
    assert "catalog_category" in dims, (
        f"expected catalog_category in stale_reasons; got {s['stale_reasons']}"
    )
    assert s["stale_first_at"] is not None


def test_d1_no_op_update_does_not_mark_stale():
    """UPDATE with same value (DISTINCT FROM check) → no stale flag."""
    _insert_material(CLIENT, "M_D1_NOOP", category="nvl")
    _insert_artifact(
        CLIENT, "P_D1_NOOP", "ba_d1_noop", 1,
        flatten_strategy="technical_exploded",
        rows=[("M_D1_NOOP", 1.0, "pcs")],
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set category='nvl' "
            "where client_id=%s and material_code='M_D1_NOOP'",
            (CLIENT,),
        )
        conn.commit()

    s = _stale_state("ba_d1_noop")
    assert s["is_stale"] is False
    assert s["stale_reasons"] == []


def test_d1_does_not_mark_source_artifacts():
    """Source raw_graph + manual_flat are immutable; trigger filters
    them out (only derived strategies marked)."""
    _insert_material(CLIENT, "M_D1_SRC", category="nvl")
    _insert_artifact(
        CLIENT, "P_D1_SRC", "ba_d1_raw", 1,
        flatten_status="non_flattened", flatten_strategy="no_strategy",
        source_bom_kind="technical_raw",
        rows=[("M_D1_SRC", 1.0, "pcs")],
    )
    _insert_artifact(
        CLIENT, "P_D1_SRC", "ba_d1_manual", 2,
        flatten_status="not_applicable",
        flatten_strategy="manual_flat_as_provided",
        source_bom_kind="manual_flat",
        rows=[("M_D1_SRC", 1.0, "pcs")],
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set category='btp_sx' "
            "where client_id=%s and material_code='M_D1_SRC'",
            (CLIENT,),
        )
        conn.commit()

    assert _stale_state("ba_d1_raw")["is_stale"] is False
    assert _stale_state("ba_d1_manual")["is_stale"] is False


def test_d1_cross_tenant_isolation():
    """UPDATE materials in CLIENT must not affect OTHER_CLIENT artifacts."""
    _insert_material(CLIENT, "M_X", category="nvl")
    _insert_material(OTHER_CLIENT, "M_X", category="nvl")
    _insert_artifact(
        CLIENT, "P_X", "ba_x_self", 1,
        flatten_strategy="technical_exploded",
        rows=[("M_X", 1.0, "pcs")],
    )
    _insert_artifact(
        OTHER_CLIENT, "P_X", "ba_x_other", 1,
        flatten_strategy="technical_exploded",
        rows=[("M_X", 1.0, "pcs")],
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set category='btp_sx' "
            "where client_id=%s and material_code='M_X'",
            (CLIENT,),
        )
        conn.commit()

    assert _stale_state("ba_x_self")["is_stale"] is True
    assert _stale_state("ba_x_other")["is_stale"] is False, (
        "cross-tenant ripple: OTHER_CLIENT artifact marked stale"
    )


# ────────────────────────────────────────────────────────────────────
# Trigger D7: materials.uom UPDATE.
# ────────────────────────────────────────────────────────────────────


def test_d7_uom_update_marks_dependent_artifact_stale():
    _insert_material(CLIENT, "M_D7", uom="pcs")
    _insert_artifact(
        CLIENT, "P_D7", "ba_d7", 1,
        flatten_strategy="purchased_btp_as_leaf",
        rows=[("M_D7", 2.0, "pcs")],
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set uom='kg' "
            "where client_id=%s and material_code='M_D7'",
            (CLIENT,),
        )
        conn.commit()

    s = _stale_state("ba_d7")
    assert s["is_stale"] is True
    dims = [r["dim"] for r in s["stale_reasons"]]
    assert "materials_uom" in dims


# ────────────────────────────────────────────────────────────────────
# Trigger D8: materials.btp_sourcing UPDATE.
# ────────────────────────────────────────────────────────────────────


def test_d8_btp_sourcing_update_marks_dependent_artifact_stale():
    _insert_material(CLIENT, "M_D8", category="btp_sx", btp_sourcing=None)
    _insert_artifact(
        CLIENT, "P_D8", "ba_d8", 1,
        flatten_strategy="technical_exploded",
        rows=[("M_D8", 1.0, "pcs")],
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set btp_sourcing='self_produced_only' "
            "where client_id=%s and material_code='M_D8'",
            (CLIENT,),
        )
        conn.commit()

    s = _stale_state("ba_d8")
    assert s["is_stale"] is True
    dims = [r["dim"] for r in s["stale_reasons"]]
    assert "btp_sourcing" in dims


# ────────────────────────────────────────────────────────────────────
# Multi-dim accumulation: stale_reasons grows on subsequent triggers.
# ────────────────────────────────────────────────────────────────────


def test_stale_reasons_dedup_same_dim_and_source_pk():
    """Mig 054: repeated edits of the same (dim, source_pk) should not
    bloat stale_reasons. Helper uses `@>` containment check."""
    _insert_material(CLIENT, "M_DEDUP", uom="pcs")
    _insert_artifact(
        CLIENT, "P_DEDUP", "ba_dedup", 1,
        flatten_strategy="technical_exploded",
        rows=[("M_DEDUP", 1.0, "pcs")],
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set uom='kg' "
            "where client_id=%s and material_code='M_DEDUP'",
            (CLIENT,),
        )
        cur.execute(
            "update hub.materials set uom='pcs' "
            "where client_id=%s and material_code='M_DEDUP'",
            (CLIENT,),
        )
        cur.execute(
            "update hub.materials set uom='kg' "
            "where client_id=%s and material_code='M_DEDUP'",
            (CLIENT,),
        )
        conn.commit()

    s = _stale_state("ba_dedup")
    assert s["is_stale"] is True
    # All three updates target same (dim='materials_uom', source_pk).
    # Helper must dedup → exactly 1 entry.
    assert len(s["stale_reasons"]) == 1, (
        f"Repeated same-dim updates must dedup; got "
        f"{len(s['stale_reasons'])} entries: {s['stale_reasons']}"
    )
    assert s["stale_reasons"][0]["dim"] == "materials_uom"


def test_stale_reasons_accumulate_across_dimensions():
    _insert_material(CLIENT, "M_MULTI", category="nvl", uom="pcs")
    _insert_artifact(
        CLIENT, "P_MULTI", "ba_multi", 1,
        flatten_strategy="technical_exploded",
        rows=[("M_MULTI", 1.0, "pcs")],
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set category='btp_sx' "
            "where client_id=%s and material_code='M_MULTI'",
            (CLIENT,),
        )
        cur.execute(
            "update hub.materials set uom='kg' "
            "where client_id=%s and material_code='M_MULTI'",
            (CLIENT,),
        )
        conn.commit()

    s = _stale_state("ba_multi")
    assert s["is_stale"] is True
    dims = [r["dim"] for r in s["stale_reasons"]]
    assert "catalog_category" in dims and "materials_uom" in dims, (
        f"both dims must accumulate; got {dims}"
    )


# ────────────────────────────────────────────────────────────────────
# Trigger D2: BTP raw BOM ingest → parents stale.
# ────────────────────────────────────────────────────────────────────


def test_d2_btp_raw_bom_insert_marks_parent_stale():
    """When a BTP product gets its first raw_graph BOM ingested,
    parent artifacts that reference the BTP as a row become stale."""
    _insert_material(CLIENT, "BTP_X", category="btp_sx")
    _insert_material(CLIENT, "PARENT_X", category="tp")
    _insert_artifact(
        CLIENT, "PARENT_X", "ba_parent_x", 1,
        flatten_strategy="purchased_btp_as_leaf",
        rows=[("BTP_X", 1.0, "pcs")],
    )

    # New BOM uploaded for BTP_X → parent goes stale.
    _insert_artifact(
        CLIENT, "BTP_X", "ba_btp_x_raw", 1,
        flatten_status="non_flattened", flatten_strategy="no_strategy",
        source_bom_kind="technical_raw",
        rows=[],
    )

    s = _stale_state("ba_parent_x")
    assert s["is_stale"] is True
    dims = [r["dim"] for r in s["stale_reasons"]]
    assert "btp_bom_added" in dims


def test_d2_does_not_mark_btp_artifact_itself():
    """The newly-inserted BTP raw_graph artifact is itself a source —
    it's the cause of the staleness, not a victim."""
    _insert_material(CLIENT, "BTP_Y", category="btp_sx")
    _insert_artifact(
        CLIENT, "BTP_Y", "ba_btp_y_raw", 1,
        flatten_status="non_flattened", flatten_strategy="no_strategy",
        source_bom_kind="technical_raw",
        rows=[],
    )

    s = _stale_state("ba_btp_y_raw")
    assert s["is_stale"] is False


def test_d2_tombstone_marks_parent_stale_symmetric():
    """Tombstoning a BTP's raw BOM means parents revert to
    'missing_child_bom' semantics → mark parents stale."""
    _insert_material(CLIENT, "BTP_T", category="btp_sx")
    _insert_material(CLIENT, "PARENT_T", category="tp")
    _insert_artifact(
        CLIENT, "BTP_T", "ba_btp_t_raw", 1,
        flatten_status="non_flattened", flatten_strategy="no_strategy",
        source_bom_kind="technical_raw",
        rows=[],
    )
    # Parent created AFTER BTP raw, so D2-INSERT trigger fires on parent
    # creation? No — D2 fires when raw is INSERTED; parent ingested later
    # is a fresh artifact, not stale. Reset stale state explicitly to
    # isolate the tombstone trigger.
    _insert_artifact(
        CLIENT, "PARENT_T", "ba_parent_t", 1,
        flatten_strategy="purchased_btp_as_leaf",
        rows=[("BTP_T", 1.0, "pcs")],
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.bom_artifacts set is_stale=false, "
            "stale_reasons='[]'::jsonb, stale_first_at=null "
            "where artifact_id='ba_parent_t'"
        )
        conn.commit()

    # Now tombstone the BTP raw.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.bom_artifacts set tombstoned_at=now(), "
            "tombstone_reason='test' where artifact_id='ba_btp_t_raw'"
        )
        conn.commit()

    s = _stale_state("ba_parent_t")
    assert s["is_stale"] is True
    dims = [r["dim"] for r in s["stale_reasons"]]
    assert "btp_bom_tombstoned" in dims
