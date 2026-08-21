"""misa_can_doi_ton — MISA "CÂN ĐỐI TỒN KHO" NXT export.

Layout: title block (rows 1-6), a two-row merged header (row N-1 carries
Mã Hàng / Tên Hàng / ĐVT, row N carries the Số Lượng sub-columns Đầu Kỳ / Nhập
/ Xuất / Cuối Kỳ at scattered, merged-cell column positions), then data rows
interleaved with "Kho hàng: …" warehouse section breaks.

Headers + qty markers live on different rows and at non-adjacent columns, so —
like ezsoft_3tsoft — this adapter combines the two header rows per column and
matches by substring rather than the exact-match alias index.
"""
from __future__ import annotations

from hub.app.parsers._excel import cell_num, cell_str, load_xlsx


def _find_col(cells: list[str], *needles: str) -> int | None:
    for i, c in enumerate(cells):
        low = (c or "").lower()
        if any(n in low for n in needles):
            return i
    return None


def _has_marker(ws) -> bool:
    """True if the sheet carries the distinctive MISA report title. Keeps parse
    keyed on the same signal as detect() so it never greedily claims a generic
    NXT file that merely has Đầu Kỳ/Cuối Kỳ headers."""
    head = " ".join(
        ("" if c is None else str(c)).lower()
        for row in ws.iter_rows(min_row=1, max_row=8, values_only=True)
        for c in row)
    return "cân đối tồn kho" in head


def _qty_header_row(ws) -> int | None:
    """The Số Lượng sub-header row — carries both Đầu Kỳ and Cuối Kỳ."""
    for idx, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True),
                              start=1):
        joined = " ".join(("" if c is None else str(c)).lower() for c in row)
        if "đầu kỳ" in joined and "cuối kỳ" in joined:
            return idx
    return None


class MisaCanDoiTonAdapter:
    name = "misa_can_doi_ton"
    label_key = "nxt.adapter.misa_can_doi_ton.label"
    description_key = "nxt.adapter.misa_can_doi_ton.desc"
    supports_mapping_override = False

    def detect(self, blob: bytes) -> float | None:
        try:
            wb = load_xlsx(blob)
        except Exception:
            return None
        for ws in wb.worksheets:
            if _has_marker(ws):
                return 0.9
        return None

    def parse(self, blob: bytes, *,
              mapping_override: dict[str, str] | None = None) -> list[dict]:
        from hub.app.parsers.nxt_adapters import NxtParseError
        try:
            wb = load_xlsx(blob)
        except Exception as e:
            raise NxtParseError(f"Cannot open workbook: {e}") from e

        for ws in wb.worksheets:
            if not _has_marker(ws):
                continue
            qty_idx = _qty_header_row(ws)
            if qty_idx is None:
                continue
            hdr_rows = list(ws.iter_rows(min_row=max(1, qty_idx - 1),
                                         max_row=qty_idx, values_only=True))
            width = max((len(r) for r in hdr_rows), default=0)
            combined = []
            for c in range(width):
                parts = [str(r[c]).strip() for r in hdr_rows
                         if c < len(r) and r[c] is not None and str(r[c]).strip()]
                combined.append(" ".join(parts))

            col_code = _find_col(combined, "mã hàng", "mã")
            col_name = _find_col(combined, "tên hàng", "tên")
            col_uom = _find_col(combined, "đvt", "đơn vị")
            col_open = _find_col(combined, "đầu kỳ")
            col_in = _find_col(combined, "nhập")
            col_out = _find_col(combined, "xuất")
            col_close = _find_col(combined, "cuối kỳ")
            if col_code is None or (col_open is None and col_close is None):
                continue

            lines = []
            for raw in ws.iter_rows(min_row=qty_idx + 1, values_only=True):
                code = cell_str(raw, col_code)
                if not code:
                    continue  # blank row or a "Kho hàng:" section break (no code)
                lines.append({
                    "internal_code": code,
                    "customs_code": None,
                    "name": cell_str(raw, col_name),
                    "uom": cell_str(raw, col_uom),
                    "reported_role": None,
                    "opening": cell_num(raw, col_open),
                    "inbound_total": cell_num(raw, col_in),
                    "out_tai_xuat": None, "out_chuyen_mdsd": None,
                    "out_xuat_sx": None, "out_xuat_khac": None,
                    "outbound_total": cell_num(raw, col_out),
                    "closing_reported": cell_num(raw, col_close),
                    "note": None,
                })
            if lines:
                return lines
        raise NxtParseError("No MISA CÂN ĐỐI TỒN KHO rows recognized.")
