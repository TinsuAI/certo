"""Parser tests for Materials, Code Mappings, BCCT, BOM."""
import io

import pytest
from openpyxl import Workbook

from app.parsers.bcct import parse_bcct_workbook, BcctParseError
from app.parsers.bom import parse_bom_workbook, BomParseError
from app.parsers.code_mappings import parse_code_mappings_workbook, CodeMappingsParseError
from app.parsers.materials import parse_materials_workbook, MaterialsParseError, normalize_category


def _xlsx(rows: list[tuple], sheet_title: str = "Sheet1", *,
          extra_sheets: list[tuple[str, list[tuple]]] | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
    for r in rows:
        ws.append(r)
    for title, srows in (extra_sheets or []):
        s = wb.create_sheet(title)
        for r in srows:
            s.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---- Materials ----

def test_materials_parses_basic_sheet():
    blob = _xlsx([
        ("Mã HQ", "Mã NB", "Tên", "Loại", "ĐVT", "HS"),
        ("PE-001", "PE-001", "Polyethylene", "nvl", "kg", "39011010"),
        ("INV-3000", "INV-3000", "Solar inverter", "tp", "pcs", "85044090"),
    ])
    rows = parse_materials_workbook(blob)
    assert len(rows) == 2
    assert rows[0]["customs_code"] == "PE-001"
    assert rows[0]["category"] == "nvl"
    assert rows[1]["category"] == "tp"


def test_materials_uses_sheet_default_when_category_missing():
    blob = _xlsx(
        [
            ("Mã HQ", "Tên", "ĐVT"),
            ("AL-100", "Aluminum", "kg"),
        ],
        sheet_title="DM NVL",
    )
    rows = parse_materials_workbook(blob)
    assert rows[0]["category"] == "nvl"


def test_materials_skips_blank_customs_code():
    blob = _xlsx([
        ("Mã HQ", "Tên", "Loại"),
        ("", "Empty row", "nvl"),
        ("OK-1", "Real row", "nvl"),
    ])
    rows = parse_materials_workbook(blob)
    assert len(rows) == 1
    assert rows[0]["customs_code"] == "OK-1"


def test_materials_raises_when_no_recognizable_headers():
    blob = _xlsx([("Random", "Junk", "Headers"), ("a", "b", "c")])
    with pytest.raises(MaterialsParseError):
        parse_materials_workbook(blob)


def test_normalize_category_handles_aliases():
    assert normalize_category("Nguyên Vật Liệu") == "nvl"
    assert normalize_category("Thành phẩm") == "tp"
    assert normalize_category("BTP_SX") == "btp_sx"
    assert normalize_category("Tool") == "ccdc"
    assert normalize_category(None) is None


# ---- Code mappings ----

def test_code_mappings_n_n_via_repeated_rows():
    blob = _xlsx([
        ("Mã nội bộ", "Mã hải quan"),
        ("PE-001", "PE-001"),
        ("PE-001", "PE-ALT"),  # 1:n
        ("PE-002", "PE-002"),
    ])
    rows = parse_code_mappings_workbook(blob)
    assert len(rows) == 3
    pairs = {(r["internal_code"], r["customs_code"]) for r in rows}
    assert ("PE-001", "PE-001") in pairs
    assert ("PE-001", "PE-ALT") in pairs


def test_code_mappings_two_columns_minimum_works():
    """BQD often has only 2 columns; parser must not require 3+ headers."""
    blob = _xlsx([
        ("Mã nội bộ", "Mã hải quan"),
        ("X", "Y"),
    ])
    rows = parse_code_mappings_workbook(blob)
    assert rows == [{
        "internal_code": "X", "customs_code": "Y", "category": None, "notes": None,
    }]


def test_code_mappings_raises_when_columns_missing():
    blob = _xlsx([("Random", "Headers"), ("x", "y")])
    with pytest.raises(CodeMappingsParseError):
        parse_code_mappings_workbook(blob)


# ---- BCCT ----

def test_bcct_extracts_typed_columns_and_direction():
    blob = _xlsx([
        ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký", "Mã NPL/SP",
         "Tên hàng", "Tổng số lượng", "ĐVT", "Trị giá", "Nguyên tệ"),
        ("104111", 1, "E11", "2025-03-15", "PE-001",
         "PE-001#&Polyethylene", 100.0, "kg", 250.0, "USD"),
        ("104112", 1, "E42", "2025-09-01", "INV-3000",
         "INV-3000#&Solar inverter", 50.0, "pcs", 12500.0, "USD"),
    ])
    rows = parse_bcct_workbook(blob)
    assert len(rows) == 2
    assert rows[0]["customs_code"] == "PE-001"
    assert rows[0]["direction"] == "import"
    assert rows[1]["direction"] == "export"
    assert rows[0]["quantity"] == 100.0
    assert rows[0]["currency"] == "USD"


def test_bcct_raises_on_unknown_format():
    blob = _xlsx([("Some", "Random"), ("a", "b")])
    with pytest.raises(BcctParseError):
        parse_bcct_workbook(blob)


def test_bcct_strips_trailing_zero_from_numeric_cells():
    """Excel stores numeric cells as float. The parser must coerce
    integer-valued floats back to int before stringifying so
    declaration_no '308449399330.0' does not leak into the DB.

    Regression for /v1/hub/bcct/invoice-matches contract — CO consumes
    declaration_no / line_no / transaction_key as opaque strings and
    rejects values that do not match the customs system's printed form.
    """
    blob = _xlsx([
        ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký", "Mã NPL/SP",
         "Tên hàng", "Tổng số lượng", "ĐVT", "Trị giá", "Nguyên tệ"),
        # Numeric values written as int — openpyxl returns them as float.
        (308449399330, 133, "E42", "2026-04-18", "SD00.0010600",
         "SD00.0010600#&pin", 368.0, "CT", 12000.0, "USD"),
    ])
    rows = parse_bcct_workbook(blob)
    assert len(rows) == 1
    assert rows[0]["declaration_no"] == "308449399330"
    assert rows[0]["line_no"] == "133"
    assert rows[0]["transaction_key"] == "308449399330-133"


def test_bcct_preserves_real_decimal_when_present():
    """Decimal values like 1.5 must survive — only integer-valued floats
    get coerced back to int in the parser."""
    from app.parsers.bcct import _cell_str
    assert _cell_str([1.5], 0) == "1.5"
    assert _cell_str([1.0], 0) == "1"
    assert _cell_str([308449399330.0], 0) == "308449399330"
    assert _cell_str(["133"], 0) == "133"
    assert _cell_str([None], 0) is None
    assert _cell_str([""], 0) is None


def test_shared_cell_str_used_everywhere():
    """All four parser modules share the same cell_str helper from
    `app/parsers/_excel.py`, so the .0 fix can't drift out of sync.

    Regression for the 4-copy duplication that allowed the bug to
    persist in materials.py / code_mappings.py / bom_adapters/_common.py
    even after bcct.py was patched."""
    from app.parsers._excel import cell_str as shared
    from app.parsers.bcct import _cell_str as bcct_cs
    from app.parsers.materials import _cell_str as materials_cs
    from app.parsers.code_mappings import _cell_str as code_mappings_cs
    from app.parsers.bom_adapters._common import cell_str as bom_cs
    # All four should be the SAME function object.
    assert bcct_cs is shared
    assert materials_cs is shared
    assert code_mappings_cs is shared
    assert bom_cs is shared


# ---- BOM ----

def test_bom_manual_flat_groups_by_product():
    blob = _xlsx([
        ("Mã SP", "Mã NVL", "Định mức", "ĐVT"),
        ("INV-3000", "PE-001", 0.45, "kg"),
        ("INV-3000", "AL-100", 0.30, "kg"),
        ("INV-5000", "PE-001", 0.60, "kg"),
    ])
    products = parse_bom_workbook(blob, profile="manual_flat")
    assert set(products.keys()) == {"INV-3000", "INV-5000"}
    assert len(products["INV-3000"]) == 2
    assert len(products["INV-5000"]) == 1


def test_bom_growatt_multi_workbook_sheet_per_product():
    blob = _xlsx(
        rows=[("Mã NVL", "Định mức", "ĐVT")],  # placeholder for default sheet
        extra_sheets=[
            ("INV-3000", [
                ("Mã NVL", "Định mức", "ĐVT"),
                ("PE-001", 0.45, "kg"),
                ("AL-100", 0.30, "kg"),
            ]),
            ("INV-5000", [
                ("Mã NVL", "Định mức", "ĐVT"),
                ("CU-WIRE", 1.20, "m"),
            ]),
        ],
    )
    products = parse_bom_workbook(blob, profile="growatt_multi_workbook")
    assert "INV-3000" in products
    assert "INV-5000" in products
    assert len(products["INV-3000"]) == 2


def test_bom_unknown_profile_raises():
    with pytest.raises(BomParseError):
        parse_bom_workbook(b"", profile="nope")
