"""Snapshot all table views to compare UX consistency."""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"

OUT = Path(__file__).resolve().parent / "ux_audit"
OUT.mkdir(parents=True, exist_ok=True)


async def shot(page, name):
    p = OUT / f"{name}.png"
    await page.screenshot(path=str(p), full_page=False)
    print(f"  {p.name}")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_cookies([
            {"name": "data_hub_theme", "value": "light", "url": BASE},
            {"name": "data_hub_lang", "value": "vi", "url": BASE},
        ])
        page = await ctx.new_page()
        await page.goto(f"{BASE}/login")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(f"{BASE}/clients", timeout=5000)

        urls = [
            ("01_catalog_list", "/clients/growatt-vn/catalog"),
            ("02_candidates_feed", "/clients/growatt-vn/catalog/candidates"),
            ("03_bcct_list", "/clients/growatt-vn/bcct"),
            ("04_bom_list", "/clients/growatt-vn/bom"),
            ("05_bqd_list", "/clients/growatt-vn/bqd"),
            ("06_proposals", "/clients/growatt-vn/proposals"),
            ("07_uploads", "/clients/growatt-vn/uploads"),
            ("08_clients_list", "/clients"),
        ]
        for name, url in urls:
            await page.goto(BASE + url)
            await page.wait_for_load_state("networkidle")
            await shot(page, name)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
