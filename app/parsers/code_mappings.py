"""Parser for code-mapping (BQD = Bảng Quy Đổi) Excel uploads."""
from __future__ import annotations

from app.parsers._excel import load_xlsx, header_row, index_headers, iter_data_rows


class CodeMappingsParseError(RuntimeError):
    pass


ALIASES = {
    "internal_code": ["mã nội bộ", "ma noi bo", "internal code", "mã nb", "ma nb",
                      "internal_code", "nb"],
    "customs_code": ["mã hải quan", "mã hq", "ma hai quan", "ma hq",
                     "customs code", "customs_code", "hq"],
    "category": ["loại", "loai", "category"],
    "notes": ["ghi chú", "ghi chu", "notes", "remark"],
}


def parse_code_mappings_workbook(blob: bytes) -> list[dict]:
    try:
        wb = load_xlsx(blob)
    except Exception as e:
        raise CodeMappingsParseError(f"Cannot open workbook: {e}") from e
    rows: list[dict] = []
    for ws in wb.worksheets:
        hdr = header_row(ws)
        if not hdr:
            continue
        header_idx, headers = hdr
        cols = index_headers(headers, ALIASES)
        if "internal_code" not in cols or "customs_code" not in cols:
            continue
        sheet_default_cat = _cat_from_sheet(ws.title)
        for row in iter_data_rows(ws, header_idx):
            ic = _cell_str(row, cols.get("internal_code"))
            cc = _cell_str(row, cols.get("customs_code"))
            if not ic or not cc:
                continue
            cat = _cell_str(row, cols.get("category")) or sheet_default_cat
            rows.append({
                "internal_code": ic,
                "customs_code": cc,
                "category": (cat or "").lower() or None,
                "notes": _cell_str(row, cols.get("notes")),
            })
    if not rows:
        raise CodeMappingsParseError("No mapping rows recognized; expected 'Mã nội bộ' + 'Mã hải quan' columns.")
    return rows


def _cat_from_sheet(name: str) -> str | None:
    n = name.lower()
    if "nvl" in n:
        return "nvl"
    if "tp" in n:
        return "tp"
    if "ccdc" in n or "tool" in n:
        return "ccdc"
    return None


def _cell_str(row, idx) -> str | None:
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    if v is None:
        return None
    s = str(v).strip()
    return s or None
