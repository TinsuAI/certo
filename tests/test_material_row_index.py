"""material_row_index — map a material code to its override row index (#13b).

Overrides are keyed by the position in product["materials"] (the same enumerate
index sheet_edit_bom_rows uses). Soft-deleted rows keep their slot but are
skipped when matching; the first ACTIVE match wins.
"""
from __future__ import annotations


def _p(*materials):
    return {"materials": list(materials)}


def test_finds_first_active_match():
    from app.main import material_row_index
    product = _p(
        {"material_code": "M1"},
        {"material_code": "M2", "deleted": True},
        {"material_code": "M2"},
        {"material_code": "M3"},
    )
    assert material_row_index(product, "M1") == 0
    assert material_row_index(product, "M2") == 2   # index 1 is soft-deleted → skipped
    assert material_row_index(product, "M3") == 3


def test_internal_code_fallback():
    from app.main import material_row_index
    product = _p({"internal_material_code": "INT-9"})
    assert material_row_index(product, "INT-9") == 0


def test_missing_returns_none():
    from app.main import material_row_index
    assert material_row_index(_p({"material_code": "M1"}), "NOPE") is None
    assert material_row_index({}, "M1") is None
