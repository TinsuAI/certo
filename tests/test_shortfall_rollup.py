"""M3 — case_shortfall_rollup: pivot an allocated case (product-centric, one entry
per SP with its short materials) into a MATERIAL-centric view for the batch "sheet
tổng hợp": one row per NVL that is short SOMEWHERE, with total needed/available/short
units + the list of SP that use it (for "thay hết") and which are short (for "thay
phần thiếu"). Pure read; only materials short in ≥1 sheet appear.
"""
from __future__ import annotations

from decimal import Decimal


def test_rollup_aggregates_short_material_across_sheets():
    from app.web.co_case_context import case_shortfall_rollup, decimal_value
    case = {"products": [
        {"code": "P1", "origin_sheet_status": "calculated", "lvc_percentage": "41.2",
         "materials": [{"material_code": "A", "material_description": "Nhôm", "uom": "kg",
                        "consumed_qty": "1000", "allocation_status": "covered", "allocation_shortage_qty": ""}]},
        {"code": "P2", "origin_sheet_status": "calculated", "lvc_percentage": "40.0",
         "materials": [{"material_code": "A", "consumed_qty": "1000", "allocation_status": "shortage",
                        "allocation_shortage_qty": "300"}]},
        {"code": "P3", "origin_sheet_status": "calculated",
         "materials": [{"material_code": "B", "consumed_qty": "50", "allocation_status": "covered"}]},
    ]}
    r = case_shortfall_rollup(case)
    assert r["material_count"] == 1  # only A is short somewhere; B fully covered → excluded
    a = r["materials"][0]
    assert a["material_code"] == "A"
    assert a["name"] == "Nhôm" and a["uom"] == "kg"
    assert decimal_value(a["needed"]) == Decimal("2000")
    assert decimal_value(a["short_qty"]) == Decimal("300")
    assert decimal_value(a["available"]) == Decimal("1700")
    assert a["using_count"] == 2          # both P1 and P2 use A
    assert a["short_count"] == 1
    assert a["short_products"] == ["P2"]
    # per-SP detail: covered P1 carries no short_qty, short P2 carries its shortfall
    by_sp = {u["product_code"]: u for u in a["using"]}
    assert by_sp["P1"]["is_short"] is False and by_sp["P1"]["short_qty"] == ""
    assert by_sp["P2"]["is_short"] is True and decimal_value(by_sp["P2"]["short_qty"]) == Decimal("300")
    assert by_sp["P1"]["lvc_percentage"] == "41.2"  # per-SP LVC carried for the drill-down


def test_rollup_material_short_in_multiple_sheets_sums_units():
    from app.web.co_case_context import case_shortfall_rollup, decimal_value
    case = {"products": [
        {"code": "P1", "materials": [{"material_code": "A", "consumed_qty": "500",
                                      "allocation_status": "shortage", "allocation_shortage_qty": "200"}]},
        {"code": "P2", "materials": [{"material_code": "A", "consumed_qty": "500",
                                      "allocation_status": "shortage", "allocation_shortage_qty": "500"}]},
    ]}
    a = case_shortfall_rollup(case)["materials"][0]
    assert decimal_value(a["short_qty"]) == Decimal("700")
    assert a["short_count"] == 2 and a["short_products"] == ["P1", "P2"]


def test_rollup_flags_no_bom_products_not_as_covered():
    # A sheet with no active NVL (no BOM loaded) must be reported as no_bom, NOT
    # silently treated as "đủ tồn" (the batch panel warns instead of "✓ Đủ tồn").
    from app.web.co_case_context import case_shortfall_rollup
    case = {"products": [
        {"code": "INV-5000", "materials": [{"material_code": "A", "consumed_qty": "100",
                                            "allocation_status": "shortage", "allocation_shortage_qty": "40"}]},
        {"code": "INV-NOBOM", "materials": []},                       # no BOM
        {"code": "INV-DEL", "materials": [{"material_code": "B", "deleted": True}]},  # only deleted → no BOM
    ]}
    r = case_shortfall_rollup(case)
    assert r["no_bom_count"] == 2
    assert set(r["no_bom_products"]) == {"INV-NOBOM", "INV-DEL"}
    assert r["material_count"] == 1  # only the real shortage still surfaces


def test_rollup_skips_deleted_and_uses_internal_code_fallback():
    from app.web.co_case_context import case_shortfall_rollup, decimal_value
    case = {"products": [
        {"code": "P1", "materials": [
            {"material_code": "A", "consumed_qty": "100", "allocation_status": "shortage",
             "allocation_shortage_qty": "40", "deleted": True},   # soft-deleted → ignored
            {"internal_material_code": "B", "consumed_qty": "80", "allocation_status": "shortage",
             "allocation_shortage_qty": "30"},                    # matched via internal code
        ]},
    ]}
    r = case_shortfall_rollup(case)
    assert [m["material_code"] for m in r["materials"]] == ["B"]
    assert decimal_value(r["materials"][0]["short_qty"]) == Decimal("30")
