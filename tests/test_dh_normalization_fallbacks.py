"""DH->CO normalization fallback contract (#22 / 2026-07-16 code-vocabulary audit).

The normalize_* adapters fill code fields from fallback chains. Verified against
the live DH data (johnson-vn 13,131 materials / 60,173 stock rows; growatt-vn 457
/ 38,287) that none erases a real distinction: the row shapes that would (a material
with only customs_code; a bcct row carrying internal_code) are absent from the DH
schema. These tests pin that contract per layer:

  - growatt-vn (declared != internal): the adapter keeps the DECLARED code as the lot
    identity and never substitutes the internal code.
  - johnson-vn (declared == internal): every fallback collapses to one string (no-op).
  - contract invariant: the removed links (bcct internal_code; material customs_code)
    stay removed — if a future DH contract reintroduces them, a test here goes red.
"""
from __future__ import annotations

from app.data_hub_client import (
    material_identity_display_code,
    normalize_bcct_row,
    normalize_material_row,
    normalize_product_row,
)


# --- normalize_material_row: material_code is the only identity source ---

def test_material_row_aliases_all_code_fields_to_material_code():
    # growatt shape: catalog keyed by the dotted internal code, no customs/internal cols.
    row = {"material_code": "005.0001300", "name": "Tụ điện", "category": "nvl"}
    out = normalize_material_row(row)
    assert out["material_code"] == "005.0001300"
    assert out["customs_code"] == "005.0001300"
    assert out["internal_code"] == "005.0001300"


def test_material_row_never_lets_customs_code_shadow_material_code():
    # Contract (#22): even if a stray customs_code appears, material_code wins — the
    # declared code can NOT become the catalog identity.
    row = {"material_code": "005.0001300", "customs_code": "TUDIEN", "category": "nvl"}
    out = normalize_material_row(row)
    assert out["material_code"] == "005.0001300"


def test_material_row_johnson_collapse_is_a_noop():
    # johnson: declared == internal, so the one string fills every field.
    out = normalize_material_row({"material_code": "NPL-001", "category": "nvl"})
    assert out["material_code"] == out["customs_code"] == out["internal_code"] == "NPL-001"


# --- normalize_product_row: a tp material's code IS its identity ---

def test_product_row_falls_back_to_material_code_when_no_product_code():
    # products drawn from category=='tp' materials carry material_code, not product_code.
    out = normalize_product_row({"material_code": "PV00.0048500", "category": "tp", "name": "Tấm pin"})
    assert out["product_code"] == "PV00.0048500"


def test_product_row_keeps_explicit_product_code():
    # list_products path: an explicit product_code is not overridden by the fallback.
    out = normalize_product_row({"product_code": "SP-1", "material_code": "M-1", "category": "tp"})
    assert out["product_code"] == "SP-1"


# --- normalize_bcct_row: item_code is the DECLARED lot identity ---

def test_bcct_item_code_is_declared_code_for_growatt_shape():
    # growatt: material_identity resolves to the declared code; allocation_code (the
    # internal dotted code) is derived LATER, not here. item_code stays declared.
    row = {
        "material_identity": {"resolved_code": "TUDIEN", "internal_code": "", "customs_code": "TUDIEN"},
        "customs_code": "TUDIEN",
        "declaration_no": "NK-1",
        "line_no": "1",
        "direction": "import",
    }
    out = normalize_bcct_row(row)
    assert out["item_code"] == "TUDIEN"


def test_bcct_item_code_never_prefers_internal_code_over_declared():
    # Core tighten (#22): with no material_identity and no item_code, a row carrying
    # BOTH internal_code and customs_code must resolve to the DECLARED customs_code —
    # internal_code is no longer a link in the chain, so it can't mis-key the lot.
    row = {"internal_code": "008.0006100", "customs_code": "DIOT", "direction": "import"}
    out = normalize_bcct_row(row)
    assert out["item_code"] == "DIOT"


def test_bcct_item_code_falls_through_to_declared_customs_code():
    # No identity, no item_code — the declared customs_code is the last resort and the
    # correct lot identity.
    out = normalize_bcct_row({"customs_code": "MOSFET", "direction": "import"})
    assert out["item_code"] == "MOSFET"


def test_bcct_johnson_collapse_is_a_noop():
    row = {"material_identity": {"resolved_code": "NPL-9"}, "customs_code": "NPL-9", "direction": "import"}
    assert normalize_bcct_row(row)["item_code"] == "NPL-9"


# --- material_identity_display_code: primary preference (schema does NOT guarantee it) ---

def test_display_code_prefers_resolved_then_internal_then_customs():
    assert material_identity_display_code({"material_identity": {"resolved_code": "R", "internal_code": "I", "customs_code": "C"}}) == "R"
    assert material_identity_display_code({"material_identity": {"internal_code": "I", "customs_code": "C"}}) == "I"
    assert material_identity_display_code({"material_identity": {"customs_code": "C"}}) == "C"
    assert material_identity_display_code({}) == ""
