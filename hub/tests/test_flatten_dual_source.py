"""Dual-source flatten tests. Spec items: 14 (TP A using dual-source BTP B
yields TWO valid flattened variants), 18 (dual-source cannot be
materialized without explicit confirmation — covered at the Decision
level here; store-side enforcement lives in slice 4 confirm route).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from hub.app.flatten import flatten
from hub.app.flatten.types import (
    CatalogEntry, FlattenContext, ParsedBom,
)


def _ctx(*, catalog=None, bcct=None, same=None, db=None, uom=None,
         explicit=None) -> FlattenContext:
    return FlattenContext(
        client_id="c1",
        catalog=catalog or (lambda m: None),
        bcct_import=bcct or (lambda m: False),
        same_upload_btp=same or (lambda m, b, v: None),
        current_db_btp=db or (lambda m, b, v: None),
        uom=uom or (lambda m, f, t: None),
        explicit_context=explicit or (lambda r: r.get("explicit_context")),
    )


def test_dual_source_emits_two_variants():
    """Item 14 — TP-A uses BTP-B, where BTP-B has BOTH BCCT-import evidence
    AND a child BOM. Engine must emit two parent versions for TP-A:
    purchased_btp_as_leaf and self_produced_btp_exploded."""
    parsed: ParsedBom = {
        "TP-A":  [{"material_code": "BTP-B", "qty_per_unit": 1, "uom": "kg"}],
        "BTP-B": [{"material_code": "NVL-1", "qty_per_unit": 0.5, "uom": "kg"}],
    }
    cat = lambda m: CatalogEntry(
        material_code=m, category="nvl", status="active", uom="kg",
    ) if m in {"NVL-1", "BTP-B"} else None
    bcct = lambda m: m == "BTP-B"

    result = flatten(parsed, _ctx(catalog=cat, bcct=bcct))
    tp_versions = [v for v in result.versions if v.key.product_code == "TP-A"]
    strategies = sorted(v.flatten_strategy for v in tp_versions)
    assert strategies == ["purchased_btp_as_leaf", "self_produced_btp_exploded"]
    # Both must be flattened — neither has unresolved nodes.
    assert all(v.flatten_status == "flattened" for v in tp_versions)

    # purchased variant has BTP-B as leaf with qty=1
    purchased = next(v for v in tp_versions
                     if v.flatten_strategy == "purchased_btp_as_leaf")
    assert [r.material_code for r in purchased.rows] == ["BTP-B"]
    assert purchased.rows[0].qty == Decimal(1)

    # exploded variant has NVL-1 as leaf with qty=0.5
    exploded = next(v for v in tp_versions
                    if v.flatten_strategy == "self_produced_btp_exploded")
    assert [r.material_code for r in exploded.rows] == ["NVL-1"]
    assert exploded.rows[0].qty == Decimal("0.5")


def test_dual_source_emits_required_decisions():
    """Item 18 — at Decision-level, dual-source must surface a
    `dual_source_variant` decision with staff_confirmation_required=True
    and pending status. Materialization of the dual variants without
    confirmation is enforced at the store/route layer (slice 4)."""
    parsed: ParsedBom = {
        "TP-A":  [{"material_code": "BTP-B", "qty_per_unit": 1, "uom": "kg"}],
        "BTP-B": [{"material_code": "NVL-1", "qty_per_unit": 1, "uom": "kg"}],
    }
    cat = lambda m: CatalogEntry(
        material_code=m, category="nvl", status="active", uom="kg",
    ) if m in {"NVL-1", "BTP-B"} else None
    bcct = lambda m: m == "BTP-B"
    result = flatten(parsed, _ctx(catalog=cat, bcct=bcct))
    types = {d.decision_type for d in result.decisions}
    assert "dual_source_variant" in types
    assert "bcct_import_vs_child_bom" in types
    for d in result.decisions:
        if d.decision_type in ("dual_source_variant", "bcct_import_vs_child_bom"):
            assert d.staff_confirmation_required is True
            assert d.status == "pending"


def test_dual_source_btp_version_still_emitted():
    """The BTP-B BOM itself must still land as a first-class BTP version,
    independent of the TP-A dual-source resolution."""
    parsed: ParsedBom = {
        "TP-A":  [{"material_code": "BTP-B", "qty_per_unit": 1, "uom": "kg"}],
        "BTP-B": [{"material_code": "NVL-1", "qty_per_unit": 1, "uom": "kg"}],
    }
    cat = lambda m: CatalogEntry(
        material_code=m, category="nvl", status="active", uom="kg",
    ) if m in {"NVL-1", "BTP-B"} else None
    bcct = lambda m: m == "BTP-B"
    result = flatten(parsed, _ctx(catalog=cat, bcct=bcct))
    btps = [v for v in result.versions if v.key.product_code == "BTP-B"]
    assert len(btps) >= 1
