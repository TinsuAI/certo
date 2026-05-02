"""Shared helpers for BOM adapters."""
from __future__ import annotations


COMMON_ALIASES = {
    "product_code": ["mã sp", "ma sp", "product", "product code", "product_code",
                     "thành phẩm", "thanh pham", "sp",
                     "成品物料"],   # zh: finished-product material
    "material_code": ["mã nvl", "ma nvl", "material", "material code", "material_code",
                      "nvl", "nguyen lieu",
                      "组件物料",       # zh: component material
                      "component number", "component code"],
    "qty_per_unit": ["định mức", "dinh muc", "qty", "quantity", "qty per", "định lượng",
                     "标准用量",                              # zh: standard quantity
                     "comp. qty", "comp qty", "comp qty cun"],
    "uom": ["đvt", "dvt", "unit", "uom",
            "单位",                    # zh: unit
            "component unit"],
    "bom_code": ["bom code", "bom", "công thức"],
    "bom_variant_id": ["variant", "phiên bản"],
}


def cell_str(row, idx) -> str | None:
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def cell_num(row, idx) -> float | None:
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def cols_from_override(headers: list[str], override: dict[str, str]) -> dict[str, int]:
    """Convert header→logical_field override dict to {logical_field: col_idx}."""
    cols: dict[str, int] = {}
    norm_to_idx = {(h or "").strip().lower(): i for i, h in enumerate(headers)}
    for header_name, logical_field in override.items():
        idx = norm_to_idx.get((header_name or "").strip().lower())
        if idx is not None and logical_field not in cols:
            cols[logical_field] = idx
    return cols
