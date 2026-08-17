"""LK1 + DC3b guard (one root cause): a sheet calculated BEFORE migration 078
stored its materials WITHOUT the `customs_relevance` field. `is_bom_technical_noise`
returns False for every such row, so rác / declarable_unmatched leak into the
exported bảng kê until the sheet is re-Tính — and lock reads the persisted case
with no forced recalc, so it can commit that stale data.

The fix is ONE guard: force a re-Tính before lock/export when any active material
is missing `customs_relevance`. The signal is field ABSENCE — the post-mig
materializers always write the key ("" when unclassified), so a present-but-empty
value is a valid post-mig row and must NOT be blocked.

Belt (mirrors the declarable_unmatched / missing_price hard-blocks):
  1. sheet_needs_recalc(product) — the predicate over the product's materials.
  2. origin_sheet_action_error(..., "lock") — 409 hard-block at lock.
  3. origin_sheet_export_blockers(...) — export blocker (even for a locked sheet).
"""
from __future__ import annotations

from decimal import Decimal


# --- predicate ---

def test_sheet_needs_recalc_flags_material_without_customs_relevance():
    from app.web.co_case_context import sheet_needs_recalc
    assert sheet_needs_recalc({"materials": [{"material_code": "M1", "allocation_status": "covered"}]}) is True


def test_sheet_needs_recalc_false_when_field_present_even_empty():
    # post-mig materialize writes "" for an unclassified row -> key present -> kept
    from app.web.co_case_context import sheet_needs_recalc
    assert sheet_needs_recalc({"materials": [{"material_code": "M1", "customs_relevance": ""}]}) is False
    assert sheet_needs_recalc({"materials": [{"material_code": "M1", "customs_relevance": "declarable"}]}) is False


def test_sheet_needs_recalc_ignores_deleted_rows():
    # a deleted pre-mig row never reaches the bảng kê -> does not force a recalc
    from app.web.co_case_context import sheet_needs_recalc
    assert sheet_needs_recalc({"materials": [{"material_code": "M1", "deleted": True}]}) is False


def test_sheet_needs_recalc_flags_when_any_row_missing_field():
    from app.web.co_case_context import sheet_needs_recalc
    materials = [
        {"material_code": "OK", "customs_relevance": "declarable"},
        {"material_code": "OLD", "allocation_status": "covered"},  # pre-mig, no field
    ]
    assert sheet_needs_recalc({"materials": materials}) is True


def test_sheet_needs_recalc_false_for_empty_sheet():
    from app.web.co_case_context import sheet_needs_recalc
    assert sheet_needs_recalc({"materials": []}) is False
    assert sheet_needs_recalc({}) is False


def test_freshly_materialized_row_carries_the_field():
    # the real Tính path materializes every row WITH customs_relevance, so a
    # freshly-Tính sheet never trips the guard.
    from app.web.co_case_context import origin_material_from_bom_row, sheet_needs_recalc
    material = origin_material_from_bom_row(
        {"material_code": "NVL-1", "qty_per": "1"}, Decimal("1"), {}, {},
        product_code="TP1", product_name="SP",
    )
    assert "customs_relevance" in material
    assert sheet_needs_recalc({"materials": [material]}) is False


# --- belt 2: lock gate ---

def _sheet(materials, *, status="calculated"):
    return {
        # Chốt requires a criterion chosen by a person (2026-08-17) — a fixture for a
        # lockable sheet carries one so it tests the guard under test, not that rule.
        "criteria_choice": {"criteria_text": "CTH", "chosen_by": "test"},
        "products": [{"code": "P1", "name": "P1", "lvc_status": "pass", "materials": materials}],
        "origin_sheet_states": {"P1": {"status": status}},
    }


def test_lock_blocks_pre_mig_sheet_even_when_status_calculated():
    from app.web.co_case_context import origin_sheet_action_error
    error = origin_sheet_action_error(
        _sheet([{"material_code": "M1", "allocation_status": "covered"}]), "P1", "lock"
    )
    assert error
    assert "Tính lại" in error
    assert "sau khi đã tính" not in error  # not the generic not-yet-calculated reason


def test_lock_allows_post_mig_sheet():
    from app.web.co_case_context import origin_sheet_action_error
    error = origin_sheet_action_error(
        _sheet([{"material_code": "M1", "allocation_status": "covered", "customs_relevance": ""}]),
        "P1", "lock",
    )
    assert error == ""


# --- belt 3: export blockers ---

def test_export_blocks_pre_mig_sheet():
    from app.web.co_case_context import origin_sheet_export_blockers
    blockers = origin_sheet_export_blockers(
        _sheet([{"material_code": "M1", "allocation_status": "covered"}])
    )
    assert "P1" in blockers


def test_export_blocks_pre_mig_sheet_even_when_locked():
    # DC3b: a sheet LOCKED before mig 078 still has un-stripped rác — export must
    # block it (status "locked" alone would let it through) until a re-Tính.
    from app.web.co_case_context import origin_sheet_export_blockers
    blockers = origin_sheet_export_blockers(
        _sheet([{"material_code": "M1", "allocation_status": "covered"}], status="locked")
    )
    assert "P1" in blockers


def test_export_allows_post_mig_sheet():
    from app.web.co_case_context import origin_sheet_export_blockers
    blockers = origin_sheet_export_blockers(
        _sheet([{"material_code": "M1", "allocation_status": "covered", "customs_relevance": ""}])
    )
    assert "P1" not in blockers
