"""Parser for Materials (Danh Mục NVL/SP/BTP) Excel uploads.

Flexible-intake contract (Slice 1 of unified upload flow):

    parse_materials_workbook(
        blob, *,
        mapping_override=None,        # dict[header_text, logical_field]
        header_row_override=None,     # 1-indexed row number on the first sheet
        extra_required_fields=None,   # list[str] in addition to identifier rule
        default_category="nvl",
    ) -> tuple[list[dict], list[dict]]

Returns `(rows, skipped_rows)`:

  - `rows[]`: parsed material records ready for ingest.
  - `skipped_rows[]`: rows that were rejected at parse time, each carrying
    `{"row_index": int, "reason": "missing_required:<field>", "raw": {...}}`.
    The preview UI surfaces these so staff can inline-edit + include or
    leave skipped. The source XLSX is never mutated.

`MIN_IDENTIFIER_FIELDS` is the public minimum: at least one of these
logical fields must be mapped to a real column AND non-empty per row.
The route layer reads this when validating the mapping form.
"""
from __future__ import annotations

from app.parsers._excel import (
    cell_str,
    header_row,
    index_headers,
    iter_data_rows,
    load_xlsx,
)


class MaterialsParseError(RuntimeError):
    pass


CATEGORY_MAP = {
    "nvl": "nvl", "nguyen vat lieu": "nvl", "nguyên vật liệu": "nvl",
    "raw material": "nvl", "raw": "nvl",
    "tp": "tp", "thanh pham": "tp", "thành phẩm": "tp", "finished": "tp",
    "btp_sx": "btp_sx", "btp sx": "btp_sx", "ban thanh pham sx": "btp_sx",
    "btp self": "btp_sx", "self produced": "btp_sx",
    "btp_nm": "btp_nm", "btp nm": "btp_nm", "btp nhap mua": "btp_nm",
    "purchased btp": "btp_nm",
    "ccdc": "ccdc", "cong cu dung cu": "ccdc", "công cụ dụng cụ": "ccdc",
    "tool": "ccdc",
}

ALIASES = {
    "customs_code": ["mã hq", "mã hải quan", "ma hq", "ma hai quan",
                     "customs code", "customs_code",
                     "mã"],   # fallback: bare 'Mã' in single-id Danh Mục files
    "internal_code": ["mã nội bộ", "ma noi bo", "mã nb", "internal code",
                      "internal_code", "product code", "product_code"],
    "name": ["tên", "ten", "name", "tên hàng", "ten hang", "description"],
    "category": ["loại", "loai", "category", "type", "phân loại", "phan loai"],
    "unit": ["đvt", "dvt", "unit", "đơn vị tính"],
    "hs_code": ["hs", "hs code", "mã hs", "ma hs", "hs_code"],
    "status": ["trạng thái", "trang thai", "status"],
}

# At-least-one-of these must resolve to a non-empty cell on every kept row.
# Public so the route + UI form validator can read the same source of truth.
MIN_IDENTIFIER_FIELDS = frozenset({"customs_code", "internal_code"})

# Logical fields the parser knows about. The mapping page lets staff pick
# from this set (plus "ignore") for each column.
LOGICAL_FIELDS = (
    "customs_code", "internal_code", "name", "category",
    "unit", "hs_code", "status",
)


def normalize_category(value: str | None) -> str | None:
    if not value:
        return None
    s = str(value).strip().lower()
    if s in CATEGORY_MAP:
        return CATEGORY_MAP[s]
    for k, v in CATEGORY_MAP.items():
        if k in s or s in k:
            return v
    return None


# DB CHECK constraint allows ('active', 'pending', 'discontinued') after
# migration 026. Pending = the agency has the material in the workflow
# but HQ approval is still outstanding; not the same as discontinued (=
# explicitly retired from new declarations). Source files carry
# agency-side lifecycle labels — normalize known VI/EN forms.
STATUS_MAP = {
    "active": "active", "đang dùng": "active", "dang dung": "active",
    "đã duyệt": "active", "da duyet": "active",
    "approved": "active", "in use": "active",
    "discontinued": "discontinued", "ngừng": "discontinued", "ngung": "discontinued",
    "không dùng": "discontinued", "khong dung": "discontinued",
    "inactive": "discontinued",
    "pending": "pending", "chờ duyệt": "pending", "cho duyet": "pending",
    "chờ phê duyệt": "pending", "cho phe duyet": "pending",
}


def normalize_status(value: str | None) -> str:
    if not value:
        return "active"
    s = str(value).strip().lower()
    return STATUS_MAP.get(s, "active")


def _cols_from_override(headers: list[str], override: dict[str, str]) -> dict[str, int]:
    """Resolve mapping override (header_text → logical_field) to column indices.

    `override` is staff-confirmed (or LLM-proposed) and authoritative.
    Headers not present in the workbook are silently dropped from the
    resulting `cols` map so the parser falls back to "field absent" for
    them. Same field claimed twice = first wins (UI prevents this).
    """
    norm_to_idx = {h.strip().lower(): i for i, h in enumerate(headers) if h}
    cols: dict[str, int] = {}
    for header_text, field in override.items():
        if not header_text or not field or field == "ignore":
            continue
        idx = norm_to_idx.get(str(header_text).strip().lower())
        if idx is None:
            continue
        cols.setdefault(field, idx)
    return cols


def parse_materials_workbook(
    blob: bytes,
    *,
    mapping_override: dict[str, str] | None = None,
    header_row_override: int | None = None,
    extra_required_fields: list[str] | None = None,
    default_category: str = "nvl",
) -> tuple[list[dict], list[dict]]:
    """Parse a Danh Mục workbook into (rows, skipped_rows).

    See module docstring for arg semantics.

    Multi-sheet workbooks: the same `mapping_override` / `header_row_override`
    are applied to every sheet (current behaviour: parser iterates sheets
    and applies the same logical-field resolution). If a sheet's column
    set doesn't contain any identifier under the override, it is silently
    skipped — same as today's "no recognizable header" branch.
    """
    try:
        wb = load_xlsx(blob)
    except Exception as e:
        raise MaterialsParseError(f"Cannot open workbook: {e}") from e

    extra_required = list(extra_required_fields or [])
    rows: list[dict] = []
    skipped: list[dict] = []
    any_sheet_had_identifier = False

    for ws in wb.worksheets:
        sheet_default = _category_from_sheet_name(ws.title) or default_category

        # Resolve header row + cell list.
        if header_row_override is not None:
            header_idx, headers = _read_header_at(ws, header_row_override)
            if not headers:
                continue
        else:
            hdr = header_row(ws, aliases=ALIASES)
            if not hdr:
                continue
            header_idx, headers = hdr

        # Resolve column map (override OR rigid alias index).
        if mapping_override:
            cols = _cols_from_override(headers, mapping_override)
        else:
            cols = index_headers(headers, ALIASES)

        # Identifier rule: at least one identifier mapped.
        has_identifier_col = any(
            field in cols for field in MIN_IDENTIFIER_FIELDS
        )
        if not has_identifier_col:
            continue
        any_sheet_had_identifier = True

        for row_idx_1based, row in _iter_data_rows_with_index(ws, header_idx):
            cc = cell_str(row, cols.get("customs_code"))
            ic = cell_str(row, cols.get("internal_code"))
            if not cc and ic:
                cc = ic

            raw_snapshot = _build_raw_snapshot(row, cols, headers)

            # Identifier check: at least one non-empty.
            if not cc and not ic:
                skipped.append({
                    "row_index": row_idx_1based,
                    "sheet": ws.title,
                    "reason": "missing_required:identifier",
                    "raw": raw_snapshot,
                })
                continue

            # Extra required-field check.
            extra_missing = [
                f for f in extra_required
                if not cell_str(row, cols.get(f))
            ]
            if extra_missing:
                skipped.append({
                    "row_index": row_idx_1based,
                    "sheet": ws.title,
                    "reason": "missing_required:" + ",".join(extra_missing),
                    "raw": raw_snapshot,
                })
                continue

            category_raw = cell_str(row, cols.get("category"))
            category = normalize_category(category_raw) or sheet_default
            rows.append({
                "customs_code": cc,
                "internal_code": ic,
                "name": cell_str(row, cols.get("name")),
                "category": category,
                "unit": cell_str(row, cols.get("unit")),
                "hs_code": cell_str(row, cols.get("hs_code")),
                "status": normalize_status(cell_str(row, cols.get("status"))),
            })

    if not any_sheet_had_identifier:
        raise MaterialsParseError(
            "No material rows recognized; need at least one identifier column "
            "(Mã HQ / Mã NB).")

    return rows, skipped


def _read_header_at(ws, row_no_1based: int) -> tuple[int, list[str]]:
    """Read a specific row as the header row (staff-overridden)."""
    cells: list[str] = []
    for r_idx, raw in enumerate(
        ws.iter_rows(min_row=row_no_1based, max_row=row_no_1based, values_only=True),
        start=row_no_1based,
    ):
        cells = [str(c).strip() if c is not None else "" for c in raw]
        return r_idx, cells
    return row_no_1based, cells


def _iter_data_rows_with_index(ws, header_row_idx: int):
    """Yield (1-based row index, row tuple) for non-empty data rows."""
    for offset, row in enumerate(
        ws.iter_rows(min_row=header_row_idx + 1, values_only=True), start=1,
    ):
        if all(c is None or (isinstance(c, str) and not c.strip()) for c in row):
            continue
        yield header_row_idx + offset, row


def _build_raw_snapshot(row, cols: dict[str, int], headers: list[str]) -> dict:
    """Snapshot a row keyed by logical field (mapped) plus 'col_<n>' for
    unmapped cells. The preview UI uses this to render inline-edit inputs
    on each required field for skipped rows."""
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


def _category_from_sheet_name(name: str) -> str | None:
    n = name.lower()
    if "nvl" in n or "raw" in n:
        return "nvl"
    if "btp_sx" in n or "btp sx" in n:
        return "btp_sx"
    if "btp_nm" in n or "btp nm" in n:
        return "btp_nm"
    if "tp" in n or "thanh" in n or "finished" in n:
        return "tp"
    if "ccdc" in n or "tool" in n:
        return "ccdc"
    return None


_cell_str = cell_str  # backward-compat alias for legacy direct imports
