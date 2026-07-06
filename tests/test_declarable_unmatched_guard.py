"""DC3c guard: a sheet carrying a `declarable_unmatched` NVL (a real, declarable
material with NO BCCT import match) must NOT be lockable/exportable. Such a
material is export-excluded from the bảng kê yet contributes 0 to VNM, so LVC is
inflated (understated non-origin value) — committing/issuing a C/O from it would
carry a wrong LVC.

Mirrors the missing-price guard: `/calculate` parks the sheet at 'bom_loaded'
(non-lockable via status!=calculated, non-exportable via the bom_loaded blocker)
until the unmatched material is resolved (matched or substituted).
"""
from __future__ import annotations


def test_enrich_flags_declarable_unmatched():
    from app.web.co_case_context import enrich_origin_product
    p = enrich_origin_product({
        "code": "P", "fob": "100",
        "materials": [{"material_code": "STEEL", "customs_relevance": "declarable_unmatched"}],
    })
    assert p["lvc_declarable_unmatched"] is True


def test_enrich_no_flag_when_matched_declarable():
    # a matched, declarable material is emitted normally -> not flagged
    from app.web.co_case_context import enrich_origin_product
    p = enrich_origin_product({
        "code": "P", "fob": "100",
        "materials": [{"material_code": "AL1", "customs_relevance": "declarable",
                       "hs_code": "76061190", "allocation_lines": [{"import_declaration_no": "X"}]}],
    })
    assert p["lvc_declarable_unmatched"] is False


def test_enrich_ignores_deleted_unmatched():
    # a deleted unmatched row is not in the bảng kê -> does not block
    from app.web.co_case_context import enrich_origin_product
    p = enrich_origin_product({
        "code": "P", "fob": "100",
        "materials": [
            {"material_code": "STEEL", "customs_relevance": "declarable_unmatched", "deleted": True},
            {"material_code": "AL1", "customs_relevance": "declarable", "hs_code": "76061190",
             "allocation_lines": [{"import_declaration_no": "X"}]},
        ],
    })
    assert p["lvc_declarable_unmatched"] is False


def test_calculated_status_parks_unmatched_sheet():
    from app.routers.co_case import calculated_sheet_status
    assert calculated_sheet_status({"lvc_status": "pass", "lvc_declarable_unmatched": True}) == "bom_loaded"
    # a clean sheet stays calculated/lockable
    assert calculated_sheet_status({"lvc_status": "pass", "lvc_declarable_unmatched": False}) == "calculated"


def test_calculate_parks_sheet_with_unmatched_material_end_to_end():
    # the real /calculate path: enrich the product, then derive its status. A sheet
    # mixing a matched declarable NVL with an unmatched one must not become lockable.
    from app.web.co_case_context import enrich_origin_product
    from app.routers.co_case import calculated_sheet_status
    enriched = enrich_origin_product({
        "code": "P", "fob": "1000",
        "materials": [
            {"material_code": "AL1", "customs_relevance": "declarable", "origin_status": "non_origin",
             "unit_value": "5", "hs_code": "76061190",
             "allocation_lines": [{"import_declaration_no": "X", "used_qty": "1"}]},
            {"material_code": "STEEL", "customs_relevance": "declarable_unmatched",
             "origin_status": "non_origin", "unit_value": "3"},
        ],
    })
    assert enriched["lvc_declarable_unmatched"] is True
    assert calculated_sheet_status(enriched) == "bom_loaded"


def test_export_blocks_unmatched_sheet():
    # a sheet parked at bom_loaded (because it has an unmatched NVL) is an export blocker
    from app.web.co_case_context import origin_sheet_export_blockers
    case = {
        "products": [{"code": "P1", "name": "P1", "materials": [{"material_code": "STEEL"}],
                      "lvc_status": "pass", "origin_sheet_status": "bom_loaded"}],
        "origin_sheet_states": {"P1": {"status": "bom_loaded", "status_label": "bom_loaded"}},
    }
    assert "P1" in origin_sheet_export_blockers(case)


# --- Defense-in-depth: the hard-block must hold even when a sheet is mis-persisted
# as "calculated" while still carrying an active unmatched NVL. The save and
# bulk-substitute routes recompute a sheet then hardcode status "calculated"
# (bypassing calculated_sheet_status), so status alone can't be trusted at the
# lock gate / export blocker — they re-check the flag directly (like the missing_bom
# guard does).

def test_lock_gate_blocks_unmatched_even_when_status_calculated():
    from app.web.co_case_context import origin_sheet_action_error
    case = {
        "products": [{"code": "P1", "lvc_status": "pass", "lvc_declarable_unmatched": True}],
        "origin_sheet_states": {"P1": {"status": "calculated"}},
    }
    assert origin_sheet_action_error(case, "P1", "lock") != ""


def test_export_blocks_unmatched_even_when_status_calculated():
    from app.web.co_case_context import origin_sheet_export_blockers
    case = {
        "products": [{"code": "P1", "lvc_status": "pass", "lvc_declarable_unmatched": True}],
        "origin_sheet_states": {"P1": {"status": "calculated"}},
    }
    assert "P1" in origin_sheet_export_blockers(case)
