"""Export ⇄ web parity: the exported bảng kê must contain EXACTLY the rows the
web grid shows — the export adds no business logic of its own (classification is
decided at "Tính bảng kê"). The bảng kê export POST rebuilds the case from the
form, so customs_relevance must round-trip through the form or the export would
keep rác/declarable_unmatched the web grid folds → web ≠ export (dangerous).
"""
from __future__ import annotations

from app.demo_data import update_products_from_form
from app.origin_material_filters import is_bom_technical_noise


def _form(customs_relevance: str) -> dict:
    return {
        "product_count": "1",
        "product_0_code": "TP1",
        "product_0_material_count": "1",
        "product_0_material_0_material_code": "X1",
        "product_0_material_0_material_description": "Thép tấm",
        "product_0_material_0_customs_relevance": customs_relevance,
    }


def test_form_roundtrips_customs_relevance():
    for rel in ("declarable", "excluded_non_material", "declarable_unmatched", ""):
        case = update_products_from_form(_form(rel))
        material = case["products"][0]["materials"][0]
        assert material["customs_relevance"] == rel, rel


def test_export_strip_set_equals_web_fold_set():
    # Web folds: deleted OR material.bom_technical_noise (field == is_bom_technical_noise).
    # Export strips: deleted OR is_bom_technical_noise(material). Same predicate ⇒ same set.
    materials = [
        {"material_code": "A", "customs_relevance": "declarable", "deleted": False},
        {"material_code": "B", "customs_relevance": "excluded_non_material", "deleted": False},
        {"material_code": "C", "customs_relevance": "declarable_unmatched", "deleted": False},
        {"material_code": "D", "customs_relevance": "declarable", "deleted": True},
        {"material_code": "E", "customs_relevance": "", "deleted": False},
    ]
    web_folded = {m["material_code"] for m in materials if m["deleted"] or is_bom_technical_noise(m)}
    export_stripped = {m["material_code"] for m in materials if m["deleted"] or is_bom_technical_noise(m)}
    assert web_folded == export_stripped
    # concrete expectation: rác (B) + unmatched (C) + deleted (D) hidden; declarable (A) + unclassified (E) kept
    assert web_folded == {"B", "C", "D"}


def test_roundtripped_relevance_strips_at_export():
    case = update_products_from_form(_form("excluded_non_material"))
    assert is_bom_technical_noise(case["products"][0]["materials"][0]) is True
    case = update_products_from_form(_form("declarable"))
    assert is_bom_technical_noise(case["products"][0]["materials"][0]) is False
