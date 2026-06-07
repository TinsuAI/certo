"""CO-case list redesign — archive flag + cheap per-case status derivation.

Brief: .ai/features/2026-06-07-co-case-list-redesign.md
"""
from __future__ import annotations

import pytest

from app.co_case_store import (
    co_case_status_view,
    create_case_record,
    get_case_record,
    set_case_archived,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CO_CASE_STORE_ROOT", str(tmp_path / "co-case-store"))


def _client():
    return {"id": "growatt-vn", "name": "Growatt VN"}


# --- archive round-trip -----------------------------------------------------

def test_archive_flag_defaults_false_and_round_trips():
    client = _client()
    record = create_case_record(client, {"title": "T", "case_code": "CO-A", "invoice_no": "INV1"})
    assert not get_case_record(client, record["case_id"]).get("archived")

    set_case_archived(client, record["case_id"], True)
    assert get_case_record(client, record["case_id"])["archived"] is True

    set_case_archived(client, record["case_id"], False)
    assert get_case_record(client, record["case_id"])["archived"] is False


def test_archive_works_on_completed_case_bypassing_close_gate():
    """Archiving a closed case is the common path; it must not hit the
    update_case_record close-gate (which rejects edits to completed cases)."""
    client = _client()
    record = create_case_record(client, {"title": "T", "case_code": "CO-B", "invoice_no": "INV2"})
    set_case_archived(client, record["case_id"], False)
    # Manually close it via the record, then archive.
    from app.co_case_store import update_case_record

    update_case_record(client, {"persisted_case_id": record["case_id"], "status": "completed"})
    set_case_archived(client, record["case_id"], True)  # must not raise
    stored = get_case_record(client, record["case_id"])
    assert stored["archived"] is True
    assert stored["status"] == "completed"


# --- status derivation ------------------------------------------------------

def test_status_missing_reference_is_attention():
    view = co_case_status_view({"case_id": "c", "shipment": {}})
    assert view["status_key"] == "attention"
    assert "Thiếu invoice/tờ khai" in view["issues"]


def test_status_missing_bill_is_attention():
    view = co_case_status_view({"case_id": "c", "shipment": {"invoice_no": "INV"}})
    assert view["status_key"] == "attention"
    assert "Thiếu B/L" in view["issues"]


def test_status_no_products_needs_origin():
    view = co_case_status_view(
        {"case_id": "c", "shipment": {"invoice_no": "INV", "bill_of_lading_no": "BL"}}
    )
    assert view["status_key"] == "attention"
    assert "Chưa có bảng kê" in view["issues"]


def test_status_in_progress_counts_locked_sheets():
    case = {
        "case_id": "c",
        "shipment": {"invoice_no": "INV", "bill_of_lading_no": "BL"},
        "products": [
            {"origin_sheet_status": "locked"},
            {"origin_sheet_status": "open"},
            {},
        ],
    }
    view = co_case_status_view(case)
    assert view["status_key"] == "progress"
    assert view["sheets_total"] == 3
    assert view["sheets_locked"] == 1
    assert "2 bảng kê chưa chốt" in view["issues"]


def test_status_completed_is_done_with_no_issues():
    case = {
        "case_id": "c",
        "status": "completed",
        "shipment": {"invoice_no": "INV", "bill_of_lading_no": "BL"},
        "products": [{"origin_sheet_status": "locked"}],
    }
    view = co_case_status_view(case, exported=True)
    assert view["status_key"] == "done"
    assert view["completed"] is True
    assert view["exported"] is True
    assert view["issues"] == []
