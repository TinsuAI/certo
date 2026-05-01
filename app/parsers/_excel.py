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


def header_row(ws, max_scan: int = 15, min_non_empty: int = 2) -> tuple[int, list[str]] | None:
    """Find the first row containing several non-empty string cells. Returns (row_index, headers)."""
    best: tuple[int, list[str]] | None = None
    for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=max_scan, values_only=True), start=1):
        cells = [str(c).strip() if c is not None else "" for c in row]
        n_non_empty = sum(1 for c in cells if c)
        if n_non_empty >= min_non_empty and (best is None or n_non_empty > sum(1 for c in best[1] if c)):
            best = (r_idx, cells)
    return best


def normalize_header(s: str) -> str:
    s = s.strip().lower()
    s = "".join(ch if ch.isalnum() or ch == " " else " " for ch in s)
    return " ".join(s.split())


def index_headers(headers: list[str], aliases: dict[str, list[str]]) -> dict[str, int]:
    """Map logical field names to column indices.

    Two-pass with column claiming: exact matches first (high specificity),
    then substring matches as fallback. Once a field claims a column, no
    other field can match it. Prevents bare aliases ('mã') from shadowing
    longer ones ('mã nội bộ') when both are present, and avoids the
    'staff-added internal-code column accidentally read as customs_code'
    case where two fields would otherwise resolve to the same column.
    """
    norm = [normalize_header(h) for h in headers]
    found: dict[str, int] = {}
    claimed: set[int] = set()

    def _claim(field: str, idx: int) -> None:
        found[field] = idx
        claimed.add(idx)

    # Pass 1: exact match (highest specificity).
    for field, alts in aliases.items():
        if field in found:
            continue
        for alt in alts:
            target = normalize_header(alt)
            for i, h in enumerate(norm):
                if i in claimed:
                    continue
                if h == target:
                    _claim(field, i)
                    break
            if field in found:
                break

    # Pass 2: substring match — only on columns not already claimed.
    for field, alts in aliases.items():
        if field in found:
            continue
        for alt in alts:
            target = normalize_header(alt)
            for i, h in enumerate(norm):
                if i in claimed:
                    continue
                if target in h or h in target:
                    _claim(field, i)
                    break
            if field in found:
                break

    return found


def iter_data_rows(ws, header_row_idx: int) -> Iterator[tuple]:
    for row in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
        if all(c is None or (isinstance(c, str) and not c.strip()) for c in row):
            continue
        yield row


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
