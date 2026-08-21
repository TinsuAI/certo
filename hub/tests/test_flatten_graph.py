"""Graph + flatten tests. Spec items: 1 (2-level flatten), 2 (multi-level
quantity multiplication), 8 (BTP stored as own version), 9 (TP→BTP→NVL
when child BTP BOM exists), 10 (TP non_flattened when missing child),
15 (code as TP-and-input doesn't break identity), 16 (cycle detection),
17 (same-upload BTP precedence over older DB BTP).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.flatten import flatten
from app.flatten.types import (
    CatalogEntry, ConversionMatch, FlattenContext, ParsedBom,
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


def _kg_catalog(mats: set[str]):
    return lambda m: CatalogEntry(
        material_code=m, category="nvl", status="active", uom="kg"
    ) if m in mats else None


# ── Item 1: simple 2-level flatten ─────────────────────────────────────

def test_simple_2_level_flatten():
    """TP-A uses BTP-B (1 unit) → BTP-B BOM has X (2 kg). Flat = X 2 kg."""
    parsed: ParsedBom = {
        "TP-A":  [{"material_code": "BTP-B", "qty_per_unit": 1, "uom": "kg"}],
        "BTP-B": [{"material_code": "X",     "qty_per_unit": 2, "uom": "kg"}],
    }
    cat = _kg_catalog({"X"})
    result = flatten(parsed, _ctx(catalog=cat))
    tp = next(v for v in result.versions if v.key.product_code == "TP-A")
    assert tp.flatten_status == "flattened"
    assert tp.source_bom_kind == "technical_flattened"
    assert tp.flatten_strategy == "technical_exploded"
    assert len(tp.rows) == 1
    assert tp.rows[0].material_code == "X"
    assert tp.rows[0].qty == Decimal(2)


# ── Item 2: multi-level quantity multiplication ────────────────────────

def test_multi_level_qty_multiplication():
    """TP-A uses 3 BTP-B; BTP-B uses 2 X. Flattened TP-A = 6 X."""
    parsed: ParsedBom = {
        "TP-A":  [{"material_code": "BTP-B", "qty_per_unit": 3, "uom": "kg"}],
        "BTP-B": [{"material_code": "X",     "qty_per_unit": 2, "uom": "kg"}],
    }
    cat = _kg_catalog({"X"})
    result = flatten(parsed, _ctx(catalog=cat))
    tp = next(v for v in result.versions if v.key.product_code == "TP-A")
    assert tp.rows[0].qty == Decimal(6)


# ── Item 8: BTP BOM stored as own version ─────────────────────────────

def test_btp_bom_stored_as_own_version():
    parsed: ParsedBom = {
        "TP-A":  [{"material_code": "BTP-B", "qty_per_unit": 1, "uom": "kg"}],
        "BTP-B": [{"material_code": "X",     "qty_per_unit": 2, "uom": "kg"}],
    }
    result = flatten(parsed, _ctx(catalog=_kg_catalog({"X"})))
    keys = {v.key.product_code for v in result.versions}
    assert "TP-A" in keys
    assert "BTP-B" in keys


# ── Item 9: TP→BTP→NVL resolves when child BTP BOM exists ─────────────

def test_tp_resolves_via_child_btp_to_nvl():
    parsed: ParsedBom = {
        "TP-A":  [{"material_code": "BTP-B", "qty_per_unit": 1, "uom": "kg"}],
        "BTP-B": [
            {"material_code": "NVL-1", "qty_per_unit": 0.5, "uom": "kg"},
            {"material_code": "NVL-2", "qty_per_unit": 0.7, "uom": "kg"},
        ],
    }
    cat = _kg_catalog({"NVL-1", "NVL-2"})
    result = flatten(parsed, _ctx(catalog=cat))
    tp = next(v for v in result.versions if v.key.product_code == "TP-A")
    assert tp.flatten_status == "flattened"
    mats = sorted(r.material_code for r in tp.rows)
    assert mats == ["NVL-1", "NVL-2"]
    assert all(r.classification_evidence == "catalog_imported_nvl" for r in tp.rows)


# ── Item 10: missing child + no leaf evidence → non_flattened ─────────

def test_missing_child_btp_yields_non_flattened():
    """TP-A uses BTP-B (no child BOM, no BCCT, no catalog NVL) → unresolved."""
    parsed: ParsedBom = {
        "TP-A": [{"material_code": "BTP-B", "qty_per_unit": 1, "uom": "kg"}],
    }
    result = flatten(parsed, _ctx())
    tp = next(v for v in result.versions if v.key.product_code == "TP-A")
    assert tp.flatten_status == "non_flattened"
    assert tp.flatten_strategy == "no_strategy"
    assert any(u.reason == "missing_child_bom" for u in tp.unresolved)


# ── Item 15: code as TP and as input doesn't break graph identity ─────

def test_same_code_as_tp_and_input_keeps_distinct_versions():
    """X is both a finished product (TP-X with its own BOM) AND used as a
    leaf inside TP-A. Both should land — TP-A gets X as leaf via catalog
    or BCCT, TP-X is its own BOM version."""
    parsed: ParsedBom = {
        "TP-X":  [{"material_code": "NVL-1", "qty_per_unit": 1, "uom": "kg"}],
        "TP-A":  [{"material_code": "X", "qty_per_unit": 2, "uom": "kg"}],
    }
    cat_lookup = lambda m: CatalogEntry(
        material_code=m, category="nvl", status="active", uom="kg"
    ) if m in {"X", "NVL-1"} else None
    result = flatten(parsed, _ctx(catalog=cat_lookup))
    keys = {v.key.product_code for v in result.versions}
    assert "TP-X" in keys
    assert "TP-A" in keys
    tp_a = next(v for v in result.versions if v.key.product_code == "TP-A")
    # X is a catalog NVL so TP-A treats it as leaf — does NOT explode TP-X
    # implicitly. Only same-upload-or-DB-btp explodes.
    assert tp_a.rows[0].material_code == "X"
    assert tp_a.rows[0].classification_evidence == "catalog_imported_nvl"


# ── Item 16: cycle detection ──────────────────────────────────────────

def test_cycle_detected_yields_unresolved_not_infinite_loop():
    """A→B and B→A. No leaves. Engine must not loop; cycle surfaces as
    UnresolvedNode(reason='cycle_detected'); version is non_flattened."""
    parsed: ParsedBom = {
        "A": [{"material_code": "B", "qty_per_unit": 1, "uom": "kg"}],
        "B": [{"material_code": "A", "qty_per_unit": 1, "uom": "kg"}],
    }
    result = flatten(parsed, _ctx())
    a = next(v for v in result.versions if v.key.product_code == "A")
    b = next(v for v in result.versions if v.key.product_code == "B")
    assert a.flatten_status == "non_flattened"
    assert b.flatten_status == "non_flattened"
    assert any(u.reason == "cycle_detected" for u in a.unresolved + b.unresolved)


# ── Item 17: same-upload BTP precedence over older DB BTP ─────────────

def test_same_upload_btp_beats_db_btp():
    """TP uses BTP. BTP exists both in same upload (NVL-FRESH) AND in DB
    (NVL-OLD). Flattened TP must reflect NVL-FRESH only."""
    parsed: ParsedBom = {
        "TP-A":  [{"material_code": "BTP-B", "qty_per_unit": 1, "uom": "kg"}],
        "BTP-B": [{"material_code": "NVL-FRESH", "qty_per_unit": 1, "uom": "kg"}],
    }
    db_btps = {
        ("BTP-B", "", "default"): [{"material_code": "NVL-OLD", "qty_per_unit": 1, "uom": "kg"}],
    }

    def db_lookup(m, b, v):
        return db_btps.get((m, b, v))

    cat = _kg_catalog({"NVL-FRESH", "NVL-OLD"})
    result = flatten(parsed, _ctx(catalog=cat, db=db_lookup))
    tp = next(v for v in result.versions if v.key.product_code == "TP-A")
    mats = [r.material_code for r in tp.rows]
    assert mats == ["NVL-FRESH"]   # not NVL-OLD


# ── Bonus: explicit_purchased context wins even with child BOM present ─

def test_explicit_purchased_with_child_does_not_explode():
    parsed: ParsedBom = {
        "TP-A":  [{"material_code": "BTP-B", "qty_per_unit": 1, "uom": "kg",
                   "explicit_context": "purchased"}],
        "BTP-B": [{"material_code": "NVL-1", "qty_per_unit": 1, "uom": "kg"}],
    }
    cat = _kg_catalog({"BTP-B", "NVL-1"})
    result = flatten(parsed, _ctx(catalog=cat))
    tp = next(v for v in result.versions if v.key.product_code == "TP-A")
    assert tp.rows[0].material_code == "BTP-B"
    assert tp.rows[0].classification_evidence == "explicit_purchased"


# ── Item 25: existing manual_flat backward-compat is in test_parsers.py
#    (already green) — no engine work needed for that path.
