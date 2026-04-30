"""Shared Excel-loading helpers."""
from __future__ import annotations

import io
from typing import Iterator

from openpyxl import load_workbook


def load_xlsx(blob: bytes):
    return load_workbook(filename=io.BytesIO(blob), data_only=True, read_only=True)


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
    """Map logical field names to column indices using fuzzy alias match."""
    norm = [normalize_header(h) for h in headers]
    found: dict[str, int] = {}
    for field, alts in aliases.items():
        for alt in alts:
            target = normalize_header(alt)
            for i, h in enumerate(norm):
                if h == target or target in h:
                    found[field] = i
                    break
            if field in found:
                break
    return found


def iter_data_rows(ws, header_row_idx: int) -> Iterator[tuple]:
    for row in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
        if all(c is None or (isinstance(c, str) and not c.strip()) for c in row):
            continue
        yield row
