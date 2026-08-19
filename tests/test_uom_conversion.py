"""BOM đơn vị tính vs the import lot's đơn vị tính: convert at the line, or block.

Measured on prod johnson-vn: 226 of 3,816 allocated lines have a BOM uom that differs
from the unit on the customs lot they consume. 184 are spelling of the same unit
(EA ↔ PIECES) and convert 1:1, but 42 lines across 25 codes are genuinely different
units — EA ↔ SETS (35), EA ↔ CAY, EA ↔ KILO-GRAMMES, KG ↔ PIECES, EA ↔ METRIC-TONS —
and CO silently treated them as 1:1, so the quantity taken off the lot was wrong.

Rules:
- same unit under another name (or another language) → factor 1, no operator needed;
- same physical family (mass/length/volume) → the deterministic factor (KG→G = 1000);
- anything else (EA ↔ SETS, KG ↔ PIECES) → needs a factor a human confirms; until then
  the row allocates as before but is flagged and Chốt is blocked.
"""
from __future__ import annotations

from decimal import Decimal


def _resolve(bom_uom, lot_uom, confirmed=None):
    from app.uom_conversion import resolve_uom_factor
    return resolve_uom_factor(bom_uom, lot_uom, confirmed=confirmed)


def test_same_unit_needs_no_conversion():
    factor, source = _resolve("PIECES", "PIECES")
    assert (factor, source) == (Decimal("1"), "same_uom")


def test_alias_of_the_same_unit_is_one_to_one():
    for bom_uom, lot_uom in [("EA", "PIECES"), ("PCS", "PIECE"), ("CÁI", "PIECES"),
                             ("SET", "SETS"), ("KG", "KILO-GRAMMES"), ("CUỘN", "ROLL")]:
        factor, source = _resolve(bom_uom, lot_uom)
        assert (factor, source) == (Decimal("1"), "uom_alias"), f"{bom_uom} vs {lot_uom}"


def test_same_family_converts_deterministically():
    assert _resolve("G", "KG") == (Decimal("0.001"), "uom_family")
    assert _resolve("KG", "G") == (Decimal("1000"), "uom_family")
    assert _resolve("KG", "METRIC-TONS") == (Decimal("0.001"), "uom_family")
    assert _resolve("M", "MM") == (Decimal("1000"), "uom_family")


def test_different_families_need_a_confirmed_factor():
    for bom_uom, lot_uom in [("EA", "SETS"), ("KG", "PIECES"), ("EA", "CAY"),
                             ("EA", "METRIC-TONS")]:
        factor, source = _resolve(bom_uom, lot_uom)
        assert factor is None and source == "unconfirmed", f"{bom_uom} vs {lot_uom}"


def test_a_confirmed_factor_wins():
    factor, source = _resolve("EA", "SETS", confirmed={("EA", "SETS"): Decimal("0.2")})
    assert (factor, source) == (Decimal("0.2"), "operator_confirmed")


def test_a_material_specific_factor_beats_the_client_wide_one():
    confirmed = {("EA", "SETS"): Decimal("0.2"), ("EA", "SETS", "M1"): Decimal("0.25")}
    from app.uom_conversion import resolve_uom_factor
    factor, source = resolve_uom_factor("EA", "SETS", confirmed=confirmed, material_code="M1")
    assert (factor, source) == (Decimal("0.25"), "operator_confirmed")


def test_missing_unit_on_either_side_is_not_a_conversion_problem():
    """A lot with no unit recorded cannot be checked — treat as 1:1, do not block."""
    assert _resolve("EA", "") == (Decimal("1"), "uom_unknown")
    assert _resolve("", "PIECES") == (Decimal("1"), "uom_unknown")


# --- the store -------------------------------------------------------------

def test_factor_store_round_trip(tmp_path, monkeypatch):
    from app import uom_factor_store
    monkeypatch.setenv("CO_UOM_FACTOR_ROOT", str(tmp_path))
    uom_factor_store.set_factor(
        "acme", bom_uom="ea", lot_uom="sets", factor=Decimal("0.2"),
        confirmed_by="thanh.tam", material_code="",
    )
    rows = uom_factor_store.list_factors("acme")
    assert len(rows) == 1
    # Stored canonically (EA is a spelling of PIECES) so lookups are spelling-proof.
    assert rows[0].bom_uom == "PIECES" and rows[0].lot_uom == "SETS"
    assert rows[0].factor == Decimal("0.2")
    assert rows[0].confirmed_by == "thanh.tam" and rows[0].confirmed_at
    # The resolver consumes the store's map shape directly.
    factor, source = _resolve("EA", "SETS", confirmed=uom_factor_store.factor_map("acme"))
    assert (factor, source) == (Decimal("0.2"), "operator_confirmed")


def test_factor_store_scopes_by_client(tmp_path, monkeypatch):
    from app import uom_factor_store
    monkeypatch.setenv("CO_UOM_FACTOR_ROOT", str(tmp_path))
    uom_factor_store.set_factor("acme", bom_uom="EA", lot_uom="SETS", factor=Decimal("0.2"),
                                confirmed_by="a")
    assert uom_factor_store.list_factors("other") == []


# --- allocation ------------------------------------------------------------

def _lot(unit: str, remaining: str = "100") -> dict:
    return {
        "source_row": "import-row-1", "import_declaration_no": "NK-1", "line_no": "1",
        "material_code": "M1", "allocation_code": "M1", "customs_item_code": "M1",
        "remaining_qty": remaining, "unit": unit, "unit_value": "1000",
        "value_currency": "VND", "currency": "VND",
        "eligibility_status": "active", "allocation_code_status": "resolved",
    }


def _material(bom_uom: str, qty_per: str, consumed: str, pool_unit: str, *,
              remaining: str = "100", uom_factors=None) -> dict:
    from app.main import co_stock_allocation_pool, origin_material_from_bom_row
    pool = co_stock_allocation_pool([_lot(pool_unit, remaining)])
    return origin_material_from_bom_row(
        {"material_code": "M1", "qty_per": qty_per, "uom": bom_uom},
        Decimal(consumed),
        {"M1": {"origin_default": "Không xuất xứ"}},
        pool,
        uom_factors=uom_factors,
    )


def test_matching_units_allocate_exactly_as_before():
    material = _material("PIECES", "2", "5", "PIECES")
    assert material["consumed_qty"] == Decimal("10")
    assert material["allocation_status"] == "covered"
    assert material["allocation_lines"][0]["allocated_qty"] == "10"
    assert material["lot_uom"] == "PIECES"
    assert material.get("uom_unconfirmed") is False


def test_an_alias_pair_is_not_flagged():
    material = _material("EA", "2", "5", "PIECES")
    assert material["allocation_lines"][0]["uom_factor_source"] == "uom_alias"
    assert material.get("uom_unconfirmed") is False


def test_an_unconfirmed_pair_allocates_one_to_one_but_is_flagged():
    """Tính must stay usable — the row keeps today's numbers and says why it cannot
    be filed, instead of silently inventing a conversion."""
    material = _material("EA", "2", "5", "SETS")
    assert material["allocation_lines"][0]["allocated_qty"] == "10"
    assert material["allocation_lines"][0]["uom_factor_source"] == "unconfirmed"
    assert material["uom_unconfirmed"] is True
    assert material["lot_uom"] == "SETS"


def test_a_confirmed_factor_converts_the_demand_into_lot_units():
    """1 SET = 5 EA → 10 EA of demand takes 2 SETS off the lot."""
    material = _material("EA", "2", "5", "SETS", uom_factors={("EA", "SETS"): Decimal("0.2")})
    line = material["allocation_lines"][0]
    assert line["allocated_qty"] == "2"                    # in the LOT's unit
    assert line["allocated_qty_bom_uom"] == "10"           # in the BOM's unit
    assert line["uom_factor"] == "0.2"
    assert line["uom_factor_source"] == "operator_confirmed"
    assert material["allocation_status"] == "covered"
    assert material.get("uom_unconfirmed") is False


def test_a_confirmed_factor_reports_shortage_in_lot_units():
    material = _material("EA", "2", "5", "SETS", remaining="1",
                         uom_factors={("EA", "SETS"): Decimal("0.2")})
    assert material["allocation_status"] == "shortage"
    assert material["allocation_lines"][0]["allocated_qty"] == "1"


# --- belt ------------------------------------------------------------------

def _product_with_uom_gap() -> dict:
    return {
        "code": "P", "fob": "100",
        "materials": [{
            "material_code": "M", "origin_status": "non_origin", "valuation_status": "ready",
            "customs_relevance": "declarable", "uom": "EA", "lot_uom": "SETS",
            "uom_unconfirmed": True, "unit_value": "10", "material_value": "100",
            "allocation_lines": [{"source_row": "L1", "allocated_qty": "10", "unit_value": "10"}],
        }],
    }


def test_enrich_flags_the_uom_gap():
    from app.web.co_case_context import enrich_origin_product
    assert enrich_origin_product(_product_with_uom_gap())["lvc_uom_unconfirmed"] is True


def test_enrich_does_not_flag_a_resolved_uom():
    from app.web.co_case_context import enrich_origin_product
    product = _product_with_uom_gap()
    product["materials"][0]["uom_unconfirmed"] = False
    assert enrich_origin_product(product)["lvc_uom_unconfirmed"] is False


def test_uom_gap_keeps_the_sheet_out_of_calculated():
    from app.routers.co_case import calculated_sheet_status
    assert calculated_sheet_status({"lvc_status": "pass", "lvc_uom_unconfirmed": True}) == "bom_loaded"


def test_lock_gate_names_the_uom_gap():
    from app.web.co_case_context import origin_sheet_action_error
    case = {
        "products": [{"code": "P1", "lvc_status": "pass", "lvc_uom_unconfirmed": True}],
        "origin_sheet_states": {"P1": {"status": "calculated"}},
    }
    error = origin_sheet_action_error(case, "P1", "lock")
    assert "đơn vị tính" in error.lower()


def test_attention_chip_names_the_uom_gap():
    from app.web.co_case_context import origin_sheet_attention
    chip = origin_sheet_attention({"origin_sheet_status": "bom_loaded", "lvc_uom_unconfirmed": True})
    assert chip["reason"] == "uom_unconfirmed"


# --- what the row actually shows -------------------------------------------

def test_an_alias_pair_shows_no_conversion_mark():
    """EA and PIECES are the same unit spelled twice: the row's numbers are
    identical either way and there is nothing for the operator to do. Marking those
    rows "⇄ PIECES" put a conversion badge on 145 lines of a Johnson sheet where
    nothing was converted (reported 2026-08-19)."""
    material = _material("EA", "2", "5", "PIECES")
    assert material["uom_converted"] is False
    assert material["uom_unconfirmed"] is False


def test_a_real_conversion_is_marked():
    material = _material("EA", "2", "5", "SETS", uom_factors={("EA", "SETS"): Decimal("0.2")})
    assert material["uom_converted"] is True


def test_a_confirmed_one_to_one_factor_is_not_marked():
    """johnson-vn confirmed EA→CAY at 1:1 ("synonym in Johnson context") — the row
    is unblocked and the quantity is unchanged, so there is nothing to show."""
    material = _material("EA", "2", "5", "CAY", uom_factors={("EA", "CAY"): Decimal("1")})
    assert material["uom_unconfirmed"] is False
    assert material["uom_converted"] is False


def test_an_unconfirmed_pair_is_not_marked_as_converted():
    material = _material("EA", "2", "5", "SETS")
    assert material["uom_unconfirmed"] is True
    assert material["uom_converted"] is False
