"""Phase 3c · `derive_btp_shallows.py` post-ingest derivation.

For each raw_graph artifact, find every intermediate `parent_code` in
`bom_edges` whose material is `btp_sx`, then mint a new raw_graph
artifact rooted at that BTP, lineage-linked to the parent. Closes the
0/342 vs 144/147 shallow-decomposability gap from memory
`project_growatt_bom_v1_v2_equivalence.md`.

Risk R3 mitigation: skip BTPs flagged `btp_sourcing='purchased_only'`
— terminal nodes need no own BOM. `self_produced_only`, `dual_source`,
and unknown all get derived.

Idempotent: re-running yields no new artifacts (normalized_hash dedup).
"""
from __future__ import annotations

import pytest

from app.database import connect
from scripts.derive_btp_shallows import derive_btp_shallows_for_artifact


CLIENT = "derive_btp_test"
ROOT_PRODUCT = "TP_DRV"
ROOT_ARTIFACT = "ba_drv_root"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "derive btp test"),
        )
        for code, cat, sourcing in [
            (ROOT_PRODUCT,    "tp",     None),
            ("BTP_INNER1",    "btp_sx", "self_produced_only"),
            ("BTP_INNER2",    "btp_sx", "dual_source"),
            ("BTP_PURCHASED", "btp_sx", "purchased_only"),
            ("NVL_X",         "nvl",    None),
            ("NVL_Y",         "nvl",    None),
            ("NVL_Z",         "nvl",    None),
        ]:
            cur.execute(
                "insert into hub.materials (client_id, material_code, "
                "name, category, btp_sourcing) "
                "values (%s, %s, %s, %s, %s) on conflict do nothing",
                (CLIENT, code, code, cat, sourcing),
            )
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, product_code, "
            "artifact_no, actor, intent, normalized_hash, source_bom_kind, "
            "flatten_status, flatten_strategy, source_channel, flatten_method, "
            "flatten_method_version) "
            "values (%s, %s, %s, 1, 'agency_staff', 'asserted_technical', "
            "'h_drv', 'technical_raw', 'non_flattened', 'no_strategy', "
            "'agency_upload', 'manual', '0.1') on conflict do nothing",
            (ROOT_ARTIFACT, CLIENT, ROOT_PRODUCT),
        )
        for i, (parent, child, qty) in enumerate([
            (ROOT_PRODUCT,    "BTP_INNER1",    1),
            (ROOT_PRODUCT,    "BTP_INNER2",    2),
            (ROOT_PRODUCT,    "BTP_PURCHASED", 3),
            ("BTP_INNER1",    "NVL_X",         5),
            ("BTP_INNER2",    "NVL_Y",         7),
            ("BTP_INNER2",    "NVL_Z",         9),
            ("BTP_PURCHASED", "NVL_X",         11),  # would be skipped
        ]):
            cur.execute(
                "insert into hub.bom_edges (artifact_id, row_index, root_code, "
                "parent_code, child_code, qty_per_parent) values (%s, %s, %s, %s, %s, %s)",
                (ROOT_ARTIFACT, i, ROOT_PRODUCT, parent, child, qty),
            )
        conn.commit()
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.bom_edges where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (CLIENT,),
        )
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


# ─────────────────────────────────────────────────────────────────────
# Core derivation
# ─────────────────────────────────────────────────────────────────────


def test_derives_one_artifact_per_self_produced_btp():
    minted = derive_btp_shallows_for_artifact(
        artifact_id=ROOT_ARTIFACT, client_id=CLIENT, status="draft",
    )
    minted_codes = {m["product_code"] for m in minted}
    assert "BTP_INNER1" in minted_codes
    assert "BTP_INNER2" in minted_codes


def test_skips_purchased_only_btp():
    """R3 mitigation: terminal purchased BTPs need no own BOM."""
    minted = derive_btp_shallows_for_artifact(
        artifact_id=ROOT_ARTIFACT, client_id=CLIENT, status="draft",
    )
    assert "BTP_PURCHASED" not in {m["product_code"] for m in minted}


def test_skips_non_btp_categories():
    """Only btp_sx parents get their own derived artifact."""
    minted = derive_btp_shallows_for_artifact(
        artifact_id=ROOT_ARTIFACT, client_id=CLIENT, status="draft",
    )
    minted_codes = {m["product_code"] for m in minted}
    # ROOT_PRODUCT is the original artifact's product_code (category=tp);
    # also a parent_code in edges, but should not get re-derived.
    assert ROOT_PRODUCT not in minted_codes


def test_derived_artifact_has_only_subtree_edges():
    """Mint must include only edges descended from the BTP, not the
    full original tree."""
    minted = derive_btp_shallows_for_artifact(
        artifact_id=ROOT_ARTIFACT, client_id=CLIENT, status="draft",
    )
    inner1 = next(m for m in minted if m["product_code"] == "BTP_INNER1")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select parent_code, child_code from hub.bom_edges "
            "where artifact_id=%s order by row_index",
            (inner1["artifact_id"],),
        )
        edges = cur.fetchall()
    pairs = {(p, c) for p, c in edges}
    assert pairs == {("BTP_INNER1", "NVL_X")}


def test_derived_artifact_lineage_marks_derivation_no_parent_link():
    """Same BTP appearing under multiple parent TPs is the same data —
    we dedup via (product_code, normalized_edges_hash) without
    parent_norm fragmenting. So `parent_artifact_id` is intentionally
    NULL on derived BTP slices; the source TP is recorded informally
    in `context.first_seen_via` for traceability + can be re-derived
    on demand by walking bom_edges. Lineage carries the derivation
    label only."""
    minted = derive_btp_shallows_for_artifact(
        artifact_id=ROOT_ARTIFACT, client_id=CLIENT, status="draft",
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select parent_artifact_id, lineage, context "
            "  from hub.bom_artifacts where artifact_id=%s",
            (minted[0]["artifact_id"],),
        )
        parent, lineage, context = cur.fetchone()
    assert parent is None
    assert lineage.get("derivation") == "btp_shallow_post_ingest"
    assert context.get("first_seen_via") == ROOT_ARTIFACT


def test_derived_artifact_status_respects_policy():
    """status='draft' lands as draft; 'publish' lands published."""
    minted = derive_btp_shallows_for_artifact(
        artifact_id=ROOT_ARTIFACT, client_id=CLIENT, status="draft",
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select status from hub.bom_artifacts where artifact_id=%s",
            (minted[0]["artifact_id"],),
        )
        assert cur.fetchone()[0] == "draft"


# ─────────────────────────────────────────────────────────────────────
# Idempotency
# ─────────────────────────────────────────────────────────────────────


def test_idempotent_second_run_yields_no_new_artifacts():
    derive_btp_shallows_for_artifact(
        artifact_id=ROOT_ARTIFACT, client_id=CLIENT, status="draft",
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.bom_artifacts where client_id=%s",
            (CLIENT,),
        )
        count_after_first = cur.fetchone()[0]
    minted_again = derive_btp_shallows_for_artifact(
        artifact_id=ROOT_ARTIFACT, client_id=CLIENT, status="draft",
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.bom_artifacts where client_id=%s",
            (CLIENT,),
        )
        count_after_second = cur.fetchone()[0]
    assert count_after_first == count_after_second
    # Returned list reflects existing + newly minted; idempotency means
    # rows NOT created don't show up as `created=True`.
    assert all(not m.get("created") for m in minted_again)


# ─────────────────────────────────────────────────────────────────────
# Disabled policy
# ─────────────────────────────────────────────────────────────────────


def test_status_disabled_raises_or_skips():
    """Per `clients.auto_derive_shallow_from_raw='disabled'` policy."""
    minted = derive_btp_shallows_for_artifact(
        artifact_id=ROOT_ARTIFACT, client_id=CLIENT, status="disabled",
    )
    assert minted == []


def test_subtree_edges_rerooted_path_and_level():
    """Edges in the minted BTP slice carry node_path starting at the BTP
    (parent TP context above the BTP stripped); level is recomputed as
    depth from the BTP root (direct children = 1)."""
    minted = derive_btp_shallows_for_artifact(
        artifact_id=ROOT_ARTIFACT, client_id=CLIENT, status="draft",
    )
    inner2 = next(m for m in minted if m["product_code"] == "BTP_INNER2")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select parent_code, child_code, level, node_path "
            "from hub.bom_edges where artifact_id=%s order by row_index",
            (inner2["artifact_id"],),
        )
        rows = cur.fetchall()
    assert rows  # at least one edge
    for parent, child, level, node_path in rows:
        # No edge above the BTP root is included → parent must descend
        # from BTP_INNER2 (in this fixture, parent is BTP_INNER2 itself).
        assert parent == "BTP_INNER2"
        # node_path begins at the BTP, not at ROOT_PRODUCT.
        assert node_path is not None
        assert node_path.startswith("BTP_INNER2")
        assert ROOT_PRODUCT not in node_path
        # Direct children of the BTP root are at level 1.
        assert level == 1
