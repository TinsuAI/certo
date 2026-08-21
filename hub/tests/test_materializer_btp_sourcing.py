"""Phase 3a · materializer respects materials.btp_sourcing.

The shallow walk in `scripts.materialize_shallow_and_full_flat`
controls when the recursion stops. Pre-3a it stopped at every BTP;
post-3a it stops at btp_sx only when sourcing != 'self_produced_only'.
btp_sx flagged 'self_produced_only' is exploded into its own children.

BOM tree under test:
    TP_X
     ├ BTP_BOUGHT (btp_sx, purchased_only)  → stop
     │  └ NVL_C1                            (won't appear in shallow)
     └ BTP_INTERNAL (btp_sx, self_produced) → explode
        ├ NVL_C2
        └ NVL_C3
"""
from __future__ import annotations

import pytest

from app.database import connect
from scripts.materialize_shallow_and_full_flat import SHALLOW_WALK_SQL, derive


CLIENT = "mat_btp_test"
PRODUCT = "TP_MAT"
ARTIFACT = "ba_mat_test_root"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "materializer btp test"),
        )
        # Materials: TP, two BTPs with explicit sourcing, NVLs
        for code, cat, sourcing in [
            (PRODUCT,        "tp",     None),
            ("BTP_BOUGHT",   "btp_sx", "purchased_only"),
            ("BTP_INTERNAL", "btp_sx", "self_produced_only"),
            ("NVL_C1",       "nvl",    None),
            ("NVL_C2",       "nvl",    None),
            ("NVL_C3",       "nvl",    None),
        ]:
            cur.execute(
                "insert into hub.materials (client_id, material_code, "
                "name, category, btp_sourcing) values (%s, %s, %s, %s, %s) "
                "on conflict do nothing",
                (CLIENT, code, code, cat, sourcing),
            )
        # Artifacts: the parent BOM (TP_MAT) and a child BOM for BTP_INTERNAL
        # (so explode has somewhere to recurse into via shared edges).
        for art_id in (ARTIFACT,):
            cur.execute(
                "insert into hub.bom_artifacts (artifact_id, client_id, product_code, "
                "artifact_no, actor, intent, normalized_hash, source_bom_kind, "
                "flatten_status, flatten_strategy, source_channel, flatten_method, "
                "flatten_method_version) "
                "values (%s, %s, %s, %s, 'agency_staff', 'asserted_technical', %s, "
                "'technical_raw', 'non_flattened', 'no_strategy', 'agency_upload', "
                "'manual', '0.1') "
                "on conflict do nothing",
                (art_id, CLIENT, PRODUCT, 1, f"hash_{art_id}"),
            )
        # Edges all live under the single ARTIFACT (the raw graph is one
        # combined graph spanning TP and its sub-BOMs, per how Growatt
        # technical_raw is stored).
        for i, (parent, child, qty) in enumerate([
            (PRODUCT,        "BTP_BOUGHT",   1),
            (PRODUCT,        "BTP_INTERNAL", 1),
            ("BTP_BOUGHT",   "NVL_C1",       2),
            ("BTP_INTERNAL", "NVL_C2",       3),
            ("BTP_INTERNAL", "NVL_C3",       5),
        ]):
            cur.execute(
                "insert into hub.bom_edges (artifact_id, row_index, root_code, "
                "parent_code, child_code, qty_per_parent) values (%s, %s, %s, %s, %s, %s)",
                (ARTIFACT, i, PRODUCT, parent, child, qty),
            )
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bom_edges where artifact_id=%s", (ARTIFACT,))
        cur.execute("delete from hub.bom_artifacts where artifact_id=%s", (ARTIFACT,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def test_shallow_stops_at_purchased_btp():
    """BTP_BOUGHT (purchased_only) should appear as a leaf; its child
    NVL_C1 should NOT appear in the shallow result."""
    rows = derive(ARTIFACT, PRODUCT, CLIENT, SHALLOW_WALK_SQL)
    codes = {r["material_code"] for r in rows}
    assert "BTP_BOUGHT" in codes
    assert "NVL_C1" not in codes, codes


def test_shallow_explodes_self_produced_btp():
    """BTP_INTERNAL (self_produced_only) should NOT appear; its children
    NVL_C2 and NVL_C3 should appear as leaves."""
    rows = derive(ARTIFACT, PRODUCT, CLIENT, SHALLOW_WALK_SQL)
    codes = {r["material_code"] for r in rows}
    assert "BTP_INTERNAL" not in codes, codes
    assert "NVL_C2" in codes
    assert "NVL_C3" in codes


def test_shallow_carries_correct_qty_for_exploded_path():
    """qty for NVL_C2 = TP→BTP_INTERNAL (1) × BTP_INTERNAL→NVL_C2 (3) = 3."""
    rows = derive(ARTIFACT, PRODUCT, CLIENT, SHALLOW_WALK_SQL)
    by_code = {r["material_code"]: r["qty_per_unit"] for r in rows}
    assert by_code.get("NVL_C2") == 3.0
    assert by_code.get("NVL_C3") == 5.0
