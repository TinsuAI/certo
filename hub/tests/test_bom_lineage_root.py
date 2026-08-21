"""Track B — group artifacts by logical phiên bản via lineage_root_id.

Per glossary, "Phiên bản BOM" (logical) = tuple (client, product,
variant, lineage_root_id, case_id). lineage_root_id is the artifact_id
at the top of the parent_artifact_id chain. A standard upload produces
3 artifacts (raw_graph + shallow + full_flat) all sharing the same
lineage_root (the raw_graph artifact_id, since shallow + full_flat are
materialized as descendants).

Locks in:
- mig 052 adds `lineage_root_id` NOT NULL column on hub.bom_artifacts.
- BEFORE INSERT trigger:
  - parent_artifact_id IS NULL → lineage_root_id := NEW.artifact_id (self).
  - parent_artifact_id NOT NULL → lineage_root_id := parent's
    lineage_root_id (inherit).
- Backfill via recursive CTE walks existing rows.
- `list_products_with_bom` groups artifacts by lineage_root_id and
  exposes `n_logical_versions` (= count distinct lineage_root per
  product) + `n_artifacts` (= total artifacts, was n_versions).
- Schema invariant: every alive artifact has lineage_root_id set;
  root self-references; non-root inherits via parent.

Spec: `.ai/features/2026-05-10-bom-vocab-3shape-uom-gate/brief.md`
Track B.
"""
from __future__ import annotations

import pytest

from hub.app.database import connect


CLIENT = "track_b_test"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "track B test"),
        )
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bom_artifacts where client_id=%s",
                    (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _insert_artifact(client_id: str, product_code: str, artifact_id: str,
                     artifact_no: int, parent_artifact_id: str | None = None,
                     bom_variant_id: str = "default",
                     flatten_status: str = "non_flattened",
                     flatten_strategy: str = "no_strategy"):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, "
            "product_code, artifact_no, status, actor, intent, "
            "parent_artifact_id, context, normalized_hash, row_count, "
            "source_bom_kind, flatten_status, flatten_strategy, "
            "source_channel, bom_variant_id, lineage, flatten_method, "
            "flatten_method_version, published_at) "
            "values (%s, %s, %s, %s, 'published', 'agency_staff', "
            "'asserted_technical', %s, '{}', %s, 0, "
            "'technical_flattened', %s, %s, "
            "'staff_form', %s, '{}', 'as_provided', 'v1', now())",
            (artifact_id, client_id, product_code, artifact_no,
             parent_artifact_id, f"h_{artifact_id}",
             flatten_status, flatten_strategy, bom_variant_id),
        )
        conn.commit()


# ─────────────────────────────────────────────────────────────────────
# Schema — column exists, NOT NULL, indexed.
# ─────────────────────────────────────────────────────────────────────


def test_lineage_root_id_column_exists():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select column_name, is_nullable from information_schema.columns "
            "where table_schema='hub' and table_name='bom_artifacts' "
            "and column_name='lineage_root_id'"
        )
        row = cur.fetchone()
    assert row is not None, "bom_artifacts.lineage_root_id column missing"
    assert row[1] == "NO", (
        f"lineage_root_id should be NOT NULL; got is_nullable={row[1]!r}"
    )


def test_lineage_root_index_exists():
    """Index supporting list-page group-by query."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select indexname from pg_indexes "
            "where schemaname='hub' and tablename='bom_artifacts' "
            "and indexdef ilike '%lineage_root_id%'"
        )
        rows = cur.fetchall()
    assert rows, "no index on bom_artifacts.lineage_root_id"


# ─────────────────────────────────────────────────────────────────────
# Trigger — root sets self, child inherits parent's root.
# ─────────────────────────────────────────────────────────────────────


def test_root_artifact_sets_lineage_root_to_self():
    aid = "ba_track_b_root1"
    _insert_artifact(CLIENT, "P1", aid, 1, parent_artifact_id=None)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select lineage_root_id from hub.bom_artifacts "
            "where artifact_id=%s",
            (aid,),
        )
        row = cur.fetchone()
    assert row[0] == aid, (
        f"Root artifact (parent NULL) must have lineage_root_id = "
        f"artifact_id ({aid}). Got: {row[0]!r}"
    )


def test_child_artifact_inherits_parent_lineage_root():
    parent = "ba_track_b_parent1"
    child = "ba_track_b_child1"
    _insert_artifact(CLIENT, "P2", parent, 1)
    _insert_artifact(CLIENT, "P2", child, 2, parent_artifact_id=parent)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select lineage_root_id from hub.bom_artifacts "
            "where artifact_id=%s",
            (child,),
        )
        row = cur.fetchone()
    assert row[0] == parent, (
        f"Child must inherit lineage_root_id from parent. "
        f"Expected {parent!r}, got {row[0]!r}"
    )


def test_grandchild_inherits_root_through_chain():
    """3-deep chain: A → B → C. C.lineage_root must be A."""
    a = "ba_track_b_chain_a"
    b = "ba_track_b_chain_b"
    c = "ba_track_b_chain_c"
    _insert_artifact(CLIENT, "P3", a, 1)
    _insert_artifact(CLIENT, "P3", b, 2, parent_artifact_id=a)
    _insert_artifact(CLIENT, "P3", c, 3, parent_artifact_id=b)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select lineage_root_id from hub.bom_artifacts "
            "where artifact_id in (%s, %s, %s) order by artifact_no",
            (a, b, c),
        )
        roots = [r[0] for r in cur.fetchall()]
    assert roots == [a, a, a], (
        f"Whole chain should resolve to root {a!r}. Got: {roots}"
    )


def test_two_separate_roots_for_same_product():
    """Same product can have multiple lineage trees (e.g., agency
    re-uploads BOM creating a fresh root). Each tree gets its own
    lineage_root_id."""
    r1 = "ba_track_b_two_root_1"
    r2 = "ba_track_b_two_root_2"
    _insert_artifact(CLIENT, "P4", r1, 1)
    _insert_artifact(CLIENT, "P4", r2, 2)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select lineage_root_id from hub.bom_artifacts "
            "where artifact_id in (%s, %s) order by artifact_no",
            (r1, r2),
        )
        roots = [r[0] for r in cur.fetchall()]
    assert roots == [r1, r2], (
        f"Two independent roots must have distinct lineage_root_id. "
        f"Got: {roots}"
    )


# ─────────────────────────────────────────────────────────────────────
# Backfill — existing rows (pre-mig) populated correctly.
# ─────────────────────────────────────────────────────────────────────


def test_existing_artifacts_have_lineage_root_after_backfill():
    """All pre-mig artifacts in seeded clients (johnson-vn, growatt-vn)
    must have non-NULL lineage_root_id post-mig."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.bom_artifacts "
            "where lineage_root_id is null "
            "and client_id in ('johnson-vn', 'growatt-vn')"
        )
        n_null = cur.fetchone()[0]
    assert n_null == 0, (
        f"{n_null} seeded artifacts have NULL lineage_root_id — "
        f"backfill incomplete."
    )


def test_root_artifacts_self_reference_after_backfill():
    """For seeded artifacts where parent_artifact_id IS NULL, the
    lineage_root_id must equal the artifact_id."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.bom_artifacts "
            "where parent_artifact_id is null "
            "and lineage_root_id <> artifact_id "
            "and client_id in ('johnson-vn', 'growatt-vn')"
        )
        n_bad = cur.fetchone()[0]
    assert n_bad == 0, (
        f"{n_bad} seeded root artifacts don't self-reference "
        f"lineage_root_id — backfill bug."
    )


def test_descendants_share_root_with_parent_after_backfill():
    """Spot-check: artifact with non-NULL parent must have same
    lineage_root_id as parent."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select count(*) from hub.bom_artifacts c
              join hub.bom_artifacts p on p.artifact_id = c.parent_artifact_id
             where c.parent_artifact_id is not null
               and c.lineage_root_id <> p.lineage_root_id
               and c.client_id in ('johnson-vn', 'growatt-vn')
            """
        )
        n_bad = cur.fetchone()[0]
    assert n_bad == 0, (
        f"{n_bad} artifacts have lineage_root mismatched from parent."
    )


# ─────────────────────────────────────────────────────────────────────
# Store — list_products_with_bom exposes n_logical_versions.
# ─────────────────────────────────────────────────────────────────────


def test_list_products_returns_n_logical_versions():
    """The store dict shape adds `n_logical_versions` (distinct
    lineage_root count per product) and renames `n_versions` →
    `n_artifacts` for clarity (counts artifact rows, not phiên bản)."""
    from hub.app.stores.bom import list_products_with_bom
    rows = list_products_with_bom("johnson-vn", limit=5)
    if not rows:
        pytest.skip("no johnson-vn BOM data")
    r = rows[0]
    assert "n_logical_versions" in r, (
        f"Must expose n_logical_versions (distinct lineage_root count). "
        f"Keys: {list(r.keys())}"
    )
    assert "n_artifacts" in r, (
        f"Must rename n_versions → n_artifacts. Keys: {list(r.keys())}"
    )
    # Standard johnson upload: 1 logical version, 3 artifacts (raw +
    # shallow + full_flat).
    assert r["n_logical_versions"] >= 1
    assert r["n_artifacts"] >= r["n_logical_versions"], (
        f"n_artifacts ({r['n_artifacts']}) must be >= "
        f"n_logical_versions ({r['n_logical_versions']})"
    )


def test_two_logical_versions_for_two_separate_root_uploads():
    """Synthetic: insert 2 root artifacts for same product → store
    reports n_logical_versions=2."""
    from hub.app.stores.bom import list_products_with_bom
    pcode = "TRACK_B_TWO_LOGICAL"
    _insert_artifact(CLIENT, pcode, "ba_track_b_logical_1", 1)
    _insert_artifact(CLIENT, pcode, "ba_track_b_logical_2", 2)
    rows = list_products_with_bom(CLIENT, limit=10)
    matches = [r for r in rows if r["product_code"] == pcode]
    assert matches, f"product {pcode} not in list output"
    r = matches[0]
    assert r["n_logical_versions"] == 2, (
        f"Two independent lineage roots → 2 phiên bản. "
        f"Got n_logical_versions={r['n_logical_versions']}"
    )
    assert r["n_artifacts"] == 2


def test_three_shapes_share_one_logical_version():
    """Standard upload pattern: raw_graph artifact spawns shallow +
    full_flat materialized children. All 3 share one lineage_root."""
    from hub.app.stores.bom import list_products_with_bom
    pcode = "TRACK_B_ONE_LOGICAL"
    raw = "ba_track_b_3shapes_raw"
    shallow = "ba_track_b_3shapes_shallow"
    full = "ba_track_b_3shapes_full"
    _insert_artifact(CLIENT, pcode, raw, 1, flatten_status="non_flattened",
                     flatten_strategy="no_strategy")
    _insert_artifact(CLIENT, pcode, shallow, 2, parent_artifact_id=raw,
                     flatten_status="flattened",
                     flatten_strategy="manual_flat_as_provided")
    _insert_artifact(CLIENT, pcode, full, 3, parent_artifact_id=raw,
                     flatten_status="flattened",
                     flatten_strategy="technical_exploded")
    rows = list_products_with_bom(CLIENT, limit=10)
    matches = [r for r in rows if r["product_code"] == pcode]
    assert matches
    r = matches[0]
    assert r["n_logical_versions"] == 1, (
        f"3 shapes from same root = 1 phiên bản. "
        f"Got n_logical_versions={r['n_logical_versions']}"
    )
    assert r["n_artifacts"] == 3
