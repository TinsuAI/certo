"""Idempotency / canonicalization tests for BOM normalized_hash."""
from hub.app.stores.bom import normalized_hash


def test_hash_is_deterministic():
    rows = [{"material_code": "A", "qty_per_unit": 1.0, "uom": "kg"}]
    assert normalized_hash(rows) == normalized_hash(rows)


def test_hash_is_invariant_under_row_order():
    rows1 = [
        {"material_code": "A", "qty_per_unit": 1.0, "uom": "kg"},
        {"material_code": "B", "qty_per_unit": 2.0, "uom": "kg"},
    ]
    rows2 = list(reversed(rows1))
    assert normalized_hash(rows1) == normalized_hash(rows2)


def test_hash_changes_on_qty_change():
    rows1 = [{"material_code": "A", "qty_per_unit": 1.0, "uom": "kg"}]
    rows2 = [{"material_code": "A", "qty_per_unit": 1.5, "uom": "kg"}]
    assert normalized_hash(rows1) != normalized_hash(rows2)


def test_hash_invariant_under_qty_precision_within_9_decimals():
    rows1 = [{"material_code": "A", "qty_per_unit": 1.000000001, "uom": "kg"}]
    rows2 = [{"material_code": "A", "qty_per_unit": 1.0000000014, "uom": "kg"}]
    # Both round to 1.000000001 at 9-decimal scale.
    assert normalized_hash(rows1) == normalized_hash(rows2)


def test_hash_distinguishes_materials():
    rows1 = [{"material_code": "A", "qty_per_unit": 1.0, "uom": "kg"}]
    rows2 = [{"material_code": "B", "qty_per_unit": 1.0, "uom": "kg"}]
    assert normalized_hash(rows1) != normalized_hash(rows2)
