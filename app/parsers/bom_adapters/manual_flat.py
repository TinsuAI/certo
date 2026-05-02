"""manual_flat — single sheet with product/material/qty columns.

The simplest and most common shape. Honours LLM-confirmed mapping
overrides via `parser_mappings` cache.
"""
from __future__ import annotations

from collections import defaultdict

from app.parsers._excel import header_row, index_headers, iter_data_rows, load_xlsx
from app.parsers.bom_adapters._common import (
    COMMON_ALIASES, cell_num, cell_str, cols_from_override,
)


class ManualFlatAdapter:
    name = "manual_flat"
    label_key = "bom.adapter.manual_flat.label"
    description_key = "bom.adapter.manual_flat.desc"
    supports_mapping_override = True
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
            hdr = header_row(ws, aliases=COMMON_ALIASES)
            if not hdr:
                continue
            header_idx, headers = hdr
            if mapping_override:
                cols = cols_from_override(headers, mapping_override)
            else:
                cols = index_headers(headers, COMMON_ALIASES)
            if "product_code" not in cols or "material_code" not in cols:
                continue
            for raw in iter_data_rows(ws, header_idx):
                product = cell_str(raw, cols.get("product_code"))
                material = cell_str(raw, cols.get("material_code"))
                if not product or not material:
                    continue
                products[product].append({
                    "material_code": material,
                    "qty_per_unit": cell_num(raw, cols.get("qty_per_unit")) or 0.0,
                    "uom": cell_str(raw, cols.get("uom")),
                    "bom_code": cell_str(raw, cols.get("bom_code")),
                    "bom_variant_id": cell_str(raw, cols.get("bom_variant_id")),
                })
        if not products:
            raise BomParseError("No BOM rows recognized; need product + material + qty headers.")
        return dict(products)
