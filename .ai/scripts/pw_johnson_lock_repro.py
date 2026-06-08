"""Playwright E2E on the LIVE local server + REAL johnson snapshot/ledger.

Reproduces the reported flow on a real johnson sheet (co-case-ec000d03522e /
MFW0506-39): edit an NVL row -> Tính bảng kê (recalc) -> Chốt. With the fix the
lock must SUCCEED. Full backup→test→restore so the dev case + ledger end
byte-for-byte unchanged.

Run: set -a; . ./.env; set +a; PYTHONPATH=. .venv/bin/python .ai/scripts/pw_johnson_lock_repro.py
"""
import copy
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.portfolio import portfolio_service as ps
from app import co_case_store
from app.workflow_state_store import get_co_case_state_store
from app.database import connect

BASE = "http://127.0.0.1:8001"
CLIENT = "johnson-vn"
CASE = "co-case-ec000d03522e"
SHEET = "MFW0506-39"
ORIGIN = f"{BASE}/clients/{CLIENT}/co-case/{CASE}/origin"
SHEET_BASE = f"{BASE}/clients/{CLIENT}/co-case/{CASE}/origin/sheet/{SHEET}"
SHOTDIR = Path(".ai/screenshots/2026-06-08-co-stock-recalc-folded-parity")
SHOTDIR.mkdir(parents=True, exist_ok=True)
JSON = {"Content-Type": "application/json"}
CLAIM_COLS = ["claim_id", "client_id", "case_id", "sheet_product_code", "source_row",
              "material_code", "material_index", "claimed_qty", "status", "locked_at",
              "released_at", "declaration_no", "line_no", "customs_code"]


def backup():
    client = ps.client(CLIENT)
    record = copy.deepcopy(co_case_store.get_case_record(client, CASE))
    with connect() as c, c.cursor() as cur:
        cur.execute(f"select {', '.join(CLAIM_COLS)} from co_stock_claims where client_id=%s and case_id=%s", (CLIENT, CASE))
        claims = cur.fetchall()
    print(f"[backup] case record + {len(claims)} claims for {CASE}")
    return record, claims


def restore(record, claims):
    store = get_co_case_state_store()
    state = store.get_state(CLIENT)
    state["cases"] = [record if c.get("case_id") == CASE else c for c in state["cases"]]
    store.save_state(CLIENT, state)
    with connect() as c, c.cursor() as cur:
        cur.execute("delete from co_stock_claims where client_id=%s and case_id=%s", (CLIENT, CASE))
        if claims:
            ph = ", ".join(["%s"] * len(CLAIM_COLS))
            cur.executemany(f"insert into co_stock_claims ({', '.join(CLAIM_COLS)}) values ({ph})", claims)
    from app import co_stock_materializer
    co_stock_materializer.invalidate_co_stock_rows_cache(CLIENT)
    # verify
    rec = co_case_store.get_case_record(ps.client(CLIENT), CASE)
    st = (rec.get("origin_sheet_states") or {}).get(SHEET, {})
    with connect() as c, c.cursor() as cur:
        cur.execute("select count(*) from co_stock_claims where client_id=%s and case_id=%s", (CLIENT, CASE))
        n = cur.fetchone()[0]
    print(f"[restore] sheet status={st.get('status')} overrides={len(st.get('material_overrides') or {})} claims={n}")


def run_browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        api = page.request
        page.goto(ORIGIN, wait_until="domcontentloaded", timeout=60000)
        assert SHEET in page.content(), f"{SHEET} not on origin page"
        page.screenshot(path=str(SHOTDIR / "1-before.png"), full_page=True)
        print("[1] origin renders, sheet present:", SHEET)

        r = api.post(f"{SHEET_BASE}/save", headers=JSON, data=json.dumps({"deletes": {"0": True}}))
        print("[2] /save delete row0:", r.status, r.json().get("operations"))
        assert r.status == 200

        r = api.post(f"{SHEET_BASE}/calculate", headers=JSON, data=json.dumps({}))
        print("[3] /calculate (recalc, FIX path):", r.status)
        assert r.status == 200, r.text()[:300]

        r = api.post(f"{SHEET_BASE}/lock", headers=JSON, data=json.dumps({}))
        blocked = "vượt tồn" in r.text()
        locked_ok = "Đã chốt" in r.text()
        print(f"[4] /lock (Chốt): HTTP {r.status} | 'vượt tồn'={blocked} | 'Đã chốt'={locked_ok}")
        page.goto(ORIGIN, wait_until="domcontentloaded", timeout=60000)
        page.screenshot(path=str(SHOTDIR / "2-after-lock.png"), full_page=True)
        browser.close()
        ok = r.status == 200 and not blocked
        print("\n==> CHỐT SUCCEEDED with fix:", "YES" if ok else "NO")
        return ok


def main():
    record, claims = backup()
    ok = False
    try:
        ok = run_browser()
    finally:
        restore(record, claims)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
