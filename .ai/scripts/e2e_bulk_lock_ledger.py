"""DB-mode e2e for Slice D (#13c) — bulk-lock writing REAL ledger claims.

The file-mode route tests stub record_sheet_lock_claims, so the actual ledger
write + overclaim pre-check are NOT exercised there. This drives the real
/origin/bulk-lock route against Postgres (DB-mode) with allocation_lines that
reference REAL co_stock_rows, then asserts co_stock_claims rows are written, an
over-allocating sheet is rejected (StockOverclaimError → skipped), and the lock
is idempotent. Self-cleaning. Run locally with .env sourced (auth-off dev):

    set -a; . ./.env; set +a
    PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_bulk_lock_ledger.py

Uses client growatt-vn (real stock) + a throwaway case; deletes the case + its
claims in finally. Expect tail: CLEANUP_OK then E2E_PASS.
"""
import sys
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import connect
from app.workflow_state_store import get_co_case_state_store
from app import co_case_store
import app.main as m

CLIENT = "growatt-vn"
CASE = "e2e-m6-lock"


def B(msg):
    print("==== " + str(msg) + " ====", flush=True)


def _claims():
    with connect() as c, c.cursor() as cur:
        cur.execute(
            "select sheet_product_code, claimed_qty from co_stock_claims "
            "where client_id=%s and case_id=%s order by sheet_product_code",
            (CLIENT, CASE),
        )
        return cur.fetchall()


def _cleanup():
    with connect() as c, c.cursor() as cur:
        cur.execute("delete from co_stock_claims where client_id=%s and case_id=%s", (CLIENT, CASE))
        cur.execute("delete from co_cases where client_id=%s and case_id=%s", (CLIENT, CASE))


store = get_co_case_state_store()
assert store is not None, "expected DB-mode (BARRY_DATABASE_URL must be set)"
m.require_local_source_writes = lambda: None
http = TestClient(m.app)

# Two real lots with ample remaining (TP-A claims a sliver; TP-B over-claims).
with connect() as c, c.cursor() as cur:
    cur.execute(
        r"""select source_row, remaining_qty::numeric from co_stock_rows
            where client_id=%s and remaining_qty ~ '^-?\d+(\.\d+)?$' and remaining_qty::numeric > 50
            order by remaining_qty::numeric desc limit 2""",
        (CLIENT,),
    )
    lots = cur.fetchall()
assert len(lots) >= 2, "need 2 real stock lots"
(lotA, remA), (lotB, remB) = lots[0], lots[1]
B(f"lots A={lotA}({remA}) B={lotB}({remB})")

_cleanup()
ok = False
try:
    now = co_case_store.now_iso()
    def _mat(code, lot, qty):
        return {"material_code": code, "uom": "cái",
                "allocation_lines": [{"source_row": lot, "allocated_qty": str(qty),
                                      "import_declaration_no": "E2E", "import_line_no": "1",
                                      "customs_material_code": code}]}
    case = {
        "id": CASE, "persisted_case_id": CASE, "case_id": CASE,
        "case_code": "E2E-M6-LOCK", "title": "E2E lock DELETE ME", "customer": "E2E",
        "destination_market": "Ấn Độ", "status": "open", "created_at": now, "updated_at": now,
        "shipment": {"invoice_no": "E2E", "export_declaration_nos": []},
        "origin_product_order": ["TP-A", "TP-B"],
        "products": [
            {"code": "TP-A", "name": "A", "materials": [_mat("MA", lotA, 100)]},
            {"code": "TP-B", "name": "B", "materials": [_mat("MB", lotB, int(remB) + 1_000_000)]},
        ],
        "origin_sheet_states": {
            "TP-A": {"status": "calculated", "status_label": "calculated"},
            "TP-B": {"status": "calculated", "status_label": "calculated"},
        },
    }
    store.save_case_record(CLIENT, case, 0)
    B("SEEDED case (TP-A claims 100; TP-B over-claims)")

    resp = http.post(f"/clients/{CLIENT}/co-case/{CASE}/origin/bulk-lock", json={})
    body = resp.json()
    B(f"bulk-lock status={resp.status_code} locked={body.get('locked')} skipped={body.get('skipped')}")

    claims = _claims()
    B(f"co_stock_claims for case: {claims}")

    # cross-case visibility: the locked claim shows up in the ledger overlay
    from app import co_stock_ledger
    used = co_stock_ledger.used_qty_by_lot(CLIENT)
    B(f"ledger used_qty for lotA = {used.get(lotA)}")

    # idempotent re-lock (TP-A already locked → counted, no duplicate claim)
    resp2 = http.post(f"/clients/{CLIENT}/co-case/{CASE}/origin/bulk-lock", json={})
    body2 = resp2.json()
    claims2 = _claims()
    B(f"re-lock already_locked={body2.get('already_locked')} claims_after={len(claims2)}")

    locked = body.get("locked") or []
    skipped = {s["product_code"]: s["reason"] for s in (body.get("skipped") or [])}
    ok = (
        resp.status_code == 200
        and locked == ["TP-A"]                                  # TP-A locked
        and "TP-B" in skipped and "tồn" in skipped["TP-B"].lower()  # TP-B overclaim skipped
        and len(claims) == 1 and claims[0][0] == "TP-A"          # exactly one real claim written
        and Decimal(str(claims[0][1])) == Decimal("100")         # claimed qty correct
        and used.get(lotA) is not None and Decimal(str(used.get(lotA))) >= Decimal("100")  # ledger sees it
        and body2.get("already_locked") == ["TP-A"]              # idempotent
        and len(claims2) == 1                                    # no duplicate
    )
finally:
    try:
        _cleanup()
    except Exception as e:
        print("cleanup err:", repr(e), flush=True)
    leftover = _claims()
    with connect() as c, c.cursor() as cur:
        cur.execute("select count(*) from co_cases where client_id=%s and case_id=%s", (CLIENT, CASE))
        case_left = cur.fetchone()[0]
    print("CLEANUP_OK" if (not leftover and case_left == 0) else "CLEANUP_MISMATCH", flush=True)

print("E2E_PASS" if ok else "E2E_FAIL", flush=True)
sys.exit(0 if ok else 1)
