"""sheet_per_product — one workbook sheet per finished product.

Each sheet's title becomes a product_code; rows are the BOM lines.
Heuristic skips obvious non-product sheets ('Summary', 'Tổng hợp', 'Config').

Originally observed in Growatt VN exports — but the structure is generic
across multiple agencies.
"""
from __future__ import annotations

from app.parsers._excel import header_row, index_headers, iter_data_rows, load_xlsx
from app.parsers.bom_adapters._common import COMMON_ALIASES, cell_num, cell_str


class SheetPerProductAdapter:
    name = "sheet_per_product"
    label_key = "bom.adapter.sheet_per_product.label"
    description_key = "bom.adapter.sheet_per_product.desc"
    supports_mapping_override = False  # layout-driven, not column-driven
    emits_intermediate_btp_versions = True

    def parse(self, blob: bytes, *,
              mapping_override: dict[str, str] | None = None,
              ) -> dict[str, list[dict]]:
        from app.parsers.bom_adapters import BomParseError
        try:
            wb = load_xlsx(blob)
        except Exception as e:
            raise BomParseError(f"Cannot open workbook: {e}") from e
        products: dict[str, list[dict]] = {}
        for ws in wb.worksheets:
            title = (ws.title or "").strip()
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
                material = cell_str(raw, cols.get("material_code"))
                if not material:
                    continue
                rows.append({
                    "material_code": material,
                    "qty_per_unit": cell_num(raw, cols.get("qty_per_unit")) or 0.0,
                    "uom": cell_str(raw, cols.get("uom")),
                    "bom_code": cell_str(raw, cols.get("bom_code")),
                    "bom_variant_id": cell_str(raw, cols.get("bom_variant_id")),
                })
            if rows:
                products[title] = rows
        if not products:
            raise BomParseError("No product sheets recognized; expected one product code per sheet.")
        return products
