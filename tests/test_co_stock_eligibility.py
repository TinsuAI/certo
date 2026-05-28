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


# Integration: pool-level filter via `case_allocation_pool` in main.py


def test_case_allocation_pool_filters_recent_imports_when_export_anchor_present():
    from app.main import case_allocation_pool

    case = {
        "shipment": {"export_declaration_nos": ["XK-EXPORT-1"]},
    }
    invoice_matches = [
        {"declaration_no": "XK-EXPORT-1", "registration_date": "2026-05-03"},
    ]
    stock_rows = [
        # Imported 5 days before export → eligible.
        {"material_code": "M-OK", "source_row": "row-1",
         "eligibility_status": "active",
         "registration_date": "2026-04-28",
         "available_qty": "100"},
        # Imported 1 day before export → too recent, filtered.
        {"material_code": "M-RECENT", "source_row": "row-2",
         "eligibility_status": "active",
         "registration_date": "2026-05-02",
         "available_qty": "50"},
        # Imported on the same day → too recent, filtered.
        {"material_code": "M-SAMEDAY", "source_row": "row-3",
         "eligibility_status": "active",
         "registration_date": "2026-05-03",
         "available_qty": "30"},
    ]

    pool = case_allocation_pool(case, invoice_matches, stock_rows)

    assert pool["M-OK"][0]["_eligibility_ok"] is True
    assert pool["M-OK"][0]["_eligibility_reason"] == REASON_OK
    assert pool["M-RECENT"][0]["_eligibility_ok"] is False
    assert pool["M-RECENT"][0]["_eligibility_reason"] == REASON_IMPORT_TOO_RECENT
    assert pool["M-SAMEDAY"][0]["_eligibility_ok"] is False
    assert pool["M-SAMEDAY"][0]["_eligibility_reason"] == REASON_IMPORT_TOO_RECENT


def test_case_allocation_pool_no_export_anchor_makes_rule_noop():
    """When the case has no matched export declaration, the gap rule is
    skipped — operators editing a case before confirming shipment shouldn't
    see "ineligible" lots that the rule can't actually anchor."""
    from app.main import case_allocation_pool

    case = {"shipment": {"export_declaration_nos": []}}
    invoice_matches = []
    stock_rows = [
        {"material_code": "M", "source_row": "row-1",
         "eligibility_status": "active",
         "registration_date": "2026-05-03",
         "available_qty": "100"},
    ]
    pool = case_allocation_pool(case, invoice_matches, stock_rows)
    # No anchor → no gap rejection.
    assert pool["M"][0]["_eligibility_ok"] is True


def test_case_allocation_pool_threshold_kwarg_overrides_default():
    """min_gap_days kwarg controls the predicate end-to-end through the
    allocation pool builder (route handlers resolve the value from
    client_config and pass it down)."""
    from app.main import case_allocation_pool

    case = {"shipment": {"export_declaration_nos": ["XK-1"]}}
    invoice_matches = [{"declaration_no": "XK-1", "registration_date": "2026-05-10"}]
    stock_rows = [
        {"material_code": "M", "source_row": "row-1",
         "eligibility_status": "active",
         "registration_date": "2026-05-05",
         "available_qty": "100"},
    ]
    # Gap = 5 days. Default (2) → eligible.
    pool_default = case_allocation_pool(case, invoice_matches, stock_rows)
    assert pool_default["M"][0]["_eligibility_ok"] is True
    # Override threshold to 7 days → rejected.
    pool_strict = case_allocation_pool(case, invoice_matches, stock_rows, min_gap_days=7)
    assert pool_strict["M"][0]["_eligibility_ok"] is False
    assert pool_strict["M"][0]["_eligibility_reason"] == REASON_IMPORT_TOO_RECENT
    # Disable the rule (threshold 0) → eligible no matter what.
    pool_off = case_allocation_pool(case, invoice_matches, stock_rows, min_gap_days=0)
    assert pool_off["M"][0]["_eligibility_ok"] is True


def test_case_allocation_pool_multi_export_uses_earliest_as_anchor():
    """Conservative anchor: the tightest constraint wins when a case
    carries multiple export declarations."""
    from app.main import case_allocation_pool

    case = {"shipment": {"export_declaration_nos": ["XK-A", "XK-B"]}}
    invoice_matches = [
        {"declaration_no": "XK-A", "registration_date": "2026-05-10"},
        {"declaration_no": "XK-B", "registration_date": "2026-05-03"},  # earlier
    ]
    stock_rows = [
        # Eligible vs the later export (XK-A 2026-05-10) but NOT vs the
        # earlier export (XK-B 2026-05-03). Anchor = XK-B → reject.
        {"material_code": "M", "source_row": "row-1",
         "eligibility_status": "active",
         "registration_date": "2026-05-02",
         "available_qty": "10"},
    ]
    pool = case_allocation_pool(case, invoice_matches, stock_rows)
    assert pool["M"][0]["_eligibility_ok"] is False
    assert pool["M"][0]["_eligibility_reason"] == REASON_IMPORT_TOO_RECENT
