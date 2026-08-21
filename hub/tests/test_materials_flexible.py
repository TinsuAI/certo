"""Tests for the flexible catalog parser flow (Slice 1).

Covers:
  - mapping_override (manual or LLM-proposed header→logical_field map)
  - header_row_override (banner/legend rows above the real header)
  - skipped_rows[] return shape (missing required cells per row)
  - MIN_IDENTIFIER_FIELDS rule (must map at least one of customs_code /
    internal_code)
  - extra_required_fields override (per-call list of fields that must be
    non-empty for the row to be kept; future hook for per-client config)

The flexible parser returns a tuple `(rows, skipped_rows)` so the
unified `_mapping_flow` helper can surface skipped rows in the preview
without re-running the parser.
"""
from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from app.parsers.materials import (
    MaterialsParseError,
    MIN_IDENTIFIER_FIELDS,
    parse_materials_workbook,
)


def _xlsx(rows: list[tuple], sheet_title: str = "Sheet1") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tuple return contract
# ---------------------------------------------------------------------------

def test_parser_returns_rows_and_skipped_tuple():
    blob = _xlsx([
        ("Mã HQ", "Mã NB", "Tên", "Loại"),
        ("PE-001", "PE-001", "PE", "nvl"),
    ])
    result = parse_materials_workbook(blob)
    assert isinstance(result, tuple)
    assert len(result) == 2
    rows, skipped = result
    assert len(rows) == 1
    assert skipped == []


def test_parser_clean_input_yields_no_skipped():
    blob = _xlsx([
        ("Mã HQ", "Tên"),
        ("A-1", "A"),
        ("A-2", "B"),
    ])
    rows, skipped = parse_materials_workbook(blob)
    assert len(rows) == 2
    assert skipped == []


# ---------------------------------------------------------------------------
# mapping_override
# ---------------------------------------------------------------------------

def test_mapping_override_with_unknown_headers():
    """Header names parser does NOT auto-recognize ('MaSP', 'TenSP') —
    staff-confirmed mapping_override must drive parsing."""
    blob = _xlsx([
        ("MaSP", "TenSP", "DonVi"),
        ("FOO-1", "Foo widget", "kg"),
        ("FOO-2", "Bar widget", "pcs"),
    ])
    mapping = {"MaSP": "internal_code", "TenSP": "name", "DonVi": "unit"}
    rows, skipped = parse_materials_workbook(blob, mapping_override=mapping)
    assert len(rows) == 2
    assert rows[0]["internal_code"] == "FOO-1"
    # parser auto-promotes internal_code → customs_code when only one
    # identifier present (existing behaviour preserved)
    assert rows[0]["customs_code"] == "FOO-1"
    assert rows[0]["name"] == "Foo widget"
    assert rows[0]["unit"] == "kg"
    assert skipped == []


def test_mapping_override_ignores_unmapped_columns():
    blob = _xlsx([
        ("Code", "Notes", "Name"),
        ("X-1", "ignore me", "Alpha"),
    ])
    mapping = {"Code": "internal_code", "Name": "name"}
    rows, skipped = parse_materials_workbook(blob, mapping_override=mapping)
    assert len(rows) == 1
    assert rows[0]["internal_code"] == "X-1"
    assert rows[0]["name"] == "Alpha"
    assert skipped == []


def test_mapping_override_must_include_an_identifier():
    """If override maps zero identifier columns, the parser raises —
    UI form-validation should also block this earlier, but defence in depth."""
    blob = _xlsx([
        ("Code", "Name"),
        ("X-1", "Alpha"),
    ])
    mapping = {"Name": "name"}  # no identifier mapped at all
    with pytest.raises(MaterialsParseError):
        parse_materials_workbook(blob, mapping_override=mapping)


def test_min_identifier_fields_constant_exposed():
    """Public constant so the route layer + UI form validator can read
    the same source of truth."""
    assert "customs_code" in MIN_IDENTIFIER_FIELDS
    assert "internal_code" in MIN_IDENTIFIER_FIELDS


# ---------------------------------------------------------------------------
# header_row_override
# ---------------------------------------------------------------------------

def test_header_row_override_when_banner_above_real_header():
    blob = _xlsx([
        ("BÁO CÁO DANH MỤC NVL", "", "", ""),  # banner row 1
        ("Công ty XYZ", "", "", ""),            # banner row 2
        ("", "", "", ""),                        # blank row 3
        ("Mã HQ", "Tên", "Loại", "ĐVT"),         # real header row 4
        ("PE-001", "PE", "nvl", "kg"),
    ])
    rows, skipped = parse_materials_workbook(blob, header_row_override=4)
    assert len(rows) == 1
    assert rows[0]["customs_code"] == "PE-001"


def test_header_row_override_with_mapping_override():
    """Both overrides applied together — header pick + non-standard names."""
    blob = _xlsx([
        ("Sheet legend", "", "", ""),
        ("MaSP", "TenSP", "DonVi", "Loai"),
        ("X-1", "Alpha", "kg", "nvl"),
    ])
    mapping = {
        "MaSP": "internal_code",
        "TenSP": "name",
        "DonVi": "unit",
        "Loai": "category",
    }
    rows, skipped = parse_materials_workbook(
        blob, header_row_override=2, mapping_override=mapping,
    )
    assert len(rows) == 1
    assert rows[0]["internal_code"] == "X-1"
    assert rows[0]["unit"] == "kg"
    assert rows[0]["category"] == "nvl"


# ---------------------------------------------------------------------------
# skipped_rows[]
# ---------------------------------------------------------------------------

def test_row_missing_identifier_goes_to_skipped():
    """A row where every identifier column is empty is now SKIPPED with
    reason, not silently dropped (current behaviour silently `continue`s)."""
    blob = _xlsx([
        ("Mã HQ", "Mã NB", "Tên"),
        ("A-1", "A-1", "ok"),
        ("", "", "no identifier"),
        ("B-1", "B-1", "also ok"),
    ])
    rows, skipped = parse_materials_workbook(blob)
    assert {r["customs_code"] for r in rows} == {"A-1", "B-1"}
    assert len(skipped) == 1
    assert skipped[0]["reason"].startswith("missing_required:")
    # raw cells preserved for the preview UI to render
    assert skipped[0]["row_index"] >= 1
    assert "raw" in skipped[0]


def test_extra_required_fields_skips_rows_missing_unit():
    blob = _xlsx([
        ("Mã HQ", "Tên", "ĐVT"),
        ("A-1", "alpha", "kg"),
        ("B-1", "beta", ""),    # missing unit
        ("C-1", "gamma", "pcs"),
    ])
    rows, skipped = parse_materials_workbook(
        blob, extra_required_fields=["unit"],
    )
    kept = {r["customs_code"] for r in rows}
    assert kept == {"A-1", "C-1"}
    assert len(skipped) == 1
    assert skipped[0]["raw"]  # snapshot present for inline-edit
    assert "unit" in skipped[0]["reason"]


def test_skipped_row_carries_raw_cells_dict_for_inline_edit():
    """Preview UI inline-edits empty cells. Raw snapshot must be a
    dict keyed by logical field (or 'col_<n>' for unmapped) so the
    template can render an <input> per required field."""
    blob = _xlsx([
        ("Mã HQ", "Tên", "ĐVT"),
        ("A-1", "alpha", ""),
    ])
    rows, skipped = parse_materials_workbook(
        blob, extra_required_fields=["unit"],
    )
    assert len(skipped) == 1
    raw = skipped[0]["raw"]
    assert isinstance(raw, dict)
    assert raw.get("customs_code") == "A-1"
    assert raw.get("name") == "alpha"
    # unit is empty in source → key may be missing or None; both acceptable
    assert raw.get("unit") in (None, "")


# ---------------------------------------------------------------------------
# Backwards-compat: existing rigid behaviour still works
# ---------------------------------------------------------------------------

def test_back_compat_no_overrides_matches_today():
    """Without overrides, parser still finds Mã HQ / Mã NB / Tên / Loại
    via the static ALIASES dict."""
    blob = _xlsx([
        ("Mã HQ", "Mã NB", "Tên", "Loại", "ĐVT", "HS"),
        ("PE-001", "PE-001", "Polyethylene", "nvl", "kg", "39011010"),
    ])
    rows, skipped = parse_materials_workbook(blob)
    assert len(rows) == 1
    assert rows[0]["customs_code"] == "PE-001"
    assert rows[0]["category"] == "nvl"
    assert skipped == []


def test_back_compat_no_id_at_all_still_raises():
    """Workbook with zero identifier columns (rigid) still raises."""
    blob = _xlsx([("Random", "Junk"), ("a", "b")])
    with pytest.raises(MaterialsParseError):
        parse_materials_workbook(blob)
