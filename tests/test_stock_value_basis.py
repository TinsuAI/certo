"""Which value column of the customs declaration CO treats as money:
`co_stock.value_basis` = "taxable_vnd" (default, unchanged) or "invoice_native".

Operator ask (johnson-vn, 2026-08-17): "anh đã cho quy đổi hết trong BCCT từ USD
sang VND ạ? anh để nguyên theo USD giúp em". CO never converted anything — it read
the declaration's VND taxable columns (`unit_price`, `total_value`) and stamped
`value_currency = "VND"` on every row, while the invoice/nguyên-tệ columns
(`unit_price_nt`, `total_value_nt`, `currency_nt`, `exchange_rate`) came through
Data Hub unused. johnson-vn imports: 74,987 USD lines + 9,244 VND lines.

The basis switches stock unit prices AND the FOB read from the export declaration
together — VNM and FOB must be in one currency or LVC is nonsense.
"""
from __future__ import annotations

from decimal import Decimal


def _config(value_basis: str | None = None) -> dict:
    config = {
        "bcct": {"eligible_import_declaration_types": []},
        "co_stock": {"lot_policy": "line_level"},
        "allocation_code": {"strategy": "same_as_customs_code", "fallback": "same_as_customs_code"},
    }
    if value_basis:
        config["co_stock"]["value_basis"] = value_basis
    return config


def _bcct_row(**overrides) -> dict:
    """A johnson-vn import line as Data Hub hands it over (normalize_bcct_row keeps
    the raw *_nt columns and adds taxable_unit_price / customs_value / currency)."""
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


def _derive(row: dict, value_basis: str | None = None) -> dict:
    from app.co_stock_derivation import co_stock_rows_from_bcct
    rows = co_stock_rows_from_bcct([row], _config(value_basis))
    assert len(rows) == 1
    return rows[0]


# --- default basis: byte-identical to today ---------------------------------

def test_default_basis_reads_the_vnd_taxable_columns():
    row = _derive(_bcct_row())
    assert row["unit_value"] == "19007.89015"
    assert row["unit_value_source"] == "bcct_taxable_unit_price"
    assert row["value_currency"] == "VND"
    assert row["currency"] == "VND"
    assert row["customs_value"] == "380157.803"
    assert row["exchange_rate_to_vnd"] == "1"
    assert row["exchange_rate_source"] == "vnd_native"


def test_default_basis_is_the_config_default():
    from app.client_config_store import default_config
    config = default_config({"id": "acme", "name": "Acme"})
    assert config["co_stock"]["value_basis"] == "taxable_vnd"


# --- invoice_native --------------------------------------------------------

def test_native_basis_reads_the_invoice_columns():
    row = _derive(_bcct_row(), "invoice_native")
    assert row["unit_value"] == "0.735317"
    assert row["unit_value_source"] == "bcct_invoice_unit_price"
    assert row["value_currency"] == "USD"
    assert row["currency"] == "USD"
    # Totals follow the same currency; the VND figures stay for reference.
    assert row["customs_value"] == "14.7063"
    assert row["customs_value_vnd"] == "380157.803"
    assert row["taxable_unit_price"] == "19007.89015"
    # The declaration's own payment rate carries the VND lane.
    assert row["exchange_rate_to_vnd"] == "25850"
    assert row["exchange_rate_source"] == "bcct_declared"


def test_native_basis_leaves_a_vnd_denominated_line_in_vnd():
    """Domestic / nhập tại chỗ lines are declared in VND (9,244 of johnson's
    import lines) — nothing to switch, and the rate must stay 1."""
    row = _derive(_bcct_row(currency_nt="VND", currency="VND", unit_price_nt="19007.890150",
                            total_value_nt="380157.803"), "invoice_native")
    assert row["value_currency"] == "VND"
    assert row["unit_value"] == "19007.89015"
    assert row["exchange_rate_to_vnd"] == "1"


def test_native_basis_derives_the_unit_price_from_the_invoice_total_when_absent():
    row = _derive(_bcct_row(unit_price_nt=""), "invoice_native")
    assert row["unit_value"] == "0.735315"  # 14.7063 / 20
    assert row["unit_value_source"] == "bcct_invoice_value_per_qty"
    assert row["value_currency"] == "USD"


def test_native_basis_falls_back_to_vnd_when_the_line_has_no_invoice_figures():
    """Never label a VND number as USD: with no nguyên-tệ value at all the row
    stays on the VND lane."""
    row = _derive(_bcct_row(unit_price_nt="", total_value_nt="", foreign_currency_value=""), "invoice_native")
    assert row["value_currency"] == "VND"
    assert row["unit_value"] == "19007.89015"
    assert row["unit_value_source"] == "bcct_taxable_unit_price"


def test_value_basis_is_validated():
    import pytest
    from app.client_config_store import migrate_config
    with pytest.raises(ValueError):
        migrate_config({"co_stock": {"lot_policy": "line_level", "value_basis": "usd_maybe"}},
                       {"id": "acme", "name": "Acme"})


def test_changing_the_basis_forces_a_full_re_derivation():
    from app.co_stock_materializer import co_config_fingerprint
    vnd = co_config_fingerprint({"co_stock": {"lot_policy": "line_level", "value_basis": "taxable_vnd"},
                                 "allocation_code": {"strategy": "same_as_customs_code"}})
    native = co_config_fingerprint({"co_stock": {"lot_policy": "line_level", "value_basis": "invoice_native"},
                                    "allocation_code": {"strategy": "same_as_customs_code"}})
    assert vnd != native


# --- allocation lines ------------------------------------------------------

def _usd_lot(**overrides) -> dict:
    lot = {
        "source_row": "import-row-1",
        "import_declaration_no": "107271797510",
        "line_no": "20",
        "customs_item_code": "1000495386",
        "allocation_code": "1000495386",
        "unit_value": "0.735317",
        "taxable_unit_price": "19007.890150",
        "value_currency": "USD",
        "exchange_rate_to_vnd": "25850",
    }
    lot.update(overrides)
    return lot


def test_allocation_line_prices_in_the_lot_currency_and_keeps_a_vnd_lane():
    from app.web.co_case_context import stock_allocation_line
    line = stock_allocation_line(_usd_lot(), Decimal("4"), Decimal("20"), {}, {})
    assert line["unit_value"] == "0.735317"
    assert line["currency"] == "USD"
    assert line["material_value"] == "2.941268"
    assert Decimal(line["unit_value_vnd"]) == Decimal("0.735317") * Decimal("25850")
    assert line["exchange_rate_to_vnd"] == "25850"  # the lot's declared payment rate


def test_a_foreign_lot_never_falls_back_to_the_vnd_taxable_price():
    """taxable_unit_price is always VND. On a USD line it must not be picked up as
    the đơn giá — that would put a VND number in a USD column."""
    from app.web.co_case_context import stock_allocation_line
    line = stock_allocation_line(_usd_lot(unit_value=""), Decimal("4"), Decimal("20"), {}, {})
    assert line["unit_value"] == ""
    assert line["valuation_source"] == ""


def test_a_vnd_lot_still_falls_back_to_the_taxable_price():
    from app.web.co_case_context import stock_allocation_line
    lot = _usd_lot(unit_value="", value_currency="VND", exchange_rate_to_vnd="1")
    line = stock_allocation_line(lot, Decimal("4"), Decimal("20"), {}, {})
    assert Decimal(line["unit_value"]) == Decimal("19007.89015")
    assert line["valuation_source"] == "co_stock"


# --- FOB side --------------------------------------------------------------

def _export_match() -> dict:
    return {
        "item_code": "MPL0109-39",
        "quantity": "2",
        "customs_value": "306528985.86",
        "total_value": "306528985.86",
        "foreign_currency_value": "11727.78",
        "currency": "USD",
        "value_currency": "VND",
    }


def test_fob_follows_the_vnd_basis_by_default():
    from app.web.co_case_context import origin_product_value
    value = origin_product_value(_export_match())
    assert value["value"] == Decimal("306528985.86")
    assert value["currency"] == "VND"


def test_fob_follows_the_invoice_currency_under_the_native_basis():
    from app.web.co_case_context import origin_product_value
    value = origin_product_value(_export_match(), value_basis="invoice_native")
    assert value["value"] == Decimal("11727.78")
    assert value["currency"] == "USD"


def test_fob_native_basis_falls_back_to_vnd_without_an_invoice_value():
    from app.web.co_case_context import origin_product_value
    match = _export_match()
    match["foreign_currency_value"] = ""
    value = origin_product_value(match, value_basis="invoice_native")
    assert value["value"] == Decimal("306528985.86")
    assert value["currency"] == "VND"


# --- mixed-currency materials (only reachable under invoice_native) ---------

def _mixed_currency_product() -> dict:
    """One material drawn from a USD lot and a VND lot. 309 of johnson-vn's 10,393
    import codes have lines in both currencies, so the native basis can produce
    this; the VND basis never can."""
    return {
        "code": "P", "fob": "100",
        "materials": [{
            "material_code": "M", "origin_status": "non_origin",
            "customs_relevance": "declarable",
            "valuation_status": "partial_valuation",
            "unit_value": "Nhiều đơn giá", "currency": "Nhiều tiền tệ",
            "material_value": "", "material_value_vnd": "500000",
            "allocation_lines": [
                {"source_row": "L1", "allocated_qty": "1", "unit_value": "0.7", "currency": "USD"},
                {"source_row": "L2", "allocated_qty": "1", "unit_value": "19000", "currency": "VND"},
            ],
        }],
    }


def test_enrich_flags_mixed_currency_material():
    from app.web.co_case_context import enrich_origin_product
    assert enrich_origin_product(_mixed_currency_product())["lvc_mixed_currency"] is True


def test_enrich_no_mixed_flag_on_single_currency_material():
    from app.web.co_case_context import enrich_origin_product
    product = _mixed_currency_product()
    product["materials"][0].update({"currency": "USD", "valuation_status": "ready", "material_value": "19000.7"})
    assert enrich_origin_product(product)["lvc_mixed_currency"] is False


def test_mixed_currency_stays_bom_loaded():
    from app.routers.co_case import calculated_sheet_status
    assert calculated_sheet_status({"lvc_status": "pass", "lvc_mixed_currency": True}) == "bom_loaded"


def test_lock_gate_names_the_currency_mix_not_a_missing_price():
    from app.web.co_case_context import origin_sheet_action_error
    case = {
        "products": [{"code": "P1", "lvc_status": "pass", "lvc_mixed_currency": True,
                      "lvc_missing_price": True}],
        "origin_sheet_states": {"P1": {"status": "calculated"}},
    }
    error = origin_sheet_action_error(case, "P1", "lock")
    assert "hai loại tiền" in error


def test_attention_chip_names_the_currency_mix():
    from app.web.co_case_context import origin_sheet_attention
    chip = origin_sheet_attention({"origin_sheet_status": "bom_loaded", "lvc_mixed_currency": True,
                                   "lvc_missing_price": True})
    assert chip["reason"] == "mixed_currency"
