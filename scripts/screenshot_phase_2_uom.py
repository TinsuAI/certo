"""Phase 2 UoM conversion engine — UI smoke screenshots.

Walks the full Phase 2 workflow:
1. Upload preview banner with drift table (badges + conversion plan).
2. Confirm button disabled state on first load.
3. Admin UI factor list + inline edit + add form.
4. Admin UI prefill from preview (?prefill_material_code=...).
5. Artifact detail with UoM drift block + Refresh button.
6. After Refresh → new artifact with converted rows.
7. Stale list view.

Saves to .ai/features/2026-05-12-bom-uom-conversion-phase-2/screenshots/
"""
from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from playwright.async_api import async_playwright


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT_ID = "growatt-vn"
PRODUCT = "TEST_TP_DRIFT"

OUT = Path(".ai/features/2026-05-12-bom-uom-conversion-phase-2/screenshots")
OUT.mkdir(parents=True, exist_ok=True)


def db():
    return psycopg.connect("host=/var/run/postgresql user=vp dbname=data_hub")


def cleanup():
    conn = db()
    with conn.cursor() as cur:
        cur.execute(
            "delete from hub.bom_artifact_rows where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where "
            "client_id=%s and product_code=%s)",
            (CLIENT_ID, PRODUCT))
        cur.execute(
            "delete from hub.bom_artifacts where client_id=%s "
            "and product_code=%s",
            (CLIENT_ID, PRODUCT))
        cur.execute(
            "delete from hub.upload_pending where client_id=%s "
            "and module='bom' and parsed_rows::text like %s",
            (CLIENT_ID, f"%{PRODUCT}%"))
        # Wipe ALL Growatt overrides for clean screenshot. Restore is
        # caller's responsibility (this is a screenshot harness, not
        # production cleanup).
        cur.execute(
            "delete from hub.client_uom_overrides where client_id=%s",
            (CLIENT_ID,))
        conn.commit()
    conn.close()


def stash_pending() -> str:
    """Insert a manual_flat upload_pending row for TEST_TP_DRIFT with
    6 rows that trigger every drift severity."""
    pid = secrets.token_urlsafe(16)
    parsed = {"products": {PRODUCT: [
        {"material_code": "940.9943700", "qty_per_unit": 5,
         "uom": "PCS"},  # alias drift (PCS == ST)
        {"material_code": "001.0001100", "qty_per_unit": 0.5,
         "uom": "kg"},  # tier-B factor_missing
        {"material_code": "005.0001100", "qty_per_unit": 1,
         "uom": "SETS"},  # tier-A unconfirmed_default
        {"material_code": "PV01.0105100", "qty_per_unit": 1,
         "uom": "CAY"},  # tier-A unconfirmed_default
        {"material_code": "DIENTRO", "qty_per_unit": 0.1,
         "uom": "kg"},  # cat null, BCCT comparator
        {"material_code": "TUDIEN", "qty_per_unit": 1,
         "uom": "WONKY_UNIT"},  # info_unknown
    ]}}
    conn = db()
    with conn.cursor() as cur:
        cur.execute(
            "insert into hub.upload_pending (pending_id, client_id, "
            "module, parsed_rows, diff_summary, expires_at) "
            "values (%s, %s, 'bom', %s::jsonb, %s::jsonb, %s)",
            (pid, CLIENT_ID, json.dumps(parsed),
             json.dumps({"profile": "manual_flat",
                          "skipped_rows": []}),
             datetime.now(timezone.utc) + timedelta(hours=1)))
        conn.commit()
    conn.close()
    return pid


async def login(page):
    await page.goto(f"{BASE}/login")
    await page.fill('input[name="email"]', EMAIL)
    await page.fill('input[name="password"]', PASSWORD)
    await page.click('button[type="submit"]')
    await page.wait_for_url(f"{BASE}/clients", timeout=5000)


async def shot(page, name: str):
    fp = OUT / f"{name}.png"
    await page.screenshot(path=str(fp), full_page=True)
    print(f"  📸 {fp}")


async def main():
    cleanup()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 1200})
        page = await ctx.new_page()
        await login(page)

        # ── 1. Upload preview with drift banner (no override yet) ──
        pid = stash_pending()
        await page.goto(f"{BASE}/clients/{CLIENT_ID}/bom/preview/{pid}")
        await page.wait_for_load_state("networkidle")
        await shot(page, "01_preview_drift_initial")

        # ── 2. Confirm button disabled, hover for tooltip ──
        # Take an extra shot focused on the bottom (form area).
        await page.evaluate("document.getElementById('confirm-form')?"
                             ".scrollIntoView({block:'center'})")
        await page.wait_for_timeout(300)
        await shot(page, "02_confirm_disabled")

        # ── 3. Admin UI: empty list ──
        await page.goto(f"{BASE}/clients/{CLIENT_ID}/uom-factors")
        await page.wait_for_load_state("networkidle")
        await shot(page, "03_admin_empty")

        # ── 4. Add factor for 005.0001100 via admin UI add form ──
        # Scope selectors to the "Thêm hệ số" form (action=/new).
        ADD_FORM = 'form[action*="/uom-factors/new"]'
        await page.fill(f'{ADD_FORM} input[name="material_code"]',
                          "005.0001100")
        await page.fill(f'{ADD_FORM} input[name="from_uom"]', "SETS")
        await page.fill(f'{ADD_FORM} input[name="to_uom"]', "ST")
        await page.fill(f'{ADD_FORM} input[name="factor"]', "4")
        await page.fill(f'{ADD_FORM} input[name="notes"]',
                          "1 SETS = 4 ST (test)")
        await page.click(f'{ADD_FORM} button[type=submit]')
        await page.wait_for_load_state("networkidle")
        await shot(page, "04_admin_after_add")

        # ── 5. Reload preview → severity drops, badge changes ──
        await page.goto(f"{BASE}/clients/{CLIENT_ID}/bom/preview/{pid}")
        await page.wait_for_load_state("networkidle")
        await shot(page, "05_preview_after_factor")

        # ── 6. Click "+ hệ số" (prefill flow) — manually navigate ──
        prefill_url = (f"{BASE}/clients/{CLIENT_ID}/uom-factors"
                        f"?prefill_material_code=001.0001100"
                        f"&prefill_from_uom=kg&prefill_to_uom=ST"
                        f"#add-factor-form")
        await page.goto(prefill_url)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(800)  # let scroll/focus animation
        await shot(page, "06_admin_prefilled")

        # ── 7. Confirm upload (tick ack first) ──
        await page.goto(f"{BASE}/clients/{CLIENT_ID}/bom/preview/{pid}")
        await page.wait_for_load_state("networkidle")
        # Tick ack checkbox.
        ack = await page.query_selector('input[name="ack_uom_drift"]')
        if ack:
            await ack.check()
            await page.wait_for_timeout(200)
        await shot(page, "07_confirm_enabled_after_ack")
        # Submit the confirm form (Lưu N dòng button = btn-primary).
        await page.click(
            '#confirm-form button[type=submit].btn-primary')
        await page.wait_for_load_state("networkidle")

        # ── 8. Find the new artifact + visit detail ──
        conn = db()
        with conn.cursor() as cur:
            cur.execute(
                "select artifact_id from hub.bom_artifacts "
                "where client_id=%s and product_code=%s "
                "and tombstoned_at is null order by created_at desc "
                "limit 1",
                (CLIENT_ID, PRODUCT))
            row = cur.fetchone()
        conn.close()
        if not row:
            print("  no artifact created — skip remaining shots")
            await browser.close()
            return
        aid = row[0]
        await page.goto(
            f"{BASE}/clients/{CLIENT_ID}/bom/artifact/{aid}")
        await page.wait_for_load_state("networkidle")
        await shot(page, "08_artifact_detail_with_drift")

        # ── 9. Add factor for 001.0001100 to demonstrate refresh-with-
        # state-change (factor_missing → resolved → diff hash → new
        # artifact + tombstone original). ──
        conn = db()
        with conn.cursor() as cur:
            cur.execute(
                "insert into hub.client_uom_overrides "
                "(client_id, material_code, from_uom, to_uom, "
                " factor, source, notes) "
                "values (%s, '001.0001100', 'kg', 'ST', 0.001, "
                "        'staff_form', 'screenshot test')",
                (CLIENT_ID,))
            conn.commit()
        conn.close()

        # Now click Refresh — this will produce different rows (001
        # converts) → diff hash → new artifact + tombstone original.
        await page.goto(
            f"{BASE}/clients/{CLIENT_ID}/bom/artifact/{aid}")
        await page.wait_for_load_state("networkidle")
        refresh_btn = await page.query_selector(
            'form[action*="/refresh"] button:has-text("Refresh")')
        if refresh_btn:
            await refresh_btn.click()
            await page.wait_for_load_state("networkidle")
            await shot(page, "09_artifact_after_refresh")

        # ── 10. Stale list view ──
        await page.goto(f"{BASE}/clients/{CLIENT_ID}/bom/stale")
        await page.wait_for_load_state("networkidle")
        await shot(page, "10_stale_list")

        # ── 11. Admin UI factor list (now populated) ──
        await page.goto(f"{BASE}/clients/{CLIENT_ID}/uom-factors")
        await page.wait_for_load_state("networkidle")
        await shot(page, "11_admin_inline_edit")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
