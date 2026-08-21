"""UI smoke — footer version badge + /whats-new page, light + dark.

Run with the dev server up on :8754:
    uv run python .ai/features/2026-06-07-app-versioning-changelog/ui_smoke.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
OUT = Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for theme in ("light", "dark"):
            ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
            await ctx.add_cookies([
                {"name": "data_hub_theme", "value": theme, "url": BASE},
                {"name": "data_hub_lang", "value": "vi", "url": BASE},
            ])
            page = await ctx.new_page()
            await page.goto(f"{BASE}/login")
            await page.fill('input[name="email"]', EMAIL)
            await page.fill('input[name="password"]', PASSWORD)
            await page.click('button[type="submit"]')
            await page.wait_for_load_state("networkidle")
            # whats-new page (full)
            await page.goto(f"{BASE}/whats-new")
            await page.wait_for_load_state("networkidle")
            await page.screenshot(path=str(OUT / f"whats_new_{theme}.png"), full_page=True)
            print(f"  saved whats_new_{theme}.png")
            # footer badge — scroll a content page to bottom, clip footer
            await page.goto(f"{BASE}/clients")
            await page.wait_for_load_state("networkidle")
            footer = page.locator(".app-footer")
            await footer.scroll_into_view_if_needed()
            await footer.screenshot(path=str(OUT / f"footer_{theme}.png"))
            print(f"  saved footer_{theme}.png")
            await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
