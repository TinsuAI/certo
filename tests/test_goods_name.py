"""Growatt goods-name internal_code parser — exact regex parity with bcqt-growatt."""
from app.parsers.goods_name import growatt_parse_internal_code


def test_pattern_hash_amp_prefix():
    assert growatt_parse_internal_code("PE-001#&Polyethylene resin grade A") == "PE-001"
    assert growatt_parse_internal_code("AL-100#&Aluminum sheet") == "AL-100"
    assert growatt_parse_internal_code("INV-3000#&Solar inverter 3kW") == "INV-3000"


def test_pattern_paren_three_digit():
    assert growatt_parse_internal_code("Mock description (123.abc)") == "123.abc"


def test_pattern_paren_letters_then_digits():
    assert growatt_parse_internal_code("Some good (AB12.def)") == "AB12.def"


def test_e13_equipment_returns_none():
    assert growatt_parse_internal_code(".#&E13 imported equipment") is None


def test_no_pattern_returns_none():
    assert growatt_parse_internal_code("Plain text no codes") is None
    assert growatt_parse_internal_code("") is None
    assert growatt_parse_internal_code("   ") is None
