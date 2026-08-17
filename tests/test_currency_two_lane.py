"""Every stock lot carries BOTH money lanes, unconditionally.

Decision (2026-08-17, after the client asked to keep USD): the VND taxable lane
stays the one every calculation runs in, and the declaration's invoice lane
(đơn giá nguyên tệ + tỷ giá thanh toán) rides along as data — not as a mode.
Switching what the bảng kê SHOWS is then a per-sheet display choice
(`origin_sheet_currency_mode`, which already exists) and never re-derives stock.

This replaces the `co_stock.value_basis` ingest switch, which forced a full
re-derivation to change a presentation choice and computed LVC across two
currencies whenever the export declaration was not USD (209 of johnson-vn's
1,304 export declarations are EUR/JPY/VND while its lots are 89% USD).

The lane a number belongs to is named by `native_currency`: `*_native` fields are
in that currency, `*_vnd` fields are always VND.
"""
from __future__ import annotations

from decimal import Decimal


def _config() -> dict:
    return {
        "bcct": {"eligible_import_declaration_types": []},
        "co_stock": {"lot_policy": "line_level"},
        "allocation_code": {"strategy": "same_as_customs_code", "fallback": "same_as_customs_code"},
    }


def _bcct_row(**overrides) -> dict:
    row = {
        "direction": "import",
        "transaction_key": "107271797510-20",
        "declaration_no": "107271797510",
        "line_no": "20",
        "declaration_type": "E13",
        "registration_date": "2025-06-16",
        "item_code": "1000495386",
        "quantity": "20",
        "unit": "PIECES",
        "unit_price": "19007.890150",
        "unit_price_nt": "0.735317",
        "total_value": "380157.803",
        "total_value_nt": "14.7063",
        "currency_nt": "USD",
        "exchange_rate": "25850",
        "taxable_unit_price": "19007.890150",
        "customs_value": "380157.803",
        "foreign_currency_value": "14.7063",
        "currency": "USD",
        "value_currency": "VND",
    }
    row.update(overrides)
    return row


def _derive(row: dict) -> dict:
    from app.co_stock_derivation import co_stock_rows_from_bcct
    rows = co_stock_rows_from_bcct([row], _config())
    assert len(rows) == 1
    return rows[0]


def test_lot_carries_both_lanes_without_any_config():
    row = _derive(_bcct_row())
    # VND lane — unchanged, still what every calculation reads.
    assert row["unit_value"] == "19007.89015"
    assert row["value_currency"] == "VND"
    assert row["customs_value"] == "380157.803"
    # Invoice lane — the declaration's own figures, labelled by native_currency.
    assert row["native_currency"] == "USD"
    assert row["unit_value_native"] == "0.735317"
    assert row["customs_value_native"] == "14.7063"
    # The declaration's payment rate ties the two lanes together.
    assert row["exchange_rate_to_vnd"] == "25850"
    assert row["exchange_rate_source"] == "bcct_declared"


def test_vnd_declared_lot_has_one_currency_in_both_lanes():
    row = _derive(_bcct_row(currency_nt="VND", currency="VND", unit_price_nt="19007.890150",
                            total_value_nt="380157.803"))
    assert row["native_currency"] == "VND"
    assert row["unit_value_native"] == row["unit_value"]
    assert row["exchange_rate_to_vnd"] == "1"


def test_lot_without_invoice_figures_stays_single_lane():
    row = _derive(_bcct_row(unit_price_nt="", total_value_nt="", foreign_currency_value=""))
    assert row["native_currency"] == "VND"
    assert row["unit_value_native"] == row["unit_value"]


def test_invoice_unit_price_derived_from_the_invoice_total_when_absent():
    row = _derive(_bcct_row(unit_price_nt=""))
    assert row["native_currency"] == "USD"
    assert row["unit_value_native"] == "0.735315"  # 14.7063 / 20


def test_value_basis_config_is_gone():
    """The ingest-time switch is removed; a stale config value must not resurrect it."""
    from app.client_config_store import default_config, migrate_config
    config = default_config({"id": "acme", "name": "Acme"})
    assert "value_basis" not in config["co_stock"]
    # A config saved by the older build still migrates (the key is simply dropped).
    migrated = migrate_config(
        {"co_stock": {"lot_policy": "line_level", "value_basis": "invoice_native"}},
        {"id": "acme", "name": "Acme"},
    )
    assert "value_basis" not in migrated["co_stock"]


# --- allocation lines ------------------------------------------------------

def _lot(**overrides) -> dict:
    lot = {
        "source_row": "import-row-1",
        "import_declaration_no": "107271797510",
        "line_no": "20",
        "customs_item_code": "1000495386",
        "allocation_code": "1000495386",
        "unit_value": "19007.89015",
        "taxable_unit_price": "19007.89015",
        "unit_value_native": "0.735317",
        "native_currency": "USD",
        "value_currency": "VND",
        "exchange_rate_to_vnd": "25850",
    }
    lot.update(overrides)
    return lot


def test_allocation_line_keeps_math_in_vnd_and_carries_the_invoice_lane():
    from app.web.co_case_context import stock_allocation_line
    line = stock_allocation_line(_lot(), Decimal("4"), Decimal("20"), {}, {})
    assert line["unit_value"] == "19007.89015"          # VND — what the math uses
    assert Decimal(line["material_value"]) == Decimal("76031.5606")
    assert line["unit_value_vnd"] == "19007.89015"      # exact VND of the declaration
    assert line["native_currency"] == "USD"
    assert line["unit_value_native"] == "0.735317"      # exact USD of the declaration
    assert Decimal(line["material_value_native"]) == Decimal("2.941268")


def test_allocation_line_of_a_vnd_lot_reports_vnd_in_both_lanes():
    from app.web.co_case_context import stock_allocation_line
    line = stock_allocation_line(
        _lot(native_currency="VND", unit_value_native="19007.89015"), Decimal("2"), Decimal("20"), {}, {},
    )
    assert line["native_currency"] == "VND"
    assert line["unit_value_native"] == line["unit_value"]


# --- display: the exact invoice number wins over a cross-conversion --------

def _product(**overrides) -> dict:
    product = {"fob_currency": "USD", "fob_fx_rate": "25850", "origin_sheet_currency_mode": "native"}
    product.update(overrides)
    return product


def test_export_prints_the_declaration_number_when_the_lane_matches_the_target():
    from app.bang_ke_renderer import _pick_currency_value
    material = {
        "currency": "VND", "unit_value": "19007.89015", "unit_value_vnd": "19007.89015",
        "native_currency": "USD", "unit_value_native": "0.735317",
    }
    # Target USD: use the lot's own USD figure, NOT 19007.89015 / 25850 (= 0.735315…).
    assert _pick_currency_value(material, "unit_value", False, _product()) == "0.735317"


def test_export_still_cross_converts_when_there_is_no_invoice_lane():
    from app.bang_ke_renderer import _pick_currency_value
    material = {"currency": "VND", "unit_value": "2450000", "unit_value_vnd": "2450000"}
    product = _product(fob_fx_rate="24500")
    assert _pick_currency_value(material, "unit_value", False, product) == "100"


def test_export_in_vnd_mode_prints_the_vnd_lane():
    from app.bang_ke_renderer import _pick_currency_value
    material = {
        "currency": "VND", "unit_value": "19007.89015", "unit_value_vnd": "19007.89015",
        "native_currency": "USD", "unit_value_native": "0.735317",
    }
    assert _pick_currency_value(material, "unit_value", True, _product()) == "19007.89015"


def test_export_ignores_an_invoice_lane_in_another_currency():
    """A JPY lot on a sheet filed in USD must not print its JPY figure."""
    from app.bang_ke_renderer import _pick_currency_value
    material = {
        "currency": "VND", "unit_value": "2585000", "unit_value_vnd": "2585000",
        "native_currency": "JPY", "unit_value_native": "15000",
    }
    assert _pick_currency_value(material, "unit_value", False, _product()) == "100"


# --- FOB: the product carries the invoice lane too; LVC stays in VND --------

def _export_match(**overrides) -> dict:
    """A johnson-vn export declaration line: VND taxable total + USD invoice total."""
    match = {
        "item_code": "MPL0109-39",
        "description": "Thiết bị luyện tập",
        "hs_code": "95069100",
        "quantity": "2",
        "unit": "SETS",
        "customs_value": "306528985.86",
        "total_value": "306528985.86",
        "foreign_currency_value": "11727.78",
        "currency": "USD",
        "value_currency": "VND",
        "exchange_rate": "26140",
        "declaration_no": "308386475150",
    }
    match.update(overrides)
    return match


def _product_from_match(match: dict) -> dict:
    from app.web.co_case_context import origin_product_from_invoice_match
    return origin_product_from_invoice_match(match, [], {}, {}, {}, allocate=False)


def test_product_keeps_vnd_fob_and_names_the_invoice_lane():
    product = _product_from_match(_export_match())
    # VND lane — unchanged: this is what LVC and the cost build-up run on.
    assert product["fob"] == "306528985.86"
    assert product["fob_currency"] == "VND"
    # Invoice lane — the declaration's own USD figures, for a sheet filed in nguyên tệ.
    assert product["invoice_currency"] == "USD"
    assert product["fob_invoice"] == "11727.78"
    assert product["fob_fx_rate"] == "26140"
    assert product["fob_fx_source"] == "bcct_declared"


def test_product_without_an_invoice_total_has_no_invoice_lane():
    product = _product_from_match(_export_match(foreign_currency_value="", exchange_rate=""))
    assert product.get("invoice_currency", "") == ""
    assert product.get("fob_invoice", "") == ""


def test_display_target_prefers_the_invoice_currency_in_native_mode():
    from app.bang_ke_renderer import _resolve_target_currency
    product = {"fob_currency": "VND", "invoice_currency": "USD"}
    assert _resolve_target_currency(product, False) == "USD"
    assert _resolve_target_currency(product, True) == "VND"


def test_display_target_falls_back_to_fob_currency():
    from app.bang_ke_renderer import _resolve_target_currency
    assert _resolve_target_currency({"fob_currency": "USD"}, False) == "USD"
    assert _resolve_target_currency({"fob_currency": "VND"}, False) == "VND"


def test_lvc_is_computed_in_vnd_even_when_fob_is_native():
    """The hole this design closes: FOB in EUR/USD against VNM summed in VND gave a
    silently wrong ratio. Both sides must come from the VND lane."""
    from app.web.co_case_context import normalized_lvc_result
    product = {
        "fob": "11727.78", "fob_currency": "USD", "fob_vnd": "306528985.86",
        "vnm_value": "4000", "vnm_value_vnd": "104000000",
        "lvc_threshold": "30",
    }
    result = normalized_lvc_result(product, [{"material_code": "M", "origin_status": "non_origin"}], "RVC 30%", False)
    assert result["percentage"] == "66.07"   # VND pair, not 65.89 from the USD pair
    assert result["status"] == "pass"


def test_lvc_unchanged_when_only_the_vnd_lane_exists():
    from app.web.co_case_context import normalized_lvc_result
    product = {"fob": "100", "vnm_value": "40", "lvc_threshold": "30"}
    result = normalized_lvc_result(product, [{"material_code": "M", "origin_status": "non_origin"}], "RVC 30%", False)
    assert result["percentage"] == "60.00"


def test_fob_printed_in_the_target_currency():
    from app.bang_ke_renderer import product_fob_in_target
    product = {
        "fob": "306528985.86", "fob_currency": "VND", "fob_vnd": "306528985.86",
        "invoice_currency": "USD", "fob_invoice": "11727.78", "fob_fx_rate": "26140",
    }
    assert product_fob_in_target(product, False) == "11727.78"   # nguyên tệ: the declaration's own total
    assert product_fob_in_target(product, True) == "306528985.86"


def test_fob_without_an_invoice_total_converts_by_the_rate():
    from app.bang_ke_renderer import product_fob_in_target
    product = {"fob": "2450000", "fob_currency": "VND", "fob_vnd": "2450000",
               "invoice_currency": "USD", "fob_fx_rate": "24500"}
    assert product_fob_in_target(product, False) == "100"


def test_fob_native_product_is_untouched():
    """growatt-style product: FOB already in USD, no invoice lane."""
    from app.bang_ke_renderer import product_fob_in_target
    product = {"fob": "100", "fob_currency": "USD", "fob_vnd": "2450000"}
    assert product_fob_in_target(product, False) == "100"
    assert product_fob_in_target(product, True) == "2450000"


def test_rebuilding_a_product_keeps_its_invoice_lane():
    """A recalculation goes product → match → product. Dropping the invoice lane on
    that round trip silently reverted the sheet to VND."""
    from app.web.co_case_context import origin_match_from_existing_product, origin_product_from_invoice_match
    product = {
        "code": "TP-A", "name": "TP", "finished_hs": "950691", "quantity": "10",
        "fob": "306528985.86", "currency": "VND", "fob_currency": "VND",
        "invoice_currency": "USD", "fob_invoice": "11727.78", "fob_fx_rate": "26140",
    }
    rebuilt = origin_product_from_invoice_match(
        origin_match_from_existing_product(product), [], {}, {}, {}, allocate=False,
    )
    assert rebuilt["fob"] == "306528985.86"
    assert rebuilt["fob_currency"] == "VND"
    assert rebuilt["invoice_currency"] == "USD"
    assert rebuilt["fob_invoice"] == "11727.78"
    assert rebuilt["fob_fx_rate"] == "26140"


def test_renderer_field_table_prints_fob_in_the_sheet_currency():
    from app.bang_ke_renderer import _build_field_table
    product = {
        "code": "TP-A", "name": "TP", "quantity": "10",
        "fob": "306528985.86", "fob_currency": "VND", "fob_vnd": "306528985.86",
        "invoice_currency": "USD", "fob_invoice": "11727.78", "fob_fx_rate": "26140",
        "origin_sheet_currency_mode": "native",
        "materials": [],
    }
    native = _build_field_table({}, product)
    assert native["fob"] == "11727.78"
    vnd = _build_field_table({}, {**product, "origin_sheet_currency_mode": "vnd"})
    assert vnd["fob"] == "306528985.86"
