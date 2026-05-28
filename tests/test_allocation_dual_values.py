"""Phase 2 of multi-currency: dual unit_value (native + VND) on allocation lines.

stock_allocation_line gains: unit_value_native, unit_value_vnd, material_value_native,
material_value_vnd, exchange_rate_to_vnd, exchange_rate_source.

origin_material_from_bom_row aggregates material_value_vnd from lines.
"""
from __future__ import annotations

from decimal import Decimal

from app.main import _allocation_line_fx, stock_allocation_line


def _bom_row(**extra):
    return {"unit_value": "", **extra}


def _stock(**extra):
    base = {
        "source_row": "ROW-X",
        "import_declaration_no": "D1",
        "registration_date": "2026-04-21",
        "line_no": "1",
        "value_currency": "VND",
        "currency": "VND",
        "unit_value": "1000",
        "exchange_rate_to_vnd": "1",
        "exchange_rate_source": "vnd_native",
    }
    base.update(extra)
    return base


def test_vnd_native_line_has_equal_native_and_vnd_values():
    line = stock_allocation_line(
        _stock(),
        allocated_qty=Decimal("10"),
        available_qty=Decimal("100"),
        bom_row=_bom_row(),
        material={},
    )
    assert line["unit_value_native"] == "1000"
    assert line["unit_value_vnd"] == "1000"
    assert line["material_value_native"] == "10000"
    assert line["material_value_vnd"] == "10000"
    assert line["exchange_rate_to_vnd"] == "1"
    assert line["exchange_rate_source"] == "vnd_native"


def test_usd_line_converts_to_vnd_using_exchange_rate():
    line = stock_allocation_line(
        _stock(
            value_currency="USD",
            currency="USD",
            unit_value="100",
            exchange_rate_to_vnd="24500",
            exchange_rate_source="bcct_declared",
        ),
        allocated_qty=Decimal("2"),
        available_qty=Decimal("50"),
        bom_row=_bom_row(),
        material={},
    )
    assert line["unit_value_native"] == "100"
    assert line["unit_value_vnd"] == "2450000"
    assert line["material_value_native"] == "200"
    assert line["material_value_vnd"] == "4900000"
    assert line["exchange_rate_source"] == "bcct_declared"


def test_missing_fx_leaves_vnd_fields_empty_but_does_not_crash():
    line = stock_allocation_line(
        _stock(
            value_currency="EUR",
            currency="EUR",
            unit_value="50",
            exchange_rate_to_vnd="",
            exchange_rate_source="missing",
        ),
        allocated_qty=Decimal("3"),
        available_qty=Decimal("10"),
        bom_row=_bom_row(),
        material={},
    )
    assert line["unit_value_native"] == "50"
    assert line["material_value_native"] == "150"
    assert line["unit_value_vnd"] == ""
    assert line["material_value_vnd"] == ""
    assert line["exchange_rate_source"] == "missing"


def test_allocation_line_fx_helper_handles_bad_input():
    rate, source = _allocation_line_fx({"exchange_rate_to_vnd": "not-a-number", "exchange_rate_source": "bcct_declared"})
    assert rate is None
    assert source == "bcct_declared"

    rate, source = _allocation_line_fx({})
    assert rate is None
    assert source == "missing"


def test_existing_unit_value_field_unchanged_for_backwards_compat():
    """Phase 3 renderer integration relies on this contract."""
    line = stock_allocation_line(
        _stock(unit_value="123"),
        allocated_qty=Decimal("1"),
        available_qty=Decimal("10"),
        bom_row=_bom_row(),
        material={},
    )
    assert line["unit_value"] == "123"  # legacy field
    assert line["material_value"] == "123"  # legacy field
