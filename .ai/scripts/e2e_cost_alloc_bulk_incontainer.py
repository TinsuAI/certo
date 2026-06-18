"""In-container e2e for Mục 4a — bulk cost-allocation ("Áp hệ số CP tất cả SP").

WHY in-container: prod + nightly both run `CO_AUTH_REQUIRED=1` + `DATA_HUB_ENABLED=1`,
so a headless browser/HTTP e2e needs an SSO token we don't have. Instead we exercise
the EXACT route logic against the DEPLOYED image + real Postgres (DB-mode) from inside
the app container. This covers the DB-mode persistence path that the file-mode unit
tests (tests/test_cost_allocation_*) do not.

WHAT it does (idempotent, self-cleaning): seed a throwaway case + one Mode-A ratio under
a UNIQUE test product code (NO Mode B → real per-client fallback untouched), run the bulk
flow, verify cost_buildup persisted in Postgres, then ALWAYS delete the case + ratio in a
`finally`. Picks `johnson-vn` (a DH client with 0 ratios → fully isolated from Growatt's
real 24). Verify cleanup independently with SQL afterwards (see bottom).

HOW to run (nightly/demo stack — NEVER seed prod, it has live data):
    cat .ai/scripts/e2e_cost_alloc_bulk_incontainer.py | \
      ssh tinsu 'docker exec -i -e COST_ALLOCATION_CONFIG_ROOT=/tmp/e2e-costalloc \
                 nightly-co-app-1 python -'
  Expect tail: `CLEANUP_OK` then `E2E_PASS` (exit 0).
  `-e COST_ALLOCATION_CONFIG_ROOT=/tmp/...` redirects the ratio JSON mirror to an
  ephemeral dir so no real config/cost-allocation/*.json is touched (DB stays authoritative).

INDEPENDENT cleanup check (run after):
    ssh tinsu "docker exec nightly-co-db-1 psql -U co -d barry_co -At \
      -c \"select count(*) from co_cases where case_id like 'e2e-%'\" \
      -c \"select count(*) from co_cost_allocation_ratio where product_code like 'E2E-%'\""
  Both must be 0.

Container names: nightly = nightly-co-app-1 / nightly-co-db-1 (demo-co.tinsu.ai);
prod = co-app-1 / co-db-1 (barry-co.tinsu.ai). Run on NIGHTLY only.
"""
import sys
from decimal import Decimal

CLIENT = "johnson-vn"
CASE_ID = "e2e-bulk4a-demo"
P1, P2 = "E2E-BULK4A-A", "E2E-BULK4A-NORATIO"

from app import co_case_store, cost_allocation_store
from app.cost_allocation_store import CostAllocationRow
from app.cost_allocation_importer import bulk_apply_to_products
from app.web.co_case_context import attach_origin_sheet_states
from app.co_case_store import get_case_record, update_case_record, delete_case_record
from app.workflow_state_store import get_co_case_state_store


def B(m):
    print("==== " + str(m) + " ====", flush=True)


store = get_co_case_state_store()
assert store is not None, "expected DB-mode store (BARRY_DATABASE_URL must be set)"
# Stub client dict: the bulk flow only needs client["id"]. resolve_client() does a
# DH /v1/hub lookup needing the app's request auth context (401 from a bare script)
# and is NOT part of the feature under test, so we skip it deliberately.
client = {"id": CLIENT, "name": "E2E Johnson"}

cases0 = len(co_case_store.load_state(CLIENT)["cases"])
ratios0 = len(cost_allocation_store.list_ratios(CLIENT))
B(f"BEFORE cases={cases0} ratios={ratios0}")

ok = False
try:
    cost_allocation_store.upsert_ratio(CLIENT, CostAllocationRow(
        product_code=P1, coef_wages=Decimal("0.03"), coef_welfare=Decimal("0.005"),
        coef_rent=Decimal("0.01"), coef_depreciation=Decimal("0.008"),
        coef_other_mfg=Decimal("0.004"), coef_transport_storage=Decimal("0.003"),
        note="E2E bulk4a — DELETE ME"))

    now = co_case_store.now_iso()
    case = {
        "id": CASE_ID, "persisted_case_id": CASE_ID, "case_id": CASE_ID,
        "case_code": "E2E-BULK4A", "title": "E2E bulk4a DELETE ME", "customer": "E2E",
        "destination_market": "Ấn Độ", "agreement": "", "co_form_type": "", "rule": "",
        "status": "open", "created_at": now, "updated_at": now,
        "shipment": {"invoice_no": "E2E", "bill_of_lading_no": "", "export_declaration_nos": []},
        "products": [
            {"code": P1, "name": "E2E A", "finished_hs": "8504.40", "fob": "100000", "cost_buildup": {}},
            {"code": P2, "name": "E2E noratio", "finished_hs": "8504.40", "fob": "100000", "cost_buildup": {}},
        ],
        "origin_sheet_states": {P1: {"criteria_override": "RVC 35%"}, P2: {"criteria_override": "RVC 35%"}},
    }
    store.save_case_record(CLIENT, case, 0)
    B("SEEDED case + Mode-A ratio")

    # Mirror the HTTP route body exactly.
    record = get_case_record(client, CASE_ID)
    caze = attach_origin_sheet_states(record)
    mode_a = {r.product_code: r for r in cost_allocation_store.list_ratios(CLIENT)}
    mode_b = cost_allocation_store.get_mode_b_default(CLIENT)
    result = bulk_apply_to_products(caze["products"], lambda c: mode_a.get(c) or mode_b)
    if result["updates"]:
        by = {str(p.get("code") or "").strip(): p for p in caze["products"]}
        for code, det in result["updates"].items():
            by[code]["cost_buildup"] = {**(by[code].get("cost_buildup") or {}), **det}
        update_case_record(client, caze)
    B(f"BULK applied={result['applied']} no_ratio={result['skipped_no_ratio']} no_fob={result['skipped_no_fob']} filled={result['skipped_filled']}")

    rr = get_case_record(client, CASE_ID)
    cb = {p["code"]: p.get("cost_buildup", {}) for p in rr["products"]}
    B(f"VERIFY P1.cost_buildup={cb.get(P1)}")
    B(f"VERIFY P2.cost_buildup={cb.get(P2)}")
    ok = (
        cb.get(P1, {}).get("wages") == "3000.00"
        and cb.get(P1, {}).get("transport_storage") == "300.00"
        and not (cb.get(P2, {}).get("wages") or "")
        and [a["code"] for a in result["applied"]] == [P1]
        and result["skipped_no_ratio"] == [P2]
    )
finally:
    try:
        delete_case_record(client, CASE_ID)
    except Exception as e:
        print("cleanup case err:", repr(e), flush=True)
    try:
        cost_allocation_store.delete_ratio(CLIENT, P1)
    except Exception as e:
        print("cleanup ratio err:", repr(e), flush=True)
    cases1 = len(co_case_store.load_state(CLIENT)["cases"])
    ratios1 = len(cost_allocation_store.list_ratios(CLIENT))
    B(f"AFTER cleanup cases={cases1} ratios={ratios1}")
    print("CLEANUP_OK" if (cases1 == cases0 and ratios1 == ratios0) else "CLEANUP_MISMATCH", flush=True)

print("E2E_PASS" if ok else "E2E_FAIL", flush=True)
sys.exit(0 if ok else 1)
