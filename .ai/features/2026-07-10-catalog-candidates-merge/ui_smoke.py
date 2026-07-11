"""UI smoke for catalog phase 2 (#32) — refresh is explicit, not on GET.

Proves the candidates page renders without writing (fast), shows the
«Làm mới» button, and that pressing it rebuilds the queue and reports
via toast.

Run with the dev server up on :8754:
    uv run python .ai/features/2026-07-10-catalog-candidates-merge/ui_smoke.py
"""
from __future__ import annotations

import asyncio
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT = "growatt-vn"

OUT = Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


async def shoot(page, name: str) -> None:
    out = OUT / f"{name}.png"
    await page.screenshot(path=str(out), full_page=False)
    print(f"  saved {out.name}")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1400, "height": 900})
        await ctx.add_cookies([
            {"name": "data_hub_lang", "value": "vi", "url": BASE},
        ])
        page = await ctx.new_page()
        await page.goto(f"{BASE}/login")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(f"{BASE}/clients", timeout=10000)

        # 1. Page load is read-only now — time it and show the button.
        t0 = time.monotonic()
        await page.goto(f"{BASE}/clients/{CLIENT}/catalog/candidates")
        load_s = time.monotonic() - t0
        await page.wait_for_load_state("networkidle")
        button = page.locator('button:has-text("Làm mới")')
        assert await button.count() == 1, "Làm mới button missing"
        print(f"  page load (no refresh on GET): {load_s:.2f}s")
        await shoot(page, "10_candidates_page_with_refresh_button")

        # 2. Press the button — 303 back with ?refreshed=<n> + toast.
        t0 = time.monotonic()
        async with page.expect_navigation(timeout=60000):
            await button.click()
        refresh_s = time.monotonic() - t0
        assert "refreshed=" in page.url, page.url
        toast = page.locator(".toast")
        assert await toast.count() >= 1, "refresh toast missing"
        print(f"  explicit refresh round-trip: {refresh_s:.2f}s")
        await shoot(page, "11_candidates_refreshed_toast")

        # 3. Phase 3 (#33) — A.5 removal trigger: an NB material that only
        #    appears inside goods_name parens shows real observation counts
        #    on the detail page straight from v_material_roles (the Python
        #    workaround is deleted).
        await page.goto(f"{BASE}/clients/{CLIENT}/catalog/001.0001100/detail")
        await page.wait_for_load_state("networkidle")
        body = await page.content()
        assert "001.0001100" in body
        m = re.search(r"Số lần quan sát[^0-9]*(\d+)", body)
        assert m and int(m.group(1)) > 0, "paren-only NB code shows 0 observations"
        await shoot(page, "12_paren_only_material_has_observations")

        await ctx.close()
        await browser.close()
        print("OK")


if __name__ == "__main__":
    asyncio.run(main())
