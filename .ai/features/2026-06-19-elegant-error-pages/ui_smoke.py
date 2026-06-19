"""UI smoke for elegant error pages — proves UI routes no longer leak raw
`{"detail": ...}` JSON. Captures the /login bounce (the exact reported case)
and the friendly 404 page in both themes.

Run with the dev server up on :8754:
    uv run python .ai/features/2026-06-19-elegant-error-pages/ui_smoke.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"

OUT = Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


async def shoot(page, name: str) -> None:
    out = OUT / f"{name}.png"
    await page.screenshot(path=str(out), full_page=True)
    print(f"  saved {out.name}")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # 1. Unauthenticated → /clients bounces to a friendly login page,
        #    NOT raw {"detail":"login required"} JSON.
        ctx = await browser.new_context(viewport={"width": 1400, "height": 900})
        await ctx.add_cookies([{"name": "data_hub_lang", "value": "vi", "url": BASE}])
        page = await ctx.new_page()
        await page.goto(f"{BASE}/clients")  # follows 303 → /login
        await page.wait_for_load_state("networkidle")
        assert "/login" in page.url, page.url
        await shoot(page, "01_unauth_bounces_to_login")
        await ctx.close()

        # 2. Logged-in 404 → friendly error page (light + dark).
        for theme in ("light", "dark"):
            ctx = await browser.new_context(viewport={"width": 1400, "height": 900})
            await ctx.add_cookies([
                {"name": "data_hub_lang", "value": "vi", "url": BASE},
                {"name": "data_hub_theme", "value": theme, "url": BASE},
            ])
            page = await ctx.new_page()
            await page.goto(f"{BASE}/login")
            await page.fill('input[name="email"]', EMAIL)
            await page.fill('input[name="password"]', PASSWORD)
            await page.click('button[type="submit"]')
            await page.wait_for_url(f"{BASE}/clients", timeout=10000)
            resp = await page.goto(f"{BASE}/clients/does-not-exist-zzz")
            assert resp.status == 404, resp.status
            await page.wait_for_load_state("networkidle")
            await shoot(page, f"0{'2' if theme == 'light' else '3'}_404_{theme}")
            await ctx.close()

        await browser.close()
    print("smoke ok")


if __name__ == "__main__":
    asyncio.run(main())
