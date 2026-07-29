"""Regression lock for the two shipped defense-in-depth hard-block belts.

Each belt is a triple belt guarding LVC integrity of a committed C/O dossier:

  flag  →  /calculate parks the sheet at 'bom_loaded' (calculated_sheet_status)
        →  lock gate re-checks the flag (409 block, bypassing the status hardcode)
        →  export blocker / export strip re-checks the flag.

Belt 1 — `lvc_missing_price` (b89e187, 2026-07-11): a non-originating NVL with no
đơn giá understates VNM, so LVC is only tạm-tính. Blocks calc-advance, lock, export.

Belt 2 — `lvc_declarable_unmatched` ("DC3c"): a declarable NVL with 0 BCCT import
match is export-excluded yet contributes 0 to VNM, inflating LVC. Blocks
calc-advance, lock, export — AND the row is stripped from every bảng kê renderer.

These assertions mirror how the two per-belt guard suites call the pure helpers
(test_missing_price_lock_guard.py, test_declarable_unmatched_guard.py). This file
locks the FULL matrix (both belts × each segment) in one place and adds the
segments those suites do not assert directly:
  - belt-1 flag DERIVED from an empty unit_value (not a hardcoded valuation_status);
  - belt-1 end-to-end enrich → calculated_sheet_status == 'bom_loaded';
  - belt-1 invariant: a missing-price row is NOT stripped from export (it blocks the
    whole sheet, it is not silently dropped like a declarable_unmatched row);
  - belt-2 export STRIP predicate (is_bom_technical_noise) — the exact gate all
    three export renderers use to drop the row;
  - both-flags precedence at the lock gate.

The true HTTP-409 wiring of the lock route is DB-backed and cannot run file-mode;
it is captured as an explicit skip below (see test_lock_route_maps_block_to_409).
"""
from __future__ import annotations

import pytest

from app.origin_material_filters import is_bom_technical_noise, is_declarable_unmatched
from app.routers.co_case import calculated_sheet_status
from app.web.co_case_context import (
    enrich_origin_product,
    origin_sheet_action_error,
    origin_sheet_export_blockers,
)

# The Vietnamese fragments the lock gate emits per belt (co_case_context.py).
MISSING_PRICE_LOCK_FRAGMENT = "thiếu đơn giá"
UNMATCHED_LOCK_FRAGMENT = "declarable_unmatched"


def _case_with_calculated_sheet(product: dict) -> dict:
    """Wrap a (possibly enriched) product in a case whose sheet is mis-persisted
    as 'calculated' — the exact bypass the belts defend against: the save /
    bulk-substitute routes hardcode status 'calculated' instead of going through
    calculated_sheet_status, so the lock gate and export blocker must re-check the
    flag, not trust the status."""
    code = str(product.get("code") or "P1")
    return {
        "products": [product],
        "origin_sheet_states": {code: {"status": "calculated"}},
    }


# ---------------------------------------------------------------------------
# Belt 1 — lvc_missing_price
# ---------------------------------------------------------------------------

def test_belt1_flag_derives_from_empty_unit_value():
    # Segment (a). Stronger than the per-belt suite: valuation_status is NOT
    # hardcoded — enrich_origin_material derives "missing_unit_value" from the empty
    # unit_value, and only then does the product flag trip. A non-origin NVL.
    p = enrich_origin_product({
        "code": "P1", "fob": "100",
        "materials": [{"material_code": "M", "origin_status": "non_origin", "unit_value": ""}],
    })
    assert p["materials"][0]["valuation_status"] == "missing_unit_value"
    assert p["lvc_missing_price"] is True


def test_belt1_flag_off_for_origin_material_without_price():
    # An ORIGIN material never enters VNM, so a missing price does not inflate LVC.
    p = enrich_origin_product({
        "code": "P1", "fob": "100",
        "materials": [{"material_code": "M", "origin_status": "origin", "unit_value": ""}],
    })
    assert p["lvc_missing_price"] is False


def test_belt1_calc_status_parks_at_bom_loaded_end_to_end():
    # Segment (b). Full path: enrich a priced-but-non-origin-missing sheet, then
    # derive its status — it must NOT advance to 'calculated'.
    enriched = enrich_origin_product({
        "code": "P1", "fob": "1000",
        "materials": [
            {"material_code": "OK", "origin_status": "non_origin", "unit_value": "5"},
            {"material_code": "NOPRICE", "origin_status": "non_origin", "unit_value": ""},
        ],
    })
    assert enriched["lvc_missing_price"] is True
    assert calculated_sheet_status(enriched) == "bom_loaded"


def test_belt1_calc_status_advances_when_priced():
    # Control: a fully-priced non-origin sheet DOES become 'calculated'.
    enriched = enrich_origin_product({
        "code": "P1", "fob": "1000",
        "materials": [{"material_code": "OK", "origin_status": "non_origin", "unit_value": "5"}],
    })
    assert enriched["lvc_missing_price"] is False
    assert calculated_sheet_status(enriched) == "calculated"


def test_belt1_lock_blocked_even_when_status_calculated():
    # Segment (c). Enrich for real, then mis-persist as 'calculated' → still blocked.
    enriched = enrich_origin_product({
        "code": "P1", "fob": "100",
        "materials": [{"material_code": "M", "origin_status": "non_origin", "unit_value": ""}],
    })
    error = origin_sheet_action_error(_case_with_calculated_sheet(enriched), "P1", "lock")
    assert MISSING_PRICE_LOCK_FRAGMENT in error
    # not the generic "loop through Tính" reason — this is the belt, not a stale sheet.
    assert "sau khi đã tính" not in error


def test_belt1_export_blocked_even_when_status_calculated():
    # Segment (d). The missing-price sheet is an export blocker despite status.
    enriched = enrich_origin_product({
        "code": "P1", "fob": "100",
        "materials": [{"material_code": "M", "origin_status": "non_origin", "unit_value": ""}],
    })
    assert "P1" in origin_sheet_export_blockers(_case_with_calculated_sheet(enriched))


def test_belt1_missing_price_row_is_not_stripped_from_export():
    # Invariant: a missing-price NVL is a REAL material — the belt blocks the whole
    # sheet, it does NOT silently drop the row (that is the declarable_unmatched
    # behavior, belt 2). If this row were stripped, the sheet could look complete
    # while the priced rows alone pass, hiding the block.
    material = {"material_code": "M", "origin_status": "non_origin", "unit_value": ""}
    assert is_bom_technical_noise(material) is False


# ---------------------------------------------------------------------------
# Belt 2 — lvc_declarable_unmatched (DC3c)
# ---------------------------------------------------------------------------

def test_belt2_flag_sets_on_declarable_unmatched():
    # Segment (a). Real filter path: customs_relevance == "declarable_unmatched"
    # → per-material declarable_unmatched → product flag.
    p = enrich_origin_product({
        "code": "P1", "fob": "100",
        "materials": [{"material_code": "STEEL", "customs_relevance": "declarable_unmatched"}],
    })
    assert p["materials"][0]["declarable_unmatched"] is True
    assert p["lvc_declarable_unmatched"] is True


def test_belt2_flag_off_for_matched_declarable():
    p = enrich_origin_product({
        "code": "P1", "fob": "100",
        "materials": [{"material_code": "AL1", "customs_relevance": "declarable",
                       "hs_code": "76061190",
                       "allocation_lines": [{"import_declaration_no": "X"}]}],
    })
    assert p["lvc_declarable_unmatched"] is False


def test_belt2_calc_status_parks_at_bom_loaded_end_to_end():
    # Segment (b). A sheet mixing a matched declarable NVL with an unmatched one
    # must not become lockable.
    enriched = enrich_origin_product({
        "code": "P1", "fob": "1000",
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


def test_belt2_lock_blocked_even_when_status_calculated():
    # Segment (c).
    enriched = enrich_origin_product({
        "code": "P1", "fob": "100",
        "materials": [{"material_code": "STEEL", "customs_relevance": "declarable_unmatched"}],
    })
    error = origin_sheet_action_error(_case_with_calculated_sheet(enriched), "P1", "lock")
    assert UNMATCHED_LOCK_FRAGMENT in error


def test_belt2_export_blocked_even_when_status_calculated():
    # Segment (d) — route blocker.
    enriched = enrich_origin_product({
        "code": "P1", "fob": "100",
        "materials": [{"material_code": "STEEL", "customs_relevance": "declarable_unmatched"}],
    })
    assert "P1" in origin_sheet_export_blockers(_case_with_calculated_sheet(enriched))


def test_belt2_export_renderers_strip_the_unmatched_row():
    # Segment (d) — the STRIP half. All three export renderers gate each row on
    # `if override.get("deleted") or is_bom_technical_noise(material): continue`
    # (bang_ke_renderer.py:261, workbook_io.py:620, bang_ke_xml_generator.py:393).
    # is_bom_technical_noise folds declarable_unmatched into the export-exclude set,
    # so the unmatched row is dropped from every rendered bảng kê.
    unmatched = {"material_code": "STEEL", "customs_relevance": "declarable_unmatched"}
    assert is_declarable_unmatched(unmatched) is True
    assert is_bom_technical_noise(unmatched) is True
    # a matched declarable row is NOT stripped.
    matched = {"material_code": "AL1", "customs_relevance": "declarable"}
    assert is_bom_technical_noise(matched) is False


# ---------------------------------------------------------------------------
# Cross-belt: precedence and the status matrix
# ---------------------------------------------------------------------------

def test_calc_status_matrix_each_flag_parks_independently():
    # Any single belt flag holds the sheet at bom_loaded; only an all-clear sheet
    # advances. Locks the branch order in calculated_sheet_status.
    assert calculated_sheet_status({"lvc_status": "pass"}) == "calculated"
    assert calculated_sheet_status({"lvc_status": "missing_bom"}) == "bom_loaded"
    assert calculated_sheet_status({"lvc_status": "pass", "lvc_missing_price": True}) == "bom_loaded"
    assert calculated_sheet_status({"lvc_status": "pass", "lvc_declarable_unmatched": True}) == "bom_loaded"


def test_both_flags_trip_and_lock_gate_reports_unmatched_first():
    # A single non-origin declarable_unmatched NVL with no price trips BOTH belt
    # flags. calculated_sheet_status still parks the sheet; the lock gate checks
    # declarable_unmatched BEFORE missing_price (co_case_context.py order), so the
    # unmatched remedy (match/substitute) is surfaced, not "add a price".
    enriched = enrich_origin_product({
        "code": "P1", "fob": "100",
        "materials": [{"material_code": "STEEL", "customs_relevance": "declarable_unmatched",
                       "origin_status": "non_origin", "unit_value": ""}],
    })
    assert enriched["lvc_missing_price"] is True
    assert enriched["lvc_declarable_unmatched"] is True
    assert calculated_sheet_status(enriched) == "bom_loaded"
    error = origin_sheet_action_error(_case_with_calculated_sheet(enriched), "P1", "lock")
    assert UNMATCHED_LOCK_FRAGMENT in error
    assert MISSING_PRICE_LOCK_FRAGMENT not in error


# ---------------------------------------------------------------------------
# Segment (c) at the HTTP layer — not exercisable file-mode.
# ---------------------------------------------------------------------------

@pytest.mark.skip(
    reason="Route-level HTTP 409 needs a DB-backed case load. lock_co_case_origin_sheet "
    "(co_case.py:2248-2253) maps a non-empty origin_sheet_action_error to "
    "TemplateResponse(status_code=409); origin_case_from_request + co_case_context "
    "require a persisted case + Data Hub, unavailable in file-mode (no .env). The "
    "pure-helper block-error assertions above cover the belt logic the route depends on."
)
def test_lock_route_maps_block_to_409():
    raise AssertionError("documentation-only; skipped in file-mode")
