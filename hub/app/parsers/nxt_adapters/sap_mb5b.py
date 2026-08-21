"""sap_mb5b — SAP MB5B stock/valuation export, per-material detail (Johnson).

Clean tabular layout: row-1 snake_case headers, one row per material, 中文
descriptions. A single lumped issue total → outbound_total.

reported_role is left null: the SAP gl_account / valuation_class → NVL/TP/BTP
mapping is per-client SAP config, not generic. The catalog resolves the
authoritative class at runtime; a per-client GL map can populate role later
without overfitting this shared adapter.
"""
from __future__ import annotations

from app.parsers._excel import cell_num, cell_str, load_xlsx

# MB5B header → canonical field.
_COLMAP = {
    "material": "internal_code",
    "material_description": "name",
    "base_unit": "uom",
    "opening_stock_qty": "opening",
    "total_receipt_qty": "inbound_total",
    "total_issue_qty": "outbound_total",
    "closing_stock_qty": "closing_reported",
}
# Headers that together unambiguously identify an MB5B export.
_SIGNATURE = {"gl_account", "valuation_class", "opening_stock_qty",
              "closing_stock_qty"}


def _header_map(ws) -> tuple[int, dict[str, int]] | None:
    """Row-1 header → {header_lower: col_idx}, if it looks like MB5B."""
    for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
        cells = {(str(c).strip().lower() if c is not None else ""): i
                 for i, c in enumerate(row)}
        cells.pop("", None)
        if _SIGNATURE <= set(cells):
            return 1, cells
    return None


class SapMb5bAdapter:
    name = "sap_mb5b"
    label_key = "nxt.adapter.sap_mb5b.label"
    description_key = "nxt.adapter.sap_mb5b.desc"
    supports_mapping_override = False

    def detect(self, blob: bytes) -> float | None:
        try:
            wb = load_xlsx(blob)
        except Exception:
            return None
        for ws in wb.worksheets:
            if _header_map(ws) is not None:
                return 0.93
        return None

    def parse(self, blob: bytes, *,
              mapping_override: dict[str, str] | None = None) -> list[dict]:
        from app.parsers.nxt_adapters import NxtParseError
        try:
            wb = load_xlsx(blob)
        except Exception as e:
            raise NxtParseError(f"Cannot open workbook: {e}") from e

        for ws in wb.worksheets:
            hm = _header_map(ws)
            if hm is None:
                continue
            _, header = hm
            cols = {field: header[h] for h, field in _COLMAP.items() if h in header}
            if "internal_code" not in cols:
                continue
            lines = []
            for raw in ws.iter_rows(min_row=2, values_only=True):
                code = cell_str(raw, cols.get("internal_code"))
                if not code:
                    continue
                line = {
                    "internal_code": code,
                    "customs_code": None,
                    "name": cell_str(raw, cols.get("name")),
                    "uom": cell_str(raw, cols.get("uom")),
                    "reported_role": None,
                    "opening": cell_num(raw, cols.get("opening")),
                    "inbound_total": cell_num(raw, cols.get("inbound_total")),
                    "out_tai_xuat": None, "out_chuyen_mdsd": None,
                    "out_xuat_sx": None, "out_xuat_khac": None,
                    "outbound_total": cell_num(raw, cols.get("outbound_total")),
                    "closing_reported": cell_num(raw, cols.get("closing_reported")),
                    "note": None,
                }
                lines.append(line)
            if lines:
                return lines
        raise NxtParseError("No SAP MB5B material rows recognized.")
