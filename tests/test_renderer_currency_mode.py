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
        "unit_value": "100",          # native (USD)
        "unit_value_native": "100",
        "unit_value_vnd": "2450000",  # converted via 24500 VND/USD
        "material_value": "1000",
        "material_value_native": "1000",
        "material_value_vnd": "24500000",
        "origin_status": "non_origin",
        "hs_code": "850440",
        "uom": "PCS",
    }
    base.update(override)
    return base


def test_renderer_b_uses_native_values_by_default():
    """Default mode is native — _pick_currency_value returns the native field."""
    mat = _sample_material()
    assert bang_ke_renderer._pick_currency_value(mat, "unit_value", use_vnd=False) == "100"
    assert bang_ke_renderer._pick_currency_value(mat, "material_value", use_vnd=False) == "1000"


def test_renderer_b_uses_vnd_values_when_use_vnd_true():
    mat = _sample_material()
    assert bang_ke_renderer._pick_currency_value(mat, "unit_value", use_vnd=True) == "2450000"
    assert bang_ke_renderer._pick_currency_value(mat, "material_value", use_vnd=True) == "24500000"


def test_renderer_falls_back_to_native_when_vnd_missing():
    """Old materialized rows lack *_vnd fields; we shouldn't print blank cells."""
    mat = _sample_material(unit_value_vnd="", material_value_vnd="")
    assert bang_ke_renderer._pick_currency_value(mat, "unit_value", use_vnd=True) == "100"
    assert bang_ke_renderer._pick_currency_value(mat, "material_value", use_vnd=True) == "1000"


def test_xml_generator_helper_mirrors_renderer():
    """Both renderers must agree on the picking logic to keep approach-A/B parity."""
    mat = _sample_material()
    assert (
        bang_ke_xml_generator._pick_currency_value(mat, "unit_value", use_vnd=True)
        == bang_ke_renderer._pick_currency_value(mat, "unit_value", use_vnd=True)
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
