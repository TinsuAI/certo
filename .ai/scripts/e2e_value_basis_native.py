"""Correctness e2e for `co_stock.value_basis = invoice_native` (Q1, 2026-08-17):
the bảng kê must carry the declaration's ĐƠN GIÁ NGUYÊN TỆ (USD) instead of the
VND taxable price, end to end — derivation → allocation → grid → HQ workbook.

DB-mode, local, real johnson-vn BCCT (54,787 USD import lines + 5,386 VND ones).
Flips the client's value basis, re-derives tồn, calculates one seeded sheet against
a real lot, exports the workbook, then restores the basis and re-derives back.

    set -a; . ./.env; set +a
    PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_value_basis_native.py
"""
import io
import sys
from decimal import Decimal

import openpyxl
from fastapi.testclient import TestClient

import app.main as m
from app import co_case_store
from app.co_case_store import update_case_record
from app.database import connect
from app.portfolio import portfolio_service
from app.routers.co_case import recalculate_origin_sheet_edits
from app.web.client_context import effective_min_gap_days, resolve_client
from app.web.co_case_context import _refresh_co_stock_delta_or_full
from app.workflow_state_store import get_co_case_state_store

CLIENT = "johnson-vn"
CASE = "e2e-value-basis"
CODE = "1000495386"          # USD-declared lot: 0.735317 USD / 19,007.89015 VND
VND_CODE_HINT = "USD"


def B(msg):
    print("==== " + str(msg) + " ====", flush=True)


def _cleanup_case():
    with connect() as c, c.cursor() as cur:
        cur.execute("delete from co_stock_claims where case_id=%s", (CASE,))
        cur.execute("delete from co_cases where case_id=%s", (CASE,))


def _set_basis(client, basis):
    config = portfolio_service.get_client_config(client)
    config["co_stock"]["value_basis"] = basis
    portfolio_service.save_client_config(client, config)
    saved = portfolio_service.get_client_config(client)["co_stock"].get("value_basis")
    B(f"value_basis = {saved}")
    summary = _refresh_co_stock_delta_or_full(client)
    B(f"refresh mode={summary.get('mode')} reason={summary.get('reason')} rows={summary.get('row_count')}")
    return saved


def _stock_sample(code):
    with connect() as c, c.cursor() as cur:
        cur.execute(
            """select payload->>'unit_value', payload->>'value_currency',
                      payload->>'exchange_rate_to_vnd', payload->>'taxable_unit_price',
                      payload->>'unit_value_source'
               from co.co_stock_rows
               where client_id=%s and customs_item_code=%s
               order by source_row limit 1""",
            (CLIENT, code),
        )
        return cur.fetchone()


def _currency_cells(content: bytes) -> set:
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    cells = set()
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for value in row:
                if value is not None:
                    cells.add(str(value).strip())
    wb.close()
    return cells


m.require_local_source_writes = lambda: None
http = TestClient(m.app)
store = get_co_case_state_store()
assert store is not None, "expected DB-mode"
client = resolve_client(CLIENT)
original_basis = portfolio_service.get_client_config(client)["co_stock"].get("value_basis") or "taxable_vnd"
B(f"original basis = {original_basis}")

ok = False
_cleanup_case()
try:
    # --- baseline: the VND basis prices the lot in VND -----------------------
    _set_basis(client, "taxable_vnd")
    vnd_row = _stock_sample(CODE)
    B(f"VND basis stock row {CODE}: {vnd_row}")
    vnd_ok = vnd_row is not None and vnd_row[1] == "VND" and Decimal(vnd_row[0]) > 1000

    # --- flip to the invoice currency ---------------------------------------
    _set_basis(client, "invoice_native")
    usd_row = _stock_sample(CODE)
    B(f"native basis stock row {CODE}: {usd_row}")
    native_ok = (
        usd_row is not None
        and usd_row[1] == "USD"
        and Decimal(usd_row[0]) < 100                     # a USD unit price, not the VND one
        and Decimal(usd_row[2]) > 1000                    # the declared payment rate carries the VND lane
        and Decimal(usd_row[3]) > 1000                    # VND taxable price kept for reference
        and usd_row[4] == "bcct_invoice_unit_price"
    )

    # --- a real sheet calculated on that basis ------------------------------
    now = co_case_store.now_iso()
    case = {
        "id": CASE, "persisted_case_id": CASE, "case_id": CASE,
        "case_code": "E2E-VALUE-BASIS", "title": "E2E value basis DELETE ME", "customer": "E2E",
        "destination_market": "Canada", "status": "open", "created_at": now, "updated_at": now,
        "shipment": {"invoice_no": "E2E", "export_declaration_nos": []},
        "source_invoice_matches": [],
        "origin_product_order": ["TP-A"],
        "products": [{
            "code": "TP-A", "name": "Thiết bị luyện tập", "finished_hs": "950691", "fob": "5000",
            "quantity": "10", "currency": "USD",
            "materials": [{"material_code": CODE, "material_description": "Chi tiết nhựa",
                           "uom": "PIECES", "bom_qty_per": "1", "hs_code": "39269099"}],
        }],
        "origin_sheet_states": {"TP-A": {"status": "calculated", "status_label": "calculated",
                                         "material_overrides": {"0": {"norm_edit_only": True}}}},
    }
    store.save_case_record(CLIENT, case, 0)
    record = co_case_store.get_case_record(client, CASE)
    record = recalculate_origin_sheet_edits(
        client, record, "TP-A", min_gap_days=effective_min_gap_days(client, {})
    )
    update_case_record(client, record)
    material = co_case_store.get_case_record(client, CASE)["products"][0]["materials"][0]
    B(f"sheet material: unit_value={material.get('unit_value')} currency={material.get('currency')} "
      f"value={material.get('material_value')} status={material.get('allocation_status')} "
      f"source={material.get('valuation_source')}")
    sheet_ok = (
        material.get("currency") == "USD"
        and material.get("unit_value")
        and Decimal(material["unit_value"]) < 100
        and material.get("allocation_status") == "covered"
    )

    # --- the exported HQ workbook must say USD, not VND ---------------------
    response = http.get(f"/clients/{CLIENT}/co-case/{CASE}/export-bang-ke")
    B(f"export HTTP {response.status_code} bytes={len(response.content)}")
    cells = _currency_cells(response.content) if response.status_code == 200 else set()
    export_ok = response.status_code == 200 and any("USD" in cell for cell in cells)
    B(f"workbook mentions USD: {export_ok}")

    ok = bool(vnd_ok and native_ok and sheet_ok and export_ok)
finally:
    _cleanup_case()
    _set_basis(client, original_basis)
    with connect() as c, c.cursor() as cur:
        cur.execute("select count(*) from co.co_cases where case_id=%s", (CASE,))
        left = cur.fetchone()[0]
    print("CLEANUP_OK" if left == 0 else "CLEANUP_MISMATCH", flush=True)

print("E2E_PASS" if ok else "E2E_FAIL", flush=True)
sys.exit(0 if ok else 1)
