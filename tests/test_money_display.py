"""Decimals on the bảng kê's money cells.

Operator, 2026-08-19: "Đơn giá và giá trị mà VNĐ mà để nhiều số sau dấu phẩy khó chịu
quá ... Mặc định nếu là VNĐ thì ko cần sau dấu phẩy". The same columns also carry USD
lots, where six decimals ARE the number — so the count follows the currency the cell is
printed in, and the operator can pin it per bảng kê.
"""
from __future__ import annotations

import pytest

from app.money_display import format_money, money_decimals, normalize_display_decimals


def test_vnd_prints_whole_dong():
    assert format_money("83634.102869", "VND", "unit") == "83.634"
    assert format_money("126956.57", "VND", "amount") == "126.957"


def test_a_foreign_currency_keeps_its_precision():
    assert format_money("1.410070092", "USD", "unit") == "1,410070"
    assert format_money("2.5", "USD", "amount") == "2,50"


def test_a_small_vnd_value_is_never_printed_as_zero():
    """johnson-vn 1000096510 is declared at đơn giá 0.078 VND. "0" is how this app says
    "thiếu đơn giá" — printing it over a priced row sends the operator hunting a defect
    that is not there."""
    assert format_money("0.078", "VND", "unit") == "0,078"
    assert format_money("0.004", "VND", "amount") == "0,004"
    assert format_money("-0.078", "VND", "unit") == "-0,078"


def test_a_real_zero_still_prints_zero():
    assert format_money("0", "VND", "unit") == "0"
    assert format_money("0", "USD", "amount") == "0,00"


def test_the_per_sheet_override_wins():
    assert format_money("83634.102869", "VND", "unit", "2") == "83.634,10"
    assert format_money("1.410070092", "USD", "unit", "0") == "1"


@pytest.mark.parametrize("raw,expected", [("", ""), ("  ", ""), ("abc", ""), ("-3", "0"), ("2", "2"), ("99", "8")])
def test_the_override_is_sanitised(raw, expected):
    assert normalize_display_decimals(raw) == expected


def test_the_default_count_by_currency_and_kind():
    assert money_decimals("VND", "unit") == 0
    assert money_decimals("VND", "amount") == 0
    assert money_decimals("USD", "unit") == 6
    assert money_decimals("USD", "amount") == 2


def test_empty_input_stays_empty():
    assert format_money("", "VND") == ""
    assert format_money(None, "VND") == ""


def test_thousands_use_the_vietnamese_convention():
    """The browser reformats these cells with toLocaleString('vi-VN'); first paint must
    not disagree with what appears a moment later."""
    assert format_money("1234567.5", "USD", "amount") == "1.234.567,50"
