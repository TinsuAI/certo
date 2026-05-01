"""Regenerate synthetic edge-case fixtures.

Each fixture exists to prove a specific parser bug or boundary. The expected
behavior (pass / specific error / row count) is asserted in
`tests/test_fixture_corpus.py`.

Re-run when the parser contract changes:
    uv run python tests/fixtures/edge_cases/_generate.py
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
import xlwt

OUT = Path(__file__).parent


def _write(name: str, sheets: list[tuple[str, list[tuple]]]) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in sheets:
        ws = wb.create_sheet(title=title[:31])
        for r in rows:
            ws.append(r)
    wb.save(OUT / name)


def _write_xls(name: str, sheets: list[tuple[str, list[tuple]]]) -> None:
    """Write legacy .xls (OLE compound) format via xlwt — for testing the
    `_excel.load_xlsx` magic-byte dispatch and `_XlsBook` adapter."""
    book = xlwt.Workbook(encoding="utf-8")
    for title, rows in sheets:
        sheet = book.add_sheet(title[:31])
        for r_idx, row in enumerate(rows):
            for c_idx, value in enumerate(row):
                if value is None:
                    continue
                sheet.write(r_idx, c_idx, value)
    book.save(OUT / name)


def growatt_bom_chinese_headers() -> None:
    """Real Growatt 2026 BOM template uses Chinese column headers.

    Hub's `bom.py` aliases don't include the Chinese strings, so all 3 profiles
    fail. Fix: add `成品物料/组件物料/标准用量/单位` to COMMON_ALIASES.
    """
    _write("growatt_bom_chinese_headers.xlsx", [
        ("Growatt", [
            ("成品物料", "组件物料", "组件物料描述", "标准用量", "单位"),
            ("PV00.0048500", "GW-NVL-001", "Main board", 1.5, "PCE"),
            ("PV00.0048500", "GW-NVL-002", "Heat sink", 0.30, "kg"),
            ("PV01.0117600", "GW-NVL-001", "Main board", 1.5, "PCE"),
        ]),
    ])


def growatt_sp_catalog_no_hq() -> None:
    """SP-only catalog (DS Thành Phẩm) — agency lists products without HQ codes.

    Hub's `materials.py` requires `customs_code` column; rejects this file.
    Fix: allow product_code-only rows when sheet=TP/SP context, or relax the
    'customs_code required' rule.
    """
    _write("growatt_sp_catalog_no_hq.xlsx", [
        ("TP", [
            ("product_code", "name", "hs_code", "rule", "status"),
            ("PV00.0048500", "Inverter PV00", "8504.40", "RVC 35% + CTSH", "active"),
            ("PV01.0117600", "Inverter PV01", "8504.40", "RVC 35% + CTSH", "active"),
        ]),
    ])


def johnson_sap_english_headers() -> None:
    """SAP-exploded BOM with English column names (Johnson real export).

    `bom.py` Johnson profile aliases for `material_code` only match Vietnamese
    'Mã NVL' or generic 'material code'. Real SAP export has 'Component number'
    + 'Comp. Qty (CUn)' + 'Component unit'. Fix: extend aliases.
    """
    _write("johnson_sap_english_headers.xlsx", [
        ("Sheet1", [
            ("Level", "Explosion level", "Component number", "Object description",
             "Comp. Qty (CUn)", "Component unit"),
            (1, 1, "ASM-001", "Assembly parent", 1, "EA"),
            (2, 2, "004426-00", "Screw; Flat Head; M6x1.0Px12L", 2, "EA"),
            (2, 2, "1000461274", "Tube; Round; 20#", 1.306, "EA"),
        ]),
    ])


def empty_workbook() -> None:
    """Boundary: workbook with one empty sheet.

    Each parser should raise its specific *ParseError, not a generic crash.
    """
    _write("empty_workbook.xlsx", [("Sheet1", [])])


def headers_in_row_5() -> None:
    """Real Vietnamese exports often have title + metadata rows before headers.

    `header_row()` scans up to row 15 for the first 'mostly-non-empty' row.
    This file puts headers in row 5 with title/metadata above. Should still
    parse correctly. Tests the scanner's tolerance.
    """
    _write("headers_in_row_5.xlsx", [
        ("BCCT", [
            ("BÁO CÁO HẢI QUAN CHI TIẾT 2025",),
            ("Doanh nghiệp: Công ty Demo",),
            ("Kỳ báo cáo: T1-T12 2025",),
            (None,),
            ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký", "Mã NPL/SP",
             "Tên hàng", "Tổng số lượng", "ĐVT", "Trị giá", "Nguyên tệ"),
            ("104111", 1, "E11", "2025-03-15", "PE-001",
             "PE-001#&Polyethylene", 100.0, "kg", 250.0, "USD"),
        ]),
    ])


def bom_workbook_uploaded_as_bcct() -> None:
    """Trap: a flat BOM accidentally uploaded to the BCCT slot.

    Hub's bcct parser only requires `customs_code OR declaration_no`. A BOM
    with 'Mã NVL' (aliases to customs_code) parses as 197K junk BCCT rows in
    real Growatt data. Fix: bcct parser should require BOTH (declaration_no
    AND customs_code) OR (declaration_no AND date AND direction-cue).
    """
    _write("bom_workbook_uploaded_as_bcct.xlsx", [
        ("BOM", [
            ("Mã SP", "Mã NVL", "Định mức", "ĐVT"),
            ("INV-3000", "PE-001", 0.45, "kg"),
            ("INV-3000", "AL-100", 0.30, "kg"),
            ("INV-5000", "CU-WIRE", 1.20, "m"),
        ]),
    ])


def legacy_xls_bcct() -> None:
    """Legacy .xls (OLE format) BCCT — exercises the xlrd adapter in
    `_excel.py:_XlsBook`. Same content shape as `dke_bcct_synthetic.xlsx`
    so the assertion is parity with the OOXML branch."""
    _write_xls("legacy_xls_bcct.xls", [
        ("BCCT 2025", [
            ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký",
             "Mã NPL/SP", "Tên hàng", "Tổng số lượng", "ĐVT", "Trị giá",
             "Nguyên tệ"),
            ("301999001", 1, "E11", "2025-01-15", "DKE-NVL-A1",
             "Steel coil", 5000.0, "kg", 12500.0, "USD"),
            ("301999099", 1, "E42", "2025-09-30", "DKE-TP-X",
             "Door panel", 600.0, "pcs", 90000.0, "USD"),
        ]),
    ])


def legacy_xls_materials() -> None:
    """Legacy .xls Danh Mục NVL — shape mirrors real DKE
    `BẢNG MÃ NVL-SP - Update March 24.xls`."""
    _write_xls("legacy_xls_materials.xls", [
        ("NVL", [
            ("Mã HQ", "Mã NB", "Tên", "Loại", "ĐVT", "HS"),
            ("PE-001", "PE-001", "Polyethylene", "nvl", "kg", "39011010"),
            ("AL-100", "AL-100", "Aluminum sheet", "nvl", "kg", "76069100"),
        ]),
    ])


def dke_bcct_real_shape() -> None:
    """DKE 2025 BCCT shape — a fourth client beyond seed.

    DKE files in `~/workspace/client/BCQT-DKE/input/` are real `.xls` (not
    parseable). This synthetic mimics that shape in `.xlsx` so the corpus
    covers DKE without depending on legacy format support landing first.
    """
    _write("dke_bcct_synthetic.xlsx", [
        ("BCCT 2025", [
            ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký",
             "Mã NPL/SP", "Tên hàng", "Tổng số lượng", "ĐVT", "Trị giá",
             "Nguyên tệ", "Xuất xứ"),
            ("301999001", 1, "E11", "2025-01-15", "DKE-NVL-A1",
             "Steel coil cold-rolled", 5000.0, "kg", 12500.0, "USD", "JP"),
            ("301999001", 2, "E11", "2025-01-15", "DKE-NVL-B2",
             "Aluminum sheet", 1200.0, "kg", 4800.0, "USD", "CN"),
            ("301999099", 1, "E42", "2025-09-30", "DKE-TP-X",
             "Door panel assembly", 600.0, "pcs", 90000.0, "USD", "VN"),
        ]),
    ])


def main() -> None:
    growatt_bom_chinese_headers()
    growatt_sp_catalog_no_hq()
    johnson_sap_english_headers()
    empty_workbook()
    headers_in_row_5()
    bom_workbook_uploaded_as_bcct()
    dke_bcct_real_shape()
    legacy_xls_bcct()
    legacy_xls_materials()
    print("Wrote synthetic fixtures to", OUT)


if __name__ == "__main__":
    main()
