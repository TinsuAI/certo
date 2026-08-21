"""Phase 1: confident rigid auto-map (skip the manual mapping page).

try_auto_map returns a header→field mapping only when the module's
required fields all resolve with no ambiguity; otherwise None → caller
shows the mapping page.
"""
from __future__ import annotations

import io

from openpyxl import Workbook

from app.routes.bcct import BCCT_MAPPING_CFG
from app.routes._mapping_flow import try_auto_map


def _xlsx(rows: list[tuple]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "BCCT"
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_STD_HEADERS = ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký",
                "Mã NPL/SP", "Tên hàng", "Tổng số lượng", "ĐVT",
                "Trị giá", "Nguyên tệ")


def test_standard_headers_resolve_confidently():
    blob = _xlsx([_STD_HEADERS,
                  ("123", 1, "E11", "2025-03-15", "PE-1", "PE", 10, "kg", 5, "USD")])
    mapping = try_auto_map(blob, BCCT_MAPPING_CFG)
    assert mapping is not None
    # required fields all present
    assert {"declaration_no", "registration_date", "customs_code"} <= set(mapping.values())
    assert mapping["Số tờ khai"] == "declaration_no"
    assert mapping["Mã NPL/SP"] == "customs_code"


def test_missing_required_field_returns_none():
    # No registration-date header → required unresolved → manual mapping page.
    blob = _xlsx([("Số tờ khai", "Mã NPL/SP", "Tên hàng"),
                  ("123", "PE-1", "PE")])
    assert try_auto_map(blob, BCCT_MAPPING_CFG) is None


def test_non_standard_headers_return_none():
    blob = _xlsx([("Number", "Date", "Code"), ("1", "2025-01-01", "X")])
    assert try_auto_map(blob, BCCT_MAPPING_CFG) is None


def test_ambiguous_duplicate_field_returns_none():
    # Two headers both rigid-match declaration_no → ambiguous → human needed.
    blob = _xlsx([("Số tờ khai", "Số TK", "Ngày đăng ký", "Mã NPL/SP"),
                  ("1", "1", "2025-01-01", "X")])
    assert try_auto_map(blob, BCCT_MAPPING_CFG) is None
