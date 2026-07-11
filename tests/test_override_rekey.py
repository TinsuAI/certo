"""Override identity re-key (VN-origin ticket #7, part A).

Per-material overrides stop being keyed by the positional render index and
become keyed by `material_sequence` (1-based, stable because a BOM version is an
immutable artifact) and `added_<n>` for hand-added rows. The binding is
version-aware: overrides written against BOM version A are not applied while
version B is selected (they are kept, not dropped — switching back re-applies).
Legacy positional keys migrate deterministically (index+1) at case load, marked
with `override_key_scheme` so migration never runs twice.
"""
from __future__ import annotations

from app.co_case_store import OVERRIDE_KEY_SCHEME, case_from_record, migrated_override_keys
from app.origin_material_filters import material_override_key
from app.web.co_case_context import attach_origin_sheet_states


# --- key helper ---

def test_material_override_key_prefers_material_sequence():
    assert material_override_key({"material_sequence": "3"}, 0) == "3"


def test_material_override_key_falls_back_to_position_plus_one():
    assert material_override_key({}, 0) == "1"
    assert material_override_key({"material_sequence": ""}, 4) == "5"


# --- legacy migration ---

def test_migrates_legacy_positional_keys_to_sequence():
    state = {
        "status": "calculated",
        "material_overrides": {"0": {"deleted": True}, "2": {"material_code": "X"}, "added_0": {"added": True}},
        "override_history": [{"0": {"deleted": True}}],
        "override_redo": [{"1": {"norm_per_unit": "2"}}],
    }
    migrated = migrated_override_keys(state)
    assert set(migrated["material_overrides"]) == {"1", "3", "added_0"}
    assert migrated["material_overrides"]["1"] == {"deleted": True}
    assert migrated["material_overrides"]["3"] == {"material_code": "X"}
    assert migrated["override_history"] == [{"1": {"deleted": True}}]
    assert migrated["override_redo"] == [{"2": {"norm_per_unit": "2"}}]
    assert migrated["override_key_scheme"] == OVERRIDE_KEY_SCHEME


def test_migration_is_marked_and_never_runs_twice():
    state = {"material_overrides": {"0": {"deleted": True}}}
    once = migrated_override_keys(state)
    twice = migrated_override_keys(once)
    assert twice["material_overrides"] == {"1": {"deleted": True}}  # not shifted again


def test_case_from_record_migrates_sheet_states():
    record = {
        "case_id": "c1",
        "case_code": "C1",
        "title": "T",
        "destination_market": "EU",
        "origin_sheet_states": {
            "P1": {"status": "locked", "material_overrides": {"1": {"material_code": "SUB"}}},
        },
    }
    case = case_from_record({}, {"id": "demo", "name": "N"}, record)
    state = case["origin_sheet_states"]["P1"]
    assert state["material_overrides"] == {"2": {"material_code": "SUB"}}
    assert state["override_key_scheme"] == OVERRIDE_KEY_SCHEME


# --- version-aware binding ---

def _case_with_override(stored_artifact: str, current_artifact: str) -> dict:
    return {
        "products": [{
            "code": "P1",
            "bom_product_artifact_id": current_artifact,
            "materials": [{"material_code": "M1", "material_sequence": "1"}],
        }],
        "origin_sheet_states": {"P1": {
            "status": "calculated",
            "material_overrides": {"1": {"material_code": "SUB"}},
            "override_key_scheme": OVERRIDE_KEY_SCHEME,
            "overrides_artifact_id": stored_artifact,
        }},
    }


def test_override_made_under_version_a_does_not_apply_under_version_b():
    product = attach_origin_sheet_states(_case_with_override("art-A", "art-B"))["products"][0]
    assert product["origin_sheet_material_overrides"] == {}
    assert product["origin_sheet_overrides_version_mismatch"] is True
    assert product["origin_sheet_material_diff_total"] == 0


def test_override_applies_when_versions_match():
    product = attach_origin_sheet_states(_case_with_override("art-A", "art-A"))["products"][0]
    assert product["origin_sheet_material_overrides"] == {"1": {"material_code": "SUB"}}
    assert product["origin_sheet_overrides_version_mismatch"] is False


def test_override_without_stored_version_still_applies():
    product = attach_origin_sheet_states(_case_with_override("", "art-B"))["products"][0]
    assert product["origin_sheet_material_overrides"] == {"1": {"material_code": "SUB"}}
    assert product["origin_sheet_overrides_version_mismatch"] is False


def test_switching_back_to_version_a_reapplies_kept_overrides():
    case = _case_with_override("art-A", "art-B")
    prepared = attach_origin_sheet_states(case)
    # The stored map is kept on the sheet state even while inapplicable.
    assert prepared["origin_sheet_states"]["P1"]["material_overrides"] == {"1": {"material_code": "SUB"}}
    case_back = _case_with_override("art-A", "art-A")
    product = attach_origin_sheet_states(case_back)["products"][0]
    assert product["origin_sheet_material_overrides"] == {"1": {"material_code": "SUB"}}


# --- write under a different version must not rebind kept overrides ---

def test_writable_overrides_starts_empty_under_version_mismatch():
    from app.routers.co_case import writable_overrides
    previous = {
        "material_overrides": {"3": {"material_code": "OLD-SUB"}},
        "overrides_artifact_id": "art-A",
        "override_key_scheme": OVERRIDE_KEY_SCHEME,
    }
    overrides, mismatch = writable_overrides(previous, {"bom_product_artifact_id": "art-B"})
    assert overrides == {}
    assert mismatch is True


def test_writable_overrides_merges_when_versions_match_or_unbound():
    from app.routers.co_case import writable_overrides
    previous = {"material_overrides": {"3": {"material_code": "OLD-SUB"}}, "overrides_artifact_id": "art-A"}
    same, mismatch_same = writable_overrides(previous, {"bom_product_artifact_id": "art-A"})
    assert same == {"3": {"material_code": "OLD-SUB"}}
    assert mismatch_same is False
    unbound, mismatch_unbound = writable_overrides(
        {"material_overrides": {"3": {"material_code": "OLD-SUB"}}, "overrides_artifact_id": ""},
        {"bom_product_artifact_id": "art-B"},
    )
    assert unbound == {"3": {"material_code": "OLD-SUB"}}
    assert mismatch_unbound is False


# --- readers keyed by sequence ---

def test_sheet_edit_bom_rows_applies_override_by_sequence():
    from app.routers.co_case import sheet_edit_bom_rows
    product = {
        "code": "P1",
        "materials": [
            {"material_code": "A", "material_sequence": "1", "bom_qty_per": "1", "uom": "PCE"},
            {"material_code": "B", "material_sequence": "2", "bom_qty_per": "1", "uom": "PCE"},
        ],
    }
    rows = sheet_edit_bom_rows(product, {"2": {"deleted": True}})
    by_code = {row["material_code"]: row for row in rows}
    assert by_code["B"].get("deleted") is True
    assert "deleted" not in by_code["A"]


def test_renderer_applies_override_by_sequence():
    from openpyxl import Workbook
    from app.bang_ke_renderer import load_form_config, render_into_sheet

    cfg = load_form_config("LVC")
    wb = Workbook()
    ws = wb.active
    product = {
        "code": "P1",
        "origin_sheet_material_overrides": {"1": {"material_code": "SUB-1", "name": "Đã thay"}},
        "materials": [{
            "material_code": "ORIG-1", "material_sequence": "1", "material_description": "Gốc",
            "origin_status": "non_origin", "hs_code": "73182200", "uom": "PCE",
            "bom_qty_per": "1", "consumed_qty": "1", "unit_value": "1", "material_value": "1",
        }],
    }
    render_into_sheet(ws, cfg, case={"case_code": "C", "products": [product]}, product=product, sheet_title="P1")
    col, start = cfg["body"]["columns"]["material_code"], cfg["body"]["start_row"]
    assert ws[f"{col}{start}"].value == "SUB-1"
