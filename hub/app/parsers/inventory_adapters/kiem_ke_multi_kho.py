"""kiem_ke_multi_kho — multi-warehouse physical stocktake (DKE-style).

One sheet per warehouse (sheet title = kho), bilingual VN/中文 header on row 2:
物料编码 / 物料名称 / 批号 / 库存主单位 / "Số lượng tồn kho … 库存量(主单位)" (sổ sách)
/ 实盘数量 (thực đếm). Headers are long bilingual concatenations, so this adapter
matches columns by substring (like ezsoft_3tsoft / misa_can_doi_ton) rather than
the exact-match alias index. Distinguished by the physical-count column.
"""
from __future__ import annotations

from hub.app.parsers._excel import cell_num, cell_str, load_xlsx

# The distinctive stocktake signal is the Chinese physical-count column (实盘 /
# 實盤). NOT the generic Vietnamese "thực đếm" — that's what our own clean
# template uses, which system_template should own. A pure-Vietnamese stocktake
# falls to system_template's generic alias parse; kiem_ke targets the DKE-style
# bilingual multi-warehouse export.
_PHYSICAL_MARKERS = ("实盘", "實盤")


def _find_col(cells: list[str], *needles: str) -> int | None:
    for i, c in enumerate(cells):
        low = (c or "").lower()
        if any(n in low for n in needles):
            return i
    return None


def _header_row(ws) -> tuple[int, list[str]] | None:
    """Header row = the one carrying the physical-count column + a code column."""
    for idx, row in enumerate(ws.iter_rows(min_row=1, max_row=12, values_only=True),
                              start=1):
        cells = [("" if c is None else str(c)).strip() for c in row]
        joined = " ".join(cells).lower()
        if any(m.lower() in joined for m in _PHYSICAL_MARKERS) and \
           ("物料编码" in joined or "物料編碼" in joined or "mã" in joined):
            return idx, cells
    return None


class KiemKeMultiKhoAdapter:
    name = "kiem_ke_multi_kho"
    label_key = "inventory.adapter.kiem_ke_multi_kho.label"
    description_key = "inventory.adapter.kiem_ke_multi_kho.desc"
    supports_mapping_override = False

    def detect(self, blob: bytes) -> float | None:
        try:
            wb = load_xlsx(blob)
        except Exception:
            return None
        for ws in wb.worksheets:
            if _header_row(ws) is not None:
                # Outranks system_template (0.9) so a stocktake gets its own
                # provenance label rather than the generic template name.
                return 0.93
        return None

    def parse(self, blob: bytes, *,
              mapping_override: dict[str, str] | None = None) -> list[dict]:
        from hub.app.parsers.inventory_adapters import InventoryParseError
        try:
            wb = load_xlsx(blob)
        except Exception as e:
            raise InventoryParseError(f"Cannot open workbook: {e}") from e

        lines: list[dict] = []
        for ws in wb.worksheets:
            hdr = _header_row(ws)
            if hdr is None:
                continue
            header_idx, cells = hdr
            col_code = _find_col(cells, "物料编码", "物料編碼", "mã")
            col_name = _find_col(cells, "物料名称", "物料名稱", "tên")
            col_uom = _find_col(cells, "库存主单位", "庫存主單位", "đvt", "đơn vị")
            col_batch = _find_col(cells, "批号", "批號", "lô")
            col_book = _find_col(cells, "số lượng tồn kho", "库存量", "庫存量",
                                 "sổ sách", "hệ thống")
            col_phys = _find_col(cells, "实盘", "實盤", "thực đếm", "kiểm kê")
            if col_code is None:
                continue
            for raw in ws.iter_rows(min_row=header_idx + 1, values_only=True):
                code = cell_str(raw, col_code)
                if not code:
                    continue
                lines.append({
                    "code": code,
                    "name": cell_str(raw, col_name),
                    "uom": cell_str(raw, col_uom),
                    "warehouse": ws.title or None,
                    "batch": cell_str(raw, col_batch),
                    "qty_book": cell_num(raw, col_book),
                    "qty_physical": cell_num(raw, col_phys),
                    "note": None,
                })
        if not lines:
            raise InventoryParseError("No stocktake rows recognized.")
        return lines
