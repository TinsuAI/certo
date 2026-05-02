"""Component classification tests. Spec items: 11 (BCCT-import → leaf),
12 (dual_source surfaced), 13 (explicit self-produced forces explode).
"""
from __future__ import annotations

import pytest

from app.flatten.classify import classify_component
from app.flatten.types import (
    BomKey, CatalogEntry, FlattenContext, ParsedRow,
)


def _ctx(*, catalog=None, bcct=None, same=None, db=None, explicit=None):
    return FlattenContext(
        client_id="c1",
        catalog=catalog or (lambda m: None),
        bcct_import=bcct or (lambda m: False),
        same_upload_btp=same or (lambda m, b, v: None),
        current_db_btp=db or (lambda m, b, v: None),
        uom=lambda m, f, t: None,
        explicit_context=explicit or (lambda r: r.get("explicit_context")),
    )


def test_explicit_purchased_overrides_everything():
    row = {"material_code": "X", "qty_per_unit": 1, "uom": "kg",
           "explicit_context": "purchased"}
    ctx = _ctx(
        bcct=lambda m: True,                   # bcct evidence present
        same=lambda m, b, v: [{"material_code": "Y"}],  # child bom present
    )
    cls = classify_component(row, parent_key=BomKey("TP-A"),
                             ctx=ctx, same_upload_keys=set())
    assert cls.action == "leaf"
    assert cls.evidence == "explicit_purchased"
    assert cls.explicit is True


def test_explicit_self_produced_forces_explode():
    """Item 13."""
    row = {"material_code": "BTP-B", "qty_per_unit": 1, "uom": "kg",
           "explicit_context": "self_produced"}
    ctx = _ctx(
        bcct=lambda m: True,                   # bcct evidence present (would normally win)
        same=lambda m, b, v: [{"material_code": "Y"}],
    )
    cls = classify_component(row, parent_key=BomKey("TP-A"),
                             ctx=ctx, same_upload_keys=set())
    assert cls.action == "explode"
    assert cls.evidence == "explicit_self_produced"
    assert cls.explicit is True


def test_bcct_import_no_child_bom_is_leaf():
    """Item 11 — BCCT-import evidence with no self-produced context → leaf."""
    row = {"material_code": "X", "qty_per_unit": 1, "uom": "kg"}
    ctx = _ctx(bcct=lambda m: m == "X")
    cls = classify_component(row, parent_key=BomKey("TP-A"),
                             ctx=ctx, same_upload_keys=set())
    assert cls.action == "leaf"
    assert cls.evidence == "bcct_import"
    assert cls.dual_source is False


def test_bcct_import_with_child_bom_marks_dual_source():
    """Item 12 — dual-source surfaced when BOTH BCCT-import AND child-BOM exist."""
    row = {"material_code": "BTP-B", "qty_per_unit": 1, "uom": "kg"}
    ctx = _ctx(
        bcct=lambda m: m == "BTP-B",
        same=lambda m, b, v: [{"material_code": "Y"}] if m == "BTP-B" else None,
    )
    cls = classify_component(row, parent_key=BomKey("TP-A"),
                             ctx=ctx, same_upload_keys=set())
    assert cls.dual_source is True
    assert cls.evidence == "bcct_import"   # default action when dual=True is leaf


def test_decision_order_same_upload_beats_db_btp():
    row = {"material_code": "BTP-B", "qty_per_unit": 1, "uom": "kg"}
    ctx = _ctx(
        same=lambda m, b, v: [{"material_code": "Y"}] if m == "BTP-B" else None,
        db=lambda m, b, v: [{"material_code": "Z"}] if m == "BTP-B" else None,
    )
    cls = classify_component(row, parent_key=BomKey("TP-A"),
                             ctx=ctx, same_upload_keys={("BTP-B", "", "default")})
    # Per spec §6 step 5: same upload wins.
    assert cls.evidence == "child_bom_same_upload"


def test_db_btp_when_no_same_upload():
    row = {"material_code": "BTP-B", "qty_per_unit": 1, "uom": "kg"}
    ctx = _ctx(
        db=lambda m, b, v: [{"material_code": "Z"}] if m == "BTP-B" else None,
    )
    cls = classify_component(row, parent_key=BomKey("TP-A"),
                             ctx=ctx, same_upload_keys=set())
    assert cls.evidence == "child_bom_current_db"
    assert cls.action == "explode"


def test_catalog_active_imported_nvl_leaf():
    row = {"material_code": "M", "qty_per_unit": 1, "uom": "kg"}
    ctx = _ctx(
        catalog=lambda m: CatalogEntry(
            material_code=m, category="nvl", status="active", unit="kg"
        ),
    )
    cls = classify_component(row, parent_key=BomKey("TP-A"),
                             ctx=ctx, same_upload_keys=set())
    assert cls.evidence == "catalog_imported_nvl"
    assert cls.action == "leaf"


def test_unresolved_when_no_evidence():
    row = {"material_code": "Q", "qty_per_unit": 1, "uom": "kg"}
    ctx = _ctx()
    cls = classify_component(row, parent_key=BomKey("TP-A"),
                             ctx=ctx, same_upload_keys=set())
    assert cls.action == "unresolved"
    assert cls.evidence == "unresolved_missing_child_bom"


def test_classification_evidence_uses_english_machine_codes():
    """Item 24 — evidence values come from the fixed English code set."""
    valid = {
        "bcct_import", "child_bom_same_upload", "child_bom_current_db",
        "catalog_imported_nvl", "explicit_self_produced", "explicit_purchased",
        "unresolved_missing_child_bom", "ambiguous_dual_source",
    }
    rows_and_ctxs = [
        ({"material_code": "X", "explicit_context": "purchased"}, _ctx()),
        ({"material_code": "X", "explicit_context": "self_produced"}, _ctx()),
        ({"material_code": "X"}, _ctx(bcct=lambda m: True)),
        ({"material_code": "X"},
         _ctx(catalog=lambda m: CatalogEntry(m, "nvl", "active", "kg"))),
        ({"material_code": "X"}, _ctx()),
    ]
    for row, ctx in rows_and_ctxs:
        cls = classify_component(row, parent_key=BomKey("TP-A"),
                                 ctx=ctx, same_upload_keys=set())
        assert cls.evidence in valid
