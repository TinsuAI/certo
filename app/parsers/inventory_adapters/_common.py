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
        "庫存主單位",
    ],
    "warehouse": ["Kho", "Kho hàng", "Tên kho", "仓库", "倉庫"],
    "batch": ["Lô/Batch", "Lô", "Batch", "Số lô", "批号", "批號"],
    "qty_book": [
        "SL sổ sách", "Số lượng sổ sách", "Số lượng hệ thống", "Tồn sổ sách",
        "Số Lượng Kế toán", "qty_book", "库存量(主单位)", "庫存量(主單位)",
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
