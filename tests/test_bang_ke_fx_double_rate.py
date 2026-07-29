"""B6 nit: the non-VND cross-conversion branch of _pick_currency_value must
apply fob_fx_rate exactly once, and only to a genuine VND amount.

New rows carry a precomputed *_vnd field (VND). Legacy rows lack it; their
base_key holds the NATIVE value. The old code did
`material.get(f"{base_key}_vnd") or material.get(base_key)` and then divided the
result by fob_fx_rate. For a legacy row that dropped the native value into the
division (native ÷ VND-per-target rate) — the FX rate applied a second time,
corrupting the figure. The fix divides only the real *_vnd value; a legacy row
without it falls back to native unconverted.
"""
from __future__ import annotations

from app import bang_ke_renderer

_pick = bang_ke_renderer._pick_currency_value


def _usd_product():
    # exporting in USD; VND-priced lots cross-convert at 24500 VND/USD
    return {"currency": "USD", "fob_currency": "USD", "fob_fx_rate": "24500"}


def test_new_row_with_vnd_field_converts_once():
    """New-style row (has *_vnd) → divide the VND amount by fob_fx_rate once."""
    new_row = {
        "currency": "VND",
        "unit_value": "2450000",        # native (VND-priced lot)
        "unit_value_vnd": "2450000",    # canonical VND amount
        "material_value": "24500000",
        "material_value_vnd": "24500000",
    }
    assert _pick(new_row, "unit_value", use_vnd=False, product=_usd_product()) == "100"
    assert _pick(new_row, "material_value", use_vnd=False, product=_usd_product()) == "1000"


def test_legacy_row_without_vnd_field_is_not_double_converted():
    """Legacy row (no *_vnd) with a non-VND native currency. base_key holds the
    native figure. The rate must NOT be applied to it — fall back to native.

    Old bug: 100 (native) / 24500 = 0.00408..., the FX rate mis-applied.
    """
    legacy_row = {
        "currency": "EUR",       # native, differs from the USD export target
        "unit_value": "100",     # native value, no unit_value_vnd present
        "material_value": "1000",
    }
    # fob_fx_rate is USD/VND, irrelevant to an EUR native value → no conversion.
    assert _pick(legacy_row, "unit_value", use_vnd=False, product=_usd_product()) == "100"
    assert _pick(legacy_row, "material_value", use_vnd=False, product=_usd_product()) == "1000"


def test_legacy_row_zero_vnd_string_still_falls_back_to_native():
    """A missing *_vnd (empty string) must not be treated as a VND amount."""
    legacy_row = {"currency": "EUR", "unit_value": "100", "unit_value_vnd": ""}
    assert _pick(legacy_row, "unit_value", use_vnd=False, product=_usd_product()) == "100"


def test_legacy_vnd_row_without_vnd_field_converts_once():
    """Regression: a VND-currency legacy row (no *_vnd) holds a genuine VND amount
    in base_key. It must convert once (2450000 / 24500 = 100), NOT print raw.

    The b6 fix dropped the fallback entirely, so this VND amount was printed raw
    (2450000) in a USD customs column — off by the FX factor. The fix gates the
    fallback on row_currency == "VND" so it still converts here while leaving the
    EUR-native rows above untouched.
    """
    vnd_legacy_row = {
        "currency": "VND",          # row stored in VND, differs from USD target
        "unit_value": "2450000",    # a genuine VND amount, no unit_value_vnd
        "material_value": "24500000",
    }
    assert _pick(vnd_legacy_row, "unit_value", use_vnd=False, product=_usd_product()) == "100"
    assert _pick(vnd_legacy_row, "material_value", use_vnd=False, product=_usd_product()) == "1000"


def test_legacy_vnd_row_empty_vnd_string_converts_once():
    """Same gate, with an explicit empty-string *_vnd (not just a missing key)."""
    vnd_legacy_row = {"currency": "VND", "unit_value": "2450000", "unit_value_vnd": ""}
    assert _pick(vnd_legacy_row, "unit_value", use_vnd=False, product=_usd_product()) == "100"
