"""Verify debounced AUTO-SAVE: stage an edit, DON'T click Lưu, and confirm the
sheet persists on its own (status=calculated, dirty banner gone, no full reload).
Backup→test→restore so the dev case + ledger end unchanged.
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
    for _ in range(3):
        _, revn = store.get_case(CLIENT, CASE)
        store.save_case_record(CLIENT, rec, revn)
        st = (co_case_store.get_case_record(ps.client(CLIENT), CASE).get("origin_sheet_states") or {}).get(SHEET, {})
        if not (st.get("material_overrides") or {}) and st.get("status") == rec.get("origin_sheet_states", {}).get(SHEET, {}).get("status"):
            break
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
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(ORIGIN, wait_until="domcontentloaded", timeout=60000)
        page.evaluate("window.__noReloadMarker = 'alive-' + Date.now()")
        page.click(f"[data-origin-sheet-tab][data-product-code='{SHEET}']")
        panel = f"[data-origin-sheet-panel][data-product-code='{SHEET}']"
        page.wait_for_selector(panel, timeout=10000)

        norm = page.query_selector(f"{panel} [data-origin-norm-edit]")
        if not norm:
            print("no norm input"); browser.close(); return False
        cur = (norm.get_attribute("value") or norm.get_attribute("data-original-value") or "1").strip() or "1"
        norm.fill(cur + "1")
        norm.evaluate("el => el.blur()")  # blur so the focus-guard lets auto-save fire
        page.wait_for_selector(f"{panel} [data-origin-dirty-banner]", timeout=5000)
        print("[1] edit staged, dirty banner shown (no manual save clicked)")

        # Auto-save fires ~2s after the pause; johnson recalc + shell swap takes a
        # few more. The banner detaching is the 'done' signal — wait for it (and so
        # there's no in-flight write racing the restore below).
        banner_gone = True
        try:
            page.wait_for_selector(f"{panel} [data-origin-dirty-banner]", state="detached", timeout=20000)
        except Exception:
            banner_gone = False
        page.wait_for_timeout(800)  # settle
        marker = page.evaluate("window.__noReloadMarker || ''")
        no_reload = marker.startswith("alive-")
        status = page.get_attribute(f"[data-origin-sheet-panel][data-product-code='{SHEET}'] input[name$='_origin_sheet_status']", "value") or ""
        page.screenshot(path=str(SHOTDIR / "4-autosaved.png"), full_page=True)
        print(f"[2] auto-saved without clicking Lưu -> no_reload={no_reload} banner_gone={banner_gone} status={status!r}")
        if errors:
            print("JS errors:", errors[:5])
        browser.close()
        return no_reload and banner_gone and status == "calculated" and not errors


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
