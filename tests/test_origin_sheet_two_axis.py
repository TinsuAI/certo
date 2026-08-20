"""Sheet state read on two axes instead of one overloaded badge (2026-08-20).

`origin_sheet_status` mixes three kinds of fact in one value — progress
(`draft` / `calculating` / `calculated`), the result of an action (`bom_loaded`)
and a verdict (`stale`, `locked`) — so the badge never said which axis the
operator was reading. `bom_loaded` in particular covers two opposite realities:
"nạp BOM xong, chưa tính" and "đã tính nhưng bị chặn".

`origin_sheet_progress` answers only "đã tính chưa"; `origin_sheet_condition`
answers only "chốt được chưa, vướng gì". Both are presentation-only: the stored
status is unchanged, and the lock / export gates still read it.
"""
from __future__ import annotations

from app.web.co_case_context import (
    ORIGIN_SHEET_STATUS_LABELS,
    attach_origin_sheet_states,
    origin_sheet_condition,
    origin_sheet_progress,
)


def _sheet(status, **flags):
    base = {"code": "TP-1", "origin_sheet_status": status, "origin_not_calculated": False}
    base.update(flags)
    return base


def test_progress_has_three_resting_values():
    assert origin_sheet_progress(_sheet("draft"))["label"] == "Chưa tính"
    assert origin_sheet_progress(_sheet("calculated"))["label"] == "Đã tính"
    assert origin_sheet_progress(_sheet("locked"))["label"] == "Đã chốt"


def test_loaded_but_never_calculated_reads_chua_tinh():
    p = _sheet("bom_loaded", origin_not_calculated=True)
    assert origin_sheet_progress(p)["key"] == "not_calculated"
    # Nothing to judge yet, so no verdict chip.
    assert origin_sheet_condition(p)["label"] == ""


def test_calculated_but_blocked_still_reads_da_tinh():
    # The bug the two axes exist to fix: this sheet rests at `bom_loaded`, which
    # used to render "Đã nạp BOM" — indistinguishable from a sheet nobody has
    # calculated. It HAS been calculated; it is only blocked.
    p = _sheet("bom_loaded", lvc_allocation_shortage=True)
    assert origin_sheet_progress(p)["label"] == "Đã tính"
    cond = origin_sheet_condition(p)
    assert cond["key"] == "attention"
    assert cond["label"] == "Cần xử lý: thiếu tồn"
    assert cond["detail"]


def test_clean_calculated_sheet_is_ready():
    cond = origin_sheet_condition(_sheet("calculated"))
    assert cond["key"] == "ready"
    assert cond["label"] == "Sẵn sàng chốt"


def test_blocker_on_a_calculated_sheet_is_not_reported_green():
    # The save / bulk-substitute routes can re-stamp a sheet `calculated` while a
    # blocker is still live; the lock and export gates block it regardless, so
    # the chip must not claim it is ready. (`origin_sheet_attention` is scoped to
    # `bom_loaded` and deliberately stays silent here — this axis is broader.)
    cond = origin_sheet_condition(_sheet("calculated", lvc_missing_price=True))
    assert cond["key"] == "attention"
    assert cond["label"] == "Cần xử lý: thiếu đơn giá"


def test_stale_wins_over_a_blocker_reason():
    # A stale result's flags describe the OLD calculation, so "tính lại" is the
    # honest instruction — reporting the stale blocker would send the operator
    # after a problem that may not exist any more.
    cond = origin_sheet_condition(_sheet("stale", lvc_allocation_shortage=True))
    assert cond["key"] == "stale"
    assert cond["label"] == "Cần tính lại"


def test_stuck_calculating_recovers_as_needs_recalculation():
    # `calculating` is optimistic browser state; a sheet resting in it had its
    # calculation interrupted. durable_sheet_status coerces it to `stale`.
    p = _sheet("calculating")
    assert origin_sheet_progress(p)["label"] == "Đã tính"
    assert origin_sheet_condition(p)["label"] == "Cần tính lại"


def test_locked_sheet_carries_no_verdict_chip():
    # Already filed — the progress badge says Đã chốt and that is the whole story.
    assert origin_sheet_condition(_sheet("locked", lvc_missing_price=True))["label"] == ""


def test_locked_label_is_a_past_participle():
    # "Chốt" was both the button and the state; the state is now `Đã chốt`,
    # matching what the workflow step and the rest of the app already say.
    assert ORIGIN_SHEET_STATUS_LABELS["locked"] == "Đã chốt"


def test_render_pipeline_attaches_both_axes():
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
    by_code = {p["code"]: p for p in attach_origin_sheet_states(case)["products"]}
    assert by_code["TP-BLOCK"]["origin_sheet_progress"]["label"] == "Đã tính"
    assert by_code["TP-BLOCK"]["origin_sheet_condition"]["key"] == "attention"
    assert by_code["TP-LOADED"]["origin_sheet_progress"]["label"] == "Chưa tính"
    assert by_code["TP-LOADED"]["origin_sheet_condition"]["label"] == ""
