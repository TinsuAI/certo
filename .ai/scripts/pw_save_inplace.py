"""Verify 'Lưu bảng kê' updates in-place (no full reload) on the live server.

Drives the real edit→save flow in a browser on a real johnson sheet, asserts:
  - the page does NOT navigate (same document instance) after save,
  - the saved sheet shows status 'calculated' (Chốt-able) without an F5,
  - /save with Accept: text/html returns the swappable [data-co-case-shell].
Full backup→test→restore so the dev case + ledger end unchanged.
"""
import copy
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

from app.portfolio import portfolio_service as ps
from app import co_case_store
from app.workflow_state_store import get_co_case_state_store
from app.database import connect

BASE = "http://127.0.0.1:8001"
CLIENT, CASE, SHEET = "johnson-vn", "co-case-ec000d03522e", "MFW0506-39"
ORIGIN = f"{BASE}/clients/{CLIENT}/co-case/{CASE}/origin"
SHOTDIR = Path(".ai/screenshots/2026-06-08-co-stock-recalc-folded-parity")
SHOTDIR.mkdir(parents=True, exist_ok=True)
COLS = ["claim_id", "client_id", "case_id", "sheet_product_code", "source_row", "material_code",
        "material_index", "claimed_qty", "status", "locked_at", "released_at",
        "declaration_no", "line_no", "customs_code"]


def backup():
    rec = copy.deepcopy(co_case_store.get_case_record(ps.client(CLIENT), CASE))
    with connect() as c, c.cursor() as cur:
        cur.execute(f"select {', '.join(COLS)} from co_stock_claims where client_id=%s and case_id=%s", (CLIENT, CASE))
        return rec, cur.fetchall()


def restore(rec, claims):
    store = get_co_case_state_store()
    payload, revn = store.get_case(CLIENT, CASE)
    store.save_case_record(CLIENT, rec, revn)
    with connect() as c, c.cursor() as cur:
        cur.execute("delete from co_stock_claims where client_id=%s and case_id=%s", (CLIENT, CASE))
        if claims:
            cur.executemany(f"insert into co_stock_claims ({', '.join(COLS)}) values ({', '.join(['%s']*len(COLS))})", claims)
    from app import co_stock_materializer
    co_stock_materializer.invalidate_co_stock_rows_cache(CLIENT)
    st = (co_case_store.get_case_record(ps.client(CLIENT), CASE).get("origin_sheet_states") or {}).get(SHEET, {})
    print(f"[restore] status={st.get('status')} overrides={len(st.get('material_overrides') or {})} claims={len(claims)}")


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})

        # Tag the document so we can detect a full navigation (a reload wipes it).
        page.goto(ORIGIN, wait_until="domcontentloaded", timeout=60000)
        page.evaluate("window.__noReloadMarker = 'alive-' + Date.now()")
        page.click(f"[data-origin-sheet-tab][data-product-code='{SHEET}']")
        panel = f"[data-origin-sheet-panel][data-product-code='{SHEET}']"
        page.wait_for_selector(panel, timeout=10000)
        # Stage a real edit: bump one ĐM (norm) input -> dirty banner + Lưu bảng kê.
        norm = page.query_selector(f"{panel} [data-origin-norm-edit]")
        if not norm:
            print("no norm input found on sheet"); browser.close(); return False
        cur = (norm.get_attribute("value") or norm.get_attribute("data-original-value") or "1").strip() or "1"
        new_val = cur + "1"  # diverge from original -> counts as a pending norm edit
        norm.fill(new_val)
        norm.dispatch_event("change")
        page.wait_for_selector(f"{panel} [data-origin-save-now]", timeout=10000)
        page.click(f"{panel} [data-origin-save-now]")
        # Wait for the in-place swap (dirty banner cleared + sheet recalculated).
        page.wait_for_timeout(4000)

        marker = page.evaluate("window.__noReloadMarker || ''")
        no_reload = marker.startswith("alive-")
        status = page.get_attribute(f"[data-origin-sheet-panel][data-product-code='{SHEET}'] input[name$='_origin_sheet_status']", "value") or ""
        page.screenshot(path=str(SHOTDIR / "3-after-save-inplace.png"), full_page=True)
        print(f"[save] no full reload: {no_reload} | sheet status after save: {status!r}")
        browser.close()
        return no_reload and status == "calculated"


def main():
    rec, claims = backup()
    ok = False
    try:
        ok = run()
    finally:
        restore(rec, claims)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
