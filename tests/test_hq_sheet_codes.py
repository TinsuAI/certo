from app.workbook_io import hq_sheet_codes_for_product, write_hq_sheet_materials, _hq_layout_for


def _product(**fields):
    return fields


def test_hq_export_writes_customs_code_not_internal():
    """The HQ bảng kê must show the customs item code (mã HQ from the matched
    lot), not the internal allocation/BOM code (lookup-only). Growatt diverges:
    HQ 'DAYTINHIEU' vs internal '012.0002700'."""
    from openpyxl import Workbook
    mat = {
        "material_code": "012.0002700",           # internal — lookup only
        "customs_material_code": "DAYTINHIEU",     # mã HQ — matched lot's customs_item_code
        "internal_material_code": "012.0002700",
        "material_description": "Dây tín hiệu", "hs_code": "85339000", "uom": "ST",
        "bom_qty_per": "1", "consumed_qty": "368", "unit_value": "6708",
        "material_value": "2468835.82", "origin_status": "non_origin",
    }
    for sheet_code in ("LVC", "PL_VII"):
        col = _hq_layout_for(sheet_code)["cols"]["mat_code"]
        wb = Workbook(); ws = wb.active
        write_hq_sheet_materials(ws, {"materials": [mat]}, 5, sheet_code=sheet_code)
        assert ws.cell(row=5, column=col).value == "DAYTINHIEU", sheet_code


def test_hq_export_falls_back_to_material_code_when_no_customs_code():
    """Unmatched NVL has no matched-lot customs code → fall back to material_code."""
    from openpyxl import Workbook
    mat = {"material_code": "INT-1", "material_description": "x", "origin_status": "non_origin"}
    col = _hq_layout_for("LVC")["cols"]["mat_code"]
    wb = Workbook(); ws = wb.active
    write_hq_sheet_materials(ws, {"materials": [mat]}, 5, sheet_code="LVC")
    assert ws.cell(row=5, column=col).value == "INT-1"


def test_eur1_with_lvc_override_picks_lvc_sheet():
    product = _product(
        origin_sheet_effective_form_code="EUR.1",
        origin_sheet_criteria_override="LVC 30%",
        origin_sheet_effective_criteria_text="LVC 30%",
        documented_result="Cần đối chiếu mô tả hàng hóa trước khi áp dụng: ...",
    )
    assert hq_sheet_codes_for_product(product) == {"LVC"}


def test_eur1_with_cth_override_picks_cth_sheet():
    product = _product(
        origin_sheet_effective_form_code="EUR.1",
        origin_sheet_criteria_override="CTH",
        documented_result="Cần đối chiếu mô tả hàng hóa trước khi áp dụng: ...",
    )
    assert hq_sheet_codes_for_product(product) == {"CTH"}


def test_eur1_with_no_criterion_match_falls_back_to_eur1():
    product = _product(
        origin_sheet_effective_form_code="EUR.1",
        origin_sheet_criteria_override="",
        documented_result="Cần đối chiếu mô tả hàng hóa trước khi áp dụng: ...",
    )
    assert hq_sheet_codes_for_product(product) == {"EUR1"}


def test_eur1_with_psr_documented_result_picks_psr():
    product = _product(
        origin_sheet_effective_form_code="EUR.1",
        documented_result="Tra PSR Form EUR.1 theo Phụ lục",
    )
    assert hq_sheet_codes_for_product(product) == {"PSR"}


def test_non_eur1_with_lvc_override_picks_lvc():
    product = _product(
        origin_sheet_effective_form_code="B",
        origin_sheet_criteria_override="LVC 30%",
    )
    assert hq_sheet_codes_for_product(product) == {"LVC"}


def test_non_eur1_with_no_criterion_defaults_to_lvc():
    product = _product(origin_sheet_effective_form_code="B")
    assert hq_sheet_codes_for_product(product) == {"LVC"}


def test_override_wins_over_documented_result():
    product = _product(
        origin_sheet_effective_form_code="AI",
        origin_sheet_criteria_override="CTH",
        documented_result="LVC 30%",
    )
    assert hq_sheet_codes_for_product(product) == {"CTH"}
