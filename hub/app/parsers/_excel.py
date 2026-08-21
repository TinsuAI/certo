"""Shared Excel-loading helpers.

Loads both modern OOXML (`.xlsx`, `.xlsm` — via openpyxl) and legacy OLE
(`.xls` — via xlrd 2.x) workbooks. Dispatch is by magic bytes so callers
don't need to know the format — every parser just calls `load_workbook`.
"""
from __future__ import annotations

import io
from typing import Iterator

import xlrd
from openpyxl import load_workbook as _openpyxl_load_workbook

OOXML_MAGIC = b"PK"               # zip-based: .xlsx / .xlsm
OLE_MAGIC = b"\xD0\xCF\x11\xE0"   # OLE2 compound: .xls


def load_xlsx(blob: bytes):
    """Load any supported Excel format. Name kept for caller compatibility."""
    if blob.startswith(OLE_MAGIC):
        return _XlsBook(blob)
    return _openpyxl_load_workbook(filename=io.BytesIO(blob), data_only=True, read_only=True)


class _XlsBook:
    """Adapter exposing the openpyxl Workbook API surface used by parsers."""

    def __init__(self, blob: bytes):
        self._book = xlrd.open_workbook(file_contents=blob, on_demand=False)

    @property
    def worksheets(self):
        return [_XlsSheet(self._book.sheet_by_index(i), self._book.datemode)
                for i in range(self._book.nsheets)]


class _XlsSheet:
    def __init__(self, sheet, datemode: int):
        self.title = sheet.name
        self._sheet = sheet
        self._datemode = datemode

    def iter_rows(self, min_row: int = 1, max_row: int | None = None,
                  values_only: bool = True):
        nrows = self._sheet.nrows
        end = nrows if max_row is None else min(max_row, nrows)
        for r in range(min_row - 1, end):
            yield tuple(self._cell(r, c) for c in range(self._sheet.ncols))

    def _cell(self, r: int, c: int):
        ct = self._sheet.cell_type(r, c)
        v = self._sheet.cell_value(r, c)
        if ct == xlrd.XL_CELL_EMPTY or ct == xlrd.XL_CELL_BLANK:
            return None
        if ct == xlrd.XL_CELL_DATE:
            try:
                return xlrd.xldate.xldate_as_datetime(v, self._datemode)
            except Exception:
                return v
        if ct == xlrd.XL_CELL_BOOLEAN:
            return bool(v)
        if ct == xlrd.XL_CELL_ERROR:
            return None
        return v


def header_row(
    ws,
    *,
    aliases: dict[str, list[str]] | None = None,
    max_scan: int = 15,
    min_non_empty: int = 2,
    min_alias_matches: int = 2,
) -> tuple[int, list[str]] | None:
    """Find the header row in a worksheet. Returns (row_index, cells).

    Two-stage detection:
    1. If `aliases` provided: try every candidate row, score by how many
       logical fields the row's cells resolve via `index_headers`. The row
       with the most matches wins (≥ `min_alias_matches`); earliest row
       breaks ties. This protects against the "STT data row beats header
       row by raw non-empty count" pitfall: a data row scores 0 alias
       matches no matter how many cells are populated.
    2. Fallback (no aliases, or no row reaches the threshold): classic
       non-empty count, earliest row tie-break. Backwards-compatible with
       callers that don't pass aliases yet.

    `min_alias_matches=2` filters out incidental 1-match noise (e.g., a
    legend/label row containing just "Mã NPL: see column B").
    """
    candidates: list[tuple[int, list[str]]] = []
    for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=max_scan, values_only=True), start=1):
        cells = [str(c).strip() if c is not None else "" for c in row]
        n_non_empty = sum(1 for c in cells if c)
        if n_non_empty >= min_non_empty:
            candidates.append((r_idx, cells))

    if not candidates:
        return None

    if aliases:
        best_match_count = 0
        best: tuple[int, list[str]] | None = None
        for r_idx, cells in candidates:
            matches = len(index_headers(cells, aliases))
            if matches > best_match_count:
                best_match_count = matches
                best = (r_idx, cells)
            # Tie: keep earliest (already first-seen, do nothing).
        if best is not None and best_match_count >= min_alias_matches:
            return best

    # Fallback: pick the row with the most non-empty cells; earliest wins on tie.
    best = candidates[0]
    best_count = sum(1 for c in best[1] if c)
    for r_idx, cells in candidates[1:]:
        n = sum(1 for c in cells if c)
        if n > best_count:
            best = (r_idx, cells)
            best_count = n
    return best


def normalize_header(s: str) -> str:
    s = s.strip().lower()
    s = "".join(ch if ch.isalnum() or ch == " " else " " for ch in s)
    return " ".join(s.split())


def index_headers(headers: list[str], aliases: dict[str, list[str]]) -> dict[str, int]:
    """Map logical field names to column indices via curated alias exact match.

    Each field claims at most one column; once a column is claimed it is not
    available to other fields. This prevents bare aliases ('mã') from
    shadowing longer ones ('mã nội bộ') when both happen to be in scope.

    Substring matching is intentionally not supported — aliases must be
    enumerated explicitly. Past substring fallback caused (a) silent
    corruption when an empty header cell '' substring-matched any alias
    target ('' in 'mã' is True), and (b) wrong-column claims when a short
    alias like 'hq' substring-matched unrelated headers like 'shq' or
    'hq date'. Adding a new header variant is a 1-line append to the
    relevant ALIASES list.
    """
    norm = [normalize_header(h) for h in headers]
    found: dict[str, int] = {}
    claimed: set[int] = set()

    for field, alts in aliases.items():
        if field in found:
            continue
        for alt in alts:
            target = normalize_header(alt)
            if not target:
                continue
            for i, h in enumerate(norm):
                if i in claimed or not h:
                    continue
                if h == target:
                    found[field] = i
                    claimed.add(i)
                    break
            if field in found:
                break

    return found


def iter_data_rows(ws, header_row_idx: int) -> Iterator[tuple]:
    for row in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
        if all(c is None or (isinstance(c, str) and not c.strip()) for c in row):
            continue
        yield row


def cell_str(row, idx) -> str | None:
    """Read a cell as a stripped string, coercing integer-valued floats
    back to int first.

    openpyxl returns numeric Excel cells as float, so the naive
    `str(v)` flow leaks `'308449399330.0'` for what is conceptually a
    text-of-number identifier (declaration_no, line_no, tax_code, etc.).
    Real decimal values like `1.5` survive untouched because
    `(1.5).is_integer()` is False.

    Every BCCT/Materials/CodeMappings/BOM parser MUST go through this
    helper for string fields — see migration 024 / 025 for the cleanup
    that was needed when individual parsers had their own `str(v)`
    copies and drifted out of sync.
    """
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s or None


def cell_num(row, idx) -> float | None:
    """Read a cell as a float. Empty / unparseable returns None."""
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_file_signature(
    *, client_id: str, module: str, headers_per_sheet: list[list[str]],
) -> str:
    """Stable hash for a workbook's structural shape.

    Used to cache LLM-proposed parser mappings under
    `hub.parser_mappings(client_id, module, file_signature)`. Includes
    `client_id` + `module` to avoid cross-client cache poisoning even if
    two agencies happen to have lexically-similar headers.

    Headers are normalized (lowercase, single-space) and sorted within
    each sheet (so column-order changes don't invalidate the cache).
    Sheets in the same order as the workbook (so reordering sheets DOES
    invalidate, since shape is different).
    """
    import hashlib

    parts: list[str] = [f"client={client_id}", f"module={module}"]
    for sheet_idx, headers in enumerate(headers_per_sheet):
        normalized = sorted(normalize_header(h) for h in headers if h)
        parts.append(f"sheet{sheet_idx}={'|'.join(normalized)}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
