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

from app.web.co_case_context import (
    attach_origin_sheet_states,
    co_case_step_status,
    co_case_workflow_steps,
    origin_sheet_attention,
)

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


# --- Readiness chip: guard-blocked vs merely-loaded (backlog ST1) ----------
# After a batch "Tính", a sheet a guard held (shortage / missing price /
# declarable-unmatched / empty BOM) stays at `bom_loaded` — identical badge to a
# sheet that only had BOM structure loaded and was never calculated.
# `origin_sheet_attention` tells them apart.

def _blocked_sheet(**flags) -> dict:
    # A CALCULATED sheet (origin_not_calculated False) resting at bom_loaded.
    base = {"code": "TP-1", "origin_sheet_status": "bom_loaded", "origin_not_calculated": False}
    base.update(flags)
    return base


def test_attention_shortage():
    chip = origin_sheet_attention(_blocked_sheet(lvc_allocation_shortage=True))
    assert chip["status"] == "attention"
    assert chip["reason"] == "shortage"
    assert chip["label"] == "Cần xử lý: thiếu tồn"
    assert chip["detail"]


def test_attention_missing_price():
    chip = origin_sheet_attention(_blocked_sheet(lvc_missing_price=True))
    assert chip["status"] == "attention"
    assert chip["reason"] == "missing_price"
    assert chip["label"] == "Cần xử lý: thiếu đơn giá"


def test_attention_declarable_unmatched():
    chip = origin_sheet_attention(_blocked_sheet(lvc_declarable_unmatched=True))
    assert chip["status"] == "attention"
    assert chip["reason"] == "declarable_unmatched"
    assert chip["label"] == "Cần xử lý: NVL chưa có tờ khai nhập"


def test_attention_missing_bom():
    chip = origin_sheet_attention(_blocked_sheet(lvc_status="missing_bom"))
    assert chip["status"] == "attention"
    assert chip["reason"] == "missing_bom"
    assert chip["label"] == "Cần xử lý: chưa đủ BOM"


def test_attention_priority_shortage_beats_missing_price():
    # A no-lot NVL trips both; the remedy is the import document, not a price, so
    # shortage wins — same order as the lock-block reason.
    chip = origin_sheet_attention(
        _blocked_sheet(lvc_allocation_shortage=True, lvc_missing_price=True)
    )
    assert chip["reason"] == "shortage"


def test_never_calculated_load_bom_stays_neutral():
    # Merely Load-BOM'd (origin_not_calculated) — even with a raw missing price it
    # is only "loaded", not "blocked". Must read neutral so the badge stays
    # "Đã nạp BOM".
    chip = origin_sheet_attention(
        {
            "code": "TP-1",
            "origin_sheet_status": "bom_loaded",
            "origin_not_calculated": True,
            "lvc_missing_price": True,
        }
    )
    assert chip["status"] == ""


def test_bom_loaded_no_flags_neutral():
    chip = origin_sheet_attention(_blocked_sheet())
    assert chip["status"] == ""


def test_non_bom_loaded_status_never_attention():
    # A calculated/locked/draft sheet is never a "Cần xử lý" chip even with a flag
    # set — the chip is scoped to sheets resting at bom_loaded.
    for status in ("draft", "calculated", "locked", "stale", ""):
        chip = origin_sheet_attention(
            {"code": "TP-1", "origin_sheet_status": status, "lvc_allocation_shortage": True}
        )
        assert chip["status"] == "", status


def test_attach_origin_sheet_states_exposes_chip():
    # Integration: the render pipeline attaches the chip onto each product.
    case = {
        "products": [
            {"code": "TP-BLOCK", "origin_not_calculated": False, "lvc_missing_price": True},
            {"code": "TP-LOADED", "origin_not_calculated": True},
        ],
        "origin_sheet_states": {
            "TP-BLOCK": {"status": "bom_loaded"},
            "TP-LOADED": {"status": "bom_loaded"},
        },
    }
    prepared = attach_origin_sheet_states(case)
    by_code = {p["code"]: p for p in prepared["products"]}
    assert by_code["TP-BLOCK"]["origin_sheet_attention"]["status"] == "attention"
    assert by_code["TP-BLOCK"]["origin_sheet_attention"]["reason"] == "missing_price"
    assert by_code["TP-LOADED"]["origin_sheet_attention"]["status"] == ""
