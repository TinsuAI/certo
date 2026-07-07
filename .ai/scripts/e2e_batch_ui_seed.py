"""Seed a multi-SP SHORTFALL case (real growatt-vn stock) for the batch
sheet-tổng-hợp UI e2e, and verify preview-stock-all returns a material-centric
rollup with the shortfall. Leaves the case in the DB so the browser can drive it.

  set -a; . ./.env.dev; set +a
  PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_batch_ui_seed.py
  # ... drive :8001 in the browser ...
  PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_batch_ui_seed.py --cleanup
"""
import sys

from fastapi.testclient import TestClient

import app.main as m
from app import co_case_store
from app.database import connect

CLIENT = "growatt-vn"
CASE = "e2e-batch-ui"
MAT = "940.0661900"   # real lot, ~6000 tồn
N = 5                 # 5 SP each consuming 2000 → ~10000 need > ~6000 stock → later SP short


def _cleanup():
    with connect() as c, c.cursor() as cur:
        cur.execute("delete from co_stock_claims where case_id=%s", (CASE,))
        cur.execute("delete from co_cases where case_id=%s", (CASE,))
    print("CLEANED", CASE, flush=True)


if "--cleanup" in sys.argv:
    _cleanup()
    sys.exit(0)

m.require_local_source_writes = lambda: None
http = TestClient(m.app)
now = co_case_store.now_iso()

codes = [f"SP-{i+1}" for i in range(N)]
products = [{
    "code": code, "name": f"Tấm pin lô {i+1}", "finished_hs": "854143", "fob": "100000",
    "quantity": "200", "currency": "USD",
    "materials": [{"material_code": MAT, "material_description": "Thanh nhôm khung",
                   "uom": "kg", "bom_qty_per": "10", "hs_code": "76042100"}],
} for i, code in enumerate(codes)]
sheet_states = {code: {"status": "calculated", "status_label": "calculated",
                       "material_overrides": {"0": {"norm_edit_only": True}}} for code in codes}
case = {
    "id": CASE, "persisted_case_id": CASE, "case_id": CASE,
    "case_code": "E2E-BATCH-UI", "title": "E2E batch UI DELETE ME", "customer": "E2E",
    "destination_market": "Ấn Độ", "status": "open", "created_at": now, "updated_at": now,
    "shipment": {"invoice_no": "E2E", "export_declaration_nos": []},
    "source_invoice_matches": [], "origin_product_order": codes,
    "products": products, "origin_sheet_states": sheet_states,
}

from app.workflow_state_store import get_co_case_state_store
store = get_co_case_state_store()
assert store is not None, "expected DB-mode — source .env.dev"
_cleanup()
store.save_case_record(CLIENT, case, 0)

r = http.post(f"/clients/{CLIENT}/co-case/{CASE}/origin/preview-stock-all", json={})
print("preview-stock-all HTTP", r.status_code, flush=True)
body = r.json()
rollup = body.get("rollup", {})
print("rollup material_count:", rollup.get("material_count"), flush=True)
for mm in rollup.get("materials", []):
    print(f"  {mm['material_code']}: cần {mm['needed']} tồn {mm['available']} thiếu {mm['short_qty']} {mm['uom']} "
          f"· thiếu {mm['short_count']}/{mm['using_count']} SP · shortIn={mm['short_products']}", flush=True)
print("SEED_OK — case left in DB; open http://127.0.0.1:8001/clients/%s/co-case/%s/origin" % (CLIENT, CASE), flush=True)
