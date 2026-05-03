"""Parser for code-mapping (BQD = Bảng Quy Đổi) Excel uploads."""
from __future__ import annotations

from app.parsers._excel import (
    cell_str,
    header_row,
    index_headers,
    iter_data_rows,
    load_xlsx,
)


class CodeMappingsParseError(RuntimeError):
    pass


ALIASES = {
    "internal_code": ["mã nội bộ", "ma noi bo", "internal code", "mã nb", "ma nb",
                      "internal_code", "nb",
                      "mã erp", "ma erp"],          # DKE: ERP system identifier
    "customs_code": ["mã hải quan", "mã hq", "ma hai quan", "ma hq",
                     "customs code", "customs_code", "hq",
                     "mã npl tp", "mã npl/tp",      # DKE: customs-registered NPL/TP code
                     "ma npl tp", "ma npl/tp"],
    "category": ["loại", "loai", "category"],
    "notes": ["ghi chú", "ghi chu", "notes", "remark"],
}


def parse_code_mappings_workbook(
    blob: bytes,
    *,
    mapping_override: dict[str, str] | None = None,
) -> list[dict]:
    """Parse a BQD workbook.

    `mapping_override`: optional dict[header_name → logical_field] from a
    confirmed LLM proposal (cached via `hub.parser_mappings`). Bypasses
    alias matching when present.
    """
    try:
        wb = load_xlsx(blob)
    except Exception as e:
        raise CodeMappingsParseError(f"Cannot open workbook: {e}") from e
    rows: list[dict] = []
    for ws in wb.worksheets:
        hdr = header_row(ws, aliases=ALIASES)
        if not hdr:
            continue
        header_idx, headers = hdr
        if mapping_override:
            cols = _cols_from_override(headers, mapping_override)
        else:
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


def _cols_from_override(headers: list[str], override: dict[str, str]) -> dict[str, int]:
    """Convert a header→logical_field override dict into the
    {logical_field: column_index} shape that the parser uses.

    Header names compare case-insensitively post-strip; first match wins.
    """
    cols: dict[str, int] = {}
    norm_to_idx = {(h or "").strip().lower(): i for i, h in enumerate(headers)}
    for header_name, logical_field in override.items():
        idx = norm_to_idx.get((header_name or "").strip().lower())
        if idx is not None and logical_field not in cols:
            cols[logical_field] = idx
    return cols


def _cat_from_sheet(name: str) -> str | None:
    """Heuristic: map sheet name → category. BTP must be checked before TP
    because 'tp' is a substring of 'btp' (Bug D)."""
    n = name.lower()
    if "nvl" in n:
        return "nvl"
    if "btp" in n:
        return "btp"
    if "tp" in n:
        return "tp"
    if "ccdc" in n or "tool" in n:
        return "ccdc"
    return None


_cell_str = cell_str  # backward-compat alias
