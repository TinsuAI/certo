"""Phase 3 of multi-currency: renderer A + B swap material values + currency
label based on product.origin_sheet_currency_mode."""
from __future__ import annotations

from decimal import Decimal

from app import bang_ke_renderer, bang_ke_xml_generator
from app.bang_ke_xml_generator import FormSpec


def _sample_material(**override):
    base = {
        "material_code": "M1",
        "material_description": "Cell",
        "bom_qty_per": "1",
        "consumed_qty": "10",
        "unit_value": "100",          # native (USD-priced lot)
        "unit_value_native": "100",
        "unit_value_vnd": "2450000",  # 100 USD × 24500 VND/USD
        "material_value": "1000",
        "material_value_native": "1000",
        "material_value_vnd": "24500000",
        "currency": "USD",            # row's native currency
        "origin_status": "non_origin",
        "hs_code": "850440",
        "uom": "PCS",
    }
    base.update(override)
    return base


def _usd_product():
    return {"currency": "USD", "fob_currency": "USD", "fob_fx_rate": "24500"}


def _vnd_product():
    return {"currency": "VND", "fob_currency": "VND"}


def test_renderer_native_mode_usd_row_usd_product_returns_native():
    """USD-native row + USD product + native mode → no conversion."""
    mat = _sample_material()
    assert bang_ke_renderer._pick_currency_value(mat, "unit_value", use_vnd=False, product=_usd_product()) == "100"
    assert bang_ke_renderer._pick_currency_value(mat, "material_value", use_vnd=False, product=_usd_product()) == "1000"


def test_renderer_vnd_mode_usd_row_converts_to_vnd():
    """USD row + vnd mode → use the materialized VND-equivalent."""
    mat = _sample_material()
    assert bang_ke_renderer._pick_currency_value(mat, "unit_value", use_vnd=True, product=_usd_product()) == "2450000"
    assert bang_ke_renderer._pick_currency_value(mat, "material_value", use_vnd=True, product=_usd_product()) == "24500000"


def test_renderer_native_mode_vnd_row_usd_product_cross_converts():
    """USER'S BUG: when product exports in USD but the NVL lot is VND-priced,
    native mode must divide the VND value by fob_fx_rate to print nguyên tệ."""
    mat = _sample_material(
        currency="VND",
        unit_value="2450000", unit_value_native="2450000", unit_value_vnd="2450000",
        material_value="24500000", material_value_native="24500000", material_value_vnd="24500000",
    )
    # In USD mode (native, USD product), 2,450,000 VND ÷ 24,500 = 100 USD.
    assert bang_ke_renderer._pick_currency_value(mat, "unit_value", use_vnd=False, product=_usd_product()) == "100"
    assert bang_ke_renderer._pick_currency_value(mat, "material_value", use_vnd=False, product=_usd_product()) == "1000"


def test_renderer_vnd_mode_vnd_row_no_op():
    """VND row + vnd mode → no conversion."""
    mat = _sample_material(
        currency="VND",
        unit_value="2450000", unit_value_native="2450000", unit_value_vnd="2450000",
    )
    assert bang_ke_renderer._pick_currency_value(mat, "unit_value", use_vnd=True, product=_vnd_product()) == "2450000"


def test_renderer_falls_back_when_fx_rate_missing():
    """Cross-conversion needs fob_fx_rate. Without it, show native value
    (renderer should already be surfacing an FX-missing chip elsewhere)."""
    mat = _sample_material(currency="VND", unit_value="2450000", unit_value_vnd="2450000")
    product = {"currency": "USD", "fob_currency": "USD"}  # no fob_fx_rate
    out = bang_ke_renderer._pick_currency_value(mat, "unit_value", use_vnd=False, product=product)
    assert out == "2450000"  # falls back to native VND value


def test_xml_generator_helper_mirrors_renderer():
    """Both renderers must agree on the picking logic to keep approach-A/B parity."""
    mat = _sample_material()
    product = _usd_product()
    assert (
        bang_ke_xml_generator._pick_currency_value(mat, "unit_value", use_vnd=True, product=product)
        == bang_ke_renderer._pick_currency_value(mat, "unit_value", use_vnd=True, product=product)
    )


def test_xml_field_table_currency_label_follows_mode():
    case = {"customer_legal_name": "X", "shipment": {"export_declaration_nos": []}}
    product = {
        "name": "P", "code": "P1", "finished_hs": "85", "quantity": "10",
        "uom": "PCS", "currency": "USD", "fob": "1000",
        "origin_sheet_currency_mode": "vnd",
    }
    form = FormSpec(criterion="LVC", phu_luc="", title="", legal_note="", conclusion="", show_cost_buildup=False)
    fields = bang_ke_xml_generator._build_field_table(case, product, form)
    # In vnd mode, the FOB label shows VND regardless of native currency.
    assert fields["fob_with_currency"]["currency"] == "VND"


def test_xml_field_table_currency_label_uses_native_in_default_mode():
    case = {"customer_legal_name": "X", "shipment": {"export_declaration_nos": []}}
    product = {
        "name": "P", "code": "P1", "finished_hs": "85", "quantity": "10",
        "uom": "PCS", "currency": "USD", "fob": "1000",
        "origin_sheet_currency_mode": "native",
    }
    form = FormSpec(criterion="LVC", phu_luc="", title="", legal_note="", conclusion="", show_cost_buildup=False)
    fields = bang_ke_xml_generator._build_field_table(case, product, form)
    assert fields["fob_with_currency"]["currency"] == "USD"
