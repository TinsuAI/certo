"""Bảng kê HQ export field wiring — user-flagged checklist:

  1. Tên thương nhân = client.legal_name (fallback client.name).
  2. Mã số thuế = client.tax_code (must appear on bảng kê).
  3. Tờ khai xuất khẩu = product.source_declaration_no + source_declaration_date.
  4. Đơn vị tiền tệ trên FOB phải khớp product.currency (không hardcode USD).
"""
from __future__ import annotations

from unittest.mock import patch

from app import bang_ke_renderer, bang_ke_xml_generator, main as main_module, workbook_io
from app.bang_ke_xml_generator import FormSpec
from app.co_case_store import case_from_record


def test_case_from_record_propagates_legal_name_and_tax_code():
    client = {"id": "demo", "name": "Growatt", "legal_name": "CÔNG TY TNHH GROWATT VIỆT NAM", "tax_code": "0123456789"}
    record = {"case_id": "case-1", "case_code": "DEMO", "title": "X", "destination_market": "EU"}
    case = case_from_record({}, client, record)
    assert case["customer_legal_name"] == "CÔNG TY TNHH GROWATT VIỆT NAM"
    assert case["customer"] == "CÔNG TY TNHH GROWATT VIỆT NAM"
    assert case["customer_tax_code"] == "0123456789"


def test_case_from_record_falls_back_to_name_when_legal_name_missing():
    client = {"id": "demo", "name": "Growatt", "tax_code": ""}
    record = {"case_id": "case-2", "case_code": "DEMO", "title": "X", "destination_market": "EU"}
    case = case_from_record({}, client, record)
    assert case["customer_legal_name"] == ""
    assert case["customer"] == "Growatt"
    assert case["customer_tax_code"] == ""


def _sample_case_and_product():
    case = {
        "customer_legal_name": "CÔNG TY TNHH X",
        "customer": "CÔNG TY TNHH X",
        "customer_tax_code": "0123",
        "shipment": {"export_declaration_nos": []},
    }
    product = {
        "name": "Product",
        "code": "P1",
        "finished_hs": "850440",
        "quantity": "100",
        "uom": "PCS",
        "currency": "VND",
        "fob": "1000000",
        "source_declaration_no": "308449399330",
        "source_declaration_date": "15/03/2026",
        "materials": [],
    }
    return case, product


def test_xml_generator_field_table_uses_dynamic_currency_and_propagates_identity():
    case, product = _sample_case_and_product()
    form = FormSpec(criterion="LVC", phu_luc="", title="", legal_note="", conclusion="", show_cost_buildup=False)
    fields = bang_ke_xml_generator._build_field_table(case, product, form)
    assert fields["merchant"] == "CÔNG TY TNHH X"
    assert fields["tax_code"] == "0123"
    assert fields["declaration"] == {"no": "308449399330", "date": "15/03/2026"}
    assert "fob_usd" not in fields
    fob_block = fields["fob_with_currency"]
    assert fob_block["currency"] == "VND"
    assert fob_block["fob"]


def test_xml_generator_field_table_with_usd_currency():
    case, product = _sample_case_and_product()
    product["currency"] = "USD"
    form = FormSpec(criterion="LVC", phu_luc="", title="", legal_note="", conclusion="", show_cost_buildup=False)
    fields = bang_ke_xml_generator._build_field_table(case, product, form)
    assert fields["fob_with_currency"]["currency"] == "USD"


def test_renderer_field_table_uses_legal_name():
    case, product = _sample_case_and_product()
    fields = bang_ke_renderer._build_field_table(case, product)
    assert fields["merchant"] == "CÔNG TY TNHH X"
    assert fields["tax_code"] == "0123"
    assert fields["declaration"] == {"no": "308449399330", "date": "15/03/2026"}


def test_backfill_uses_cached_matches_when_available():
    case = {
        "products": [
            {"source_declaration_no": "308449399330", "source_declaration_date": ""},
        ],
        "source_invoice_matches": [
            {"declaration_no": "308449399330", "declaration_date": "21/04/2026"},
        ],
    }
    main_module._hydrate_product_export_declaration_dates(case, client={"id": "growatt"})
    assert case["products"][0]["source_declaration_date"] == "21/04/2026"


def test_backfill_falls_back_to_data_hub_and_updates_cache():
    case = {
        "products": [
            {"source_declaration_no": "308449399330", "source_declaration_date": ""},
        ],
        "source_invoice_matches": [
            {"declaration_no": "308449399330"},  # cached match without date
        ],
    }
    fake_dates = {"308449399330": "21/04/2026"}
    with patch.object(main_module, "_fetch_export_declaration_dates", return_value=fake_dates):
        main_module._hydrate_product_export_declaration_dates(case, client={"id": "growatt"})
    assert case["products"][0]["source_declaration_date"] == "21/04/2026"
    # Cache should be patched so subsequent renders skip the Data Hub call.
    assert case["source_invoice_matches"][0]["declaration_date"] == "21/04/2026"


def test_backfill_iso_to_vietnamese_date_format():
    # Data Hub returns earliest_bcct_date as ISO; xlsx expects DD/MM/YYYY.
    assert main_module._to_vietnamese_date("2026-04-21") == "21/04/2026"
    assert main_module._to_vietnamese_date("") == ""
    assert main_module._to_vietnamese_date("not-a-date") == "not-a-date"  # passthrough


def test_xml_config_uses_dynamic_currency_format():
    config_text = (workbook_io.__file__ + "/../..").replace("/app/", "/")  # repo root via app path
    # Read the XML config directly to assert no hard-coded "USD".
    import pathlib

    repo_root = pathlib.Path(workbook_io.__file__).resolve().parents[1]
    xml = (repo_root / "config" / "bang-ke-config.xml").read_text(encoding="utf-8")
    assert 'format="{fob} USD"' not in xml
    assert 'field="fob_with_currency"' in xml
    assert 'format="{fob} {currency}"' in xml
