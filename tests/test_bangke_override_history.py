"""Per-sheet override UNDO/REDO history — backs 'giữ undo qua lần lưu'.

attach_origin_sheet_states REBUILDS each sheet state from a whitelist, so the
undo/redo stacks must be explicitly carried or they'd be wiped on every
recompute/render (and thus never persist). These tests pin that carry + the
bounding so a long editing session can't bloat the case JSON.
"""
from __future__ import annotations

from app.web.co_case_context import (
    OVERRIDE_HISTORY_MAX,
    attach_origin_sheet_states,
    clean_override_stack,
)


def test_clean_override_stack_sanitizes_non_dicts():
    assert clean_override_stack([1, "x", None, {}, {"a": {"k": 1}}]) == [{}, {"a": {"k": 1}}]


def test_clean_override_stack_drops_non_dict_override_values():
    # Each snapshot is a row_key -> override-dict map; non-dict values are dropped.
    assert clean_override_stack([{"0": {"deleted": True}, "junk": 5}]) == [{"0": {"deleted": True}}]


def test_clean_override_stack_bounds_to_max():
    big = [{str(i): {"v": i}} for i in range(OVERRIDE_HISTORY_MAX + 15)]
    stack = clean_override_stack(big)
    assert len(stack) == OVERRIDE_HISTORY_MAX
    # keeps the MOST RECENT entries
    assert stack[-1] == {str(OVERRIDE_HISTORY_MAX + 14): {"v": OVERRIDE_HISTORY_MAX + 14}}


def test_attach_carries_history_and_exposes_counts():
    case = {
        "products": [{"code": "TP1", "name": "SP"}],
        "origin_sheet_states": {
            "TP1": {
                "status": "calculated",
                "material_overrides": {"0": {"deleted": True}},
                "override_history": [{}, {"1": {"material_code": "X"}}],
                "override_redo": [{"2": {"deleted": True}}],
            }
        },
    }
    out = attach_origin_sheet_states(case)
    state = out["origin_sheet_states"]["TP1"]
    assert len(state["override_history"]) == 2
    assert state["override_redo"] == [{"2": {"deleted": True}}]
    product = out["products"][0]
    assert product["origin_sheet_undo_count"] == 2
    assert product["origin_sheet_redo_count"] == 1


def test_attach_defaults_empty_history_to_zero_counts():
    case = {
        "products": [{"code": "TP1", "name": "SP"}],
        "origin_sheet_states": {"TP1": {"status": "draft"}},
    }
    product = attach_origin_sheet_states(case)["products"][0]
    assert product["origin_sheet_undo_count"] == 0
    assert product["origin_sheet_redo_count"] == 0
