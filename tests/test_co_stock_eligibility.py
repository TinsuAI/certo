from __future__ import annotations

from datetime import date

import pytest

from app.co_stock_eligibility import (
    DEFAULT_MIN_GAP_DAYS,
    REASON_IMPORT_TOO_RECENT,
    REASON_INELIGIBLE_STATUS,
    REASON_OK,
    REASON_UNRESOLVED_ALLOCATION,
    earliest_export_date,
    is_stock_lot_eligible,
    min_gap_days_from_config,
    parse_flexible_date,
)


def test_eligible_row_with_no_gap_anchor_passes():
    row = {"eligibility_status": "active", "allocation_code_status": "resolved",
           "registration_date": "2026-01-01"}
    v = is_stock_lot_eligible(row, export_date=None)
    assert v.ok and v.reason == REASON_OK


def test_ineligible_status_is_rejected_before_gap_check():
    row = {"eligibility_status": "inactive", "registration_date": "2026-01-01"}
    v = is_stock_lot_eligible(row, export_date=date(2026, 5, 1))
    assert not v.ok
    assert v.reason == REASON_INELIGIBLE_STATUS


def test_unresolved_allocation_code_rejected():
    row = {"eligibility_status": "active", "allocation_code_status": "needs_review"}
    v = is_stock_lot_eligible(row, export_date=date(2026, 5, 1))
    assert not v.ok
    assert v.reason == REASON_UNRESOLVED_ALLOCATION


def test_blank_status_treated_as_eligible():
    row = {"registration_date": "2026-01-01"}
    v = is_stock_lot_eligible(row)
    assert v.ok


def test_gap_check_inclusive_at_threshold_passes():
    row = {"eligibility_status": "active", "allocation_code_status": "resolved",
           "registration_date": "2026-05-01"}
    v = is_stock_lot_eligible(row, export_date=date(2026, 5, 3), min_gap_days=2)
    assert v.ok and v.reason == REASON_OK


def test_gap_check_below_threshold_rejects():
    row = {"eligibility_status": "active", "allocation_code_status": "resolved",
           "registration_date": "2026-05-02"}
    v = is_stock_lot_eligible(row, export_date=date(2026, 5, 3), min_gap_days=2)
    assert not v.ok
    assert v.reason == REASON_IMPORT_TOO_RECENT


def test_gap_check_same_day_rejects():
    row = {"eligibility_status": "active", "registration_date": "2026-05-03"}
    v = is_stock_lot_eligible(row, export_date=date(2026, 5, 3))
    assert not v.ok and v.reason == REASON_IMPORT_TOO_RECENT


def test_gap_check_after_export_rejects():
    row = {"eligibility_status": "active", "registration_date": "2026-05-10"}
    v = is_stock_lot_eligible(row, export_date=date(2026, 5, 3))
    assert not v.ok and v.reason == REASON_IMPORT_TOO_RECENT


def test_min_gap_days_zero_disables_rule():
    row = {"eligibility_status": "active", "registration_date": "2026-05-03"}
    v = is_stock_lot_eligible(row, export_date=date(2026, 5, 3), min_gap_days=0)
    assert v.ok


def test_missing_import_date_does_not_reject():
    row = {"eligibility_status": "active"}
    v = is_stock_lot_eligible(row, export_date=date(2026, 5, 3), min_gap_days=2)
    # Legacy rows without registration_date fall through — operator sees
    # them; refresh repopulates the field.
    assert v.ok


def test_dd_mm_yyyy_date_parses():
    row = {"eligibility_status": "active", "registration_date": "01/05/2026"}
    v = is_stock_lot_eligible(row, export_date=date(2026, 5, 3), min_gap_days=2)
    assert v.ok


def test_fallback_to_declaration_date_when_registration_blank():
    row = {"eligibility_status": "active", "registration_date": "",
           "declaration_date": "2026-05-01"}
    v = is_stock_lot_eligible(row, export_date=date(2026, 5, 3), min_gap_days=2)
    assert v.ok


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-05-01", date(2026, 5, 1)),
        ("2026-05-01T00:00:00", date(2026, 5, 1)),
        ("2026-05-01T00:00:00Z", date(2026, 5, 1)),
        ("01/05/2026", date(2026, 5, 1)),
        ("20260501", date(2026, 5, 1)),
        ("", None),
        ("garbage", None),
        (None, None),
    ],
)
def test_parse_flexible_date(value, expected):
    assert parse_flexible_date(value) == expected


def test_earliest_export_date_picks_min():
    records = [
        {"registration_date": "2026-05-10"},
        {"registration_date": "2026-05-03"},
        {"registration_date": "2026-05-15"},
    ]
    assert earliest_export_date(records) == date(2026, 5, 3)


def test_earliest_export_date_falls_back_to_declaration_date():
    records = [
        {"declaration_date": "2026-05-15"},
        {"registration_date": "", "declaration_date": "2026-05-10"},
    ]
    assert earliest_export_date(records) == date(2026, 5, 10)


def test_earliest_export_date_returns_none_when_empty():
    assert earliest_export_date([]) is None
    assert earliest_export_date([{}, {"registration_date": ""}]) is None


def test_min_gap_days_from_config_default_when_missing():
    assert min_gap_days_from_config(None) == DEFAULT_MIN_GAP_DAYS
    assert min_gap_days_from_config({}) == DEFAULT_MIN_GAP_DAYS
    assert min_gap_days_from_config({"co_stock": {}}) == DEFAULT_MIN_GAP_DAYS


def test_min_gap_days_from_config_explicit_value():
    assert min_gap_days_from_config({"co_stock": {"min_days_before_export": 5}}) == 5
    assert min_gap_days_from_config({"co_stock": {"min_days_before_export": 0}}) == 0


def test_min_gap_days_from_config_rejects_negative():
    assert min_gap_days_from_config({"co_stock": {"min_days_before_export": -3}}) == DEFAULT_MIN_GAP_DAYS


def test_min_gap_days_from_config_rejects_garbage():
    assert min_gap_days_from_config({"co_stock": {"min_days_before_export": "abc"}}) == DEFAULT_MIN_GAP_DAYS
