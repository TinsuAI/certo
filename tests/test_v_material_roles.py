"""View `hub.v_material_roles` — atomic signals + observed_roles[] + multi-role + conflict.

Brief: .ai/features/2026-05-07-catalog-roles-refactor/brief.md (rev 5)

Pins D4 walk-through (10 states), tombstone awareness, D8 conflict matrix,
and the lossy-state regressions.
"""
from __future__ import annotations

import secrets

import pytest

from app.database import connect


@pytest.fixture
def cid():
    """Throwaway client per test."""
    client_id = "vmr-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (client_id, "v_material_roles test"),
        )
    yield client_id
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bcct_rows where client_id=%s", (client_id,))
        cur.execute("delete from hub.bcct_row_history where client_id=%s", (client_id,))
        cur.execute(
            "delete from hub.bom_edges where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (client_id,),
        )
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (client_id,))
        cur.execute("delete from hub.materials where client_id=%s", (client_id,))
        cur.execute("delete from hub.clients where client_id=%s", (client_id,))


def _seed_material(cur, *, client_id, code, kind="nvl"):
    cur.execute(
        "insert into hub.materials (client_id, customs_code, internal_code, "
        "name, category) values (%s, %s, %s, %s, %s)",
        (client_id, code, code, code, kind),
    )


def _seed_bcct(cur, *, client_id, code, direction, txkey=None,
               regdate="2026-01-15", declaration_type=None):
    """Insert a synthetic BCCT row.

    Default declaration_type:
      - export → E42 (canonical TP export for DNCX)
      - import → E11 (canonical NVL import for DNCX, fires `nvl` role)

    Override `declaration_type` to test non-NVL imports (e.g. A11 commercial)
    or other export types.
    """
    if txkey is None:
        txkey = f"TXKEY-{code}-{direction}"
    if declaration_type is None:
        declaration_type = "E42" if direction == "export" else "E11"
    cur.execute(
        "insert into hub.bcct_rows (client_id, transaction_key, line_no, "
        "declaration_no, declaration_type, direction, registration_date, "
        "customs_code, goods_name, payload) "
        "values (%s, %s, '1', %s, %s, %s, %s, %s, %s, '{}'::jsonb)",
        (client_id, txkey, txkey.split('-')[0],
         declaration_type, direction, regdate, code, f"{code} test"),
    )


def _seed_bom_artifact(cur, *, client_id, product_code, artifact_id, tombstoned=False):
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, product_code, "
        "artifact_no, actor, intent, normalized_hash, source_bom_kind, "
        "flatten_status, flatten_strategy, source_channel, flatten_method, "
        "flatten_method_version, status, published_at) "
        "values (%s, %s, %s, 1, 'agency_staff', 'asserted_technical', %s, "
        "'technical_flattened', 'flattened', 'technical_exploded', "
        "'agency_upload', 'manual', '0.1', 'published', now())",
        (artifact_id, client_id, product_code, f"hash_{artifact_id}"),
    )
    if tombstoned:
        cur.execute(
            "update hub.bom_artifacts set tombstoned_at = now(), "
            "tombstone_reason = 'test' where artifact_id = %s",
            (artifact_id,),
        )


def _seed_bom_edge(cur, *, artifact_id, parent_code, child_code, qty=1.0):
    cur.execute(
        "insert into hub.bom_edges (artifact_id, row_index, root_code, "
        "parent_code, child_code, qty_per_parent, uom, level) "
        "values (%s, 1, %s, %s, %s, %s, 'PCS', 1)",
        (artifact_id, parent_code, parent_code, child_code, qty),
    )


def _query_view(cur, *, client_id, code):
    cur.execute(
        "select declared_kind, has_imports, has_exports, is_consumed_in_bom, "
        "has_own_bom, observed_roles, is_multi_role, declared_observed_conflict "
        "from hub.v_material_roles where client_id=%s and customs_code=%s",
        (client_id, code),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "declared_kind": row[0],
        "has_imports": row[1],
        "has_exports": row[2],
        "is_consumed_in_bom": row[3],
        "has_own_bom": row[4],
        "observed_roles": list(row[5] or []),
        "is_multi_role": row[6],
        "declared_observed_conflict": row[7],
    }


# ─── D4 walk-through (10 states) ────────────────────────────────────


def test_pure_tp(cid):
    """exp + own_bom → ['tp']"""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="TP1", kind="tp")
        _seed_bcct(cur, client_id=cid, code="TP1", direction="export")
        _seed_bom_artifact(cur, client_id=cid, product_code="TP1", artifact_id=f"ba_{cid}_tp1")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="TP1")
    assert v["observed_roles"] == ["tp"]
    assert v["is_multi_role"] is False
    assert v["declared_observed_conflict"] is False


def test_rework_tp_multi_role(cid):
    """exp + consumed + own_bom → ['tp','btp_sx']"""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="REWORK", kind="btp_sx")
        _seed_material(cur, client_id=cid, code="PARENT", kind="tp")
        _seed_bcct(cur, client_id=cid, code="REWORK", direction="export")
        _seed_bom_artifact(cur, client_id=cid, product_code="REWORK", artifact_id=f"ba_{cid}_rw")
        _seed_bom_artifact(cur, client_id=cid, product_code="PARENT", artifact_id=f"ba_{cid}_p")
        _seed_bom_edge(cur, artifact_id=f"ba_{cid}_p", parent_code="PARENT", child_code="REWORK")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="REWORK")
    assert sorted(v["observed_roles"]) == ["btp_sx", "tp"]
    assert v["is_multi_role"] is True
    # declared='btp_sx' is in observed, so no conflict.
    assert v["declared_observed_conflict"] is False


def test_btp_self_produced(cid):
    """consumed + own_bom (no exp/imp) → ['btp_sx']"""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="BTP_SX1", kind="btp_sx")
        _seed_material(cur, client_id=cid, code="PARENT", kind="tp")
        _seed_bom_artifact(cur, client_id=cid, product_code="BTP_SX1", artifact_id=f"ba_{cid}_b")
        _seed_bom_artifact(cur, client_id=cid, product_code="PARENT", artifact_id=f"ba_{cid}_p")
        _seed_bom_edge(cur, artifact_id=f"ba_{cid}_p", parent_code="PARENT", child_code="BTP_SX1")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="BTP_SX1")
    assert v["observed_roles"] == ["btp_sx"]
    assert v["is_multi_role"] is False


def test_btp_purchased_no_bom(cid):
    """imp + consumed (no own_bom) → ['nvl'] (collapses with pure NVL)"""
    with connect() as conn, conn.cursor() as cur:
        # Declared as btp_nm (per Phase 3a semantic) — observation can't distinguish.
        _seed_material(cur, client_id=cid, code="BTPP", kind="btp_nm")
        _seed_material(cur, client_id=cid, code="PARENT", kind="tp")
        _seed_bcct(cur, client_id=cid, code="BTPP", direction="import")
        _seed_bom_artifact(cur, client_id=cid, product_code="PARENT", artifact_id=f"ba_{cid}_p")
        _seed_bom_edge(cur, artifact_id=f"ba_{cid}_p", parent_code="PARENT", child_code="BTPP")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="BTPP")
    # Structural collapse: ['nvl'] regardless of declared btp_nm.
    assert v["observed_roles"] == ["nvl"]
    # btp_nm declared NEVER triggers conflict per D8 last-row.
    assert v["declared_observed_conflict"] is False


def test_btp_purchased_with_own_bom(cid):
    """imp + consumed + own_bom → ['btp_sx'] (Growatt-derived shape)"""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="BTPP_OWN", kind="btp_sx")
        _seed_material(cur, client_id=cid, code="PARENT", kind="tp")
        _seed_bcct(cur, client_id=cid, code="BTPP_OWN", direction="import")
        _seed_bom_artifact(cur, client_id=cid, product_code="BTPP_OWN", artifact_id=f"ba_{cid}_o")
        _seed_bom_artifact(cur, client_id=cid, product_code="PARENT", artifact_id=f"ba_{cid}_p")
        _seed_bom_edge(cur, artifact_id=f"ba_{cid}_p", parent_code="PARENT", child_code="BTPP_OWN")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="BTPP_OWN")
    assert v["observed_roles"] == ["btp_sx"]


def test_pure_nvl(cid):
    """imp + consumed (no own_bom) → ['nvl']"""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="NVL1", kind="nvl")
        _seed_material(cur, client_id=cid, code="PARENT", kind="tp")
        _seed_bcct(cur, client_id=cid, code="NVL1", direction="import")
        _seed_bom_artifact(cur, client_id=cid, product_code="PARENT", artifact_id=f"ba_{cid}_p")
        _seed_bom_edge(cur, artifact_id=f"ba_{cid}_p", parent_code="PARENT", child_code="NVL1")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="NVL1")
    assert v["observed_roles"] == ["nvl"]
    assert v["is_multi_role"] is False


def test_imported_unused_with_nvl_declaration_type(cid):
    """imp only (E11 NVL declaration, no consumed, no own_bom) → ['nvl'].

    Per mig 034: has_nvl_import alone is enough — strict consumption
    requirement was relaxed."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="UNUSED", kind="nvl")
        _seed_bcct(cur, client_id=cid, code="UNUSED", direction="import")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="UNUSED")
    assert v["observed_roles"] == ["nvl"]
    assert v["has_imports"] is True
    assert v["is_consumed_in_bom"] is False
    assert v["declared_observed_conflict"] is False


def test_imported_only_non_nvl_declaration_type(cid):
    """imp only with declaration_type='A11' (commercial, not NVL set) → [].

    `has_imports=true` but `has_nvl_import=false` → 'nvl' rule does NOT fire."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="A11_ONLY", kind="nvl")
        _seed_bcct(cur, client_id=cid, code="A11_ONLY", direction="import",
                   declaration_type="A11")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="A11_ONLY")
    assert v["has_imports"] is True
    assert v["observed_roles"] == []  # not auto-classified


def test_imported_with_e13_mixed_declaration_type(cid):
    """imp only with declaration_type='E13' (mixed: NVL+máy móc) → [].

    E13 is intentionally excluded from auto-NVL set per QĐ 1357
    'Nhập hàng hóa khác vào DNCX' (mixed). Operator confirms via
    declared category."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="E13_ONLY", kind="nvl")
        _seed_bcct(cur, client_id=cid, code="E13_ONLY", direction="import",
                   declaration_type="E13")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="E13_ONLY")
    assert v["has_imports"] is True
    assert v["observed_roles"] == []


def test_e13_plus_e11_fires_nvl(cid):
    """imp with mixed E13 AND E11 NVL → ['nvl'] (E11 alone enough)."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="MIXED", kind="nvl")
        _seed_bcct(cur, client_id=cid, code="MIXED", direction="import",
                   declaration_type="E13", txkey="TX-mixed-E13")
        _seed_bcct(cur, client_id=cid, code="MIXED", direction="import",
                   declaration_type="E11", txkey="TX-mixed-E11")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="MIXED")
    assert v["observed_roles"] == ["nvl"]


def test_re_export_trader_with_nvl_import(cid):
    """exp + imp (E11 NVL, no consumed) → ['tp','nvl'] multi-role.

    Per mig 034 relax: NVL import alone (no consume) fires 'nvl'.
    Combined with 'tp' from export = trader pattern, multi-role flagged."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="TRADER", kind="tp")
        _seed_bcct(cur, client_id=cid, code="TRADER", direction="import",
                   txkey="TX-trader-imp")
        _seed_bcct(cur, client_id=cid, code="TRADER", direction="export",
                   txkey="TX-trader-exp")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="TRADER")
    assert sorted(v["observed_roles"]) == ["nvl", "tp"]
    assert v["is_multi_role"] is True


def test_re_export_trader_with_a11_commercial_import(cid):
    """exp + imp (A11 commercial, not NVL set) → ['tp'] only.

    Imp doesn't qualify for NVL (commercial declaration_type)."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="TRADER2", kind="tp")
        _seed_bcct(cur, client_id=cid, code="TRADER2", direction="import",
                   txkey="TX-t2-imp", declaration_type="A11")
        _seed_bcct(cur, client_id=cid, code="TRADER2", direction="export",
                   txkey="TX-t2-exp")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="TRADER2")
    assert v["observed_roles"] == ["tp"]


def test_trader_also_consumer_multi_role(cid):
    """exp + imp + consumed (no own_bom) → ['tp','nvl'] multi-role"""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="TRADER2", kind="nvl")
        _seed_material(cur, client_id=cid, code="PARENT", kind="tp")
        _seed_bcct(cur, client_id=cid, code="TRADER2", direction="import",
                   txkey="TX-t2-imp")
        _seed_bcct(cur, client_id=cid, code="TRADER2", direction="export",
                   txkey="TX-t2-exp")
        _seed_bom_artifact(cur, client_id=cid, product_code="PARENT", artifact_id=f"ba_{cid}_p")
        _seed_bom_edge(cur, artifact_id=f"ba_{cid}_p", parent_code="PARENT", child_code="TRADER2")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="TRADER2")
    assert sorted(v["observed_roles"]) == ["nvl", "tp"]
    assert v["is_multi_role"] is True


def test_orphan_tp_with_bom_only(cid):
    """own_bom only (no exp/imp/consumed) → []"""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="ORPHAN", kind="tp")
        _seed_bom_artifact(cur, client_id=cid, product_code="ORPHAN", artifact_id=f"ba_{cid}_o")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="ORPHAN")
    assert v["observed_roles"] == []
    assert v["has_own_bom"] is True
    # Orphan: no observation → no conflict per D8.
    assert v["declared_observed_conflict"] is False


# ─── Tombstone awareness ────────────────────────────────────────────


def test_tombstone_flips_is_consumed_in_bom(cid):
    """Tombstoning the only consuming bom_artifact flips is_consumed_in_bom T→F.
    Per mig 034 relax: NVL stays even after consume signal goes (NVL import
    alone keeps it). To verify is_consumed_in_bom flips, watch the atomic
    signal directly."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="LEAF", kind="nvl")
        _seed_material(cur, client_id=cid, code="PARENT", kind="tp")
        _seed_bcct(cur, client_id=cid, code="LEAF", direction="import")
        _seed_bom_artifact(cur, client_id=cid, product_code="PARENT", artifact_id=f"ba_{cid}_p")
        _seed_bom_edge(cur, artifact_id=f"ba_{cid}_p", parent_code="PARENT", child_code="LEAF")
    with connect() as conn, conn.cursor() as cur:
        before = _query_view(cur, client_id=cid, code="LEAF")
        assert before["is_consumed_in_bom"] is True
        assert before["observed_roles"] == ["nvl"]
        cur.execute(
            "update hub.bom_artifacts set tombstoned_at = now(), "
            "tombstone_reason = 'test' where artifact_id = %s",
            (f"ba_{cid}_p",),
        )
    with connect() as conn, conn.cursor() as cur:
        after = _query_view(cur, client_id=cid, code="LEAF")
    # Atomic signal flips: consumed → false.
    assert after["is_consumed_in_bom"] is False
    # NVL role stays because has_nvl_import alone is enough now.
    assert after["observed_roles"] == ["nvl"]


def test_tombstone_flips_has_own_bom(cid):
    """Tombstoning the only own bom_artifact for X flips has_own_bom T→F."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="X", kind="tp")
        _seed_bcct(cur, client_id=cid, code="X", direction="export")
        _seed_bom_artifact(cur, client_id=cid, product_code="X", artifact_id=f"ba_{cid}_x")
    with connect() as conn, conn.cursor() as cur:
        before = _query_view(cur, client_id=cid, code="X")
        assert before["has_own_bom"] is True
        # Tombstone the only own artifact.
        cur.execute(
            "update hub.bom_artifacts set tombstoned_at = now(), "
            "tombstone_reason = 'test' where artifact_id = %s",
            (f"ba_{cid}_x",),
        )
    with connect() as conn, conn.cursor() as cur:
        after = _query_view(cur, client_id=cid, code="X")
    assert after["has_own_bom"] is False
    # Still has_exports → ['tp'] still fires.
    assert after["observed_roles"] == ["tp"]


# ─── D8 conflict matrix ──────────────────────────────────────────────


def test_conflict_tp_declared_only_consumed(cid):
    """declared='tp', observed=['btp_sx'] → conflict True"""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="MISDECL", kind="tp")
        _seed_material(cur, client_id=cid, code="PARENT", kind="tp")
        _seed_bom_artifact(cur, client_id=cid, product_code="MISDECL", artifact_id=f"ba_{cid}_m")
        _seed_bom_artifact(cur, client_id=cid, product_code="PARENT", artifact_id=f"ba_{cid}_p")
        _seed_bom_edge(cur, artifact_id=f"ba_{cid}_p", parent_code="PARENT", child_code="MISDECL")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="MISDECL")
    assert v["observed_roles"] == ["btp_sx"]
    assert v["declared_observed_conflict"] is True


def test_conflict_ccdc_declared_with_observation(cid):
    """declared='ccdc', observed=['nvl'] → conflict True (CCDC shouldn't show role)"""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="TOOL", kind="ccdc")
        _seed_material(cur, client_id=cid, code="PARENT", kind="tp")
        _seed_bcct(cur, client_id=cid, code="TOOL", direction="import")
        _seed_bom_artifact(cur, client_id=cid, product_code="PARENT", artifact_id=f"ba_{cid}_p")
        _seed_bom_edge(cur, artifact_id=f"ba_{cid}_p", parent_code="PARENT", child_code="TOOL")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="TOOL")
    assert v["observed_roles"] == ["nvl"]
    assert v["declared_observed_conflict"] is True


def test_no_conflict_btp_nm_always(cid):
    """declared='btp_nm' NEVER triggers conflict regardless of observed."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="BTPNM", kind="btp_nm")
        _seed_material(cur, client_id=cid, code="PARENT", kind="tp")
        _seed_bcct(cur, client_id=cid, code="BTPNM", direction="import")
        _seed_bom_artifact(cur, client_id=cid, product_code="PARENT", artifact_id=f"ba_{cid}_p")
        _seed_bom_edge(cur, artifact_id=f"ba_{cid}_p", parent_code="PARENT", child_code="BTPNM")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="BTPNM")
    assert v["observed_roles"] == ["nvl"]
    assert v["declared_observed_conflict"] is False


def test_no_conflict_orphan(cid):
    """observed=[] → never a conflict (no evidence yet)."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="ORF", kind="tp")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="ORF")
    assert v["observed_roles"] == []
    assert v["declared_observed_conflict"] is False


def test_re_export_trader_declared_nvl_no_conflict(cid):
    """declared='nvl', observed=['tp','nvl'] (re-export trader, NVL import) →
    no conflict because 'nvl' IS in observed_roles. Multi-role flagged."""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="RT", kind="nvl")
        _seed_bcct(cur, client_id=cid, code="RT", direction="import",
                   txkey="TX-rt-imp")
        _seed_bcct(cur, client_id=cid, code="RT", direction="export",
                   txkey="TX-rt-exp")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="RT")
    assert sorted(v["observed_roles"]) == ["nvl", "tp"]
    assert v["is_multi_role"] is True
    # declared='nvl' IS in ['tp','nvl'] → no conflict.
    assert v["declared_observed_conflict"] is False


# ─── Lossy state regressions ────────────────────────────────────────


def test_lossy_consumed_no_source(cid):
    """(F,F,T,F): consumed but not imp + not own_bom → observed=[] (signal lost)"""
    # Note: structurally weird (phantom child). This pins the lossy behavior.
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="PHANTOM", kind="nvl")
        _seed_material(cur, client_id=cid, code="PARENT", kind="tp")
        _seed_bom_artifact(cur, client_id=cid, product_code="PARENT", artifact_id=f"ba_{cid}_p")
        _seed_bom_edge(cur, artifact_id=f"ba_{cid}_p", parent_code="PARENT", child_code="PHANTOM")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="PHANTOM")
    assert v["is_consumed_in_bom"] is True
    assert v["has_imports"] is False
    assert v["has_own_bom"] is False
    # Documented limitation: signal silently lost.
    assert v["observed_roles"] == []


def test_lossy_exp_consumed_no_source(cid):
    """(T,F,T,F): exp + consumed, no imp/own_bom → observed=['tp'] (consumption lost)"""
    with connect() as conn, conn.cursor() as cur:
        _seed_material(cur, client_id=cid, code="PHX", kind="tp")
        _seed_material(cur, client_id=cid, code="PARENT", kind="tp")
        _seed_bcct(cur, client_id=cid, code="PHX", direction="export")
        _seed_bom_artifact(cur, client_id=cid, product_code="PARENT", artifact_id=f"ba_{cid}_p")
        _seed_bom_edge(cur, artifact_id=f"ba_{cid}_p", parent_code="PARENT", child_code="PHX")
    with connect() as conn, conn.cursor() as cur:
        v = _query_view(cur, client_id=cid, code="PHX")
    # 'btp_sx' rule needs has_own_bom — fails. Only 'tp'.
    assert v["observed_roles"] == ["tp"]
    assert v["is_consumed_in_bom"] is True


# ─── Cross-client isolation ──────────────────────────────────────────


def test_cross_client_isolation(cid):
    """Other clients' BOM/BCCT must not leak into this client's view rows."""
    other = "vmrother-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (other, "other"),
        )
        # Both clients have same code 'SHARED'.
        _seed_material(cur, client_id=cid, code="SHARED", kind="tp")
        _seed_material(cur, client_id=other, code="SHARED", kind="nvl")
        # Only the OTHER client has BCCT export of SHARED.
        _seed_bcct(cur, client_id=other, code="SHARED", direction="export")
    try:
        with connect() as conn, conn.cursor() as cur:
            v_cid = _query_view(cur, client_id=cid, code="SHARED")
            v_other = _query_view(cur, client_id=other, code="SHARED")
        # cid sees no observation; other sees ['tp'].
        assert v_cid["has_exports"] is False
        assert v_cid["observed_roles"] == []
        assert v_other["has_exports"] is True
        assert v_other["observed_roles"] == ["tp"]
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from hub.bcct_rows where client_id=%s", (other,))
            cur.execute("delete from hub.bcct_row_history where client_id=%s", (other,))
            cur.execute("delete from hub.materials where client_id=%s", (other,))
            cur.execute("delete from hub.clients where client_id=%s", (other,))


# ─── Real-data smoke (env-gated could be added later) ────────────────


def test_real_growatt_rework_pv01_0104300():
    """Real-data assertion: PV01.0104300 verified to have all 3 signals
    (export=1, consumed=1, own_bom=3, no imports). Pin observed_roles."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select observed_roles, is_multi_role, has_exports, "
            "is_consumed_in_bom, has_own_bom, has_imports "
            "from hub.v_material_roles "
            "where client_id='growatt-vn' and customs_code='PV01.0104300'",
        )
        row = cur.fetchone()
    if row is None:
        pytest.skip("Growatt PV01.0104300 not present in current DB; "
                    "smoke test skipped (run after wipe + ingest fresh)")
    roles, multi, exp, cons, own, imp = row
    assert sorted(roles) == ["btp_sx", "tp"]
    assert multi is True
    assert exp is True
    assert cons is True
    assert own is True
    assert imp is False
