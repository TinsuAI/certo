"""Converter: agency trừ-lùi workbook → standard CO stock template.

Pure tests (file-mode) — the converter does not touch the DB. Ingest is the
operator's separate step via the existing "Import tồn CO" upload.
"""
from __future__ import annotations

from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import Workbook

from app.co_stock_ledger import apply_used_qty
from app.co_stock_template import read_standard_co_stock, write_standard_co_stock
from app.co_stock_workbook import (
    CoStockWorkbookError,
    convert_to_standard_template,
    matching_code,
    parse_workbook,
    stock_rows_from_standard,
)
from app.database import database_url

_GROWATT_CFG = {"allocation_code": {"strategy": "description_regex",
                                    "description_regex": r"\(([A-Z0-9][A-Z0-9._/-]{3,})\)",
                                    "fallback": "same_as_customs_code"}}
_JOHNSON_CFG = {"allocation_code": {"strategy": "same_as_customs_code",
                                    "description_regex": r"\(([A-Z0-9][A-Z0-9._/-]{3,})\)",
                                    "fallback": "same_as_customs_code"}}


def _nk2_workbook(rows: list[dict]) -> bytes:
    """Agency NK2 layout: 3 preamble rows + header row 4 + data row 5."""
    wb = Workbook()
    ws = wb.active
    ws.title = "NK2"
    for _ in range(3):
        ws.append([None] * 22)
    ws.append([
        "Số TK", "Ngày ĐK", "Mã loại hình", "STT hàng", "Mã NPL/SP",
        "Mã HS", "Tên hàng", "Xuất xứ", "Đơn giá", "Đơn giá tính thuế",
        "Tổng số lượng", "Đơn vị tính", "Tên đối tác", "Số hóa đơn", "Ngày hóa đơn",
        "Tỷ giá thanh toán", "Đã xuất", "Tồn", "Check", "TKX",
    ])
    for row in rows:
        ws.append([
            row.get("declaration_no"), row.get("registration_date"), row.get("declaration_type"),
            row.get("line_no"), row.get("customs_code"), row.get("hs_code"), row.get("goods_name"),
            row.get("origin_country"), row.get("unit_price"), row.get("taxable_unit_price"),
            row.get("opening_qty"), row.get("unit"), row.get("partner"), row.get("invoice_no"),
            row.get("invoice_date"), row.get("exchange_rate"), row.get("used_qty"),
            row.get("ton"), None, row.get("transaction_key"),  # idx17 = Tồn (R)
        ])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------- matching_code (lot key = BCCT customs_item_code = name "#&" prefix) ----------

def test_matching_code_growatt_uses_name_prefix_not_npl_column():
    """Growatt: Mã NPL/SP is the dotted internal/BOM code; the system's lot key
    is the category PREFIX ("DIOT"). Must NOT return the NPL column."""
    name = "DIOT#&Đi ốt, 16A/650V, nhà sản xuất Infineon. Hàng mới 100%. (008.0035900)"
    assert matching_code(name, "008.0035900") == "DIOT"


def test_matching_code_johnson_prefix_equals_unified_code():
    assert matching_code("CT#&Camera quan sát DS-2CD2643G2", "CT") == "CT"
    assert matching_code("MOULD-GM111-AC1-03#&Khuôn hàn", "MOULD-GM111-AC1-03") == "MOULD-GM111-AC1-03"


def test_matching_code_ignores_spec_parentheses():
    """Johnson names sometimes have spec parens like (1250A); the prefix, not the
    parenthetical, is the code."""
    assert matching_code("CT#&Tủ điện (đã lắp ráp) PPT-1 (1250A)", "CT") == "CT"


def test_matching_code_falls_back_to_column_without_delimiter():
    assert matching_code("Sơn bột tĩnh điện", "M-A") == "M-A"
    assert matching_code("", "M-B") == "M-B"


# ---------- parse_workbook ----------

def test_parse_keeps_zero_used_lots_by_default():
    content = _nk2_workbook([
        {"declaration_no": "D1", "line_no": "1", "customs_code": "M-A", "opening_qty": 500, "used_qty": 197.631},
        {"declaration_no": "D2", "line_no": "1", "customs_code": "M-Z", "opening_qty": 100, "used_qty": 0},
    ])
    rows, summary = parse_workbook(content, sheet="NK2")
    assert summary["rows_unique"] == 2
    assert summary["rows_skipped_zero_used"] == 0
    by_key = {(r["declaration_no"], r["line_no"], r["customs_code"]): r for r in rows}
    assert ("D2", "1", "M-Z") in by_key


def test_parse_consolidates_duplicate_triplet_summing_used():
    content = _nk2_workbook([
        {"declaration_no": "D1", "line_no": "1", "customs_code": "M-A", "opening_qty": 500, "used_qty": 10},
        {"declaration_no": "D1", "line_no": "1", "customs_code": "M-A", "opening_qty": 500, "used_qty": 25},
    ])
    rows, summary = parse_workbook(content, sheet="NK2")
    assert summary["rows_unique"] == 1
    assert rows[0]["used_qty"] == Decimal("35")


def test_parse_drops_rows_missing_triplet():
    content = _nk2_workbook([
        {"declaration_no": "D1", "line_no": "1", "customs_code": "M-A", "opening_qty": 100, "used_qty": 5},
        {"declaration_no": "", "line_no": "", "customs_code": "", "used_qty": 99},
    ])
    rows, summary = parse_workbook(content, sheet="NK2")
    assert summary["rows_unique"] == 1
    assert summary["rows_dropped"] == 1
    assert "thiếu declaration_no" in summary["dropped"][0]


def test_parse_unknown_sheet_raises():
    content = _nk2_workbook([{"declaration_no": "D1", "line_no": "1", "customs_code": "M-A", "opening_qty": 1, "used_qty": 1}])
    with pytest.raises(CoStockWorkbookError):
        parse_workbook(content, sheet="DoesNotExist")


# ---------- convert_to_standard_template (no DB) ----------

def test_convert_growatt_keys_customs_code_on_name_prefix():
    """End-to-end: a Growatt-shaped row (Mã NPL/SP = dotted internal code, name =
    'DIOT#&...') converts to customs_code = 'DIOT' (the BCCT lot key the CO system
    matches on), NOT the dotted code — otherwise the trừ-lùi overlay matches 0 lots."""
    content = _nk2_workbook([
        {"declaration_no": "105263666060", "line_no": "1", "customs_code": "008.0035900",
         "goods_name": "DIOT#&Đi ốt, 16A/650V, nhà sản xuất Infineon (008.0035900)",
         "opening_qty": 500, "unit": "PIECES", "used_qty": 197.631},
    ])
    xlsx_bytes, summary, preview = convert_to_standard_template(content, sheet="NK2")
    assert summary["rows_unique"] == 1
    standard_rows, errors = read_standard_co_stock(xlsx_bytes)
    assert errors == []
    assert standard_rows[0]["customs_code"] == "DIOT"   # name prefix, not 008.0035900
    assert standard_rows[0]["opening_qty"] == Decimal("500")
    assert preview[0]["customs_code"] == "DIOT"
    assert preview[0]["remaining_qty"] == "302.369"


def test_convert_falls_back_to_column_when_name_has_no_delimiter():
    content = _nk2_workbook([
        {"declaration_no": "D1", "line_no": "1", "customs_code": "M-A", "goods_name": "Sơn",
         "opening_qty": 500, "unit": "KG", "used_qty": 197.631},
    ])
    standard_rows, errors = read_standard_co_stock(convert_to_standard_template(content, sheet="NK2")[0])
    assert errors == []
    assert standard_rows[0]["customs_code"] == "M-A"


def test_convert_preview_handles_zero_used_and_over_reconciled():
    content = _nk2_workbook([
        {"declaration_no": "D2", "line_no": "1", "customs_code": "M-Z", "opening_qty": 1000, "used_qty": 0},
        {"declaration_no": "D3", "line_no": "1", "customs_code": "M-C", "opening_qty": 10, "used_qty": 12},
    ])
    _, summary, preview = convert_to_standard_template(content, sheet="NK2")
    assert summary["rows_unique"] == 2
    by_code = {p["customs_code"]: p for p in preview}
    assert by_code["M-Z"]["remaining_qty"] == "1000"   # zero-used keeps full opening
    assert by_code["M-C"]["remaining_qty"] == "-2"      # over-reconciled → negative


# ---------- standard template: remaining_qty column ----------

def test_standard_template_round_trips_remaining_qty():
    payload = write_standard_co_stock([
        {"declaration_no": "D1", "line_no": "1", "customs_code": "M-A",
         "opening_qty": Decimal("500"), "used_qty": Decimal("197"), "remaining_qty": Decimal("303")},
    ])
    rows, errors = read_standard_co_stock(payload)
    assert errors == []
    assert rows[0]["remaining_qty"] == Decimal("303")


def test_template_without_remaining_qty_still_reads():
    payload = write_standard_co_stock([
        {"declaration_no": "D1", "line_no": "1", "customs_code": "M-A", "opening_qty": Decimal("5")},
    ])
    rows, errors = read_standard_co_stock(payload)
    assert errors == []
    assert rows[0].get("remaining_qty") in (None, "")


# ---------- converter: emit remaining_qty + cross-check workbook "Tồn" ----------

def test_convert_emits_remaining_and_crosscheck_ton_ok():
    content = _nk2_workbook([
        {"declaration_no": "D1", "line_no": "1", "customs_code": "M-A",
         "goods_name": "DIOT#&x (008.0035900)", "opening_qty": 500, "used_qty": 197, "ton": 303},
    ])
    xlsx, summary, _ = convert_to_standard_template(content, sheet="NK2")
    assert summary["ton_mismatch"] == 0
    rows, _ = read_standard_co_stock(xlsx)
    assert rows[0]["remaining_qty"] == Decimal("303")  # opening - used


def test_convert_flags_ton_mismatch():
    content = _nk2_workbook([
        {"declaration_no": "D1", "line_no": "1", "customs_code": "M-A",
         "goods_name": "DIOT#&x (008.0035900)", "opening_qty": 500, "used_qty": 197, "ton": 999},
    ])
    _, summary, _ = convert_to_standard_template(content, sheet="NK2")
    assert summary["ton_mismatch"] == 1


# ---------- stock_rows_from_standard: bake remaining + resolve allocation ----------

def test_stock_rows_bakes_remaining_and_resolves_growatt_allocation():
    rows = stock_rows_from_standard([
        {"declaration_no": "D1", "line_no": "1", "customs_code": "DIOT",
         "goods_name": "DIOT#&Đi ốt (008.0035900)", "opening_qty": Decimal("500"),
         "used_qty": Decimal("197"), "remaining_qty": Decimal("303")},
    ], _GROWATT_CFG)
    r = rows[0]
    assert r["remaining_qty"] == "303"               # baked
    assert r["allocation_code"] == "008.0035900"     # description_regex from name parens
    assert r["eligibility_status"] == "active"
    assert r["opening_qty"] == "500"
    assert r["baseline_used_qty"] == "197"           # opening - remaining
    assert r["customs_item_code"] == "DIOT"


def test_stock_rows_johnson_allocation_same_as_customs_not_spec():
    rows = stock_rows_from_standard([
        {"declaration_no": "D1", "line_no": "1", "customs_code": "CT",
         "goods_name": "CT#&Camera (1250A)", "opening_qty": Decimal("10"),
         "used_qty": Decimal("3"), "remaining_qty": Decimal("7")},
    ], _JOHNSON_CFG)
    assert rows[0]["allocation_code"] == "CT"   # NOT the spec "1250A"


def test_stock_rows_remaining_fallback_when_absent():
    rows = stock_rows_from_standard([
        {"declaration_no": "D1", "line_no": "1", "customs_code": "M-A",
         "goods_name": "M-A#&x", "opening_qty": Decimal("10"), "used_qty": Decimal("4")},
    ], _JOHNSON_CFG)
    assert rows[0]["remaining_qty"] == "6"   # opening - used fallback


# ---------- read-path overlay honours the baked remaining ----------

def test_overlay_empty_ledger_keeps_baked_remaining():
    rows = stock_rows_from_standard([
        {"declaration_no": "D1", "line_no": "1", "customs_code": "DIOT", "goods_name": "DIOT#&x (008.0035900)",
         "opening_qty": Decimal("500"), "used_qty": Decimal("200"), "remaining_qty": Decimal("300")},
    ], _GROWATT_CFG)
    out = apply_used_qty([dict(r) for r in rows], used_by_lot={})
    assert out[0]["remaining_signed_qty"] == "300"
    assert out[0]["ledger_overclaim"] is False


def test_overlay_subtracts_live_claim_on_top_of_remaining():
    rows = stock_rows_from_standard([
        {"declaration_no": "D1", "line_no": "1", "customs_code": "DIOT", "goods_name": "DIOT#&x (008.0035900)",
         "opening_qty": Decimal("500"), "used_qty": Decimal("200"), "remaining_qty": Decimal("300")},
    ], _GROWATT_CFG)
    src = rows[0]["source_row"]
    out = apply_used_qty([dict(r) for r in rows], used_by_lot={src: Decimal("120")})
    assert out[0]["remaining_signed_qty"] == "180"   # 300 - 120


# ---------- DB: standalone import sets rows + re-import replaces ----------

@pytest.mark.skipif(not database_url(), reason="needs BARRY_DATABASE_URL")
def test_standalone_import_sets_rows_and_reimport_replaces():
    from app import co_stock_materializer
    from app.co_stock_workbook import import_standard_snapshot
    from app.co_stock_template import write_standard_co_stock as _w
    from app.database import connect

    client_id = "test-wb-remaining-pytest"
    client = {"id": client_id}

    def _cleanup():
        try:
            with connect() as conn, conn.cursor() as cur:
                cur.execute("delete from co_stock_rows where client_id = %s", (client_id,))
                cur.execute("delete from co_stock_refresh_state where client_id = %s", (client_id,))
                cur.execute("delete from co_stock_events where client_id = %s", (client_id,))
        except Exception:
            pass

    _cleanup()
    try:
        tpl = _w([
            {"declaration_no": "D1", "line_no": "1", "customs_code": "DIOT",
             "goods_name": "DIOT#&x (008.0035900)", "opening_qty": Decimal("500"),
             "used_qty": Decimal("200"), "remaining_qty": Decimal("300")},
            {"declaration_no": "D2", "line_no": "1", "customs_code": "PCBA",
             "goods_name": "PCBA#&y (B700.0092002)", "opening_qty": Decimal("100"),
             "used_qty": Decimal("0"), "remaining_qty": Decimal("100")},
        ])
        res = import_standard_snapshot(client, tpl, config=_GROWATT_CFG, filename="snap.xlsx")
        assert not res["materialize"].get("errors")
        assert co_stock_materializer.row_count(client_id) == 2
        page, _ = co_stock_materializer.read_co_stock_page(client_id, q="D1")
        d1 = [r for r in page if r["import_declaration_no"] == "D1"][0]
        assert d1["remaining_qty"] == "300"           # baked, no fold
        assert d1["allocation_code"] == "008.0035900"  # dotted → BOM-matchable

        # Re-import a different snapshot → full replace.
        tpl2 = _w([
            {"declaration_no": "D1", "line_no": "1", "customs_code": "DIOT",
             "goods_name": "DIOT#&x (008.0035900)", "opening_qty": Decimal("500"),
             "used_qty": Decimal("250"), "remaining_qty": Decimal("250")},
        ])
        import_standard_snapshot(client, tpl2, config=_GROWATT_CFG, filename="snap2.xlsx")
        assert co_stock_materializer.row_count(client_id) == 1  # D2 removed
        page2, _ = co_stock_materializer.read_co_stock_page(client_id, q="D1")
        assert page2[0]["remaining_qty"] == "250"
    finally:
        _cleanup()
