"""Regression tests for the /rev critic findings on the BOM flatten feature.

Each test pins down the specific bug the critic flagged and would have
fired before the fix. Keeping them in their own file makes it cheap to
re-grep against future regressions.
"""
from __future__ import annotations

import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from hub.app.database import connect
from hub.app.flatten import flatten as flatten_engine
from hub.app.flatten.types import (
    CatalogEntry, FlattenContext, ParsedBom,
)
from hub.app.main import app
from hub.app.parsers import bom_adapters
from hub.app.stores import bom as bom_store
from hub.app.stores import flatten_decisions as decisions_store


CLIENT = "rev_findings_client"


@pytest.fixture(autouse=True)
def setup_client():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.clients (client_id, name) values (%s, %s)
            on conflict (client_id) do nothing
            """,
            (CLIENT, "rev findings"),
        )
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id = %s", (CLIENT,))


def _ctx(*, catalog=None, bcct=None, same=None, db=None) -> FlattenContext:
    return FlattenContext(
        client_id=CLIENT,
        catalog=catalog or (lambda m: None),
        bcct_import=bcct or (lambda m: False),
        same_upload_btp=same or (lambda m, b, v: None),
        current_db_btp=db or (lambda m, b, v: None),
        uom=lambda m, f, t: None,
        explicit_context=lambda r: r.get("explicit_context"),
    )


# ─────────────────────────────────────────────────────────────────────
# C3 — strict variant matching (settlement-correctness bug)
# ─────────────────────────────────────────────────────────────────────

def test_C3_engine_same_upload_does_not_treat_default_as_wildcard():
    """If a parent asks for bom_variant_id='default' and the parsed BTP
    is variant 'V_RoHS', the wrapper must NOT return the V_RoHS rows."""
    parsed: ParsedBom = {
        "TP-A": [{"material_code": "BTP-X", "qty_per_unit": 1, "uom": "kg",
                  "bom_variant_id": "default"}],
        "BTP-X": [{"material_code": "NVL-RoHS", "qty_per_unit": 1, "uom": "kg",
                   "bom_variant_id": "V_RoHS"}],
    }
    cat = lambda m: CatalogEntry(m, "nvl", "active", "kg") if m == "NVL-RoHS" else None
    result = flatten_engine(parsed, _ctx(catalog=cat))
    tp = next(v for v in result.versions if v.key.product_code == "TP-A")
    # The TP should NOT explode into BTP-X (variant mismatch). It should
    # treat BTP-X as unresolved (no child BOM, no catalog, no BCCT).
    assert tp.flatten_status == "non_flattened"
    assert any(u.material_code == "BTP-X" and u.reason == "missing_child_bom"
               for u in tp.unresolved)


def test_C3_db_btp_lookup_does_not_fall_back_when_variant_specified():
    """make_current_db_btp_lookup must return None when caller passes a
    specific variant that doesn't exist for the code."""
    bom_store.create_artifact(
        client_id=CLIENT, product_code="C3_BTP",
        rows=[{"material_code": "C3_NVL", "qty_per_unit": 1, "uom": "kg"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None,
        source_bom_kind="manual_flat",
        flatten_status="not_applicable",
        flatten_strategy="manual_flat_as_provided",
        bom_variant_id="V_existing",
    )
    lookup = bom_store.make_current_db_btp_lookup(CLIENT)
    # Asking for variant that doesn't exist: must return None.
    assert lookup("C3_BTP", "", "V_does_not_exist") is None
    # Asking for the existing variant: hit.
    rows = lookup("C3_BTP", "", "V_existing")
    assert rows is not None and rows[0]["material_code"] == "C3_NVL"
    # Asking with empty variant (no constraint): hit (any variant OK).
    rows = lookup("C3_BTP", "", "")
    assert rows is not None


# ─────────────────────────────────────────────────────────────────────
# C2 — dual-source variants must require staff confirm even when
#       also non_flattened (engine + publish_filter)
# ─────────────────────────────────────────────────────────────────────

def test_C2_dual_source_strategy_preserved_when_unresolved():
    """When dual-source TP also has unresolved nodes (e.g. one of the
    non-dual children is missing), the engine must KEEP the variant's
    dual strategy (purchased_btp_as_leaf / self_produced_btp_exploded),
    not collapse to no_strategy. The publish_filter relies on the
    strategy column to recognise dual variants."""
    parsed: ParsedBom = {
        "TP-A": [
            {"material_code": "BTP-DUAL", "qty_per_unit": 1, "uom": "kg"},
            {"material_code": "GHOST-NVL", "qty_per_unit": 1, "uom": "kg"},   # unresolved
        ],
        "BTP-DUAL": [{"material_code": "REAL-NVL", "qty_per_unit": 0.5, "uom": "kg"}],
    }
    cat = lambda m: CatalogEntry(m, "nvl", "active", "kg") if m in {"REAL-NVL", "BTP-DUAL"} else None
    bcct = lambda m: m == "BTP-DUAL"
    result = flatten_engine(parsed, _ctx(catalog=cat, bcct=bcct))
    tps = [v for v in result.versions if v.key.product_code == "TP-A"]
    strategies = sorted(v.flatten_strategy for v in tps)
    assert strategies == ["purchased_btp_as_leaf", "self_produced_btp_exploded"]
    # Both should be non_flattened (because GHOST-NVL is unresolved).
    assert all(v.flatten_status == "non_flattened" for v in tps)


# ─────────────────────────────────────────────────────────────────────
# I1 — multi_sheet_per_root must reject single-root flat files (no
#       intermediate parents) so manual_flat handles them
# ─────────────────────────────────────────────────────────────────────

def test_I1_multi_sheet_per_root_rejects_flat_single_root():
    """A simple manual_flat file with 1 TP + 3 NVLs must NOT be claimed
    by multi_sheet_per_root (which would mark every row as do_not_explode
    and bypass catalog/BCCT classification)."""
    from hub.app.parsers.bom_adapters.multi_sheet_per_root import MultiSheetPerRootAdapter
    from hub.app.parsers.bom_adapters import BomParseError
    adapter = MultiSheetPerRootAdapter()
    # 1 TP, 3 leaf rows, no intermediate parents.
    blob = _xlsx([
        ("Mã SP", "Mã NVL",  "Định mức", "ĐVT"),
        ("FLAT_TP", "FLAT_NVL_1", 1.0, "kg"),
        ("FLAT_TP", "FLAT_NVL_2", 2.0, "kg"),
        ("FLAT_TP", "FLAT_NVL_3", 0.5, "kg"),
    ])
    with pytest.raises(BomParseError, match="defer to manual_flat"):
        adapter.parse(blob)


def test_I1_multi_sheet_per_root_accepts_genuine_multi_sheet_tree():
    """A workbook with a TP + intermediate BTP (BTP appears as both
    parent AND child) should be accepted."""
    from hub.app.parsers.bom_adapters.multi_sheet_per_root import MultiSheetPerRootAdapter
    adapter = MultiSheetPerRootAdapter()
    blob = _xlsx([
        ("Mã SP", "Mã NVL", "Định mức", "ĐVT"),
        ("MS_TP", "MS_BTP", 2.0, "kg"),     # TP → BTP
        ("MS_BTP", "MS_NVL", 0.5, "kg"),    # BTP → NVL  (BTP is intermediate)
    ])
    parsed = adapter.parse(blob)
    assert "MS_TP" in parsed
    leaf = parsed["MS_TP"][0]
    # Pre-multiplied: 2.0 * 0.5 = 1.0
    assert leaf["material_code"] == "MS_NVL"
    assert leaf["qty_per_unit"] == 1.0
    assert leaf["explicit_context"] == "do_not_explode"


# ─────────────────────────────────────────────────────────────────────
# I3 — dual-source decisions must propagate through _explode (not just
#      at the TP level)
# ─────────────────────────────────────────────────────────────────────

def test_I3_nested_dual_source_emits_decision():
    """A TP whose direct child is plain-explode but whose grandchild has
    BCCT-import + child-BOM (dual-source) — engine must emit a
    dual_source_variant decision for the grandchild even though the
    fan-out happens at the TP level only."""
    parsed: ParsedBom = {
        "TP-OUTER": [{"material_code": "BTP-MID", "qty_per_unit": 1, "uom": "kg"}],
        "BTP-MID":  [{"material_code": "BTP-INNER", "qty_per_unit": 1, "uom": "kg"}],
        "BTP-INNER": [{"material_code": "NVL-LEAF", "qty_per_unit": 1, "uom": "kg"}],
    }
    cat = lambda m: CatalogEntry(m, "nvl", "active", "kg") if m == "NVL-LEAF" else None
    bcct = lambda m: m == "BTP-INNER"   # nested dual-source signal
    result = flatten_engine(parsed, _ctx(catalog=cat, bcct=bcct))
    types = {d.decision_type for d in result.decisions}
    assert "dual_source_variant" in types, \
        "nested dual-source must surface a decision (spec §7+§11)"
    # It should also surface bcct_import_vs_child_bom.
    assert "bcct_import_vs_child_bom" in types


# ─────────────────────────────────────────────────────────────────────
# C1 — single-transaction materialize: failure mid-loop must roll back
# ─────────────────────────────────────────────────────────────────────

def test_C1_materialize_rolls_back_on_failure():
    """If the materialization raises mid-way, NO versions or unresolved
    nodes for this run should be persisted. Verifies the single-tx
    refactor: previously each create_artifact had its own connection +
    commit, leaving partial state."""
    from hub.app.flatten.types import (
        BomKey, FlattenedRow, FlattenedVersion, FlattenResult,
    )
    from decimal import Decimal as Dec
    # Build a synthetic FlattenResult with TWO versions where the
    # SECOND has an invalid flatten_status (CHECK constraint violation).
    v1 = FlattenedVersion(
        key=BomKey(product_code="C1_OK"),
        source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy="technical_exploded",
        rows=[FlattenedRow(material_code="C1_NVL", qty=Dec(1), uom="kg",
                           node_path="C1_OK>C1_NVL",
                           classification_evidence="catalog_imported_nvl")],
    )
    v2_bad = FlattenedVersion(
        key=BomKey(product_code="C1_BAD"),
        source_bom_kind="technical_flattened",
        flatten_status="not_a_real_status",   # violates chk_flatten_status
        flatten_strategy="technical_exploded",
        rows=[FlattenedRow(material_code="C1_NVL2", qty=Dec(1), uom="kg",
                           node_path="C1_BAD>C1_NVL2",
                           classification_evidence="catalog_imported_nvl")],
    )
    fr = FlattenResult(versions=[v1, v2_bad], decisions=[])

    with pytest.raises(Exception):
        bom_store.create_flattened_artifact_set(
            client_id=CLIENT, source_upload_id=None, result=fr,
        )

    # v1 must NOT have been committed (rollback).
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.bom_artifacts "
            "where client_id = %s and product_code in ('C1_OK','C1_BAD')",
            (CLIENT,),
        )
        (n,) = cur.fetchone()
    assert n == 0, "partial commit detected — single-tx refactor failed"


def _xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
