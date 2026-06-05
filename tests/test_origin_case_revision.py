"""Optimistic-concurrency token stability.

Regression for customer feedback #9 ("phải F5 mới load được BOM tiếp"): the
revision hash used to include source_snapshot / bom_snapshot / origin_snapshot,
which co_case_context recomputes on every render from live source metadata
(BCCT review counts, catalog versions). On prod those drift between a sheet
lock and the next calculate, so the next action falsely 409'd with
"Origin case state changed; reload before saving". The token must reflect only
user-editable case state.
"""
from __future__ import annotations

from app.web.co_case_context import origin_case_revision


def _base_case() -> dict:
    return {
        "origin_product_order": ["TP-1", "TP-2"],
        "origin_sheet_states": {
            "TP-1": {"status": "locked", "status_label": "Đã chốt"},
            "TP-2": {"status": "calculated", "status_label": "Đã tính"},
        },
        "bom_product_artifact_overrides": {"TP-1": "bom-a", "TP-2": "bom-b"},
        "products": [{"code": "TP-1", "quantity": "10"}, {"code": "TP-2", "quantity": "5"}],
        "source_snapshot": {"bcct_reviewed_row_count": 100, "correction_candidate_count": 3},
        "bom_snapshot": {"composition": [{"x": 1}]},
        "origin_snapshot": {"readiness_status": "ready", "issue_count": 0},
    }


def test_revision_stable_when_derived_snapshots_drift():
    base = _base_case()
    rev0 = origin_case_revision(base)

    drifted = _base_case()
    # Simulate a benign prod source refresh between two actions.
    drifted["source_snapshot"] = {"bcct_reviewed_row_count": 137, "correction_candidate_count": 9}
    drifted["bom_snapshot"] = {"composition": [{"x": 1}, {"y": 2}]}
    drifted["origin_snapshot"] = {"readiness_status": "review", "issue_count": 4}

    assert origin_case_revision(drifted) == rev0, (
        "revision must not change when only derived/source snapshots drift"
    )


def test_revision_changes_on_sheet_status_transition():
    base = _base_case()
    rev0 = origin_case_revision(base)
    edited = _base_case()
    edited["origin_sheet_states"]["TP-2"]["status"] = "locked"
    assert origin_case_revision(edited) != rev0


def test_revision_changes_on_reorder():
    base = _base_case()
    rev0 = origin_case_revision(base)
    edited = _base_case()
    edited["origin_product_order"] = ["TP-2", "TP-1"]
    assert origin_case_revision(edited) != rev0


def test_revision_changes_on_bom_override():
    base = _base_case()
    rev0 = origin_case_revision(base)
    edited = _base_case()
    edited["bom_product_artifact_overrides"]["TP-1"] = "bom-c"
    assert origin_case_revision(edited) != rev0


def test_revision_is_nonempty():
    assert origin_case_revision(_base_case())
    assert origin_case_revision({})
