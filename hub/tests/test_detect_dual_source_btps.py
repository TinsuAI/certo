"""Phase 3a · BTP sourcing classifier (`scripts/detect_dual_source_btps.py`).

Classification rule per brief 2026-05-06-phase-3-resolver-profiles:
- BCCT import row for the code → purchased signal
- code appears as bom_edges.parent_code → self_produced signal
- both → 'dual_source'; only purchased → 'purchased_only';
  only self-produced → 'self_produced_only'; neither → 'unknown'.

Scope: only materials.category='btp_sx' rows are classified.
"""
from __future__ import annotations

import pytest

from hub.app.database import connect
from hub.scripts.detect_dual_source_btps import (
    apply_classifications,
    classify_btp_sourcing_for_client,
)


CLIENT = "btp_classify_test"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "btp classify test"),
        )
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.bom_edges where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (CLIENT,),
        )
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.bcct_rows where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _add_material(cur, code: str, *, category: str = "btp_sx"):
    cur.execute(
        "insert into hub.materials (client_id, material_code, "
        "name, category) values (%s, %s, %s, %s)",
        (CLIENT, code, f"mat {code}", category),
    )


def _add_bcct_import(cur, code: str, *, year: int = 2025, line: int = 1, dt: str = "E11"):
    # mig 038: material_identity column dropped — classifier now uses
    # material_code only. So seed customs_code = code (the agency code
    # we want flagged as imported).
    cur.execute(
        "insert into hub.bcct_rows (client_id, registration_date, transaction_key, line_no, "
        "customs_code, direction, declaration_type, declaration_no) "
        "values (%s, %s, %s, %s, %s, 'import', %s, %s)",
        (CLIENT, f"{year}-01-15", f"tk_{code}_{line}", line, code, dt,
         f"DEC{year}{line}"),
    )


def _add_bom_edge(cur, parent: str, child: str):
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, product_code, "
        "artifact_no, actor, intent, normalized_hash, source_bom_kind, "
        "flatten_status, flatten_strategy, source_channel, flatten_method, "
        "flatten_method_version) "
        "values (%s, %s, %s, %s, 'agency_staff', 'asserted_technical', %s, "
        "'technical_raw', 'non_flattened', 'no_strategy', 'agency_upload', "
        "'manual', '0.1') "
        "on conflict do nothing",
        (f"ba_test_{parent}", CLIENT, "TP-TEST", 1, f"hash_{parent}"),
    )
    cur.execute(
        "insert into hub.bom_edges (artifact_id, row_index, root_code, "
        "parent_code, child_code, qty_per_parent) "
        "values (%s, %s, 'TP-TEST', %s, %s, 1)",
        (f"ba_test_{parent}", hash((parent, child)) % 100000, parent, child),
    )


# ─────────────────────────────────────────────────────────────────────
# Classification rule
# ─────────────────────────────────────────────────────────────────────


def test_classify_purchased_only_when_imported_not_in_bom():
    with connect() as conn, conn.cursor() as cur:
        _add_material(cur, "BTP_PURCHASED")
        _add_bcct_import(cur, "BTP_PURCHASED")
        out = classify_btp_sourcing_for_client(cur, CLIENT)
    assert out["BTP_PURCHASED"] == "purchased_only"


def test_classify_self_produced_only_when_in_bom_not_imported():
    with connect() as conn, conn.cursor() as cur:
        _add_material(cur, "BTP_INTERNAL")
        _add_bom_edge(cur, "BTP_INTERNAL", "NVL_X")
        out = classify_btp_sourcing_for_client(cur, CLIENT)
    assert out["BTP_INTERNAL"] == "self_produced_only"


def test_classify_dual_source_when_both_signals():
    with connect() as conn, conn.cursor() as cur:
        _add_material(cur, "BTP_BOTH")
        _add_bcct_import(cur, "BTP_BOTH")
        _add_bom_edge(cur, "BTP_BOTH", "NVL_Y")
        out = classify_btp_sourcing_for_client(cur, CLIENT)
    assert out["BTP_BOTH"] == "dual_source"


def test_classify_unknown_when_neither_signal():
    with connect() as conn, conn.cursor() as cur:
        _add_material(cur, "BTP_ORPHAN")
        out = classify_btp_sourcing_for_client(cur, CLIENT)
    assert out["BTP_ORPHAN"] == "unknown"


# ─────────────────────────────────────────────────────────────────────
# Scope — only btp_sx materials
# ─────────────────────────────────────────────────────────────────────


def test_classify_skips_non_btp_categories():
    with connect() as conn, conn.cursor() as cur:
        _add_material(cur, "NVL_RAW", category="nvl")
        _add_material(cur, "TP_FINAL", category="tp")
        _add_bcct_import(cur, "NVL_RAW")
        _add_bom_edge(cur, "TP_FINAL", "NVL_RAW")
        out = classify_btp_sourcing_for_client(cur, CLIENT)
    assert "NVL_RAW" not in out
    assert "TP_FINAL" not in out


# ─────────────────────────────────────────────────────────────────────
# Apply — writes to materials.btp_sourcing
# ─────────────────────────────────────────────────────────────────────


def test_apply_writes_classification_to_db():
    with connect() as conn, conn.cursor() as cur:
        _add_material(cur, "BTP_WRITE")
        _add_bcct_import(cur, "BTP_WRITE")
        _add_bom_edge(cur, "BTP_WRITE", "NVL_Z")
        classifications = classify_btp_sourcing_for_client(cur, CLIENT)
        n = apply_classifications(cur, CLIENT, classifications)
        assert n == 1
        cur.execute(
            "select btp_sourcing from hub.materials "
            "where client_id=%s and material_code=%s",
            (CLIENT, "BTP_WRITE"),
        )
        assert cur.fetchone()[0] == "dual_source"


def test_apply_is_idempotent_when_value_unchanged():
    with connect() as conn, conn.cursor() as cur:
        _add_material(cur, "BTP_IDEMP")
        _add_bcct_import(cur, "BTP_IDEMP")
        classifications = classify_btp_sourcing_for_client(cur, CLIENT)
        apply_classifications(cur, CLIENT, classifications)
        # second call should write 0 rows (value unchanged)
        n2 = apply_classifications(cur, CLIENT, classifications)
        assert n2 == 0
