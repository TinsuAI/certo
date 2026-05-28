"""Phase 5 of multi-currency: per-product fob_currency + fob_vnd attach.

`_attach_fob_vnd` computes fob_vnd at case-load time so renderers in VND mode
print the converted FOB without re-doing FX work per render.
"""
from __future__ import annotations

from unittest.mock import patch

from app.main import _attach_fob_vnd


def test_vnd_native_fob_passes_through():
    product = {"fob": "1000000", "currency": "VND"}
    _attach_fob_vnd(product)
    assert product["fob_vnd"] == "1000000"
    assert product["fob_fx_source"] == "vnd_native"


def test_empty_fob_is_treated_as_missing():
    product = {"fob": "", "currency": "USD"}
    _attach_fob_vnd(product)
    assert product["fob_vnd"] == ""
    assert product["fob_fx_source"] == "missing"


def test_usd_fob_with_customs_lookup_hit_converts_to_vnd():
    product = {
        "fob": "100",
        "fob_currency": "USD",
        "source_declaration_date": "2026-04-25",
    }
    fake_rows = [
        {"currency_code": "USD", "effective_date": "2026-04-23", "rate_vnd_per_unit": "24500"},
    ]
    with patch("app.customs_fx_store.get_customs_fx_store") as mock_store:
        mock_store.return_value.rows.return_value = fake_rows
        _attach_fob_vnd(product)
    assert product["fob_vnd"] == "2450000"
    assert product["fob_fx_rate"] == "24500"
    assert product["fob_fx_source"] == "customs_lookup"


def test_usd_fob_missing_lookup_leaves_fob_vnd_empty():
    product = {
        "fob": "100",
        "fob_currency": "USD",
        "source_declaration_date": "2026-04-25",
    }
    with patch("app.customs_fx_store.get_customs_fx_store") as mock_store:
        mock_store.return_value.rows.return_value = []  # no rates available
        _attach_fob_vnd(product)
    assert product["fob_vnd"] == ""
    assert product["fob_fx_source"] == "missing"


def test_fob_currency_falls_back_to_product_currency():
    """When fob_currency is not set explicitly, use product.currency."""
    product = {"fob": "1000", "currency": "VND"}  # no fob_currency
    _attach_fob_vnd(product)
    assert product["fob_fx_source"] == "vnd_native"
