"""Tests for app.parsers.declaration_files."""
from __future__ import annotations

from pathlib import Path

import pytest
import xlwt

from hub.app.parsers.declaration_files import (
    DeclarationFileError,
    extract_declaration_no_from_xls,
    is_supported_filename,
    parse_declaration_file,
    parse_filename,
)


# ── filename parsing ────────────────────────────────────────────────


def test_parse_filename_xls_with_seq_prefix():
    assert parse_filename("00000001_107243749650.xls") == (
        "107243749650", "xls",
    )


def test_parse_filename_xls_with_alphanumeric_prefix():
    assert parse_filename("9004400904_107739780520.xls") == (
        "107739780520", "xls",
    )


def test_parse_filename_xls_with_dashed_prefix():
    assert parse_filename("26SQYAG-008_108067284030.xls") == (
        "108067284030", "xls",
    )


def test_parse_filename_xls_with_long_prefix():
    assert parse_filename("202505150040506_107185157440.xls") == (
        "107185157440", "xls",
    )


def test_parse_filename_xlsx():
    assert parse_filename("XYZ_107243749650.xlsx") == (
        "107243749650", "xls",
    )


def test_parse_filename_pdf():
    assert parse_filename("scan_107243749650.pdf") == (
        "107243749650", "pdf",
    )


def test_parse_filename_with_path_components():
    # Should ignore directory parts.
    assert parse_filename("/some/dir/00000001_107243749650.xls") == (
        "107243749650", "xls",
    )


def test_parse_filename_rejects_no_underscore():
    with pytest.raises(DeclarationFileError):
        parse_filename("107243749650.xls")


def test_parse_filename_rejects_unknown_extension():
    with pytest.raises(DeclarationFileError):
        parse_filename("00000001_107243749650.doc")


def test_parse_filename_rejects_short_number():
    # 9 digits — below minimum 10.
    with pytest.raises(DeclarationFileError):
        parse_filename("foo_123456789.xls")


def test_is_supported_filename():
    assert is_supported_filename("00000001_107243749650.xls")
    assert is_supported_filename("scan_107243749650.pdf")
    assert not is_supported_filename("README.md")
    assert not is_supported_filename(".DS_Store")
    assert not is_supported_filename("107243749650.xls")  # no prefix


# ── XLS content extraction ──────────────────────────────────────────


def _make_xls(cells: dict[tuple[int, int], object]) -> bytes:
    """Build a minimal XLS in memory with given (row, col): value cells."""
    wb = xlwt.Workbook()
    ws = wb.add_sheet("TKN")
    for (r, c), v in cells.items():
        ws.write(r, c, v)
    import io
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_decl_no_single_match():
    content = _make_xls({
        (3, 4): "107185157440",
        (1, 2): "Some other text",
    })
    assert extract_declaration_no_from_xls(content) == "107185157440"


def test_extract_decl_no_from_label_text():
    """Cell value embeds decl number in surrounding text."""
    content = _make_xls({
        (2, 26): "*107185157440*",  # Mirrors actual TKN format.
    })
    assert extract_declaration_no_from_xls(content) == "107185157440"


def test_extract_decl_no_consistent_across_cells():
    """Same number repeated in multiple cells = one candidate."""
    content = _make_xls({
        (3, 4): "107185157440",
        (3, 17): "107185157440  - some suffix",
        (2, 26): "*107185157440*",
    })
    assert extract_declaration_no_from_xls(content) == "107185157440"


def test_extract_decl_no_rejects_when_none_found():
    content = _make_xls({(0, 0): "no numbers here"})
    with pytest.raises(DeclarationFileError, match="no 10-14-digit"):
        extract_declaration_no_from_xls(content)


def test_extract_decl_no_rejects_when_multiple_candidates():
    content = _make_xls({
        (1, 1): "107185157440",
        (2, 2): "108162102860",
    })
    with pytest.raises(DeclarationFileError, match="multiple distinct"):
        extract_declaration_no_from_xls(content)


def test_extract_decl_no_handles_numeric_cell():
    """xlrd returns numbers as float — parser must coerce."""
    content = _make_xls({
        (3, 4): 107185157440,  # Int → stored as float in xls
    })
    assert extract_declaration_no_from_xls(content) == "107185157440"


def test_extract_decl_no_rejects_corrupt_xls():
    with pytest.raises(DeclarationFileError, match="could not open XLS"):
        extract_declaration_no_from_xls(b"not actually an XLS file")


# ── Combined parse + validate ───────────────────────────────────────


def test_parse_declaration_file_xls_match():
    content = _make_xls({(3, 4): "107185157440"})
    info = parse_declaration_file("00000001_107185157440.xls", content)
    assert info.declaration_no == "107185157440"
    assert info.file_kind == "xls"
    assert info.filename_decl == "107185157440"
    assert info.content_decl == "107185157440"


def test_parse_declaration_file_xls_mismatch():
    content = _make_xls({(3, 4): "999999999999"})
    with pytest.raises(DeclarationFileError, match="mismatch"):
        parse_declaration_file("00000001_107185157440.xls", content)


def test_parse_declaration_file_pdf_skips_content_check():
    # PDF content is ignored (OCR deferred). Garbage content accepted.
    info = parse_declaration_file(
        "scan_107185157440.pdf", b"not a real pdf",
    )
    assert info.declaration_no == "107185157440"
    assert info.file_kind == "pdf"
    assert info.content_decl is None


def test_parse_declaration_file_validate_content_false():
    """When validate_content=False, content is not opened."""
    info = parse_declaration_file(
        "00000001_107185157440.xls",
        b"would-fail-if-opened",
        validate_content=False,
    )
    assert info.declaration_no == "107185157440"
    assert info.content_decl is None


# ── Real Johnson sample (smoke; skip if not present) ────────────────


JOHNSON_TKN = Path(__file__).resolve().parent.parent / "data" / "source_inventory" / "johnson-vn" / "2026-05-07-updated" / "Johnson" / "TKN"


@pytest.mark.skipif(not JOHNSON_TKN.exists(), reason="Johnson source data not present")
def test_real_johnson_sample_passes_full_parse():
    sample = JOHNSON_TKN / "202505150040506_107185157440.xls"
    if not sample.exists():
        pytest.skip(f"Sample not present: {sample}")
    info = parse_declaration_file(sample.name, sample.read_bytes())
    assert info.declaration_no == "107185157440"
    assert info.file_kind == "xls"
    assert info.content_decl == "107185157440"
