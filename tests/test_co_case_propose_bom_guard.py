"""BOM-proposal re-POST guard — backlog M1, sub-bug 2 (server half).

The "Đã propose ✓" button must not file a duplicate proposal. The client half is
a JS guard in `co_case.html` (`initOriginProposeBom` skips wiring the POST and
hard-disables the button when `data-proposed-artifact-id` is set). The server
half, tested here, is that any material_overrides WRITE clears the prior proposal
stamp via `override_state_stamp`, so a genuinely changed BOM re-renders the button
as "Lưu BOM mới" and a fresh proposal is allowed — while an unchanged, already
proposed sheet stays inert.
"""
from __future__ import annotations

from app.routers.co_case import override_state_stamp


def test_override_state_stamp_clears_prior_proposal():
    stamp = override_state_stamp({"bom_product_artifact_id": "bv-9"})
    assert stamp["overrides_artifact_id"] == "bv-9"
    assert stamp["proposed_artifact_id"] == ""
    assert stamp["proposed_proposal_id"] == ""
    assert stamp["proposed_status"] == ""


def test_override_write_pattern_drops_proposed_stamp():
    # A sheet locked + proposed (proposed_* set), then edited: the write pattern
    # every override endpoint uses is {**previous, ..., **override_state_stamp}.
    previous = {
        "status": "locked",
        "material_overrides": {"row-1": {"deleted": True}},
        "proposed_artifact_id": "art-1",
        "proposed_proposal_id": "prop-1",
        "proposed_status": "submitted",
    }
    product = {"bom_product_artifact_id": "bv-9"}
    new_state = {
        **previous,
        "material_overrides": {"row-1": {"deleted": True}, "row-2": {"added": True}},
        **override_state_stamp(product),
        "status": "stale",
    }
    assert new_state["proposed_artifact_id"] == ""
    assert new_state["proposed_proposal_id"] == ""
    assert new_state["proposed_status"] == ""
    # The edit itself is preserved; only the proposal reference is dropped.
    assert new_state["overrides_artifact_id"] == "bv-9"
    assert "row-2" in new_state["material_overrides"]
