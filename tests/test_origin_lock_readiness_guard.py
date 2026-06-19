"""Guard: a 'calculated' sheet with NO active materials (empty/no-BOM) must not
be lockable or exportable — locking it commits an empty bảng kê + 0 ledger
claims. The narrow signal is 'no active (non-deleted) material' (⟺ lvc_status
'missing_bom'); shortage / missing-unit-value sheets DO have materials and stay
lockable (no behaviour change).
"""
from __future__ import annotations


def _case(materials, *, status="calculated", lvc_status="pass"):
    return {
        "products": [{
            "code": "P1", "name": "P1", "materials": materials,
            "lvc_status": lvc_status, "origin_sheet_status": status,
        }],
        "origin_sheet_states": {"P1": {"status": status, "status_label": status}},
    }


def test_lock_blocked_when_no_active_materials():
    from app.main import origin_sheet_action_error
    err = origin_sheet_action_error(_case([], lvc_status="missing_bom"), "P1", "lock")
    assert err and ("BOM" in err or "NVL" in err)


def test_lock_blocked_when_all_materials_deleted():
    from app.main import origin_sheet_action_error
    case = _case([{"material_code": "M1", "deleted": True}], lvc_status="missing_bom")
    assert origin_sheet_action_error(case, "P1", "lock")


def test_lock_allowed_with_covered_material():
    from app.main import origin_sheet_action_error
    case = _case([{"material_code": "M1", "allocation_status": "covered"}])
    assert origin_sheet_action_error(case, "P1", "lock") == ""


def test_lock_allowed_with_shortage_material_not_overblocked():
    # shortage = materials exist but insufficient stock — must STAY lockable.
    from app.main import origin_sheet_action_error
    case = _case([{"material_code": "M1", "allocation_status": "shortage"}], lvc_status="review")
    assert origin_sheet_action_error(case, "P1", "lock") == ""


def test_export_blocks_empty_calculated_sheet():
    from app.web.co_case_context import origin_sheet_export_blockers
    blockers = origin_sheet_export_blockers(_case([], lvc_status="missing_bom"))
    assert "P1" in blockers


def test_export_allows_sheet_with_materials():
    from app.web.co_case_context import origin_sheet_export_blockers
    blockers = origin_sheet_export_blockers(_case([{"material_code": "M1", "allocation_status": "covered"}]))
    assert "P1" not in blockers
