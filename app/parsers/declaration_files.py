"""Parse customs declaration form files (TKN/TKX XLS, scan PDF).

Extracts declaration number from filename + optionally cross-validates
against XLS cell content. Scope: metadata only — file content is NOT
ingested into Data Hub DB. Files live in FileBackend storage; this
parser produces metadata for `hub.customs_declaration_files`.

See `.ai/features/2026-05-10-johnson-onboarding/brief.md` Feature 6.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

import openpyxl
import xlrd


_FILENAME_RE = re.compile(
    r"^(?P<prefix>.*?)_(?P<num>\d{10,14})\.(?P<ext>xlsx?|pdf)$",
    re.IGNORECASE,
)
_DECL_NO_RE = re.compile(r"\b(\d{10,14})\b")

# How far into the XLS we scan for the declaration number cell. Form
# files have it in the first ~10 rows × first ~30 cols of the main sheet.
_SCAN_ROWS = 25
_SCAN_COLS = 32


@dataclass(frozen=True)
class DeclarationFileInfo:
    """Result of parsing a declaration file's metadata."""
    declaration_no: str
    file_kind: str       # 'xls' | 'pdf'
    filename_decl: str   # decl_no extracted from filename
    content_decl: str | None  # decl_no extracted from content (None for PDF)


class DeclarationFileError(Exception):
    """Raised when a file's metadata cannot be parsed or validated."""


def parse_filename(filename: str) -> tuple[str, str]:
    """Extract `(declaration_no, file_kind)` from filename pattern
    `<prefix>_<digits>.<ext>`.

    `file_kind` is `'xls'` for `.xls`/`.xlsx` and `'pdf'` for `.pdf`.

    Raises DeclarationFileError on unmatched pattern.
    """
    m = _FILENAME_RE.match(Path(filename).name)
    if not m:
        raise DeclarationFileError(
            f"filename does not match expected pattern "
            f"`<prefix>_<digits>.(xls|xlsx|pdf)`: {filename!r}",
        )
    ext = m.group("ext").lower()
    kind = "pdf" if ext == "pdf" else "xls"
    return m.group("num"), kind


def extract_declaration_no_from_xls(content: bytes) -> str:
    """Find the declaration number in the first sheet of an XLS form.

    Scans first ~25 rows × ~32 cols for 10-14-digit numbers. Picks the
    one with the most occurrences (declaration_no appears multiple times
    in the form header; tax code, contract numbers etc appear once).
    Tie-break by longer number (12-digit decl_no over 10-digit tax code).

    Raises DeclarationFileError if zero candidates or all candidates tie
    at one occurrence (ambiguous).
    """
    counts: dict[str, int] = {}
    # XLS (BIFF) → xlrd. XLSX (OOXML) → openpyxl. Try both; xlrd fails
    # loudly on xlsx with a recognizable error so we dispatch by error.
    try:
        wb = xlrd.open_workbook(file_contents=content)
        for sh_idx in range(wb.nsheets):
            sh = wb.sheet_by_index(sh_idx)
            max_row = min(_SCAN_ROWS, sh.nrows)
            max_col = min(_SCAN_COLS, sh.ncols)
            for r in range(max_row):
                for c in range(max_col):
                    v = sh.cell_value(r, c)
                    if not isinstance(v, str):
                        if isinstance(v, float) and v.is_integer():
                            v = str(int(v))
                        else:
                            continue
                    for m in _DECL_NO_RE.finditer(v):
                        n = m.group(1)
                        counts[n] = counts.get(n, 0) + 1
            if counts:
                break
    except xlrd.XLRDError as xlrd_exc:
        if "xlsx" not in str(xlrd_exc).lower():
            raise DeclarationFileError(
                f"could not open XLS: {type(xlrd_exc).__name__}: {xlrd_exc}",
            ) from xlrd_exc
        # Fall through to openpyxl for .xlsx files.
        try:
            wb = openpyxl.load_workbook(
                io.BytesIO(content), read_only=True, data_only=True,
            )
        except Exception as exc:
            raise DeclarationFileError(
                f"could not open XLSX: {type(exc).__name__}: {exc}",
            ) from exc
        for sh in wb.worksheets:
            for r_idx, row in enumerate(sh.iter_rows(values_only=True)):
                if r_idx >= _SCAN_ROWS:
                    break
                for c_idx, v in enumerate(row):
                    if c_idx >= _SCAN_COLS:
                        break
                    if v is None:
                        continue
                    if isinstance(v, (int, float)):
                        if isinstance(v, float) and not v.is_integer():
                            continue
                        v = str(int(v))
                    elif not isinstance(v, str):
                        continue
                    for m in _DECL_NO_RE.finditer(v):
                        n = m.group(1)
                        counts[n] = counts.get(n, 0) + 1
            if counts:
                break
        wb.close()
    except Exception as exc:
        raise DeclarationFileError(
            f"could not open file: {type(exc).__name__}: {exc}",
        ) from exc

    if not counts:
        raise DeclarationFileError(
            "no 10-14-digit declaration number found in first "
            f"{_SCAN_ROWS}×{_SCAN_COLS} cells",
        )

    # Sort: most-frequent first, then longest number, then lex smallest.
    ranked = sorted(
        counts.items(),
        key=lambda kv: (-kv[1], -len(kv[0]), kv[0]),
    )
    top, top_count = ranked[0]
    # Ambiguous if all candidates tie at 1 occurrence and there are 2+.
    if top_count == 1 and len(ranked) > 1:
        raise DeclarationFileError(
            "multiple distinct declaration number candidates with no "
            f"clear winner (each occurs once): "
            f"{[c[0] for c in ranked]}",
        )
    return top


def parse_declaration_file(
    filename: str, content: bytes, *, validate_content: bool = True,
) -> DeclarationFileInfo:
    """Parse and (for XLS) cross-validate a declaration file.

    Always extracts declaration_no from filename. For XLS files when
    `validate_content=True`, also reads the number from cell content
    and rejects if it disagrees. PDF files skip content extraction
    (MVP — OCR deferred).
    """
    filename_decl, kind = parse_filename(filename)

    if kind == "pdf" or not validate_content:
        return DeclarationFileInfo(
            declaration_no=filename_decl,
            file_kind=kind,
            filename_decl=filename_decl,
            content_decl=None,
        )

    content_decl = extract_declaration_no_from_xls(content)
    if content_decl != filename_decl:
        raise DeclarationFileError(
            f"declaration number mismatch: filename has {filename_decl!r}, "
            f"XLS content has {content_decl!r}",
        )
    return DeclarationFileInfo(
        declaration_no=filename_decl,
        file_kind=kind,
        filename_decl=filename_decl,
        content_decl=content_decl,
    )


def is_supported_filename(filename: str) -> bool:
    """Quick check without raising — useful when scanning archive
    folders that may include README, .DS_Store, etc."""
    return bool(_FILENAME_RE.match(Path(filename).name))
