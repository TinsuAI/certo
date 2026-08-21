"""Shared inventory-snapshot parsing helpers + canonical field aliases.

Canonical snapshot line shape every adapter maps INTO:

    code, name, uom, warehouse, batch, qty_book, qty_physical, note

`variance = qty_physical - qty_book` is derived at runtime (never stored).
ALIASES seeds the system_template adapter and the slice-4 flexible flow
(DKE multi-warehouse 实盘, MISA, SAP MB5B closing). One-line append to extend.
"""
from __future__ import annotations

ALIASES: dict[str, list[str]] = {
    "code": [
        "Mã", "Mã hàng", "Mã vật tư", "Mã NVL", "Mã hàng hóa",
        "material_code", "物料编码", "物料編碼", "代碼",
    ],
    "name": [
        "Tên", "Tên hàng", "Tên vật tư", "name", "物料名称", "物料名稱", "名稱",
    ],
    "uom": [
        "ĐVT", "Đvt", "Đơn vị tính", "Đơn vị", "uom", "单位", "單位",
        "庫存主單位", "库存主单位",
    ],
    "warehouse": ["Kho", "Kho hàng", "Tên kho", "仓库", "倉庫"],
    "batch": ["Lô/Batch", "Lô", "Batch", "Số lô", "批号", "批號"],
    "qty_book": [
        "SL sổ sách", "Số lượng sổ sách", "Số lượng hệ thống", "Tồn sổ sách",
        "Số Lượng Kế toán", "Số lượng tồn kho", "qty_book",
        "库存量(主单位)", "庫存量(主單位)",
    ],
    "qty_physical": [
        "SL thực đếm", "Số lượng thực đếm", "Số lượng kiểm kê", "Tồn thực tế",
        "qty_physical", "实盘数量", "實盤數量",
    ],
    "note": ["Ghi chú", "note", "備註", "备注"],
}

NUMERIC_FIELDS = ("qty_book", "qty_physical")


def variance(line: dict) -> float | None:
    """Chênh lệch = thực đếm − sổ sách. None when neither side present."""
    book = line.get("qty_book")
    physical = line.get("qty_physical")
    if book is None and physical is None:
        return None
    return (physical or 0.0) - (book or 0.0)


def parse_inventory_sheets(blob: bytes, *,
                           mapping_override: dict[str, str] | None = None
                           ) -> list[dict]:
    """Shared snapshot parse: iterate every sheet, alias/override-match columns,
    one canonical line per coded row. warehouse falls back to the sheet title
    (DKE = one sheet per kho). Used by both system_template and
    kiem_ke_multi_kho. Raises InventoryParseError on no recognizable rows."""
    from hub.app.parsers._excel import (
        cell_num, cell_str, header_row, index_headers, normalize_header, load_xlsx,
    )
    from hub.app.parsers.inventory_adapters import InventoryParseError

    try:
        wb = load_xlsx(blob)
    except Exception as e:
        raise InventoryParseError(f"Cannot open workbook: {e}") from e

    def _cols(headers):
        if mapping_override:
            norm = [normalize_header(h) for h in headers]
            out: dict[str, int] = {}
            for header_text, field in mapping_override.items():
                if field in out:
                    continue  # two headers → one field: first column wins
                target = normalize_header(header_text)
                for i, h in enumerate(norm):
                    if h and h == target and i not in out.values():
                        out[field] = i
                        break
            return out
        return index_headers(headers, ALIASES)

    lines: list[dict] = []
    for ws in wb.worksheets:
        hdr = header_row(ws, aliases=ALIASES)
        if not hdr:
            continue
        header_idx, headers = hdr
        cols = _cols(headers)
        if "code" not in cols:
            continue
        for raw in ws.iter_rows(min_row=header_idx + 1, values_only=True):
            if all(c is None or (isinstance(c, str) and not c.strip()) for c in raw):
                continue
            code = cell_str(raw, cols.get("code"))
            if not code:
                continue
            line = {
                "code": code,
                "name": cell_str(raw, cols.get("name")),
                "uom": cell_str(raw, cols.get("uom")),
                "warehouse": cell_str(raw, cols.get("warehouse")) or ws.title or None,
                "batch": cell_str(raw, cols.get("batch")),
                "note": cell_str(raw, cols.get("note")),
            }
            for f in NUMERIC_FIELDS:
                line[f] = cell_num(raw, cols.get(f))
            lines.append(line)

    if not lines:
        raise InventoryParseError("No inventory rows recognized.")
    return lines
