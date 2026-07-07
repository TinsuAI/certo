"""M2 — plan_shortfall_substitution: expand a 'thay NVL' choice into the
per-product substitutions the bulk-substitute route consumes.

mode="only_short"  → target only sheets where the material is short (thiếu tồn)
mode="everywhere"  → target every sheet that uses the material (thay hết)

Locked sheets can't be edited (bulk-substitute skips them) → excluded from the
plan and reported as locked_count. Pure read over an allocated case.
"""
from __future__ import annotations


def _case(products):
    return {"products": products, "origin_sheet_states": {}}


def _mat(code, status="covered"):
    return {"material_code": code, "allocation_status": status}


def test_plan_everywhere_targets_all_sheets_using_material():
    from app.substitution_plan import plan_shortfall_substitution
    case = _case([
        {"code": "P1", "materials": [_mat("A", "covered")]},
        {"code": "P2", "materials": [_mat("A", "shortage")]},
        {"code": "P3", "materials": [_mat("B", "covered")]},  # does NOT use A
    ])
    plan = plan_shortfall_substitution(case, "A", "A-SUB", "everywhere")
    assert sorted(s["product_code"] for s in plan["substitutions"]) == ["P1", "P2"]
    assert plan["summary"]["target_count"] == 2
    assert plan["summary"]["short_count"] == 1
    assert plan["summary"]["using_count"] == 2


def test_plan_only_short_targets_short_sheets():
    from app.substitution_plan import plan_shortfall_substitution
    case = _case([
        {"code": "P1", "materials": [_mat("A", "covered")]},
        {"code": "P2", "materials": [_mat("A", "shortage")]},
    ])
    plan = plan_shortfall_substitution(case, "A", "A-SUB", "only_short")
    assert [s["product_code"] for s in plan["substitutions"]] == ["P2"]
    assert plan["summary"]["target_count"] == 1
    assert plan["summary"]["short_count"] == 1
    assert plan["summary"]["using_count"] == 2


def test_plan_excludes_locked_sheets_and_counts_them():
    from app.substitution_plan import plan_shortfall_substitution
    case = _case([
        {"code": "P1", "origin_sheet_status": "locked", "materials": [_mat("A", "shortage")]},
        {"code": "P2", "materials": [_mat("A", "shortage")]},
    ])
    plan = plan_shortfall_substitution(case, "A", "A-SUB", "everywhere")
    assert [s["product_code"] for s in plan["substitutions"]] == ["P2"]
    assert plan["summary"]["locked_count"] == 1
    assert plan["summary"]["using_count"] == 1  # locked sheet not counted as usable


def test_plan_carries_substitute_fields():
    from app.substitution_plan import plan_shortfall_substitution
    case = _case([{"code": "P1", "materials": [_mat("A", "shortage")]}])
    plan = plan_shortfall_substitution(
        case, "A", "A-SUB", "everywhere",
        substitute_fields={"name": "Nhôm SUB", "uom": "kg", "hs_code": "760612", "ignored": "x"},
    )
    sub = plan["substitutions"][0]
    assert sub["name"] == "Nhôm SUB" and sub["uom"] == "kg" and sub["hs_code"] == "760612"
    assert "ignored" not in sub


def test_plan_unknown_mode_defaults_to_only_short():
    from app.substitution_plan import plan_shortfall_substitution
    case = _case([
        {"code": "P1", "materials": [_mat("A", "covered")]},
        {"code": "P2", "materials": [_mat("A", "shortage")]},
    ])
    plan = plan_shortfall_substitution(case, "A", "A-SUB", "bogus")
    assert [s["product_code"] for s in plan["substitutions"]] == ["P2"]
    assert plan["summary"]["mode"] == "only_short"


def test_plan_matches_internal_material_code_and_skips_deleted():
    from app.substitution_plan import plan_shortfall_substitution
    case = _case([
        {"code": "P1", "materials": [{"internal_material_code": "A", "allocation_status": "shortage"}]},
        {"code": "P2", "materials": [{"material_code": "A", "allocation_status": "shortage", "deleted": True}]},
    ])
    plan = plan_shortfall_substitution(case, "A", "A-SUB", "everywhere")
    # P1 matched via internal_material_code; P2's only A-row is soft-deleted → not used
    assert [s["product_code"] for s in plan["substitutions"]] == ["P1"]
