"""BOM Excel parsers — manual_flat / growatt_multi_workbook / johnson_sap_exploded.

Returns a dict[product_code, list[row_dict]] mapping each finished product to its rows.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from app.parsers._excel import load_xlsx, header_row, index_headers, iter_data_rows


class BomParseError(RuntimeError):
    pass


COMMON_ALIASES = {
    "product_code": ["mã sp", "ma sp", "product", "product code", "product_code",
                     "thành phẩm", "thanh pham", "sp",
                     "成品物料"],  # zh: finished-product material
    "material_code": ["mã nvl", "ma nvl", "material", "material code", "material_code",
                      "nvl", "nguyen lieu",
                      "组件物料",      # zh: component material
                      "component number", "component code"],
    "qty_per_unit": ["định mức", "dinh muc", "qty", "quantity", "qty per", "định lượng",
                     "标准用量",                              # zh: standard quantity
                     "comp. qty", "comp qty", "comp qty cun"],  # SAP "Comp. Qty (CUn)"
    "uom": ["đvt", "dvt", "unit", "uom",
            "单位",                    # zh: unit
            "component unit"],
    "bom_code": ["bom code", "bom", "công thức"],
    "bom_variant_id": ["variant", "phiên bản"],
}


def parse_bom_workbook(
    blob: bytes,
    *,
    profile: str = "manual_flat",
    mapping_override: dict[str, str] | None = None,
) -> dict[str, list[dict]]:
    """Parse a BOM workbook.

    `mapping_override`: optional dict[header_name → logical_field] from a
    confirmed LLM proposal (cached via `hub.parser_mappings`). Bypasses
    alias matching when present. Only the manual_flat profile honours
    overrides today; the other two profiles infer structure from sheet
    layout, not column matching.
    """
    if profile == "manual_flat":
        return _parse_flat(blob, mapping_override=mapping_override)
    if profile == "growatt_multi_workbook":
        return _parse_growatt_multi(blob)
    if profile == "johnson_sap_exploded":
        return _parse_johnson(blob)
    raise BomParseError(f"Unknown BOM profile: {profile}")


def _parse_flat(
    blob: bytes,
    *,
    mapping_override: dict[str, str] | None = None,
) -> dict[str, list[dict]]:
    """One sheet, columns include product_code + material_code + qty_per_unit."""
    try:
        wb = load_xlsx(blob)
    except Exception as e:
        raise BomParseError(f"Cannot open workbook: {e}") from e
    products: dict[str, list[dict]] = defaultdict(list)
    for ws in wb.worksheets:
        hdr = header_row(ws, aliases=COMMON_ALIASES)
        if not hdr:
            continue
        header_idx, headers = hdr
        if mapping_override:
            cols = _cols_from_override(headers, mapping_override)
        else:
            cols = index_headers(headers, COMMON_ALIASES)
        if "product_code" not in cols or "material_code" not in cols:
            continue
        for raw in iter_data_rows(ws, header_idx):
            product = _cell_str(raw, cols.get("product_code"))
            material = _cell_str(raw, cols.get("material_code"))
            if not product or not material:
                continue
            row = {
                "material_code": material,
                "qty_per_unit": _cell_num(raw, cols.get("qty_per_unit")) or 0.0,
                "uom": _cell_str(raw, cols.get("uom")),
                "bom_code": _cell_str(raw, cols.get("bom_code")),
                "bom_variant_id": _cell_str(raw, cols.get("bom_variant_id")),
            }
            products[product].append(row)
    if not products:
        raise BomParseError("No BOM rows recognized; need product + material + qty headers.")
    return dict(products)


def _parse_growatt_multi(blob: bytes) -> dict[str, list[dict]]:
    """Each sheet name = product code; rows are material lines.

    Heuristic: sheets whose names look like product codes (alphanumeric, optionally
    dotted) are interpreted as one BOM each.
    """
    try:
        wb = load_xlsx(blob)
    except Exception as e:
        raise BomParseError(f"Cannot open workbook: {e}") from e
    products: dict[str, list[dict]] = {}
    for ws in wb.worksheets:
        title = ws.title.strip()
        if not title or title.lower() in {"summary", "tong hop", "config"}:
            continue
        hdr = header_row(ws, aliases=COMMON_ALIASES)
        if not hdr:
            continue
        header_idx, headers = hdr
        cols = index_headers(headers, COMMON_ALIASES)
        if "material_code" not in cols:
            continue
        rows: list[dict] = []
        for raw in iter_data_rows(ws, header_idx):
            material = _cell_str(raw, cols.get("material_code"))
            if not material:
                continue
            rows.append({
                "material_code": material,
                "qty_per_unit": _cell_num(raw, cols.get("qty_per_unit")) or 0.0,
                "uom": _cell_str(raw, cols.get("uom")),
                "bom_code": _cell_str(raw, cols.get("bom_code")),
                "bom_variant_id": _cell_str(raw, cols.get("bom_variant_id")),
            })
        if rows:
            products[title] = rows
    if not products:
        raise BomParseError("No product sheets recognized; expected one product code per sheet.")
    return products


def _parse_johnson(blob: bytes) -> dict[str, list[dict]]:
    """SAP-exploded format: typically a single sheet with parent-child rows
    where lower-level rows roll up under their parent finished product."""
    try:
        wb = load_xlsx(blob)
    except Exception as e:
        raise BomParseError(f"Cannot open workbook: {e}") from e
    products: dict[str, list[dict]] = defaultdict(list)
    sap_aliases = {
        **COMMON_ALIASES,
        "level": ["level", "lvl", "cấp"],
        "parent": ["parent", "tk cha", "cha"],
    }
    for ws in wb.worksheets:
        hdr = header_row(ws, aliases=sap_aliases)
        if not hdr:
            continue
        header_idx, headers = hdr
        cols = index_headers(headers, sap_aliases)
        if "material_code" not in cols:
            continue
        current_product: str | None = None
        parent_level: int | None = None
        for raw in iter_data_rows(ws, header_idx):
            material = _cell_str(raw, cols.get("material_code"))
            if not material:
                continue
            level_raw = _cell_str(raw, cols.get("level"))
            level = _to_int(level_raw)
            # The first level we see is the "parent" level (0 in true SAP
            # exports, 1 in Johnson's variant). Rows at that level are
            # finished products; their material rows live at deeper levels.
            if level is not None and parent_level is None:
                parent_level = level
            if level == 0 or level == parent_level \
               or _cell_str(raw, cols.get("product_code")) == material:
                current_product = material
                continue
            if not current_product:
                current_product = _cell_str(raw, cols.get("product_code")) or material
            products[current_product].append({
                "material_code": material,
                "qty_per_unit": _cell_num(raw, cols.get("qty_per_unit")) or 0.0,
                "uom": _cell_str(raw, cols.get("uom")),
                "bom_code": _cell_str(raw, cols.get("bom_code")),
                "bom_variant_id": _cell_str(raw, cols.get("bom_variant_id")),
            })
    if not products:
        raise BomParseError("No BOM rows recognized in SAP-exploded format.")
    return dict(products)


def _cols_from_override(headers: list[str], override: dict[str, str]) -> dict[str, int]:
    """Convert header→logical_field override dict to {logical_field: col_idx}."""
    cols: dict[str, int] = {}
    norm_to_idx = {(h or "").strip().lower(): i for i, h in enumerate(headers)}
    for header_name, logical_field in override.items():
        idx = norm_to_idx.get((header_name or "").strip().lower())
        if idx is not None and logical_field not in cols:
            cols[logical_field] = idx
    return cols


def _cell_str(row, idx) -> str | None:
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _cell_num(row, idx) -> float | None:
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None
