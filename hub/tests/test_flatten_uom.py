"""UOM unit + conversion tests for the pure flatten layer.
Spec items: 3 (alias normalize), 4 (client-specific precedence),
5 (UOM with conversion produces flattened + evidence), 6 (UOM mismatch
without conversion → non_flattened uom_conversion_missing),
7 (ambiguous → uom_conversion_ambiguous), 21 (alias does not require
special confirmation).

These run against the pure module — no DB. The injected `lookup` fn
simulates the per-client UOM resolution stack.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.flatten import flatten
from app.flatten.types import (
    CatalogEntry, ConversionMatch, FlattenContext, ParsedBom,
)
from app.flatten.uom import normalize_uom_alias, convert_qty


# ── Pure UOM helpers ───────────────────────────────────────────────────

def test_normalize_alias_lower_and_strips():
    assert normalize_uom_alias(" KG ") == "kg"
    assert normalize_uom_alias("Mét") == "mét"
    assert normalize_uom_alias(None) == ""
    assert normalize_uom_alias("") == ""


def test_alias_equivalent_uom_returns_factor_one():
    """Item 21 — alias normalization is automatic, no special decision."""
    qty, match, err = convert_qty(
        Decimal("3.5"), "KG", "kg",
        material_code="X", lookup=lambda *a: None,  # never called
    )
    assert qty == Decimal("3.5")
    assert match is not None
    assert match.factor == Decimal(1)
    assert match.source == "alias"
    assert err is None


def test_lookup_returns_global_match():
    def lookup(mat, frm, to):
        if (frm, to) == ("g", "kg"):
            return ConversionMatch(
                factor=Decimal("0.001"), from_uom="g", to_uom="kg",
                source="global",
            )
        return None
    qty, match, err = convert_qty(
        Decimal("250"), "g", "kg",
        material_code="X", lookup=lookup,
    )
    assert qty == Decimal("0.250")
    assert match.source == "global"
    assert err is None


def test_lookup_missing_returns_uom_conversion_missing():
    """Item 6 — UOM mismatch without conversion → unresolved."""
    qty, match, err = convert_qty(
        Decimal("1"), "ml", "kg",
        material_code="X", lookup=lambda *a: None,
    )
    assert qty is None
    assert match is None
    assert err == "uom_conversion_missing"


def test_canonical_uom_missing_passes_qty_with_signal():
    """Catalog has no canonical UOM → propagate qty unmodified, signal err."""
    qty, match, err = convert_qty(
        Decimal("2"), "kg", None,
        material_code="X", lookup=lambda *a: None,
    )
    assert qty == Decimal("2")
    assert match is None
    assert err == "canonical_uom_missing"


# ── Flatten-engine integration: client_uom precedence + ambiguity ─────

def _ctx(*, uom_lookup, catalog=None, bcct=None, same=None, db=None,
         explicit=None) -> FlattenContext:
    return FlattenContext(
        client_id="c1",
        catalog=catalog or (lambda m: None),
        bcct_import=bcct or (lambda m: False),
        same_upload_btp=same or (lambda m, b, v: None),
        current_db_btp=db or (lambda m, b, v: None),
        uom=uom_lookup,
        explicit_context=explicit or (lambda r: r.get("explicit_context")),
    )


def test_client_specific_uom_overrides_global():
    """Item 4 — client-specific conversion wins over global.

    The lookup callable is responsible for precedence (it'll come from
    app/stores/uom.py in slice 3). Here we simulate: the lookup returns
    a 'client_specific' ConversionMatch when material+from+to match a
    per-material override; otherwise the global factor.
    """
    calls: list[tuple] = []

    def uom_lookup(mat, frm, to):
        calls.append((mat, frm, to))
        if mat == "X" and (frm, to) == ("box", "pcs"):
            return ConversionMatch(
                factor=Decimal(50), from_uom="box", to_uom="pcs",
                source="client_specific",
            )
        if (frm, to) == ("box", "pcs"):
            return ConversionMatch(
                factor=Decimal(12), from_uom="box", to_uom="pcs",
                source="global",
            )
        return None

    catalog = lambda m: CatalogEntry(material_code=m, category="nvl",
                                     status="active", uom="pcs") if m == "X" else None
    parsed: ParsedBom = {
        "TP-A": [{"material_code": "X", "qty_per_unit": 2, "uom": "box"}],
    }
    result = flatten(parsed, _ctx(uom_lookup=uom_lookup, catalog=catalog))
    # exactly one TP version, flattened, qty = 2 * 50 = 100 (client-specific wins)
    [version] = [v for v in result.versions if v.key.product_code == "TP-A"]
    assert version.flatten_status == "flattened"
    assert len(version.rows) == 1
    assert version.rows[0].qty == Decimal(100)
    assert version.rows[0].conversion_evidence["source"] == "client_specific"
    # Lookup was called with the material code first (precedence honored
    # by the lookup itself).
    assert calls[0] == ("X", "box", "pcs")


def test_global_uom_emits_decision_for_staff_confirm():
    """Item 20 — global conversion w/o client-specific → staff_confirm."""
    def uom_lookup(mat, frm, to):
        if (frm, to) == ("g", "kg"):
            return ConversionMatch(
                factor=Decimal("0.001"), from_uom="g", to_uom="kg",
                source="global",
            )
        return None
    catalog = lambda m: CatalogEntry(material_code=m, category="nvl",
                                     status="active", uom="kg") if m == "X" else None
    parsed: ParsedBom = {"TP-A": [{"material_code": "X", "qty_per_unit": 500, "uom": "g"}]}
    result = flatten(parsed, _ctx(uom_lookup=uom_lookup, catalog=catalog))
    types = {d.decision_type for d in result.decisions}
    assert "global_uom_conversion" in types
    [d] = [d for d in result.decisions if d.decision_type == "global_uom_conversion"]
    assert d.staff_confirmation_required is True
    assert d.status == "pending"


def test_alias_only_normalization_no_decision():
    """Item 21 — alias-equivalence path emits no special decision."""
    catalog = lambda m: CatalogEntry(material_code=m, category="nvl",
                                     status="active", uom="kg") if m == "X" else None
    parsed: ParsedBom = {"TP-A": [{"material_code": "X", "qty_per_unit": 1, "uom": "KG"}]}
    result = flatten(parsed, _ctx(uom_lookup=lambda *a: None, catalog=catalog))
    types = {d.decision_type for d in result.decisions}
    # Neither global_uom_conversion nor non_alias_uom_conversion fires for
    # alias-only equivalence.
    assert "global_uom_conversion" not in types
    assert "non_alias_uom_conversion" not in types
    [v] = result.versions
    assert v.rows[0].conversion_evidence["source"] == "alias"


def test_uom_missing_yields_non_flattened_with_reason():
    """Item 6 again, end-to-end: missing conversion → non_flattened
    version with one UnresolvedNode(reason='uom_conversion_missing')."""
    catalog = lambda m: CatalogEntry(material_code=m, category="nvl",
                                     status="active", uom="kg") if m == "X" else None
    parsed: ParsedBom = {"TP-A": [{"material_code": "X", "qty_per_unit": 1, "uom": "ml"}]}
    result = flatten(parsed, _ctx(uom_lookup=lambda *a: None, catalog=catalog))
    [v] = result.versions
    assert v.flatten_status == "non_flattened"
    assert any(u.reason == "uom_conversion_missing" for u in v.unresolved)


def test_non_flattened_emits_publish_decision():
    """Item 19 prerequisite — non_flattened versions emit a
    `non_flattened_publish` decision, default block_publish."""
    catalog = lambda m: CatalogEntry(material_code=m, category="nvl",
                                     status="active", uom="kg") if m == "X" else None
    parsed: ParsedBom = {"TP-A": [{"material_code": "X", "qty_per_unit": 1, "uom": "ml"}]}
    result = flatten(parsed, _ctx(uom_lookup=lambda *a: None, catalog=catalog))
    types = {d.decision_type for d in result.decisions}
    assert "non_flattened_publish" in types
    [d] = [d for d in result.decisions if d.decision_type == "non_flattened_publish"]
    assert d.staff_confirmation_required is True
    assert d.chosen_action == "block_publish"
