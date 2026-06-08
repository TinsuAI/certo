"""Verify the persistent edit toolbar: always visible per unlocked sheet, shows
saved/dirty state, and does NOT hide after saving. Backup→test→restore.
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
PANEL = f"[data-origin-sheet-panel][data-product-code='{SHEET}']"
BAR = f"{PANEL} [data-origin-edit-toolbar]"
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
        if not (st.get("material_overrides") or {}):
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
        page.click(f"[data-origin-sheet-tab][data-product-code='{SHEET}']")
        page.wait_for_selector(BAR, timeout=10000)

        bar_visible_0 = page.is_visible(BAR)
        msg_0 = (page.inner_text(f"{BAR} [data-origin-dirty-msg]") or "").strip()
        save_disabled_0 = page.get_attribute(f"{BAR} [data-origin-save-now]", "disabled") is not None
        print(f"[1] on load: toolbar visible={bar_visible_0} msg={msg_0!r} save_disabled={save_disabled_0}")

        # Edit a ĐM → dirty.
        norm = page.query_selector(f"{PANEL} [data-origin-norm-edit]")
        cur = (norm.get_attribute("value") or "1").strip() or "1"
        norm.fill(cur + "1")
        norm.evaluate("el => el.blur()")
        page.wait_for_function(
            "sel => { const m = document.querySelector(sel); return m && /Chưa lưu/.test(m.textContent); }",
            arg=f"{BAR} [data-origin-dirty-msg]", timeout=5000,
        )
        msg_dirty = (page.inner_text(f"{BAR} [data-origin-dirty-msg]") or "").strip()
        save_disabled_dirty = page.get_attribute(f"{BAR} [data-origin-save-now]", "disabled") is not None
        print(f"[2] after edit: msg={msg_dirty!r} save_disabled={save_disabled_dirty}")

        # Let auto-save run; toolbar must STAY visible and go back to 'Đã lưu'.
        page.wait_for_function(
            "sel => { const m = document.querySelector(sel); return m && /Đã lưu/.test(m.textContent); }",
            arg=f"{BAR} [data-origin-dirty-msg]", timeout=20000,
        )
        page.wait_for_timeout(600)
        bar_visible_after = page.is_visible(BAR)
        msg_after = (page.inner_text(f"{BAR} [data-origin-dirty-msg]") or "").strip()
        page.screenshot(path=str(SHOTDIR / "5-toolbar-persists.png"), full_page=True)
        print(f"[3] after save: toolbar STILL visible={bar_visible_after} msg={msg_after!r}")
        if errors:
            print("JS errors:", errors[:5])
        browser.close()
        return (bar_visible_0 and "Đã lưu" in msg_0 and save_disabled_0
                and "Chưa lưu" in msg_dirty and not save_disabled_dirty
                and bar_visible_after and "Đã lưu" in msg_after and not errors)


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
