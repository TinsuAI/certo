"""The matched import lot prices its own allocation line — a value carried back
from the previous calculation must never override it.

Live defect (johnson-vn, 2026-08-17): a material covered by two lots with
differing unit prices gets the DISPLAY marker "Nhiều đơn giá" as its
`unit_value` (allocation_unit_value_summary). The grid round-trips that field
(hidden input) into `sheet_edit_bom_rows`, which fed it back as a BOM row price;
`stock_allocation_line` ranked "bom" ABOVE "co_stock", and `first_decimal_source`
accepted any non-empty string while `decimal_value` swallowed the parse error and
returned 0. Result: every lot line persisted đơn giá 0 / trị giá 0 with
`valuation_status == "ready"`, the bảng kê exported 0, VNM was understated and
LVC overstated — on 34 rows across 11 prod cases, some already locked and filed.
Recalculating could not repair it: the 0 was carried back as a "BOM price".
"""
from __future__ import annotations

from decimal import Decimal


def test_first_decimal_source_skips_non_numeric_text():
    from app.web.co_case_context import first_decimal_source
    value, source = first_decimal_source(
        ("bom", "Nhiều đơn giá"),
        ("co_stock", "19007.89015"),
    )
    assert (value, source) == (Decimal("19007.89015"), "co_stock")


def test_first_decimal_source_keeps_real_zero():
    from app.web.co_case_context import first_decimal_source
    value, source = first_decimal_source(("co_stock", "0"), ("bom", "5"))
    assert (value, source) == (Decimal("0"), "co_stock")


def _lot(unit_value: str = "19007.89015") -> dict:
    return {
        "source_row": "import-row-1",
        "import_declaration_no": "107271797510",
        "line_no": "20",
        "customs_item_code": "1000495386",
        "allocation_code": "1000495386",
        "unit_value": unit_value,
        "value_currency": "VND",
        "exchange_rate_to_vnd": "1",
    }


def test_lot_price_beats_carried_marker():
    from app.web.co_case_context import stock_allocation_line
    line = stock_allocation_line(
        _lot(), Decimal("4"), Decimal("20"), {"unit_value": "Nhiều đơn giá"}, {},
    )
    assert line["unit_value"] == "19007.89015"
    assert line["material_value"] == "76031.56060"
    assert line["valuation_source"] == "co_stock"


def test_lot_price_beats_carried_zero():
    from app.web.co_case_context import stock_allocation_line
    line = stock_allocation_line(_lot(), Decimal("4"), Decimal("20"), {"unit_value": "0"}, {})
    assert line["unit_value"] == "19007.89015"
    assert line["valuation_source"] == "co_stock"


def test_lot_without_price_still_falls_back_to_bom_row():
    from app.web.co_case_context import stock_allocation_line
    line = stock_allocation_line(_lot(""), Decimal("2"), Decimal("5"), {"unit_value": "7"}, {})
    assert line["unit_value"] == "7"
    assert line["valuation_source"] == "bom"


def test_multi_lot_material_keeps_real_values_when_recalculated_from_marker():
    """End-to-end of the live defect: the second Tính lại must reprice from the
    lots, not from the "Nhiều đơn giá" text the first pass wrote."""
    from app.main import co_stock_allocation_pool, origin_material_from_bom_row

    def pool():
        return co_stock_allocation_pool([
            {
                "source_row": "LOT-001", "import_declaration_no": "NK-1", "line_no": "1",
                "material_code": "MAT-LOT", "allocation_code": "MAT-LOT",
                "customs_item_code": "MAT-LOT", "remaining_qty": "2", "unit_value": "10",
                "currency": "VND", "value_currency": "VND",
                "eligibility_status": "active", "allocation_code_status": "resolved",
            },
            {
                "source_row": "LOT-002", "import_declaration_no": "NK-2", "line_no": "2",
                "material_code": "MAT-LOT", "allocation_code": "MAT-LOT",
                "customs_item_code": "MAT-LOT", "remaining_qty": "4", "unit_value": "20",
                "currency": "VND", "value_currency": "VND",
                "eligibility_status": "active", "allocation_code_status": "resolved",
            },
        ])

    first = origin_material_from_bom_row(
        {"material_code": "MAT-LOT", "qty_per": "3", "uom": "PCS"},
        Decimal("2"), {"MAT-LOT": {"origin_default": "Không xuất xứ"}}, pool(),
    )
    assert first["unit_value"] == "Nhiều đơn giá"
    assert first["material_value"] == "100"

    # Second pass: the sheet row carries the marker back as the BOM row's price.
    second = origin_material_from_bom_row(
        {"material_code": "MAT-LOT", "qty_per": "3", "uom": "PCS", "unit_value": first["unit_value"]},
        Decimal("2"), {"MAT-LOT": {"origin_default": "Không xuất xứ"}}, pool(),
    )
    assert second["material_value"] == "100"
    assert second["non_origin_cif_value"] == "100"
    assert [line["unit_value"] for line in second["allocation_lines"]] == ["10", "20"]


def test_sheet_edit_bom_rows_does_not_carry_non_numeric_price():
    from app.routers.co_case import sheet_edit_bom_rows
    product = {
        "code": "P1",
        "materials": [
            {"material_code": "M1", "bom_qty_per": "1", "unit_value": "Nhiều đơn giá"},
            {"material_code": "M2", "bom_qty_per": "1", "unit_value": "12.5"},
        ],
    }
    rows = sheet_edit_bom_rows(product, {})
    assert rows[0].get("unit_value", "") == ""
    assert rows[1]["unit_value"] == "12.5"


# --- belt: a priced-0 row with matched lots must not be lockable ------------

def _zero_priced_product() -> dict:
    return {
        "code": "P", "fob": "100",
        "materials": [{
            "material_code": "M", "origin_status": "non_origin",
            "valuation_status": "ready", "unit_value": "0", "material_value": "0",
            "customs_relevance": "declarable",
            "allocation_lines": [{"source_row": "LOT-1", "allocated_qty": "4", "unit_value": "0"}],
        }],
    }


def test_enrich_flags_zero_lot_price():
    from app.web.co_case_context import enrich_origin_product
    assert enrich_origin_product(_zero_priced_product())["lvc_zero_lot_price"] is True


def test_enrich_no_zero_flag_when_lot_is_priced():
    from app.web.co_case_context import enrich_origin_product
    product = _zero_priced_product()
    product["materials"][0].update({"unit_value": "10", "material_value": "40"})
    product["materials"][0]["allocation_lines"][0]["unit_value"] = "10"
    assert enrich_origin_product(product)["lvc_zero_lot_price"] is False


def test_enrich_no_zero_flag_without_lots():
    """A no-lot row is a DOCUMENT problem (shortage / unmatched), not a price of 0."""
    from app.web.co_case_context import enrich_origin_product
    product = _zero_priced_product()
    product["materials"][0]["allocation_lines"] = []
    product["materials"][0]["material_value"] = ""
    assert enrich_origin_product(product)["lvc_zero_lot_price"] is False


def test_enrich_no_zero_flag_on_technical_noise():
    """A phi-vật-tư row is folded out of the bảng kê and adds 0 to VNM by design."""
    from app.web.co_case_context import enrich_origin_product
    product = _zero_priced_product()
    product["materials"][0]["customs_relevance"] = "excluded_non_material"
    assert enrich_origin_product(product)["lvc_zero_lot_price"] is False


def test_zero_lot_price_stays_bom_loaded():
    from app.routers.co_case import calculated_sheet_status
    assert calculated_sheet_status({"lvc_status": "pass", "lvc_zero_lot_price": True}) == "bom_loaded"
    assert calculated_sheet_status({"lvc_status": "pass", "lvc_zero_lot_price": False}) == "calculated"


def test_lock_gate_rechecks_zero_lot_price():
    from app.web.co_case_context import origin_sheet_action_error
    case = {
        "products": [{"code": "P1", "lvc_status": "pass", "lvc_zero_lot_price": True}],
        "origin_sheet_states": {"P1": {"status": "calculated"}},
    }
    error = origin_sheet_action_error(case, "P1", "lock")
    assert "đơn giá 0" in error


def test_export_blockers_include_zero_lot_price():
    from app.web.co_case_context import origin_sheet_export_blockers
    case = {
        "products": [
            {"code": "P1", "lvc_status": "pass", "lvc_zero_lot_price": True,
             "materials": [{"material_code": "M", "customs_relevance": "declarable"}]},
            {"code": "P2", "lvc_status": "pass",
             "materials": [{"material_code": "M", "customs_relevance": "declarable"}]},
        ],
        "origin_sheet_states": {"P1": {"status": "locked"}, "P2": {"status": "locked"}},
    }
    blockers = origin_sheet_export_blockers(case, {"id": "c"})
    assert "P1" in blockers
    assert "P2" not in blockers


def test_attention_chip_names_the_zero_price():
    from app.web.co_case_context import origin_sheet_attention
    chip = origin_sheet_attention({
        "origin_sheet_status": "bom_loaded", "lvc_zero_lot_price": True,
    })
    assert chip["reason"] == "zero_lot_price"
    assert "đơn giá 0" in chip["label"] or "đơn giá 0" in chip["detail"]
