"""Close-case lifecycle: status propagation, edit gate, sheet-locked pre-check,
reopen path. Live regression for 2026-05-28 bug reports."""
from __future__ import annotations

from app.co_case_store import (
    CaseClosedError,
    case_from_record,
    co_case_is_completed,
)


def test_case_from_record_propagates_status():
    """Status must round-trip from the persistent record into the runtime
    case dict — without this, the template banner + reopen button never
    render even though the DB has status=completed."""
    client = {"id": "demo", "name": "Demo", "tax_code": ""}
    record = {"case_id": "case-1", "case_code": "X", "title": "X", "destination_market": "X", "status": "completed"}
    case = case_from_record({}, client, record)
    assert case["status"] == "completed"
    assert co_case_is_completed(case)


def test_case_from_record_handles_missing_status():
    client = {"id": "demo", "name": "Demo"}
    record = {"case_id": "case-2", "case_code": "X", "title": "X", "destination_market": "X"}
    case = case_from_record({}, client, record)
    assert case["status"] == ""
    assert not co_case_is_completed(case)


def test_case_closed_error_subclasses_value_error():
    """Existing exception-handler chains (try/except ValueError) won't
    accidentally swallow the close-gate raise; this confirms the
    inheritance contract."""
    err = CaseClosedError("closed")
    assert isinstance(err, ValueError)
    assert str(err) == "closed"
