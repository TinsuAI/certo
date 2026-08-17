"""Correctness e2e for the two-lane currency design (2026-08-17):

flipping ONE sheet between VND and nguyên tệ must change what the bảng kê PRINTS —
the declaration's own USD đơn giá vs its VND đơn giá tính thuế — without touching the
stock snapshot and without moving LVC.

DB-mode, local, real johnson-vn lots. Refreshes tồn once (the derivation schema bump
forces a full re-derive so existing rows gain the invoice lane), then calculates one
seeded sheet and exports it twice.

    set -a; . ./.env; set +a
    PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_invoice_lane_display.py
"""
import io
import sys
from decimal import Decimal

import openpyxl
from fastapi.testclient import TestClient

import app.main as m
from app import co_case_store
from app.co_case_store import json_safe, now_iso, update_case_record
from app.database import connect
from app.routers.co_case import recalculate_origin_sheet_edits
from app.web.client_context import effective_min_gap_days, resolve_client
from app.web.co_case_context import _refresh_co_stock_delta_or_full
from app.workflow_state_store import get_co_case_state_store

CLIENT = "johnson-vn"
CASE = "e2e-invoice-lane"
CODE = "1000495386"   # USD-declared lot: ~0.73 USD @ ~25.850 = ~19.007 VND


def B(msg):
    print("==== " + str(msg) + " ====", flush=True)


def _cleanup():
    with connect() as c, c.cursor() as cur:
        cur.execute("delete from co.co_stock_claims where case_id=%s", (CASE,))
        cur.execute("delete from co.co_cases where case_id=%s", (CASE,))


def _lot_sample():
    with connect() as c, c.cursor() as cur:
        cur.execute(
            """select payload->>'unit_value', payload->>'value_currency',
                      payload->>'native_currency', payload->>'unit_value_native',
                      payload->>'exchange_rate_to_vnd', payload->>'exchange_rate_source'
               from co.co_stock_rows
               where client_id=%s and customs_item_code=%s and payload->>'native_currency' = 'USD'
               order by source_row limit 1""",
            (CLIENT, CODE),
        )
        return cur.fetchone()


def _num_matches(cell: str, value: Decimal) -> bool:
    """The workbook writes numbers, formatted; compare numerically within a cent."""
    try:
        return abs(Decimal(cell.replace(",", "")) - value) <= Decimal("0.01")
    except Exception:  # noqa: BLE001 — a text cell simply is not the number
        return False


def _cells(content: bytes) -> set:
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    out = set()
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for value in row:
                if value is not None:
                    out.add(str(value).strip())
    wb.close()
    return out


def _set_currency_mode(client, mode):
    record = co_case_store.get_case_record(client, CASE)
    states = dict(record.get("origin_sheet_states") or {})
    state = dict(states.get("TP-A") or {})
    state["currency_mode"] = mode
    states["TP-A"] = state
    record["origin_sheet_states"] = states
    update_case_record(client, record)


m.require_local_source_writes = lambda: None
http = TestClient(m.app)
store = get_co_case_state_store()
assert store is not None, "expected DB-mode"
client = resolve_client(CLIENT)

ok = False
_cleanup()
try:
    summary = _refresh_co_stock_delta_or_full(client)
    B(f"refresh mode={summary.get('mode')} reason={summary.get('reason')}")
    lot = _lot_sample()
    B(f"lot {CODE}: unit_value={lot[0]} value_ccy={lot[1]} native_ccy={lot[2]} "
      f"native={lot[3]} rate={lot[4]} rate_src={lot[5]}")
    lane_ok = (
        lot is not None
        and lot[1] == "VND" and Decimal(lot[0]) > 1000        # calculation lane untouched
        and lot[2] == "USD" and Decimal(lot[3]) < 100         # invoice lane present
        and Decimal(lot[4]) > 1000 and lot[5] == "bcct_declared"
    )

    now = now_iso()
    case = {
        "id": CASE, "persisted_case_id": CASE, "case_id": CASE,
        "case_code": "E2E-INVOICE-LANE", "title": "E2E invoice lane DELETE ME", "customer": "E2E",
        "destination_market": "Canada", "status": "open", "created_at": now, "updated_at": now,
        "shipment": {"invoice_no": "E2E", "export_declaration_nos": []},
        "source_invoice_matches": [],
        "origin_product_order": ["TP-A"],
        "products": [{
            "code": "TP-A", "name": "Thiết bị luyện tập", "finished_hs": "950691",
            "quantity": "10", "unit": "SETS",
            # VND lane (what LVC runs on) + the export declaration's invoice lane.
            "fob": "500000000", "currency": "VND", "fob_currency": "VND",
            "invoice_currency": "USD", "fob_invoice": "19342.7", "fob_fx_rate": "25850",
            "materials": [{"material_code": CODE, "material_description": "Chi tiết nhựa",
                           "uom": "PIECES", "bom_qty_per": "1", "hs_code": "39269099"}],
        }],
        "origin_sheet_states": {"TP-A": {"status": "calculated", "status_label": "calculated",
                                         "currency_mode": "native",
                                         "material_overrides": {"0": {"norm_edit_only": True}}}},
    }
    store.save_case_record(CLIENT, case, 0)
    record = co_case_store.get_case_record(client, CASE)
    record = recalculate_origin_sheet_edits(
        client, record, "TP-A", min_gap_days=effective_min_gap_days(client, {})
    )
    update_case_record(client, record)
    material = co_case_store.get_case_record(client, CASE)["products"][0]["materials"][0]
    B(f"material: unit_value={material.get('unit_value')} ccy={material.get('currency')} "
      f"native_ccy={material.get('native_currency')} native={material.get('unit_value_native')} "
      f"value={material.get('material_value')} value_vnd={material.get('material_value_vnd')}")
    material_ok = (
        material.get("currency") == "VND"
        and material.get("native_currency") == "USD"
        and material.get("unit_value_native") not in (None, "")
        and Decimal(material["unit_value_native"]) < 100
        and Decimal(material["unit_value"]) > 1000
    )
    # Compare the FILE against what THIS sheet computed (the allocation may pick a
    # different lot of the same code than the sample above).
    native_price = Decimal(material["unit_value_native"])
    vnd_price = Decimal(material["unit_value"])
    lvc_native = co_case_store.get_case_record(client, CASE)["products"][0].get("lvc_percentage")

    # --- export in nguyên tệ: must print the declaration's USD figure ---------
    r_native = http.get(f"/clients/{CLIENT}/co-case/{CASE}/export-bang-ke")
    cells_native = _cells(r_native.content) if r_native.status_code == 200 else set()
    has_usd_label = any(cell == "USD" for cell in cells_native)
    has_native_price = any(_num_matches(cell, native_price) for cell in cells_native)
    B(f"native export HTTP {r_native.status_code} usd_label={has_usd_label} native_price={has_native_price}")

    # --- same sheet, VND mode: no re-derivation, only the printed lane changes -
    _set_currency_mode(client, "vnd")
    r_vnd = http.get(f"/clients/{CLIENT}/co-case/{CASE}/export-bang-ke")
    cells_vnd = _cells(r_vnd.content) if r_vnd.status_code == 200 else set()
    has_vnd_label = any(cell == "VND" for cell in cells_vnd)
    has_vnd_price = any(_num_matches(cell, vnd_price) for cell in cells_vnd)
    B(f"vnd export HTTP {r_vnd.status_code} vnd_label={has_vnd_label} vnd_price={has_vnd_price}")

    lvc_vnd = co_case_store.get_case_record(client, CASE)["products"][0].get("lvc_percentage")
    B(f"LVC native-mode={lvc_native} vnd-mode={lvc_vnd} (must match — the ratio is VND either way)")

    ok = bool(
        lane_ok and material_ok
        and r_native.status_code == 200 and r_vnd.status_code == 200
        and has_usd_label and has_native_price
        and has_vnd_label and has_vnd_price
        and lvc_native == lvc_vnd
    )
finally:
    _cleanup()
    with connect() as c, c.cursor() as cur:
        cur.execute("select count(*) from co.co_cases where case_id=%s", (CASE,))
        left = cur.fetchone()[0]
    print("CLEANUP_OK" if left == 0 else "CLEANUP_MISMATCH", flush=True)

print("E2E_PASS" if ok else "E2E_FAIL", flush=True)
sys.exit(0 if ok else 1)
