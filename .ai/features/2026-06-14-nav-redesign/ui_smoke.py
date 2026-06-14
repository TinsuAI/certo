"""Screenshots for the admin nav redesign (G.1). Captures the shared grouped
sub-nav on the admin landing, an open dropdown, and the active-state on a
Dữ liệu tham chiếu page. Run against a live dev server on :8754.

    uv run python .ai/features/2026-06-14-nav-redesign/ui_smoke.py
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
            ctx = await browser.new_context(viewport={"width": 1440, "height": 720})
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

            # 1. Admin landing — grouped sub-nav, collapsed.
            await page.goto(f"{BASE}/admin/users")
            await page.wait_for_selector(".admin-tabs")
            await shot(page, "01_admin_nav", theme)

            # 2. "Dữ liệu tham chiếu" dropdown open.
            await page.click("summary:has-text('Dữ liệu tham chiếu')")
            await page.wait_for_selector(".nav-menu[open] .nav-menu-panel")
            await shot(page, "02_dropdown_open", theme)

            # 3. Active-state highlight on a reference page.
            await page.goto(f"{BASE}/admin/uom")
            await page.wait_for_selector(".admin-tabs .tab-link-active")
            await shot(page, "03_active_uom", theme)

            await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
