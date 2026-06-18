"""Correctness e2e: substitute a material, then export the HQ bảng kê and check
the FINAL workbook reflects the swap. DB-mode, local, real growatt-vn stock.

Flow: seed a case whose sheet is calculated against a real lot (940.0661900);
export → the bảng kê shows that code. Then POST /origin/bulk-substitute to swap
it to 940.0662900; export again → the bảng kê now shows the SUBSTITUTE code and
no longer the original, with the consumed qty preserved. Self-cleaning.

Run with .env sourced:
    set -a; . ./.env; set +a
    PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_substitute_export.py
"""
import io
import sys

import openpyxl
from fastapi.testclient import TestClient

import app.main as m
from app import co_case_store
from app.routers.co_case import recalculate_origin_sheet_edits
from app.web.client_context import resolve_client, effective_min_gap_days
from app.workflow_state_store import get_co_case_state_store
from app.co_case_store import update_case_record
from app.database import connect

CLIENT = "growatt-vn"
CASE = "e2e-sub-export"
ORIG = "940.0661900"   # real lot, ~6000 tồn
SUBST = "940.0662900"  # real lot, ~6000 tồn (a DH substitute of ORIG)


def B(msg):
    print("==== " + str(msg) + " ====", flush=True)


def _cleanup():
    with connect() as c, c.cursor() as cur:
        cur.execute("delete from co_stock_claims where case_id=%s", (CASE,))
        cur.execute("delete from co_cases where case_id=%s", (CASE,))


def _codes_in_workbook(content: bytes) -> set:
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    cells = set()
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for v in row:
                if v is not None:
                    cells.add(str(v).strip())
    wb.close()
    return cells


m.require_local_source_writes = lambda: None
http = TestClient(m.app)
store = get_co_case_state_store()
assert store is not None, "expected DB-mode"
client = resolve_client(CLIENT)

_cleanup()
ok = False
try:
    now = co_case_store.now_iso()
    case = {
        "id": CASE, "persisted_case_id": CASE, "case_id": CASE,
        "case_code": "E2E-SUB-EXPORT", "title": "E2E sub export DELETE ME", "customer": "E2E",
        "destination_market": "Ấn Độ", "status": "open", "created_at": now, "updated_at": now,
        "shipment": {"invoice_no": "E2E", "export_declaration_nos": []},
        "source_invoice_matches": [],
        "origin_product_order": ["TP-A"],
        "products": [{
            "code": "TP-A", "name": "Bộ biến tần", "finished_hs": "850440", "fob": "100000",
            "quantity": "100", "currency": "USD",
            "materials": [{"material_code": ORIG, "material_description": "Tem nhãn 70x100",
                           "uom": "cái", "bom_qty_per": "10", "hs_code": "48219090"}],
        }],
        # norm_edit_only override forces the recompute path (materials from seed).
        "origin_sheet_states": {"TP-A": {"status": "calculated", "status_label": "calculated",
                                         "material_overrides": {"0": {"norm_edit_only": True}}}},
    }
    store.save_case_record(CLIENT, case, 0)
    # baseline: allocate the sheet against real stock + persist (so export has lines)
    rec = co_case_store.get_case_record(client, CASE)
    min_gap = effective_min_gap_days(client, {})
    rec = recalculate_origin_sheet_edits(client, rec, "TP-A", min_gap_days=min_gap)
    update_case_record(client, rec)
    mats = co_case_store.get_case_record(client, CASE)["products"][0]["materials"]
    B(f"baseline material[0]={mats[0].get('material_code')} status={mats[0].get('allocation_status')} consumed={mats[0].get('consumed_qty')}")

    # export BEFORE
    r1 = http.get(f"/clients/{CLIENT}/co-case/{CASE}/export-bang-ke")
    B(f"export-before HTTP {r1.status_code} bytes={len(r1.content)}")
    codes1 = _codes_in_workbook(r1.content)
    before_has_orig = ORIG in codes1
    before_has_subst = SUBST in codes1
    B(f"BEFORE: orig({ORIG})={before_has_orig} subst({SUBST})={before_has_subst}")

    # substitute ORIG -> SUBST via the real bulk endpoint
    rsub = http.post(f"/clients/{CLIENT}/co-case/{CASE}/origin/bulk-substitute",
                     json={"substitutions": [{"product_code": "TP-A", "material_code": ORIG, "substitute_code": SUBST}]})
    B(f"bulk-substitute HTTP {rsub.status_code} applied={rsub.json().get('applied')}")
    mats2 = co_case_store.get_case_record(client, CASE)["products"][0]["materials"]
    B(f"after-swap material[0]={mats2[0].get('material_code')} status={mats2[0].get('allocation_status')} consumed={mats2[0].get('consumed_qty')}")

    # export AFTER
    r2 = http.get(f"/clients/{CLIENT}/co-case/{CASE}/export-bang-ke")
    B(f"export-after HTTP {r2.status_code} bytes={len(r2.content)}")
    codes2 = _codes_in_workbook(r2.content)
    after_has_orig = ORIG in codes2
    after_has_subst = SUBST in codes2
    B(f"AFTER: orig({ORIG})={after_has_orig} subst({SUBST})={after_has_subst}")

    ok = (
        r1.status_code == 200 and r2.status_code == 200 and rsub.status_code == 200
        and before_has_orig and not before_has_subst          # before: only the original code
        and after_has_subst and not after_has_orig            # after: only the substitute code
        and mats2[0].get("material_code") == SUBST            # persisted material swapped
        and str(mats2[0].get("consumed_qty")) == str(mats[0].get("consumed_qty"))  # norm preserved
    )
finally:
    _cleanup()
    with connect() as c, c.cursor() as cur:
        cur.execute("select count(*) from co_cases where case_id=%s", (CASE,))
        left = cur.fetchone()[0]
    print("CLEANUP_OK" if left == 0 else "CLEANUP_MISMATCH", flush=True)

print("E2E_PASS" if ok else "E2E_FAIL", flush=True)
sys.exit(0 if ok else 1)
