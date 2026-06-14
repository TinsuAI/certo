"""ezsoft_3tsoft — Growatt's EZSOFT / 3TSoft NXT export.

One sheet ("EZSOFT - 3TSoft") for all material types, with:
  - a title block (rows 1-4: company, "TỔNG HỢP NHẬP - XUẤT", period),
  - a bilingual VN/中文 header band (category row "Tồn đầu - 期初庫存" / "Nhập -
    入庫" / "Xuất - 輸出" / "Tồn cuối - 期末庫存" + sub-rows Mã/Tên/Đvt),
  - group rows whose code is a type marker (BTP / TP / NVL / VT) that carry
    subtotals and segment the sheet — these set `reported_role` and are skipped,
  - a single lumped "Xuất" column → outbound_total (no 4-way split).

Headers are bilingual concatenations ("Tồn đầu - 期初庫存"), so this adapter uses
substring matching on its known layout rather than the exact-match alias index.
"""
from __future__ import annotations

from app.parsers._excel import cell_num, cell_str, load_xlsx

GROUP_ROLES = {"BTP": "btp", "TP": "tp", "NVL": "nvl", "VT": "nvl"}
_SUBHEADER_TOKENS = ("mã", "tên", "đvt", "số lượng", "tiếng việt", "tiếng hoa",
                     "代碼", "代码", "名稱", "名称", "數量", "数量", "越文", "中文")


def _find_col(cells: list[str], *needles: str) -> int | None:
    for i, c in enumerate(cells):
        low = (c or "").lower()
        if any(n in low for n in needles):
            return i
    return None


def _target_sheet(wb):
    """The ezsoft/3tsoft-titled sheet, or None. Keyed on the title (same signal
    as detect()) so this adapter never greedily claims a generic NXT file that
    merely happens to have Tồn đầu/Tồn cuối headers — that's manual_generic's job."""
    for ws in wb.worksheets:
        if "ezsoft" in ws.title.lower() or "3tsoft" in ws.title.lower():
            return ws
    return None


def _header_row(ws) -> tuple[int, list[str]] | None:
    """Find the category header row: the one carrying both an opening marker
    (Tồn đầu / 期初) and a closing marker (Tồn cuối / 期末)."""
    for idx, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True),
                              start=1):
        cells = [("" if c is None else str(c)).strip() for c in row]
        joined = " ".join(cells).lower()
        if ("tồn đầu" in joined or "期初" in joined) and \
           ("tồn cuối" in joined or "期末" in joined):
            return idx, cells
    return None


class Ezsoft3TSoftAdapter:
    name = "ezsoft_3tsoft"
    label_key = "nxt.adapter.ezsoft_3tsoft.label"
    description_key = "nxt.adapter.ezsoft_3tsoft.desc"
    supports_mapping_override = False

    def detect(self, blob: bytes) -> float | None:
        try:
            wb = load_xlsx(blob)
        except Exception:
            return None
        for ws in wb.worksheets:
            t = ws.title.lower()
            if "ezsoft" in t or "3tsoft" in t:
                # An explicit EZSOFT/3TSoft-titled sheet is the strongest signal
                # — outrank system_template (0.95) for mega-workbooks that also
                # carry agency NVL/TP/BTP working sheets.
                return 0.97
        return None

    def parse(self, blob: bytes, *,
              mapping_override: dict[str, str] | None = None) -> list[dict]:
        from app.parsers.nxt_adapters import NxtParseError
        try:
            wb = load_xlsx(blob)
        except Exception as e:
            raise NxtParseError(f"Cannot open workbook: {e}") from e

        ws = _target_sheet(wb)
        if ws is None:
            raise NxtParseError("No EZSOFT/3TSoft NXT sheet found.")
        hdr = _header_row(ws)
        if hdr is None:
            raise NxtParseError("No bilingual NXT header band found.")
        header_idx, cat_cells = hdr

        # Combine the category row + next 2 sub-rows. The category label
        # ("Vật tư") sits in the same column as the sub-header ("Mã"), so JOIN
        # every header row per column (not first-non-empty) to see both.
        rows = list(ws.iter_rows(min_row=header_idx, max_row=header_idx + 2,
                                 values_only=True))
        width = max((len(r) for r in rows), default=0)
        combined = []
        for c in range(width):
            parts = [str(r[c]).strip() for r in rows
                     if c < len(r) and r[c] is not None and str(r[c]).strip()]
            combined.append(" ".join(parts))

        col_code = _find_col(combined, "mã", "代碼", "代码")
        col_name = _find_col(combined, "tên", "名稱", "名称")
        col_uom = _find_col(combined, "đvt", "單位", "单位")
        col_open = _find_col(combined, "tồn đầu", "期初")
        col_in = _find_col(combined, "nhập", "入庫", "入库")
        col_out = _find_col(combined, "xuất", "輸出", "输出")
        col_close = _find_col(combined, "tồn cuối", "期末")
        if col_code is None or col_open is None or col_close is None:
            raise NxtParseError("EZSOFT header missing code/opening/closing.")

        lines: list[dict] = []
        role: str | None = None
        for row in ws.iter_rows(min_row=header_idx + 1, values_only=True):
            code = cell_str(row, col_code)
            if not code:
                continue
            low = code.strip().lower()
            if any(tok == low or tok in low for tok in _SUBHEADER_TOKENS):
                continue  # leftover sub-header row
            upper = code.strip().upper()
            if upper in GROUP_ROLES:
                role = GROUP_ROLES[upper]
                continue  # group subtotal row
            out_total = cell_num(row, col_out)
            lines.append({
                "internal_code": code,
                "customs_code": None,
                "name": cell_str(row, col_name),
                "uom": cell_str(row, col_uom),
                "reported_role": role,
                "opening": cell_num(row, col_open),
                "inbound_total": cell_num(row, col_in),
                "out_tai_xuat": None, "out_chuyen_mdsd": None,
                "out_xuat_sx": None, "out_xuat_khac": None,
                "outbound_total": out_total,
                "closing_reported": cell_num(row, col_close),
                "note": None,
            })
        if not lines:
            raise NxtParseError("No EZSOFT NXT data rows recognized.")
        return lines
