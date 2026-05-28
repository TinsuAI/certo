"""Phase 1 of multi-currency: per-row FX rate resolution on co_stock_rows.

Verifies the 4-tier priority chain in `co_stock_fx_fields`:
  1. value_currency=VND          → rate=1, source=vnd_native
  2. BCCT row.exchange_rate set  → source=bcct_declared
  3. customs_fx_rows lookup hit  → source=customs_lookup (weekly granularity)
  4. nothing                     → rate="", source=missing
"""
from __future__ import annotations

from app.source_store import co_stock_fx_fields, co_stock_rows_from_bcct


CLIENT_CONFIG = {
    "co_stock": {"lot_policy": "line_level"},
    "bcct": {"eligible_import_declaration_types": []},
    "allocation_code": {"strategy": "same_as_customs_code", "fallback": "same_as_customs_code"},
}


def _value_fields(currency: str) -> dict:
    return {"value_currency": currency, "currency": currency}


def test_vnd_native_returns_rate_one():
    fx = co_stock_fx_fields({}, _value_fields("VND"), "2026-04-21", None)
    assert fx == {"exchange_rate_to_vnd": "1", "exchange_rate_source": "vnd_native"}


def test_bcct_declared_rate_wins_over_customs_lookup():
    bcct_row = {"exchange_rate": "24500"}
    customs_rows = [{"currency_code": "USD", "effective_date": "2026-04-21", "rate_vnd_per_unit": "25000"}]
    fx = co_stock_fx_fields(bcct_row, _value_fields("USD"), "2026-04-21", customs_rows)
    assert fx["exchange_rate_source"] == "bcct_declared"
    assert fx["exchange_rate_to_vnd"] == "24500"


def test_customs_lookup_used_when_bcct_rate_missing():
    bcct_row = {"exchange_rate": ""}
    customs_rows = [
        {"currency_code": "USD", "effective_date": "2026-04-14", "rate_vnd_per_unit": "24800"},
        {"currency_code": "USD", "effective_date": "2026-04-21", "rate_vnd_per_unit": "25000"},
    ]
    fx = co_stock_fx_fields(bcct_row, _value_fields("USD"), "2026-04-22", customs_rows)
    assert fx["exchange_rate_source"] == "customs_lookup"
    assert fx["exchange_rate_to_vnd"] == "25000"


def test_customs_lookup_uses_weekly_granularity():
    # Declaration on 2026-04-25 — customs publishes weekly on Thursday. Pick
    # the most recent rate ≤ declaration date.
    customs_rows = [
        {"currency_code": "USD", "effective_date": "2026-04-23", "rate_vnd_per_unit": "25100"},  # Thursday
        {"currency_code": "USD", "effective_date": "2026-04-30", "rate_vnd_per_unit": "25200"},  # next Thursday
    ]
    fx = co_stock_fx_fields({}, _value_fields("USD"), "2026-04-25", customs_rows)
    assert fx["exchange_rate_to_vnd"] == "25100"  # picks Apr 23, not the future Apr 30


def test_missing_when_no_bcct_rate_and_no_customs_lookup():
    fx = co_stock_fx_fields({}, _value_fields("EUR"), "2026-04-21", customs_fx_rows=[])
    assert fx == {"exchange_rate_to_vnd": "", "exchange_rate_source": "missing"}


def test_missing_when_currency_empty():
    fx = co_stock_fx_fields({}, _value_fields(""), "2026-04-21", None)
    assert fx["exchange_rate_source"] == "missing"


def test_co_stock_rows_from_bcct_attaches_fx_fields_on_each_row():
    bcct_rows = [
        {
            "direction": "import",
            "transaction_key": "T1",
            "declaration_no": "D1",
            "registration_date": "2026-04-21",
            "currency": "VND",
            "taxable_unit_price": "1000",
            "quantity": "10",
            "item_code": "X",
        },
        {
            "direction": "import",
            "transaction_key": "T2",
            "declaration_no": "D2",
            "registration_date": "2026-04-21",
            "currency": "USD",
            "exchange_rate": "24500",
            "foreign_currency_value": "100",
            "quantity": "1",
            "item_code": "Y",
        },
    ]
    rows = co_stock_rows_from_bcct(bcct_rows, CLIENT_CONFIG, customs_fx_rows=[])
    sources = [r["exchange_rate_source"] for r in rows]
    assert sources == ["vnd_native", "bcct_declared"]
    rates = [r["exchange_rate_to_vnd"] for r in rows]
    assert rates == ["1", "24500"]


def test_co_stock_rows_from_bcct_works_without_customs_rows_kwarg():
    """Backwards-compat: existing callers that don't pass customs_fx_rows still get
    output rows (with source='missing' for non-VND, no exception)."""
    bcct_rows = [
        {
            "direction": "import",
            "transaction_key": "T1",
            "currency": "USD",
            "foreign_currency_value": "100",
            "quantity": "1",
        },
    ]
    rows = co_stock_rows_from_bcct(bcct_rows, CLIENT_CONFIG)
    assert rows[0]["exchange_rate_source"] == "missing"
