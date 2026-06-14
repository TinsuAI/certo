"""Shared NXT parsing helpers + canonical field aliases.

The canonical NXT line shape every adapter maps INTO:

    internal_code, customs_code, name, uom, reported_role,
    opening, inbound_total,
    out_tai_xuat, out_chuyen_mdsd, out_xuat_sx, out_xuat_khac,
    closing_reported, note

`reported_role` is provenance (nvl|tp|btp) derived from the source
sheet/section, NOT an authoritative classification — see the migration 082
header and the feature brief.

ALIASES seeds both the system_template adapter (exact canonical headers) and
the slice-2 `manual_generic` flexible flow (real-world naming variance across
EZSOFT/3TSoft, MISA, SAP MB5B, bilingual VN/中文). Adding a variant is a
one-line append, mirroring the BOM adapters' COMMON_ALIASES.
"""
from __future__ import annotations

# Logical field → accepted header strings (exact match after normalize_header).
ALIASES: dict[str, list[str]] = {
    "internal_code": [
        "Mã nội bộ", "Mã NB", "Mã vật tư", "Mã hàng", "Mã NVL", "Mã NPL",
        "Mã sản phẩm", "Mã ERP", "material_code", "物料编码", "物料編碼", "代碼",
    ],
    "customs_code": [
        "Mã hải quan", "Mã HQ", "Mã nguyên liệu, vật tư",
        "Mã sản phẩm xuất khẩu", "customs_code",
    ],
    "name": [
        "Tên", "Tên hàng", "Tên nguyên liệu, vật tư", "Tên sản phẩm",
        "Tên sản phẩm xuất khẩu", "name", "物料名称", "物料名稱", "名稱",
    ],
    "uom": [
        "ĐVT", "Đvt", "Đơn vị tính", "Đơn vị", "uom", "unit", "单位", "單位",
        "庫存主單位",
    ],
    "opening": [
        "Tồn đầu kỳ", "Đầu kỳ", "Tồn đầu", "Lượng NL, VT tồn kho đầu kỳ",
        "Lượng sản phẩm tồn kho đầu kỳ", "opening_stock_qty", "期初庫存",
    ],
    "inbound_total": [
        "Nhập trong kỳ", "Nhập", "Tổng nhập kho", "Lượng NL, VT nhập trong kỳ",
        "Lượng sản phẩm nhập trong kỳ", "total_receipt_qty", "入庫",
    ],
    "out_tai_xuat": ["Tái xuất", "tai_xuat"],
    "out_chuyen_mdsd": [
        "Chuyển MĐSD/TTNĐ/tiêu hủy",
        "Chuyển mục đích sử dụng, tiêu thụ nội địa, tiêu hủy",
        "Chuyển mục đích sử dụng", "Chuyển MĐSD", "chuyen_mdsd",
    ],
    "out_xuat_sx": [
        "Xuất kho SX", "Xuất kho để sản xuất", "Xuất SX", "xuat_sx",
    ],
    "out_xuat_khac": ["Xuất kho khác", "Xuất khác", "xuat_khac"],
    "closing_reported": [
        "Tồn cuối kỳ", "Cuối kỳ", "Tồn cuối",
        "Lượng NL, VT nhập khẩu tồn kho cuối kỳ",
        "Lượng sản phẩm tồn kho cuối kỳ theo sổ sách theo dõi",
        "closing_stock_qty", "期末庫存",
    ],
    "note": ["Ghi chú", "note", "備註", "备注"],
}

OUT_BUCKETS = ("out_tai_xuat", "out_chuyen_mdsd", "out_xuat_sx", "out_xuat_khac")

NUMERIC_FIELDS = (
    "opening", "inbound_total", *OUT_BUCKETS, "outbound_total", "closing_reported",
)


def outbound_value(line: dict) -> float | None:
    """Canonical total xuất. Prefers the explicit outbound_total; falls back to
    the sum of the 4 regulatory buckets when present."""
    total = line.get("outbound_total")
    if total is not None:
        return total
    buckets = [line.get(f) for f in OUT_BUCKETS]
    if all(b is None for b in buckets):
        return None
    return sum(b or 0.0 for b in buckets)


def closing_implied(line: dict) -> float | None:
    """Tồn cuối kỳ ngụ ý = đầu kỳ + nhập − tổng xuất. Derived at runtime
    (never stored). Returns None when opening and inbound are both absent."""
    opening = line.get("opening")
    inbound = line.get("inbound_total")
    if opening is None and inbound is None:
        return None
    return (opening or 0.0) + (inbound or 0.0) - (outbound_value(line) or 0.0)
