"""Screenshots for the clients-page + top-nav redesign + Vietnamese sweep.
Run against a live dev server on :8754.

    uv run python .ai/features/2026-06-14-clients-topnav-vi-sweep/ui_smoke.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


async def shot(page, slug: str, theme: str):
    path = OUT / f"{slug}_{theme}.png"
    await page.screenshot(path=str(path))
    print(f"  saved {path}")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for theme in ("light", "dark"):
            ctx = await browser.new_context(viewport={"width": 1440, "height": 820})
            await ctx.add_cookies([
                {"name": "data_hub_theme", "value": theme, "url": BASE},
                {"name": "data_hub_lang", "value": "vi", "url": BASE},
            ])
            page = await ctx.new_page()
            await page.goto(f"{BASE}/login")
            await page.fill('input[name="email"]', EMAIL)
            await page.fill('input[name="password"]', PASSWORD)
            await page.click('button[type="submit"]')
            await page.wait_for_url(f"{BASE}/clients", timeout=8000)

            # 1. Clients list — global topnav (Khách hàng · Quản trị + avatar),
            #    search + VN mode badges + condensed legend.
            await page.wait_for_selector("#client-filter")
            await shot(page, "01_clients", theme)

            # 1b. User menu open (name/role · language · logout).
            await page.click("summary.user-avatar")
            await page.wait_for_selector(".user-menu[open] .user-menu-panel")
            await shot(page, "01b_user_menu", theme)
            await page.click("summary.user-avatar")

            # 2. Instant filter.
            await page.fill("#client-filter", "johnson")
            await page.wait_for_timeout(150)
            await shot(page, "02_clients_filter", theme)

            # 3. Workspace — VN tabs + module tiles + config summary; top-nav sep.
            await page.goto(f"{BASE}/clients/growatt-vn")
            await page.wait_for_selector(".client-tabs")
            await shot(page, "03_workspace", theme)

            await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
