"""Stepper (case-level) per-step status — backlog B2.

The 5-step stepper status was wrong in ways staff noticed (brief
`.ai/features/2026-06-08-workflow-step-status-display.md`):

- Step 3 "Bảng kê C/O" could never reach a finished state — its best status was
  `review`/"Cần soát" (yellow) even after every sheet was locked. There was no
  `done`. Now it derives from the same `products[].origin_sheet_status` the list
  page uses (`co_case_status_view`), so locked-all → "Đã chốt N/N".
- An English "Preview" label sat among Vietnamese ones; `review` and `preview`
  rendered identically; `todo` was muted with opacity (project rule violation);
  a dead `wip` key was rendered but never produced.

Contract: `co_case_step_status` returns {"status", "label"} where status is one
of the four keys done / in_progress / attention / todo, and label is contextual
per step (not a single generic map).
"""
from __future__ import annotations

from app.web.co_case_context import co_case_step_status, co_case_workflow_steps

STATUS_KEYS = {"done", "in_progress", "attention", "todo"}


def _sheet(code: str, status: str) -> dict:
    return {"code": code, "origin_sheet_status": status, "origin_sheet_status_label": status}


def _case(**over) -> dict:
    base = {
        "persisted_case_id": "case-1",
        "shipment": {"invoice_no": "INV-1"},
        "destination_market": "Canada",
        "products": [],
    }
    base.update(over)
    return base


def _status(case, step_key, **kw):
    return co_case_step_status(case, step_key, **kw)


# --- Step 1: Lô hàng -------------------------------------------------------

def test_shipment_ref_and_market_done():
    s = _status(_case(), "shipment")
    assert s["status"] == "done"
    assert s["label"] == "Đủ"


def test_shipment_ref_only_attention_missing_market():
    case = _case(destination_market="Chưa nhập")
    s = _status(case, "shipment")
    assert s["status"] == "attention"
    assert s["label"] == "Thiếu thị trường"


def test_shipment_market_only_attention_missing_invoice():
    case = _case(shipment={})
    s = _status(case, "shipment")
    assert s["status"] == "attention"
    assert s["label"] == "Thiếu invoice"


def test_shipment_neither_todo():
    case = _case(shipment={}, destination_market="Chưa nhập")
    s = _status(case, "shipment")
    assert s["status"] == "todo"
    assert s["label"] == "Chưa nhập"


# --- Step 2: Chứng từ ------------------------------------------------------

def test_documents_with_files_done():
    case = _case(supporting_files=[{"name": "bl.pdf"}])
    s = _status(case, "documents")
    assert s["status"] == "done"
    assert s["label"] == "Đã tải"


def test_documents_no_files_todo():
    s = _status(_case(), "documents")
    assert s["status"] == "todo"
    assert s["label"] == "Chưa tải"


# --- Step 3: Bảng kê C/O (the core fix) ------------------------------------

def test_origin_no_products_todo():
    s = _status(_case(products=[]), "origin")
    assert s["status"] == "todo"
    assert s["label"] == "Chưa có NVL"


def test_origin_all_draft_todo_not_yet_calculated():
    case = _case(products=[_sheet("TP-1", "draft"), _sheet("TP-2", "draft")])
    s = _status(case, "origin", invoice_matches=[{"x": 1}])
    assert s["status"] == "todo"
    assert s["label"] == "Chưa tính"


def test_origin_some_worked_not_locked_in_progress():
    case = _case(products=[_sheet("TP-1", "calculated"), _sheet("TP-2", "draft")])
    s = _status(case, "origin", invoice_matches=[{"x": 1}])
    assert s["status"] == "in_progress"
    assert s["label"] == "Đang làm · 0/2 chốt"


def test_origin_partially_locked_in_progress_with_count():
    case = _case(products=[_sheet("TP-1", "locked"), _sheet("TP-2", "calculated")])
    s = _status(case, "origin", invoice_matches=[{"x": 1}])
    assert s["status"] == "in_progress"
    assert s["label"] == "Đang làm · 1/2 chốt"


def test_origin_all_locked_done_not_stuck_on_review():
    # Regression: previously "best" status was review/"Cần soát" forever — even
    # with every sheet locked. Now it must reach done.
    case = _case(products=[_sheet("TP-1", "locked"), _sheet("TP-2", "locked")])
    s = _status(case, "origin", invoice_matches=[{"x": 1}])
    assert s["status"] == "done"
    assert s["label"] == "Đã chốt 2/2"


def test_origin_status_never_preview_or_english():
    for products in ([], [_sheet("TP-1", "draft")], [_sheet("TP-1", "locked")]):
        s = _status(_case(products=products), "origin", invoice_matches=[{"x": 1}])
        assert s["status"] in STATUS_KEYS
        assert "Preview" not in s["label"]


# --- Step 4: TKX / TKN -----------------------------------------------------

def test_exports_no_reference_todo():
    s = _status(_case(shipment={}), "exports")
    assert s["status"] == "todo"
    assert s["label"] == "Chưa có"


def test_exports_no_invoice_matches_attention():
    s = _status(_case(), "exports", invoice_matches=[])
    assert s["status"] == "attention"
    assert s["label"] == "Thiếu tờ khai"


def test_exports_missing_declarations_attention():
    s = _status(
        _case(), "exports",
        invoice_matches=[{"x": 1}],
        tkx_tkn_summary={"missing_tkx": ["D1"], "missing_tkn": []},
    )
    assert s["status"] == "attention"
    assert s["label"] == "Thiếu tờ khai"


def test_exports_all_present_done():
    s = _status(
        _case(), "exports",
        invoice_matches=[{"x": 1}],
        tkx_tkn_summary={"missing_tkx": [], "missing_tkn": []},
    )
    assert s["status"] == "done"
    assert s["label"] == "Đủ"


# --- Step 5: Review & Xuất -------------------------------------------------

def test_review_completed_case_done():
    case = _case(status="completed", products=[_sheet("TP-1", "locked")])
    s = _status(case, "review", invoice_matches=[{"x": 1}])
    assert s["status"] == "done"
    assert s["label"] == "Đã xuất"


def test_review_ready_in_progress():
    case = _case(products=[_sheet("TP-1", "locked")])
    s = _status(case, "review", invoice_matches=[{"x": 1}])
    assert s["status"] == "in_progress"
    assert s["label"] == "Sẵn sàng"


def test_review_nothing_todo():
    s = _status(_case(shipment={}, products=[]), "review")
    assert s["status"] == "todo"
    assert s["label"] == "Chưa sẵn sàng"


# --- Integration: co_case_workflow_steps -----------------------------------

def test_workflow_steps_emit_four_key_status_and_label():
    case = _case(products=[_sheet("TP-1", "locked"), _sheet("TP-2", "locked")])
    steps = co_case_workflow_steps(
        "growatt", case, "origin",
        invoice_matches=[{"x": 1}],
        tkx_tkn_summary={"missing_tkx": [], "missing_tkn": []},
    )
    assert {step["key"] for step in steps} == {"shipment", "documents", "origin", "exports", "review"}
    for step in steps:
        assert step["status"] in STATUS_KEYS, step
        assert step["status_label"]
        assert "wip" not in step  # dead key removed

    origin = next(s for s in steps if s["key"] == "origin")
    assert origin["status"] == "done"
    assert origin["status_label"] == "Đã chốt 2/2"
