"""Parser for code-mapping (BQD = Bảng Quy Đổi) Excel uploads.

Slice 2 of the unified upload flow — signature aligned with materials:

    parse_code_mappings_workbook(
        blob, *,
        mapping_override=None,        # dict[header_text, logical_field]
        header_row_override=None,     # 1-indexed row number on the first sheet
        extra_required_fields=None,   # list[str] in addition to identifier rule
    ) -> tuple[list[dict], list[dict]]

BQD requires BOTH `internal_code` AND `customs_code` per row — neither
is enough alone (it's a join table). Rows missing either go into
`skipped_rows[]` with reason="missing_required:<field>" and the preview
UI surfaces them with inline-edit affordance.
"""
from __future__ import annotations

from hub.app.parsers._excel import (
    cell_str,
    header_row,
    index_headers,
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

# BQD must always have both id columns mapped — it's a join table.
REQUIRED_MAPPED_FIELDS = frozenset({"internal_code", "customs_code"})

# `min_identifier_fields` semantic for the helper: at-least-one. BQD
# requires both, so this contains both — combined with REQUIRED_MAPPED_FIELDS
# the form validation accepts only when both map to a real column.
MIN_IDENTIFIER_FIELDS = frozenset({"internal_code"})

LOGICAL_FIELDS = ("internal_code", "customs_code", "category", "notes")


def _cols_from_override(headers: list[str], override: dict[str, str]) -> dict[str, int]:
    """Convert a header→logical_field override dict into the
    {logical_field: column_index} shape the parser uses.

    Header names compare case-insensitively post-strip; first match wins.
    Override entries with empty / 'ignore' field are dropped.
    """
    cols: dict[str, int] = {}
    norm_to_idx = {(h or "").strip().lower(): i for i, h in enumerate(headers)}
    for header_name, logical_field in override.items():
        if not logical_field or logical_field == "ignore":
            continue
        idx = norm_to_idx.get((header_name or "").strip().lower())
        if idx is not None and logical_field not in cols:
            cols[logical_field] = idx
    return cols


def parse_code_mappings_workbook(
    blob: bytes,
    *,
    mapping_override: dict[str, str] | None = None,
    header_row_override: int | None = None,
    extra_required_fields: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Parse a BQD workbook into (rows, skipped_rows). See module docstring."""
    try:
        wb = load_xlsx(blob)
    except Exception as e:
        raise CodeMappingsParseError(f"Cannot open workbook: {e}") from e

    extra_required = list(extra_required_fields or [])
    rows: list[dict] = []
    skipped: list[dict] = []
    any_sheet_had_both = False

    for ws in wb.worksheets:
        if header_row_override is not None:
            header_idx, headers = _read_header_at(ws, header_row_override)
            if not headers:
                continue
        else:
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
        any_sheet_had_both = True

        sheet_default_cat = _cat_from_sheet(ws.title)
        for row_idx_1based, row in _iter_data_rows_with_index(ws, header_idx):
            ic = cell_str(row, cols.get("internal_code"))
            cc = cell_str(row, cols.get("customs_code"))
            raw = _build_raw_snapshot(row, cols, headers)

            missing: list[str] = []
            if not ic:
                missing.append("internal_code")
            if not cc:
                missing.append("customs_code")
            for f in extra_required:
                if not cell_str(row, cols.get(f)):
                    missing.append(f)
            if missing:
                skipped.append({
                    "row_index": row_idx_1based,
                    "sheet": ws.title,
                    "reason": "missing_required:" + ",".join(missing),
                    "raw": raw,
                })
                continue

            cat = cell_str(row, cols.get("category")) or sheet_default_cat
            rows.append({
                "internal_code": ic,
                "customs_code": cc,
                "category": (cat or "").lower() or None,
                "notes": cell_str(row, cols.get("notes")),
            })

    if not any_sheet_had_both:
        raise CodeMappingsParseError(
            "No mapping rows recognized; expected both 'Mã nội bộ' + 'Mã hải quan' columns."
        )

    return rows, skipped


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
