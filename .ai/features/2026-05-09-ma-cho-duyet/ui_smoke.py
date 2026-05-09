"""Mã chờ duyệt — UI smoke + screenshots.

Run with dev server up at 127.0.0.1:8754.
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


async def shot(page, name: str, *, full=False):
    path = OUT / f"{name}.png"
    await page.screenshot(path=str(path), full_page=full)
    print(f"  saved {path}")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_cookies([
            {"name": "data_hub_theme", "value": "light", "url": BASE},
            {"name": "data_hub_lang", "value": "vi", "url": BASE},
        ])
        page = await ctx.new_page()

        # Login
        await page.goto(f"{BASE}/login")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(f"{BASE}/clients", timeout=5000)

        # Growatt: dual-system (rules + mappings) → mix of NB/HQ candidates
        await page.goto(f"{BASE}/clients/growatt-vn/catalog/candidates")
        await page.wait_for_load_state("networkidle")
        await shot(page, "01_growatt_feed_all")

        await page.goto(f"{BASE}/clients/growatt-vn/catalog/candidates?kind=hq")
        await page.wait_for_load_state("networkidle")
        await shot(page, "02_growatt_feed_hq_filter")

        await page.goto(f"{BASE}/clients/growatt-vn/catalog/candidates?kind=nb")
        await page.wait_for_load_state("networkidle")
        await shot(page, "03_growatt_feed_nb_filter")

        # Johnson: unified — single kind
        await page.goto(f"{BASE}/clients/johnson-vn/catalog/candidates")
        await page.wait_for_load_state("networkidle")
        await shot(page, "04_johnson_feed_unified")

        # Catalog page with new "Mã chờ duyệt" link visible
        await page.goto(f"{BASE}/clients/growatt-vn/catalog")
        await page.wait_for_load_state("networkidle")
        await shot(page, "05_catalog_with_candidates_link")

        # Pagination footer with smaller page_size to fit viewport
        await page.goto(
            f"{BASE}/clients/growatt-vn/catalog/candidates?page=2&page_size=5"
        )
        await page.wait_for_load_state("networkidle")
        await shot(page, "06_pagination_footer")

        # Catalog material detail with cross-source warnings (Growatt has
        # bucket-level codes that may show HS drift / direction drift).
        await page.goto(f"{BASE}/clients/growatt-vn/catalog/IC/detail")
        await page.wait_for_load_state("networkidle")
        await shot(page, "07_detail_with_warnings")

        # Catalog material edit form
        await page.goto(f"{BASE}/clients/growatt-vn/catalog/IC/edit")
        await page.wait_for_load_state("networkidle")
        await shot(page, "08_material_edit_form")

        # Candidate detail page — pick top pending candidate via list page
        await page.goto(f"{BASE}/clients/growatt-vn/catalog/candidates")
        await page.wait_for_load_state("networkidle")
        href = await page.eval_on_selector(
            'tbody tr td a[href*="/candidates/"]',
            'el => el.getAttribute("href")',
        )
        if href:
            await page.goto(BASE + href)
            await page.wait_for_load_state("networkidle")
            await shot(page, "09_candidate_detail")

        # Material detail with mappings panel (DIENTRO has many)
        await page.goto(f"{BASE}/clients/growatt-vn/catalog/DIENTRO/detail")
        await page.wait_for_load_state("networkidle")
        await shot(page, "11_detail_with_mappings")

        # Material detail with audit feed (find material with edits)
        await page.goto(f"{BASE}/clients/growatt-vn/catalog/IC/detail")
        await page.wait_for_load_state("networkidle")
        # Expand the inline edit panel for the screenshot
        await page.evaluate("""
            document.querySelectorAll('details.inline-edit summary')
              .forEach(s => s.parentElement.open = true);
        """)
        await page.wait_for_timeout(300)
        await shot(page, "10_material_detail_inline_edit")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
