"""BCCT material_identity surfaces observed_roles + atomic signals + conflict.

Brief: .ai/features/2026-05-07-catalog-roles-refactor/brief.md (rev 5)

Tests the integration: ResolverContext loads from v_material_roles,
resolver response carries new fields top-level + per-candidate per D6.
"""
from __future__ import annotations

import secrets

import pytest

from app.database import connect
from app.resolvers.bcct_material_identity import (
    ResolverContext, resolve_material_identity,
)


@pytest.fixture
def cid():
    client_id = "pidroles-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, code_resolution_mode) "
            "values (%s, %s, 'identity')",
            (client_id, "pid roles test"),
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


def _seed_rework_tp(cur, *, client_id, code="REWORK_TP"):
    """Seed a rework code: declared btp_sx + own BOM + consumed in another BOM + exported.
    Result: observed_roles=['tp','btp_sx'], multi_role=true."""
    cur.execute(
        "insert into hub.materials (client_id, customs_code, internal_code, "
        "name, category, btp_sourcing) values (%s, %s, %s, %s, 'btp_sx', 'self_produced_only')",
        (client_id, code, code, code),
    )
    cur.execute(
        "insert into hub.materials (client_id, customs_code, internal_code, "
        "name, category) values (%s, 'PARENT', 'PARENT', 'PARENT', 'tp')",
        (client_id,),
    )
    # Own BOM artifact for the rework code.
    own_id = f"ba_{client_id}_own"
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, product_code, "
        "artifact_no, actor, intent, normalized_hash, source_bom_kind, "
        "flatten_status, flatten_strategy, source_channel, flatten_method, "
        "flatten_method_version, status, published_at) "
        "values (%s, %s, %s, 1, 'agency_staff', 'asserted_technical', "
        "'h_own', 'technical_flattened', 'flattened', 'technical_exploded', "
        "'agency_upload', 'manual', '0.1', 'published', now())",
        (own_id, client_id, code),
    )
    # Parent BOM that consumes the rework code.
    par_id = f"ba_{client_id}_par"
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, product_code, "
        "artifact_no, actor, intent, normalized_hash, source_bom_kind, "
        "flatten_status, flatten_strategy, source_channel, flatten_method, "
        "flatten_method_version, status, published_at) "
        "values (%s, %s, 'PARENT', 1, 'agency_staff', 'asserted_technical', "
        "'h_par', 'technical_flattened', 'flattened', 'technical_exploded', "
        "'agency_upload', 'manual', '0.1', 'published', now())",
        (par_id, client_id),
    )
    cur.execute(
        "insert into hub.bom_edges (artifact_id, row_index, root_code, "
        "parent_code, child_code, qty_per_parent, uom, level) "
        "values (%s, 1, 'PARENT', 'PARENT', %s, 1.0, 'PCS', 1)",
        (par_id, code),
    )
    # Export of the rework code.
    cur.execute(
        "insert into hub.bcct_rows (client_id, transaction_key, line_no, "
        "declaration_no, declaration_type, direction, registration_date, "
        "customs_code, goods_name, payload) "
        "values (%s, 'TX-rework', '1', 'DECL.RW', 'E42', 'export', '2026-01-15', "
        "%s, %s, '{}'::jsonb)",
        (client_id, code, f"{code} test"),
    )


def _seed_pure_nvl(cur, *, client_id, code="NVL_PE"):
    """Seed pure NVL: imported, consumed in BOM, no own BOM."""
    cur.execute(
        "insert into hub.materials (client_id, customs_code, internal_code, "
        "name, category) values (%s, %s, %s, %s, 'nvl')",
        (client_id, code, code, code),
    )
    cur.execute(
        "insert into hub.materials (client_id, customs_code, internal_code, "
        "name, category) values (%s, 'PRODUCT', 'PRODUCT', 'PRODUCT', 'tp')",
        (client_id,),
    )
    par_id = f"ba_{client_id}_prod"
    cur.execute(
        "insert into hub.bom_artifacts (artifact_id, client_id, product_code, "
        "artifact_no, actor, intent, normalized_hash, source_bom_kind, "
        "flatten_status, flatten_strategy, source_channel, flatten_method, "
        "flatten_method_version, status, published_at) "
        "values (%s, %s, 'PRODUCT', 1, 'agency_staff', 'asserted_technical', "
        "'h_prd', 'technical_flattened', 'flattened', 'technical_exploded', "
        "'agency_upload', 'manual', '0.1', 'published', now())",
        (par_id, client_id),
    )
    cur.execute(
        "insert into hub.bom_edges (artifact_id, row_index, root_code, "
        "parent_code, child_code, qty_per_parent, uom, level) "
        "values (%s, 1, 'PRODUCT', 'PRODUCT', %s, 1.0, 'KG', 1)",
        (par_id, code),
    )
    cur.execute(
        "insert into hub.bcct_rows (client_id, transaction_key, line_no, "
        "declaration_no, declaration_type, direction, registration_date, "
        "customs_code, goods_name, payload) "
        "values (%s, 'TX-nvl-imp', '1', 'DECL.IMP', 'E11', 'import', '2026-01-10', "
        "%s, %s, '{}'::jsonb)",
        (client_id, code, f"{code} import"),
    )


# ─── Top-level fields on resolved row ───────────────────────────────


def test_resolved_rework_carries_observed_roles_and_multi_role(cid):
    """A rework code in catalog → material_identity top-level has observed_roles=['tp','btp_sx'],
    is_multi_role=true, and atomic signals all true except imports."""
    with connect() as conn, conn.cursor() as cur:
        _seed_rework_tp(cur, client_id=cid)
    row = {
        "transaction_key": "TX-rework",
        "declaration_no": "DECL.RW",
        "line_no": "1",
        "customs_code": "REWORK_TP",
        "internal_code": "REWORK_TP",
        "goods_name": "REWORK_TP test",
    }
    with connect() as conn, conn.cursor() as cur:
        ctx = ResolverContext.from_db(cid, cur)
    pid = resolve_material_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "resolved"
    assert pid["resolved_code"] == "REWORK_TP"
    assert pid["product_kind"] == "btp_sx"  # declared
    # New top-level fields per D6.
    assert sorted(pid["observed_roles"]) == ["btp_sx", "tp"]
    assert pid["is_multi_role"] is True
    assert pid["has_imports"] is False
    assert pid["has_exports"] is True
    assert pid["is_consumed_in_bom"] is True
    assert pid["has_own_bom"] is True
    assert pid["btp_sourcing"] == "self_produced_only"
    # declared 'btp_sx' is in observed → no conflict.
    assert pid["declared_observed_conflict"] is False


def test_resolved_pure_nvl_top_level_fields(cid):
    """Pure NVL via Stage 1 → product_kind='nvl', observed_roles=['nvl'], not multi-role."""
    with connect() as conn, conn.cursor() as cur:
        _seed_pure_nvl(cur, client_id=cid)
    row = {
        "transaction_key": "TX-nvl-imp",
        "declaration_no": "DECL.IMP",
        "line_no": "1",
        "customs_code": "NVL_PE",
        "internal_code": "NVL_PE",
        "goods_name": "NVL_PE import",
    }
    with connect() as conn, conn.cursor() as cur:
        ctx = ResolverContext.from_db(cid, cur)
    pid = resolve_material_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "resolved"
    assert pid["resolved_code"] == "NVL_PE"
    assert pid["product_kind"] == "nvl"
    assert pid["observed_roles"] == ["nvl"]
    assert pid["is_multi_role"] is False
    assert pid["has_imports"] is True
    assert pid["has_exports"] is False
    assert pid["is_consumed_in_bom"] is True
    assert pid["has_own_bom"] is False
    assert pid["bom_product_code"] is None  # NVL has no BOM, alias gated
    assert pid["declared_observed_conflict"] is False


def test_unresolved_missing_has_no_signals(cid):
    """Unresolved row → no atomic signals, observed_roles=[]."""
    with connect() as conn, conn.cursor() as cur:
        ctx = ResolverContext.from_db(cid, cur)
    row = {
        "transaction_key": "TX-x",
        "declaration_no": "DECL.X",
        "line_no": "1",
        "customs_code": "NOT_IN_CATALOG",
        "internal_code": "NOT_IN_CATALOG",
        "goods_name": "stuff",
    }
    pid = resolve_material_identity(row, ctx=ctx)

    assert pid["resolution_status"] == "missing"
    assert pid["resolved_code"] is None
    # New fields present but null/empty even when missing.
    assert pid["observed_roles"] == []
    assert pid["is_multi_role"] is False
    assert pid["has_imports"] is False
    assert pid["has_exports"] is False
    assert pid["is_consumed_in_bom"] is False
    assert pid["has_own_bom"] is False
    assert pid["btp_sourcing"] is None
    assert pid["declared_observed_conflict"] is False


# ─── Per-candidate scoping per D6 ───────────────────────────────────


def test_per_candidate_carries_observed_roles_minimal_set(cid):
    """Per D6: candidates get product_kind + observed_roles[] + bom_artifact_count
    + latest_flatten_status. Atomic signals NOT propagated to candidates."""
    with connect() as conn, conn.cursor() as cur:
        _seed_rework_tp(cur, client_id=cid)
    row = {
        "transaction_key": "TX-rework",
        "declaration_no": "DECL.RW",
        "line_no": "1",
        "customs_code": "REWORK_TP",
        "internal_code": "REWORK_TP",
        "goods_name": "REWORK_TP test",
    }
    with connect() as conn, conn.cursor() as cur:
        ctx = ResolverContext.from_db(cid, cur)
    pid = resolve_material_identity(row, ctx=ctx)

    assert pid["candidates"], "expected at least one candidate"
    cand = pid["candidates"][0]
    # Minimal set per D6.
    assert "product_kind" in cand
    assert "observed_roles" in cand
    assert sorted(cand["observed_roles"]) == ["btp_sx", "tp"]
    assert "bom_artifact_count" in cand
    assert cand["bom_artifact_count"] >= 1
    # Atomic signals must NOT appear on candidates (wire-format constraint).
    assert "has_imports" not in cand
    assert "has_exports" not in cand
    assert "is_consumed_in_bom" not in cand
    assert "has_own_bom" not in cand


# ─── D8 conflict detection ──────────────────────────────────────────


def test_conflict_surfaces_in_resolver(cid):
    """Mis-declared code (declared='tp' but only consumed) → declared_observed_conflict=true."""
    code = "MISDECL"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, customs_code, internal_code, "
            "name, category) values (%s, %s, %s, %s, 'tp')",
            (cid, code, code, code),
        )
        cur.execute(
            "insert into hub.materials (client_id, customs_code, internal_code, "
            "name, category) values (%s, 'PARENT', 'PARENT', 'PARENT', 'tp')",
            (cid,),
        )
        own_id = f"ba_{cid}_md"
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, product_code, "
            "artifact_no, actor, intent, normalized_hash, source_bom_kind, "
            "flatten_status, flatten_strategy, source_channel, flatten_method, "
            "flatten_method_version, status, published_at) "
            "values (%s, %s, %s, 1, 'agency_staff', 'asserted_technical', "
            "'h_md', 'technical_flattened', 'flattened', 'technical_exploded', "
            "'agency_upload', 'manual', '0.1', 'published', now())",
            (own_id, cid, code),
        )
        par_id = f"ba_{cid}_md_par"
        cur.execute(
            "insert into hub.bom_artifacts (artifact_id, client_id, product_code, "
            "artifact_no, actor, intent, normalized_hash, source_bom_kind, "
            "flatten_status, flatten_strategy, source_channel, flatten_method, "
            "flatten_method_version, status, published_at) "
            "values (%s, %s, 'PARENT', 1, 'agency_staff', 'asserted_technical', "
            "'h_par2', 'technical_flattened', 'flattened', 'technical_exploded', "
            "'agency_upload', 'manual', '0.1', 'published', now())",
            (par_id, cid),
        )
        cur.execute(
            "insert into hub.bom_edges (artifact_id, row_index, root_code, "
            "parent_code, child_code, qty_per_parent, uom, level) "
            "values (%s, 1, 'PARENT', 'PARENT', %s, 1.0, 'PCS', 1)",
            (par_id, code),
        )
    row = {
        "transaction_key": "TX-md",
        "declaration_no": "DECL.MD",
        "line_no": "1",
        "customs_code": code,
        "internal_code": code,
        "goods_name": f"{code} test",
    }
    with connect() as conn, conn.cursor() as cur:
        ctx = ResolverContext.from_db(cid, cur)
    pid = resolve_material_identity(row, ctx=ctx)
    # observed=['btp_sx'] but declared='tp' → conflict.
    assert pid["observed_roles"] == ["btp_sx"]
    assert pid["product_kind"] == "tp"
    assert pid["declared_observed_conflict"] is True


# ─── BOM resolver Phase 3 regression (R5) ──────────────────────────
#
# Full coverage of Phase 3 stop-set behavior lives in tests/test_bom_resolver.py
# (~27 tests). This refactor must not change that suite — verified by running
# the global pytest suite. No synthetic in-file smoke needed.
