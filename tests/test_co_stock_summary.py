"""Feedback #12 — số tồn tổng. Tests the pure aggregation reference
(`summarize_stock_value_rows`) that backs the SQL in `co_stock_summary`:
free-remaining value (VND), code/lot counts, ledger subtraction, registration
date filtering, and eligibility gating.
"""
from __future__ import annotations

from app.co_stock_materializer import summarize_stock_value_rows


def _lot(source_row, *, remaining, unit_value="100", code="A", reg="2025-04-10",
         fx="", eligibility="active", alloc_status="resolved"):
    return {
        "source_row": source_row,
        "remaining_qty": remaining,
        "unit_value": unit_value,
        "allocation_code": code,
        "registration_date": reg,
        "exchange_rate_to_vnd": fx,
        "eligibility_status": eligibility,
        "allocation_code_status": alloc_status,
    }


def test_value_counts_basic():
    rows = [
        _lot("r1", remaining="10", unit_value="100", code="A"),
        _lot("r2", remaining="5", unit_value="200", code="B"),
    ]
    out = summarize_stock_value_rows(rows)
    assert out["lot_count"] == 2
    assert out["code_count"] == 2
    assert out["total_value_vnd"] == "2000"  # 10*100 + 5*200
    assert out["total_qty"] == "15.000000"  # 10 + 5, unit-agnostic


def test_same_code_two_lots_counts_one_code():
    rows = [
        _lot("r1", remaining="10", code="A"),
        _lot("r2", remaining="3", code="A"),
    ]
    out = summarize_stock_value_rows(rows)
    assert out["lot_count"] == 2
    assert out["code_count"] == 1


def test_ledger_claim_subtracted_from_free():
    rows = [_lot("r1", remaining="10", unit_value="100")]
    out = summarize_stock_value_rows(rows, {"r1": __import__("decimal").Decimal("4")})
    assert out["lot_count"] == 1
    assert out["total_value_vnd"] == "600"  # (10-4)*100
    assert out["total_qty"] == "6.000000"  # 10 - 4 claimed


def test_fully_claimed_lot_drops_out():
    rows = [_lot("r1", remaining="10"), _lot("r2", remaining="5", code="B")]
    from decimal import Decimal
    out = summarize_stock_value_rows(rows, {"r1": Decimal("10")})
    assert out["lot_count"] == 1
    assert out["code_count"] == 1


def test_zero_and_negative_remaining_excluded():
    rows = [
        _lot("r1", remaining="0"),
        _lot("r2", remaining="-3"),
        _lot("r3", remaining="7", code="B"),
    ]
    out = summarize_stock_value_rows(rows)
    assert out["lot_count"] == 1
    assert out["total_value_vnd"] == "700"


def test_inactive_and_unresolved_excluded():
    rows = [
        _lot("r1", remaining="10", eligibility="inactive"),
        _lot("r2", remaining="10", alloc_status="ambiguous"),
        _lot("r3", remaining="10", code="C"),
    ]
    out = summarize_stock_value_rows(rows)
    assert out["lot_count"] == 1
    assert out["code_count"] == 1


def test_date_filter_includes_only_in_range():
    rows = [
        _lot("r1", remaining="10", reg="2025-01-15", code="A"),
        _lot("r2", remaining="10", reg="2025-06-20", code="B"),
        _lot("r3", remaining="10", reg="2025-12-31", code="C"),
    ]
    out = summarize_stock_value_rows(rows, date_from="2025-03-01", date_to="2025-09-30")
    assert out["lot_count"] == 1
    assert out["code_count"] == 1
    assert out["filtered"] is True
    assert out["date_from"] == "2025-03-01"


def test_date_filter_open_ended_from():
    rows = [
        _lot("r1", remaining="10", reg="2025-01-15"),
        _lot("r2", remaining="10", reg="2025-06-20", code="B"),
    ]
    out = summarize_stock_value_rows(rows, date_from="2025-03-01")
    assert out["lot_count"] == 1


def test_row_without_registration_date_excluded_when_filtering():
    rows = [_lot("r1", remaining="10", reg="")]
    assert summarize_stock_value_rows(rows, date_from="2025-01-01")["lot_count"] == 0
    # but counted when no date bound is set
    assert summarize_stock_value_rows(rows)["lot_count"] == 1


def test_foreign_currency_converted_by_fx():
    rows = [_lot("r1", remaining="2", unit_value="100", fx="25000")]
    out = summarize_stock_value_rows(rows)
    assert out["total_value_vnd"] == "5000000"  # 2 * 100 * 25000


def test_missing_or_nonpositive_fx_defaults_to_one():
    rows = [
        _lot("r1", remaining="2", unit_value="100", fx=""),
        _lot("r2", remaining="2", unit_value="100", fx="0", code="B"),
        _lot("r3", remaining="2", unit_value="100", fx="-5", code="C"),
    ]
    out = summarize_stock_value_rows(rows)
    assert out["total_value_vnd"] == "600"  # 3 lots * (2*100*1)


def test_non_numeric_remaining_or_value_ignored():
    rows = [
        _lot("r1", remaining="abc"),
        _lot("r2", remaining="5", unit_value="n/a", code="B"),  # value 0 → counted lot, 0 value
    ]
    out = summarize_stock_value_rows(rows)
    assert out["lot_count"] == 1  # only r2 (positive remaining)
    assert out["total_value_vnd"] == "0"


def test_empty_input():
    out = summarize_stock_value_rows([])
    assert out["lot_count"] == 0
    assert out["code_count"] == 0
    assert out["total_qty"] == "0.000000"
    assert out["total_value_vnd"] == "0"
    assert out["filtered"] is False


def test_total_qty_mixes_units_across_uom():
    """User accepts unit-mixing: free remaining is summed regardless of UOM."""
    rows = [
        _lot("r1", remaining="100", code="A"),   # e.g. cái
        _lot("r2", remaining="2.5", code="B"),   # e.g. kg
    ]
    out = summarize_stock_value_rows(rows)
    assert out["total_qty"] == "102.500000"
