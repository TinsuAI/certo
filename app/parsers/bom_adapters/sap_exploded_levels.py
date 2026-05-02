"""sap_exploded_levels — SAP-style multi-level export with a Level column.

Single sheet; rows roll up under their parent finished product based on
indent level (`Level` / `Lvl` / `Cấp`). The first level seen is the
parent level (typically 0 or 1), and subsequent rows at deeper levels
are component lines for the most recently seen parent.

Originally observed in Johnson VN's SAP exports — but this is the
generic SAP exploded BOM shape.
"""
from __future__ import annotations

from collections import defaultdict

from app.parsers._excel import header_row, index_headers, iter_data_rows, load_xlsx
from app.parsers.bom_adapters._common import (
    COMMON_ALIASES, cell_num, cell_str, to_int,
)


_SAP_ALIASES = {
    **COMMON_ALIASES,
    "level":  ["level", "lvl", "cấp"],
    "parent": ["parent", "tk cha", "cha"],
}


class SapExplodedLevelsAdapter:
    name = "sap_exploded_levels"
    label_key = "bom.adapter.sap_exploded_levels.label"
    description_key = "bom.adapter.sap_exploded_levels.desc"
    supports_mapping_override = False
    emits_intermediate_btp_versions = True

    def parse(self, blob: bytes, *,
              mapping_override: dict[str, str] | None = None,
              ) -> dict[str, list[dict]]:
        from app.parsers.bom_adapters import BomParseError
        try:
            wb = load_xlsx(blob)
        except Exception as e:
            raise BomParseError(f"Cannot open workbook: {e}") from e
        products: dict[str, list[dict]] = defaultdict(list)
        for ws in wb.worksheets:
            hdr = header_row(ws, aliases=_SAP_ALIASES)
            if not hdr:
                continue
            header_idx, headers = hdr
            cols = index_headers(headers, _SAP_ALIASES)
            if "material_code" not in cols:
                continue
            current_product: str | None = None
            parent_level: int | None = None
            for raw in iter_data_rows(ws, header_idx):
                material = cell_str(raw, cols.get("material_code"))
                if not material:
                    continue
                level = to_int(cell_str(raw, cols.get("level")))
                if level is not None and parent_level is None:
                    parent_level = level
                if level == 0 or level == parent_level \
                        or cell_str(raw, cols.get("product_code")) == material:
                    current_product = material
                    continue
                if not current_product:
                    current_product = cell_str(raw, cols.get("product_code")) or material
                products[current_product].append({
                    "material_code": material,
                    "qty_per_unit": cell_num(raw, cols.get("qty_per_unit")) or 0.0,
                    "uom": cell_str(raw, cols.get("uom")),
                    "bom_code": cell_str(raw, cols.get("bom_code")),
                    "bom_variant_id": cell_str(raw, cols.get("bom_variant_id")),
                })
        if not products:
            raise BomParseError("No BOM rows recognized in SAP-exploded format.")
        return dict(products)
