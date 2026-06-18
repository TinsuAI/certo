"""case_missing_stock_summary — aggregate 'mã thiếu tồn' across products (#13a).

A short material = allocation_status == "shortage" after running stock.
Soft-deleted rows are ignored; grouped by product; distinct short codes
are surfaced for batch substitution (Slice C).
"""
from __future__ import annotations


def _mat(code, status, *, qty="", uom="kg", name="", deleted=False, norm="1", needed="", avail=""):
    return {
        "material_code": code,
        "material_description": name or f"NVL {code}",
        "uom": uom,
        "allocation_status": status,
        "allocation_shortage_qty": qty,
        "bom_qty_per": norm,
        "consumed_qty": needed,
        "available_qty": avail,
        "deleted": deleted,
    }


def test_empty_case():
    from app.main import case_missing_stock_summary
    out = case_missing_stock_summary({})
    assert out == {"products": [], "missing_codes": [], "missing_code_count": 0, "product_count": 0}


def test_covered_only_product_not_listed():
    from app.main import case_missing_stock_summary
    case = {"products": [{"code": "P1", "name": "Sản phẩm 1", "materials": [_mat("M1", "covered")]}]}
    out = case_missing_stock_summary(case)
    assert out["products"] == []
    assert out["missing_code_count"] == 0


def test_groups_shortages_by_product_and_dedups_codes():
    from app.main import case_missing_stock_summary
    case = {
        "products": [
            {"code": "P1", "name": "SP1", "materials": [
                _mat("M1", "covered"),
                _mat("M2", "shortage", qty="5", uom="kg"),
            ]},
            {"code": "P2", "name": "SP2", "materials": [
                _mat("M3", "shortage", qty="2", uom="pcs"),
                _mat("M4", "covered"),
                _mat("M2", "shortage", qty="1", uom="kg"),
            ]},
        ]
    }
    out = case_missing_stock_summary(case)
    assert [p["product_code"] for p in out["products"]] == ["P1", "P2"]
    assert out["products"][0]["materials"] == [
        {"material_code": "M2", "name": "NVL M2", "uom": "kg", "shortage_qty": "5",
         "norm": "1", "needed_qty": "", "available_qty": ""}
    ]
    assert [m["material_code"] for m in out["products"][1]["materials"]] == ["M3", "M2"]
    # distinct short codes across the whole case, sorted
    assert out["missing_codes"] == ["M2", "M3"]
    assert out["missing_code_count"] == 2
    assert out["product_count"] == 2


def test_soft_deleted_shortage_ignored():
    from app.main import case_missing_stock_summary
    case = {"products": [{"code": "P1", "name": "SP1", "materials": [
        _mat("M1", "shortage", qty="3", deleted=True),
        _mat("M2", "shortage", qty="4"),
    ]}]}
    out = case_missing_stock_summary(case)
    assert out["missing_codes"] == ["M2"]
    assert out["products"][0]["materials"][0]["material_code"] == "M2"
