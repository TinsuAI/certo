"""UI smoke for catalog multi-source feature.

Captures screenshots of:
  1. Catalog list with status filter chip (post-mig-042)
  2. Catalog-derive tool — empty state (no configs)
  3. Catalog-derive tool — config form
  4. Catalog list filtered by status=under_review (review queue)

Run with the dev server up on http://127.0.0.1:8754.
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


async def capture(page, slug: str):
    out = OUT / f"{slug}.png"
    await page.screenshot(path=str(out), full_page=True)
    print(f"  saved {out.relative_to(Path.cwd())}")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1600, "height": 1000})
        await context.add_cookies([
            {"name": "data_hub_theme", "value": "light", "url": BASE},
            {"name": "data_hub_lang", "value": "vi", "url": BASE},
        ])
        page = await context.new_page()
        await page.goto(f"{BASE}/login")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(f"{BASE}/clients", timeout=5000)

        # 1. Catalog list — default view with new status filter chip + source pill
        await page.goto(f"{BASE}/clients/growatt-vn/catalog")
        await page.wait_for_load_state("networkidle")
        await capture(page, "01_catalog_with_status_filter")

        # 2. Catalog-derive tool — landing page (empty configs for fresh client)
        await page.goto(f"{BASE}/clients/growatt-vn/catalog/derive")
        await page.wait_for_load_state("networkidle")
        await capture(page, "02_catalog_derive_landing")

        # 3. Filter by status=under_review (review queue)
        await page.goto(f"{BASE}/clients/growatt-vn/catalog?status=under_review")
        await page.wait_for_load_state("networkidle")
        await capture(page, "03_catalog_under_review_queue")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
