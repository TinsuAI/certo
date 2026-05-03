"""Shared helpers for BOM adapters."""
from __future__ import annotations

from app.parsers._excel import cell_num as _cell_num_shared
from app.parsers._excel import cell_str as _cell_str_shared


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


# BOM adapters used to ship their own copy of cell_str/cell_num here.
# The shared helper in app/parsers/_excel.py has the int-coerce fix that
# prevents `'308449399330.0'`-style trailing-zero pollution; re-export
# from there so every adapter gets the fix automatically.
cell_str = _cell_str_shared
cell_num = _cell_num_shared


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
