"""Temp: screenshot the redesigned UoM pages (global + client 537-row)."""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORDS = ["admin123", "local_test_password"]
OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
CLIENT = "johnson-vn"


async def shot(page, name):
    p = OUT / f"{name}.png"
    await page.screenshot(path=str(p))
    print("saved", p)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 760})
        await ctx.add_cookies([
            {"name": "data_hub_lang", "value": "vi", "url": BASE},
            {"name": "data_hub_theme", "value": "light", "url": BASE},
        ])
        page = await ctx.new_page()
        # login (try known passwords)
        for pw in PASSWORDS:
            await page.goto(f"{BASE}/login")
            await page.fill('input[name="email"]', EMAIL)
            await page.fill('input[name="password"]', pw)
            await page.click('button[type="submit"]')
            try:
                await page.wait_for_url(f"{BASE}/clients", timeout=4000)
                print("logged in with", pw)
                break
            except Exception:
                continue
        else:
            raise SystemExit("login failed with both passwords")

        # ── Global standards ──
        await page.goto(f"{BASE}/admin/uom")
        await page.wait_for_timeout(400)
        await shot(page, "global_01_collapsed")
        # expand first canonical row
        await page.click(".uom-row")
        await page.wait_for_timeout(300)
        await shot(page, "global_02_expanded")
        # search
        await page.fill("#uom-search", "kg")
        await page.wait_for_timeout(300)
        await shot(page, "global_03_search")
        await page.fill("#uom-search", "")
        # add canonical toggle
        await page.click('[data-toggle="add-canonical"]')
        await page.wait_for_timeout(250)
        await shot(page, "global_04_addform")

        # ── Client factors (537 rows) ──
        await page.goto(f"{BASE}/clients/{CLIENT}/uom-factors")
        await page.wait_for_timeout(500)
        await shot(page, "client_01_list")
        # cross-only filter
        await page.check("#uomf-crossonly")
        await page.wait_for_timeout(300)
        await shot(page, "client_02_crossonly")
        await page.uncheck("#uomf-crossonly")
        # open editor on first row
        await page.click(".uom-edit-btn")
        await page.wait_for_timeout(300)
        await shot(page, "client_03_editor")
        # add panel + preview
        await page.click('[data-uom-toggle="add-factor-panel"]')
        await page.fill("#uomf-from", "EA")
        await page.fill("#uomf-to", "KG")
        await page.fill("#uomf-factor", "0.5")
        await page.wait_for_timeout(300)
        await shot(page, "client_04_addpanel")
        await browser.close()


asyncio.run(main())
