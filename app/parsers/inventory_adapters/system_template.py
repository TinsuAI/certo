"""system_template — the canonical year-end inventory snapshot workbook.

One data sheet "Tồn kho": header row 1, data row 2+. Snapshot date + client
come from the upload form. Single source of truth for the canonical snapshot
column set: renders AND parses it.
"""
from __future__ import annotations

import io

from app.parsers._excel import header_row, index_headers, load_xlsx
from app.parsers.inventory_adapters._common import ALIASES, parse_inventory_sheets

# (header text written into the template, logical field). "Chênh lệch" is shown
# for human convenience but derived on read, so it is NOT a parsed input column.
CANONICAL_COLUMNS: list[tuple[str, str]] = [
    ("Mã", "code"),
    ("Tên", "name"),
    ("ĐVT", "uom"),
    ("Kho", "warehouse"),
    ("Lô/Batch", "batch"),
    ("SL sổ sách", "qty_book"),
    ("SL thực đếm", "qty_physical"),
    ("Ghi chú", "note"),
]
DATA_SHEET = "Tồn kho"


class SystemTemplateInventoryAdapter:
    name = "system_template"
    label_key = "inventory.adapter.system_template.label"
    description_key = "inventory.adapter.system_template.desc"
    supports_mapping_override = False

    def detect(self, blob: bytes) -> float | None:
        try:
            wb = load_xlsx(blob)
        except Exception:
            return None
        for ws in wb.worksheets:
            hdr = header_row(ws, aliases=ALIASES)
            if not hdr:
                continue
            cols = index_headers(hdr[1], ALIASES)
            if "code" in cols and ("qty_book" in cols or "qty_physical" in cols):
                return 0.9
        return None

    def parse(self, blob: bytes, *,
              mapping_override: dict[str, str] | None = None) -> list[dict]:
        return parse_inventory_sheets(blob, mapping_override=mapping_override)


def render_template_xlsx() -> bytes:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = DATA_SHEET
    headers = [h for h, _ in CANONICAL_COLUMNS]
    # Show the derived chênh lệch column for human readers (ignored on parse).
    display_headers = headers[:-1] + ["Chênh lệch", "Ghi chú"]
    for ci, h in enumerate(display_headers, 1):
        c = ws.cell(row=1, column=ci, value=h)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="D9E1F2")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    samples = [
        ["NVL-001", "Nhựa ABS", "KG", "Kho NVL", "LOT-2025-001", 1500, 1495, "", "Hụt 5"],
        ["TP-001", "Bộ biến tần 5kW", "PCE", "Kho TP", "", 20, 20, "", ""],
    ]
    for ri, sample in enumerate(samples, start=2):
        for ci, v in enumerate(sample, 1):
            ws.cell(row=ri, column=ci, value=v)
    for ci in range(1, len(display_headers) + 1):
        ws.column_dimensions[chr(64 + ci)].width = 18

    inst = wb.create_sheet("Hướng dẫn")
    inst["A1"] = "Mẫu chốt tồn kho cuối kỳ — chuẩn hệ thống"
    inst["A1"].font = Font(size=13, bold=True)
    lines = [
        "",
        "Một sheet 'Tồn kho': dòng 1 tiêu đề cột, dữ liệu từ dòng 2.",
        "Cột: " + " | ".join(h for h, _ in CANONICAL_COLUMNS),
        "",
        "Quy ước:",
        "• Mã là bắt buộc.",
        "• SL sổ sách = số theo sổ; SL thực đếm = số kiểm kê thực tế.",
        "• Chênh lệch (= thực đếm − sổ sách) do hệ thống tự tính — cột trong file chỉ để xem.",
        "• Ngày chốt chọn ở màn hình tải lên, không nhập trong file.",
        "• Nếu mỗi kho một sheet: để trống cột Kho, hệ thống lấy tên sheet làm kho.",
    ]
    for ri, line in enumerate(lines, start=2):
        inst.cell(row=ri, column=1, value=line).alignment = Alignment(
            wrap_text=True, vertical="top")
    inst.column_dimensions["A"].width = 100

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
