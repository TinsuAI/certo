"""P2 — nút "Tính bảng kê" contextual: chỉ bật khi có việc thật để tính
(draft / bom_loaded / stale). Sheet đã `calculated` (và không stale) → disable +
giải thích "sửa bảng kê sẽ tự tính lại". Nhãn động: stale → "Tính lại".
"""
from __future__ import annotations

from app.web.co_case_context import attach_origin_sheet_states


def _prod(status: str) -> dict:
    case = {
        "products": [{"code": "TP1", "name": "SP"}],
        "origin_sheet_states": {"TP1": {"status": status}},
    }
    return attach_origin_sheet_states(case)["products"][0]


def test_calculated_sheet_cannot_recalculate():
    p = _prod("calculated")
    assert p["origin_can_calculate"] is False
    assert "tự tính lại" in p["origin_calculate_block_reason"]


def test_stale_sheet_can_recalculate_label_tinh_lai():
    p = _prod("stale")
    assert p["origin_can_calculate"] is True
    assert p["origin_calculate_label"] == "Tính lại"


def test_draft_and_bom_loaded_label_tinh_bang_ke():
    for status in ("draft", "bom_loaded"):
        p = _prod(status)
        assert p["origin_can_calculate"] is True, status
        assert p["origin_calculate_label"] == "Tính bảng kê", status


def test_locked_sheet_cannot_calculate():
    assert _prod("locked")["origin_can_calculate"] is False
