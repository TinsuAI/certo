"""Correctness e2e for Phase B (ĐVT) + Phase C (tiêu chí), 2026-08-17.

Real johnson-vn lots, DB-mode, local. Uses code 1000485357, whose lots are all counted
in SETS, against a BOM row in EA — the pair CO used to treat as 1:1.

Checks, in order:
1. Tính with the mismatch → the row keeps 1:1 numbers, is flagged, and the sheet is
   held out of `calculated`; Chốt refuses and names ĐVT.
2. POST the uom-factor route as the operator would from the row ("1 SET = 5 EA") →
   the demand converts (10 EA → 2 SETS off the lot), the flag clears.
3. Chốt still refuses — now for the criterion, which nobody chose.
4. POST the case-criteria route ("CTH") → every sheet inherits it, the criterion gate
   passes, and the LVC metric stops being a pass/fail (a tariff-shift rule has no
   threshold to meet).

    set -a; . ./.env; set +a
    PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_uom_and_criteria.py
"""
import sys
from decimal import Decimal

from fastapi.testclient import TestClient

import app.main as m
from app import co_case_store, uom_factor_store
from app.co_case_store import now_iso, update_case_record
from app.database import connect
from app.routers.co_case import calculated_sheet_status, recalculate_origin_sheet_edits
from app.web.client_context import effective_min_gap_days, resolve_client
from app.web.co_case_context import (
    attach_origin_sheet_states,
    enrich_origin_product,
    origin_sheet_action_error,
)
from app.workflow_state_store import get_co_case_state_store

CLIENT = "johnson-vn"
CASE = "e2e-uom-criteria"
CODE = "1000485357"      # every lot of this code is counted in SETS
BOM_UOM = "EA"


def B(msg):
    print("==== " + str(msg) + " ====", flush=True)


def _cleanup():
    with connect() as c, c.cursor() as cur:
        cur.execute("delete from co.co_stock_claims where case_id=%s", (CASE,))
        cur.execute("delete from co.co_cases where case_id=%s", (CASE,))
        cur.execute("delete from co.co_uom_factor where client_id=%s and material_code=%s", (CLIENT, CODE))


def _recalc(client):
    record = co_case_store.get_case_record(client, CASE)
    record = recalculate_origin_sheet_edits(
        client, record, "TP-A", min_gap_days=effective_min_gap_days(client, {})
    )
    update_case_record(client, record)
    record = co_case_store.get_case_record(client, CASE)
    product = enrich_origin_product(attach_origin_sheet_states(record)["products"][0])
    return record, product, product["materials"][0]


m.require_local_source_writes = lambda: None
http = TestClient(m.app)
store = get_co_case_state_store()
assert store is not None, "expected DB-mode"
client = resolve_client(CLIENT)

ok = False
_cleanup()
try:
    now = now_iso()
    case = {
        "id": CASE, "persisted_case_id": CASE, "case_id": CASE,
        "case_code": "E2E-UOM-CRITERIA", "title": "E2E uom+criteria DELETE ME", "customer": "E2E",
        "destination_market": "Canada", "status": "open", "created_at": now, "updated_at": now,
        "shipment": {"invoice_no": "E2E", "export_declaration_nos": []},
        "source_invoice_matches": [], "origin_product_order": ["TP-A"],
        "products": [{
            "code": "TP-A", "name": "Thiết bị luyện tập", "finished_hs": "950691",
            "quantity": "5", "unit": "SETS", "fob": "500000000", "currency": "VND",
            "materials": [{"material_code": CODE, "material_description": "NVL SETS",
                           "uom": BOM_UOM, "bom_qty_per": "2", "hs_code": "39269099"}],
        }],
        "origin_sheet_states": {"TP-A": {"status": "calculated", "status_label": "calculated",
                                         "material_overrides": {"0": {"norm_edit_only": True}}}},
    }
    store.save_case_record(CLIENT, case, 0)

    # 1. mismatch → 1:1 numbers, flagged, not lockable
    record, product, material = _recalc(client)
    line = (material.get("allocation_lines") or [{}])[0]
    B(f"before: bom_uom={material.get('uom')} lot_uom={material.get('lot_uom')} "
      f"allocated={line.get('allocated_qty')} bom_uom_qty={line.get('allocated_qty_bom_uom')} "
      f"factor_src={line.get('uom_factor_source')} flagged={material.get('uom_unconfirmed')}")
    lock_error_uom = origin_sheet_action_error(record, "TP-A", "lock")
    status_before = calculated_sheet_status(product)
    B(f"status={status_before} lock_error={lock_error_uom[:90]}")
    step1 = (
        material.get("lot_uom") == "SETS"
        and material.get("uom_unconfirmed") is True
        and line.get("allocated_qty") == "10"          # today's 1:1 arithmetic, unchanged
        and line.get("uom_factor_source") == "unconfirmed"
        and status_before == "bom_loaded"
        and "đơn vị tính" in lock_error_uom.lower()
    )

    # 2. the operator confirms 1 SET = 5 EA, from the row
    response = http.post(
        f"/clients/{CLIENT}/co-case/{CASE}/origin/uom-factor",
        json={"product_code": "TP-A", "material_code": CODE, "bom_uom": BOM_UOM,
              "lot_uom": "SETS", "factor": str(Decimal(1) / Decimal(5)), "scope": "material"},
    )
    B(f"uom-factor HTTP {response.status_code} {response.json() if response.status_code == 200 else response.text[:120]}")
    record, product, material = _recalc(client)
    line = (material.get("allocation_lines") or [{}])[0]
    B(f"after factor: allocated={line.get('allocated_qty')} (SETS) "
      f"bom_uom_qty={line.get('allocated_qty_bom_uom')} (EA) factor={line.get('uom_factor')} "
      f"src={line.get('uom_factor_source')} flagged={material.get('uom_unconfirmed')}")
    step2 = (
        response.status_code == 200
        and material.get("uom_unconfirmed") is False
        and line.get("allocated_qty") == "2"           # 10 EA ÷ 5 = 2 SETS off the lot
        and line.get("allocated_qty_bom_uom") == "10"
        and line.get("uom_factor_source") == "operator_confirmed"
        and uom_factor_store.factor_map(CLIENT).get(("PIECES", "SETS", CODE)) == Decimal("0.2")
    )

    # 3. now the criterion is what blocks
    lock_error_criteria = origin_sheet_action_error(record, "TP-A", "lock")
    B(f"lock error now: {lock_error_criteria[:110]}")
    step3 = "tiêu chí" in lock_error_criteria.lower()

    # 4. choose the criterion for the whole lô hàng
    response2 = http.post(
        f"/clients/{CLIENT}/co-case/{CASE}/origin/case-criteria",
        json={"criteria_text": "CTH"},
    )
    record = co_case_store.get_case_record(client, CASE)
    product = enrich_origin_product(attach_origin_sheet_states(record)["products"][0])
    B(f"case-criteria HTTP {response2.status_code} source={product.get('origin_sheet_criteria_source')} "
      f"effective={product.get('origin_sheet_effective_criteria_text')} "
      f"family={product.get('origin_sheet_criteria_family')} lvc_applies={product.get('origin_sheet_lvc_applies')} "
      f"threshold={product.get('origin_sheet_effective_lvc_threshold')!r} method={product.get('origin_method_label')}")
    lock_error_after = origin_sheet_action_error(record, "TP-A", "lock")
    B(f"lock error after choosing: {lock_error_after[:110] or '(none)'}")
    step4 = (
        response2.status_code == 200
        and product.get("origin_sheet_criteria_source") == "case"
        and product.get("origin_sheet_effective_criteria_text") == "CTH"
        and product.get("origin_sheet_criteria_family") == "tariff_shift"
        and product.get("origin_sheet_lvc_applies") is False
        and product.get("origin_sheet_effective_lvc_threshold") == ""
        and product.get("origin_method_label") == "Chuyển đổi mã số (CTC)"
        and "tiêu chí" not in lock_error_after.lower()
    )
    B(f"steps: uom_gap={step1} converted={step2} criteria_blocks={step3} criteria_chosen={step4}")
    ok = bool(step1 and step2 and step3 and step4)
finally:
    _cleanup()
    with connect() as c, c.cursor() as cur:
        cur.execute("select count(*) from co.co_cases where case_id=%s", (CASE,))
        left = cur.fetchone()[0]
    print("CLEANUP_OK" if left == 0 else "CLEANUP_MISMATCH", flush=True)

print("E2E_PASS" if ok else "E2E_FAIL", flush=True)
sys.exit(0 if ok else 1)
