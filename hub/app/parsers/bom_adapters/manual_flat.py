"""manual_flat — single sheet with product/material/qty columns.

The simplest and most common shape. Honours LLM-confirmed mapping
overrides via `parser_mappings` cache, plus the slice-3 flexible flow
(header_row_override + extra_required_fields + skipped-row tracking).

`parse()` returns the dict shape (existing contract — unchanged so the
4 other adapters + the flatten engine + technical_flatten path don't
care about the slice 3 changes). `parse_with_skipped()` is the new
slice-3 entry point that returns `(products, skipped_rows)` for the
unified mapping flow.
"""
from __future__ import annotations

from collections import defaultdict

from hub.app.parsers._excel import (
    cell_str, header_row, index_headers, load_xlsx,
)
from hub.app.parsers.bom_adapters._common import (
    COMMON_ALIASES, cell_num, cols_from_override,
)


# Slice 3: surface ALIASES so `_mapping_flow._module_aliases('bom')` can
# find them for rigid auto-match on the mapping page.
ALIASES = COMMON_ALIASES


class ManualFlatAdapter:
    name = "manual_flat"
    label_key = "bom.adapter.manual_flat.label"
    description_key = "bom.adapter.manual_flat.desc"
    supports_mapping_override = True
    emits_intermediate_btp_versions = True

    def detect(self, blob: bytes, *, root_code: str | None = None
               ) -> float | None:
        # Generic flat layout — no unambiguous structural marker. Abstain so
        # parse_with_fallback keeps registration order (tried after the
        # high-precision SAP detectors).
        return None

    def parse(self, blob: bytes, *,
              mapping_override: dict[str, str] | None = None,
              header_row_override: int | None = None,
              extra_required_fields: list[str] | None = None,
              ) -> dict[str, list[dict]]:
        products, _skipped = _parse_core(
            blob,
            mapping_override=mapping_override,
            header_row_override=header_row_override,
            extra_required_fields=extra_required_fields,
        )
        return products


def parse_with_skipped(
    blob: bytes, *,
    mapping_override: dict[str, str] | None = None,
    header_row_override: int | None = None,
    extra_required_fields: list[str] | None = None,
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Slice-3 entry point: return (products, skipped_rows) tuple.

    Used by the unified upload mapping flow for the manual_flat profile
    only. Layout-driven adapters keep the dict-only contract.
    """
    return _parse_core(
        blob,
        mapping_override=mapping_override,
        header_row_override=header_row_override,
        extra_required_fields=extra_required_fields,
    )


def _parse_core(
    blob: bytes, *,
    mapping_override: dict[str, str] | None,
    header_row_override: int | None,
    extra_required_fields: list[str] | None,
) -> tuple[dict[str, list[dict]], list[dict]]:
    from hub.app.parsers.bom_adapters import BomParseError
    try:
        wb = load_xlsx(blob)
    except Exception as e:
        raise BomParseError(f"Cannot open workbook: {e}") from e

    extra_required = list(extra_required_fields or [])
    products: dict[str, list[dict]] = defaultdict(list)
    skipped: list[dict] = []
    any_sheet_had_both = False

    for ws in wb.worksheets:
        if header_row_override is not None:
            header_idx, headers = _read_header_at(ws, header_row_override)
            if not headers:
                continue
        else:
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
        any_sheet_had_both = True

        for row_idx_1based, raw in _iter_data_rows_with_index(ws, header_idx):
            product = cell_str(raw, cols.get("product_code"))
            material = cell_str(raw, cols.get("material_code"))
            qty = cell_num(raw, cols.get("qty_per_unit"))
            raw_snap = _build_raw_snapshot(raw, cols, headers)

            missing: list[str] = []
            if not product:
                missing.append("product_code")
            if not material:
                missing.append("material_code")
            for f in extra_required:
                if f == "qty_per_unit":
                    if qty is None or qty == 0:
                        missing.append("qty_per_unit")
                else:
                    if not cell_str(raw, cols.get(f)):
                        missing.append(f)
            if missing:
                skipped.append({
                    "row_index": row_idx_1based,
                    "sheet": ws.title,
                    "reason": "missing_required:" + ",".join(missing),
                    "raw": raw_snap,
                })
                continue

            products[product].append({
                "material_code": material,
                "qty_per_unit": qty if qty is not None else 0.0,
                "uom": cell_str(raw, cols.get("uom")),
                "bom_code": cell_str(raw, cols.get("bom_code")),
                "bom_variant_id": cell_str(raw, cols.get("bom_variant_id")),
            })

    if not any_sheet_had_both:
        raise BomParseError(
            "No BOM rows recognized; need product + material + qty headers."
        )

    return dict(products), skipped


def _read_header_at(ws, row_no_1based: int) -> tuple[int, list[str]]:
    cells: list[str] = []
    for r_idx, raw in enumerate(
        ws.iter_rows(min_row=row_no_1based, max_row=row_no_1based, values_only=True),
        start=row_no_1based,
    ):
        cells = [str(c).strip() if c is not None else "" for c in raw]
        return r_idx, cells
    return row_no_1based, cells


def _iter_data_rows_with_index(ws, header_row_idx: int):
    for offset, row in enumerate(
        ws.iter_rows(min_row=header_row_idx + 1, values_only=True), start=1,
    ):
        if all(c is None or (isinstance(c, str) and not c.strip()) for c in row):
            continue
        yield header_row_idx + offset, row


def _build_raw_snapshot(row, cols: dict[str, int], headers: list[str]) -> dict:
    snap: dict = {}
    claimed: set[int] = set()
    for field, idx in cols.items():
        snap[field] = cell_str(row, idx)
        claimed.add(idx)
    for i, h in enumerate(headers):
        if i in claimed or not h:
            continue
        v = cell_str(row, i)
        if v is not None:
            snap[f"col_{i}"] = v
    return snap
