"""Guard: a 'calculated' sheet whose LVC is only a tạm-tính because a
non-originating material is missing its đơn giá (unit price) must NOT be
lockable/exportable — VNM is understated so LVC is inflated, and a committed CO
dossier would carry a provisional LVC. Mirror of the empty/no-BOM guard (#13c):
/calculate keeps such a sheet at 'bom_loaded' (non-lockable, non-exportable).

Shortage is no longer lockable: ADR 2026-07-11 decides shortage blocks issuance
via its own flag (`lvc_allocation_shortage`, see test_shortage_lock_guard.py).
The missing-price downgrade branch here is independent of that flag and stays.

Three belts (same set as shortage): /calculate parks at bom_loaded; the lock
gate re-checks the flag (the save / bulk-substitute routes hardcode status
"calculated", bypassing calculated_sheet_status); export blockers re-check it.
"""
from __future__ import annotations


def test_missing_price_stays_bom_loaded():
    from app.routers.co_case import calculated_sheet_status
    assert calculated_sheet_status({"lvc_status": "partial_pass", "lvc_missing_price": True}) == "bom_loaded"
    assert calculated_sheet_status({"lvc_status": "partial_fail", "lvc_missing_price": True}) == "bom_loaded"


def test_priced_sheet_without_shortage_flag_still_calculated():
    from app.routers.co_case import calculated_sheet_status
    assert calculated_sheet_status({"lvc_status": "partial_fail", "lvc_missing_price": False}) == "calculated"
    assert calculated_sheet_status({"lvc_status": "pass"}) == "calculated"


def test_missing_bom_still_bom_loaded():
    from app.routers.co_case import calculated_sheet_status
    assert calculated_sheet_status({"lvc_status": "missing_bom"}) == "bom_loaded"


def test_enrich_flags_missing_price_non_origin():
    from app.web.co_case_context import enrich_origin_product
    p = enrich_origin_product({
        "code": "P", "fob": "100",
        "materials": [{"material_code": "M", "origin_status": "non_origin",
                       "valuation_status": "missing_unit_value", "unit_value": ""}],
    })
    assert p["lvc_missing_price"] is True


def test_enrich_no_flag_when_origin_material_missing_price():
    # an ORIGIN (có xuất xứ) material doesn't contribute to VNM -> missing price
    # does not make LVC unreliable -> not flagged.
    from app.web.co_case_context import enrich_origin_product
    p = enrich_origin_product({
        "code": "P", "fob": "100",
        "materials": [{"material_code": "M", "origin_status": "origin",
                       "valuation_status": "missing_unit_value", "unit_value": ""}],
    })
    assert p["lvc_missing_price"] is False


def test_enrich_no_flag_when_priced_shortage():
    from app.web.co_case_context import enrich_origin_product
    p = enrich_origin_product({
        "code": "P", "fob": "100",
        "materials": [{"material_code": "M", "origin_status": "non_origin", "unit_value": "5",
                       "valuation_status": "ready", "allocation_status": "shortage"}],
    })
    assert p["lvc_missing_price"] is False


def test_enrich_ignores_deleted_missing_price():
    from app.web.co_case_context import enrich_origin_product
    p = enrich_origin_product({
        "code": "P", "fob": "100",
        "materials": [
            {"material_code": "DEL", "origin_status": "non_origin", "valuation_status": "missing_unit_value",
             "unit_value": "", "deleted": True},
            {"material_code": "OK", "origin_status": "non_origin", "unit_value": "5", "valuation_status": "ready"},
        ],
    })
    assert p["lvc_missing_price"] is False


def test_export_blocks_missing_price_sheet():
    # a bom_loaded sheet is an export blocker (status branch) — the route /calculate
    # parks a missing-price sheet at bom_loaded, so it is non-exportable.
    from app.web.co_case_context import origin_sheet_export_blockers
    case = {
        "products": [{"code": "P1", "name": "P1", "materials": [{"material_code": "M"}],
                      "lvc_status": "partial_pass", "origin_sheet_status": "bom_loaded"}],
        "origin_sheet_states": {"P1": {"status": "bom_loaded", "status_label": "bom_loaded"}},
    }
    assert "P1" in origin_sheet_export_blockers(case)


# --- belt 2: lock gate re-check (save-route status hardcode bypass) ---

def test_lock_gate_blocks_missing_price_even_when_status_calculated():
    from app.web.co_case_context import origin_sheet_action_error
    case = {
        "products": [{"code": "P1", "lvc_status": "partial_pass", "lvc_missing_price": True}],
        "origin_sheet_states": {"P1": {"status": "calculated"}},
    }
    error = origin_sheet_action_error(case, "P1", "lock")
    assert "thiếu đơn giá" in error
    assert "sau khi đã tính" not in error  # not the generic loop-through-Tính reason


def test_lock_gate_shortage_takes_precedence_over_missing_price():
    # a no-lot NVL trips BOTH flags; the remedy is the document, never a price.
    from app.web.co_case_context import origin_sheet_action_error
    case = {
        "products": [{"code": "P1", "lvc_status": "partial_pass",
                      "lvc_allocation_shortage": True, "lvc_missing_price": True}],
        "origin_sheet_states": {"P1": {"status": "calculated"}},
    }
    error = origin_sheet_action_error(case, "P1", "lock")
    assert "chứng từ" in error
    assert "thiếu đơn giá" not in error


# --- belt 3: export blockers re-check the flag ---

def test_export_blocks_missing_price_even_when_status_calculated():
    from app.web.co_case_context import origin_sheet_export_blockers
    case = {
        "products": [{"code": "P1", "lvc_status": "partial_pass", "lvc_missing_price": True}],
        "origin_sheet_states": {"P1": {"status": "calculated"}},
    }
    assert "P1" in origin_sheet_export_blockers(case)
