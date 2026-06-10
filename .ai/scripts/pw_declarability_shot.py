"""Authentic screenshot of declarability badges on the REAL johnson sheet.

The local sheet is locked + its saved materials predate DH mig 078. So:
  reopen -> recalc (pulls REAL customs_relevance from DH) -> shots -> restore.
Full backup/restore so the dev case + claims end byte-for-byte unchanged.

Run: set -a; . ./.env; set +a; PYTHONPATH=. .venv/bin/python .ai/scripts/pw_declarability_shot.py
"""
import copy
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.portfolio import portfolio_service as ps
from app import co_case_store
from app.workflow_state_store import get_co_case_state_store
from app.database import connect

BASE = "http://127.0.0.1:8001"
CLIENT = "johnson-vn"
CASE = "co-case-ec000d03522e"
SHEET = "MFW0509-39"
ORIGIN = f"{BASE}/clients/{CLIENT}/co-case/{CASE}/origin"
SHEET_BASE = f"{BASE}/clients/{CLIENT}/co-case/{CASE}/origin/sheet/{SHEET}"
SHOTDIR = Path(".ai/screenshots/2026-06-09-declarability")
SHOTDIR.mkdir(parents=True, exist_ok=True)
CLAIM_COLS = ["claim_id", "client_id", "case_id", "sheet_product_code", "source_row",
              "material_code", "material_index", "claimed_qty", "status", "locked_at",
              "released_at", "declaration_no", "line_no", "customs_code"]


def backup():
    record = copy.deepcopy(co_case_store.get_case_record(ps.client(CLIENT), CASE))
    with connect() as c, c.cursor() as cur:
        cur.execute(f"select {', '.join(CLAIM_COLS)} from co_stock_claims where client_id=%s and case_id=%s", (CLIENT, CASE))
        claims = cur.fetchall()
    print(f"[backup] case + {len(claims)} claims")
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
    rec = co_case_store.get_case_record(ps.client(CLIENT), CASE)
    st = (rec.get("origin_sheet_states") or {}).get(SHEET, {})
    print(f"[restore] sheet status={st.get('status')} (want locked)")


def scoped_shot(page, name):
    page.goto(ORIGIN, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)
    tab = page.query_selector(f'[data-origin-sheet-tab][data-product-code="{SHEET}"]')
    if tab:
        tab.click(); page.wait_for_timeout(900)
    scope = f'[data-origin-sheet-panel][data-product-code="{SHEET}"]'
    page.evaluate(f"""() => {{ const p=document.querySelector('{scope}');
      const s=p && p.querySelector('.origin-warning-summary');
      if(s){{ s.scrollIntoView({{block:'start'}}); window.scrollBy(0,-90); }} }}""")
    page.wait_for_timeout(300)
    page.screenshot(path=str(SHOTDIR / f"{name}-summary.png"))
    page.evaluate(f"""() => {{ const p=document.querySelector('{scope}');
      const t=p && p.querySelector('.origin-material-table');
      if(t){{ t.scrollIntoView({{block:'start'}}); window.scrollBy(0,-70); }} }}""")
    page.wait_for_timeout(300)
    page.screenshot(path=str(SHOTDIR / f"{name}-table.png"))
    vis = page.evaluate("""() => { const t=document.body.innerText;
      return {rac:(t.match(/phi vật tư · không xuất/g)||[]).length,
              rev:(t.match(/chưa khớp · cần đối soát/g)||[]).length,
              sumRac:(t.match(/Đã loại phi vật tư/g)||[]).length,
              sumRev:(t.match(/Vật tư chưa khớp tờ khai/g)||[]).length}; }""")
    print(f"[shot {name}] visible badges:", vis)


def run():
    rec, claims = backup()
    try:
        with sync_playwright() as p:
            page = p.chromium.launch(headless=True).new_page(viewport={"width": 1500, "height": 1050})
            r = page.request.post(f"{SHEET_BASE}/reopen", data="")
            print("[reopen]", r.status)
            page.wait_for_timeout(500)
            r = page.request.post(f"{SHEET_BASE}/calculate", headers={"Content-Type": "application/json"}, data="{}")
            print("[calculate]", r.status)
            page.wait_for_timeout(2000)
            scoped_shot(page, "5-real")
            page.context.browser.close()
    finally:
        restore(rec, claims)


if __name__ == "__main__":
    run()
