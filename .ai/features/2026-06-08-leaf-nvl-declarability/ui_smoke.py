"""UI smoke: catalog rác / declarable_unmatched badges (mig 078).

Captures the new customs_relevance badges in the johnson-vn NVL catalog:
  🗑 <item_category>  → excluded_non_material (drawing/document/label)
  ⚠ chưa khớp         → declarable_unmatched (physical, no BCCT import match)

Run with the dev server up on :8754 (local-socket DB, post-backfill):
    uv run python .ai/features/2026-06-08-leaf-nvl-declarability/ui_smoke.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT = "johnson-vn"
OUT = Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

SHOTS = [
    # q="10004785" surfaces a mix: tube (declarable_unmatched) + label/document (rác).
    ("01_catalog_nvl_mixed_badges",
     f"/clients/{CLIENT}/catalog?category=nvl&q=10004785"),
    # A drawing code → 🗑 drawing (excluded_non_material).
    ("02_catalog_nvl_drawing_rac",
     f"/clients/{CLIENT}/catalog?category=nvl&q=1000439883"),
    # A tube code → ⚠ chưa khớp (declarable_unmatched).
    ("03_catalog_nvl_tube_unmatched",
     f"/clients/{CLIENT}/catalog?category=nvl&q=1000478517"),
]


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1500, "height": 950})
        await context.add_cookies([
            {"name": "data_hub_lang", "value": "vi", "url": BASE},
            {"name": "data_hub_theme", "value": "light", "url": BASE},
        ])
        page = await context.new_page()
        await page.goto(f"{BASE}/login")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(f"{BASE}/clients", timeout=8000)
        for slug, path in SHOTS:
            await page.goto(f"{BASE}{path}")
            await page.wait_for_load_state("networkidle")
            # Full page for context.
            await page.screenshot(path=str(OUT / f"{slug}.png"), full_page=True)
            print(f"saved {slug}.png")
            # Legible close-up of just the results table.
            table = page.locator("table.dh-table[data-col-table='catalog_list']")
            if await table.count():
                await table.first.screenshot(path=str(OUT / f"{slug}_table.png"))
                print(f"saved {slug}_table.png")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
