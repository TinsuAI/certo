"""Shortage guard (VN-origin ticket #8): a sheet whose consumed quantity exceeds
its matched import lots — including a material with no matched lot at all — must
NOT be lockable/exportable. The shortfall has no lawful value on the bảng kê
(TT 05/2018 Điều 6.4.b: only import-CIF-tied or VAT-invoice-tied values exist),
so issuing from it ships an unlawful document. The remedy is supplying the
missing document (match the import declaration / enter the VAT invoice), never
an estimated price — the BOM/catalog fallback price for no-lot materials is gone.

Reverses the pre-ADR behaviour pinned in test_missing_price_lock_guard.py
("shortage stays lockable"): ADR 2026-07-11 decides shortage blocks issuance.
Three belts, mirroring the declarable_unmatched guard: (1) status derivation,
(2) lock gate re-check (with a shortage-specific reason, not a generic
"not calculated" that loops the user through Tính), (3) export blockers.
The missing_price status-downgrade branch is untouched (hard constraint).
"""
from __future__ import annotations

from decimal import Decimal


# --- flag derivation (enrich) ---

def test_enrich_flags_partial_shortage():
    from app.web.co_case_context import enrich_origin_product
    p = enrich_origin_product({
        "code": "P", "fob": "100",
        "materials": [{"material_code": "M", "origin_status": "non_origin", "unit_value": "5",
                       "valuation_status": "partial_allocation", "allocation_status": "shortage",
                       "allocation_lines": [{"import_declaration_no": "X", "allocated_qty": "1"}]}],
    })
    assert p["lvc_allocation_shortage"] is True


def test_enrich_flags_no_lot_material():
    from app.web.co_case_context import enrich_origin_product
    p = enrich_origin_product({
        "code": "P", "fob": "100",
        "materials": [{"material_code": "M", "origin_status": "non_origin", "unit_value": "5",
                       "allocation_status": "shortage"}],
    })
    assert p["lvc_allocation_shortage"] is True


def test_enrich_no_flag_when_covered():
    from app.web.co_case_context import enrich_origin_product
    p = enrich_origin_product({
        "code": "P", "fob": "100",
        "materials": [{"material_code": "M", "origin_status": "non_origin", "unit_value": "5",
                       "valuation_status": "ready", "allocation_status": "covered",
                       "allocation_lines": [{"import_declaration_no": "X", "allocated_qty": "1"}]}],
    })
    assert p["lvc_allocation_shortage"] is False


def test_enrich_ignores_deleted_and_noise_rows():
    from app.web.co_case_context import enrich_origin_product
    p = enrich_origin_product({
        "code": "P", "fob": "100",
        "materials": [
            {"material_code": "GONE", "allocation_status": "shortage", "deleted": True},
            {"material_code": "GLUE", "allocation_status": "shortage",
             "customs_relevance": "excluded_non_material"},
            {"material_code": "OK", "origin_status": "non_origin", "unit_value": "5",
             "valuation_status": "ready", "allocation_status": "covered",
             "allocation_lines": [{"import_declaration_no": "X"}]},
        ],
    })
    assert p["lvc_allocation_shortage"] is False


# --- belt 1: status derivation ---

def test_calculated_status_parks_shortage_sheet():
    from app.routers.co_case import calculated_sheet_status
    assert calculated_sheet_status({"lvc_status": "pass", "lvc_allocation_shortage": True}) == "bom_loaded"
    assert calculated_sheet_status({"lvc_status": "pass", "lvc_allocation_shortage": False}) == "calculated"


def test_missing_price_downgrade_branch_untouched():
    # HARD constraint: the shortage guard must not ride with removing the
    # status-downgrade branches — missing_price is enforced only there today.
    from app.routers.co_case import calculated_sheet_status
    assert calculated_sheet_status({"lvc_status": "partial_pass", "lvc_missing_price": True}) == "bom_loaded"
    assert calculated_sheet_status({"lvc_status": "missing_bom"}) == "bom_loaded"
    assert calculated_sheet_status({"lvc_status": "pass", "lvc_declarable_unmatched": True}) == "bom_loaded"


# --- belt 2: lock gate re-check (save-route status hardcode bypass) ---

def test_lock_gate_blocks_shortage_even_when_status_calculated():
    from app.web.co_case_context import origin_sheet_action_error
    case = {
        "products": [{"code": "P1", "lvc_status": "pass", "lvc_allocation_shortage": True}],
        "origin_sheet_states": {"P1": {"status": "calculated"}},
    }
    error = origin_sheet_action_error(case, "P1", "lock")
    assert "thiếu tồn" in error
    assert "chứng từ" in error  # remedy: supply the document, never a price


def test_lock_gate_reason_is_shortage_specific_not_generic():
    from app.web.co_case_context import origin_sheet_action_error
    case = {
        "products": [{"code": "P1", "lvc_status": "pass", "lvc_allocation_shortage": True}],
        "origin_sheet_states": {"P1": {"status": "calculated"}},
    }
    error = origin_sheet_action_error(case, "P1", "lock")
    assert "sau khi đã tính" not in error  # not the generic loop-through-Tính reason


def test_lock_block_reason_surfaces_on_sheet_state():
    # Pre-action surface: a shortage sheet parked at bom_loaded must SAY shortage,
    # not invite another Tính.
    from app.web.co_case_context import attach_origin_sheet_states
    case = {
        "products": [{"code": "P1", "lvc_status": "pass", "lvc_allocation_shortage": True}],
        "origin_sheet_states": {"P1": {"status": "bom_loaded"}},
    }
    product = attach_origin_sheet_states(case)["products"][0]
    assert product["origin_can_lock"] is False
    assert "thiếu tồn" in product["origin_lock_block_reason"]


# --- belt 3: export blockers ---

def test_export_blocks_shortage_even_when_status_calculated():
    from app.web.co_case_context import origin_sheet_export_blockers
    case = {
        "products": [{"code": "P1", "lvc_status": "pass", "lvc_allocation_shortage": True}],
        "origin_sheet_states": {"P1": {"status": "calculated"}},
    }
    assert "P1" in origin_sheet_export_blockers(case)


# --- fallback price removal: no document, no value ---

def test_no_lot_material_gets_no_fallback_price():
    from app.web.co_case_context import origin_material_from_bom_row
    row = {"material_code": "NVL-1", "qty_per": "2", "unit_value": "7"}
    material = origin_material_from_bom_row(
        row, Decimal("3"), {"NVL-1": {"unit_price": "9"}}, {}, product_code="TP1", product_name="SP",
    )
    assert material["allocation_status"] == "shortage"
    assert material["material_value"] == ""  # BOM price 7 / catalog 9 must NOT price 6 units
    assert material["non_origin_cif_value"] == ""


def test_covered_material_still_priced_from_lots():
    from app.web.co_case_context import origin_material_from_bom_row
    stock = {
        "source_row": "ROW-1", "material_code": "NVL-1", "allocation_code": "NVL-1",
        "customs_item_code": "NVL-1", "import_declaration_no": "D100",
        "registration_date": "2026-04-21", "line_no": "1", "value_currency": "VND",
        "currency": "VND", "unit_value": "1000", "remaining_qty": "100",
        "available_qty": "100", "exchange_rate_to_vnd": "1", "exchange_rate_source": "vnd_native",
    }
    row = {"material_code": "NVL-1", "qty_per": "1"}
    material = origin_material_from_bom_row(
        row, Decimal("5"), {}, {"NVL-1": [stock]}, product_code="TP1", product_name="SP",
    )
    assert material["allocation_status"] == "covered"
    assert material["material_value"] == "5000"


def test_no_lot_material_warning_names_the_document_remedy():
    from app.web.co_case_context import origin_material_from_bom_row
    row = {"material_code": "NVL-1", "qty_per": "1", "unit_value": "7"}
    material = origin_material_from_bom_row(
        row, Decimal("3"), {}, {}, product_code="TP1", product_name="SP",
    )
    assert any("chứng từ" in warning for warning in material["material_warnings"])
    # The defect is the missing document, not a missing price — no price warning,
    # no "missing_unit_value" classification for a no-lot line.
    assert not any("thiếu đơn giá" in warning for warning in material["material_warnings"])
    assert material["valuation_status"] == "partial_allocation"


def test_real_flow_no_lot_block_reason_names_document_not_price():
    # Real flow, not hand-set flags: a no-lot non-origin material also trips
    # lvc_missing_price (its value is empty by design), and the pre-action block
    # reason must STILL name the document remedy, never "bổ sung đơn giá".
    from app.web.co_case_context import (
        attach_origin_sheet_states,
        enrich_origin_product,
        origin_material_from_bom_row,
    )
    material = origin_material_from_bom_row(
        {"material_code": "NVL-1", "qty_per": "1", "unit_value": "7"},
        Decimal("3"), {}, {}, product_code="TP1", product_name="SP",
    )
    enriched = enrich_origin_product({"code": "P1", "fob": "100", "materials": [material]})
    assert enriched["lvc_allocation_shortage"] is True
    case = {
        "products": [enriched],
        "origin_sheet_states": {"P1": {"status": "bom_loaded"}},
    }
    product = attach_origin_sheet_states(case)["products"][0]
    assert "chứng từ" in product["origin_lock_block_reason"]
    assert "bổ sung đơn giá" not in product["origin_lock_block_reason"]
