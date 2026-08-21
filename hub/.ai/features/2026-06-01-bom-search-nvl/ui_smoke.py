"""UI smoke: BOM product search matches NVL/component codes.

Captures the BOM list page searching by a real component code
(`001.0033100`, used in 8 growatt-vn products) — proving reverse
lookup "which finished products use this NVL".
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT = "growatt-vn"
NVL = "001.0033100"

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 1000})
        await ctx.add_cookies([
            {"name": "data_hub_lang", "value": "vi", "url": BASE},
        ])
        page = await ctx.new_page()
        await page.goto(f"{BASE}/login")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(f"{BASE}/clients", timeout=5000)

        # NVL search — finished products whose BOM contains the component.
        await page.goto(f"{BASE}/clients/{CLIENT}/bom?q={NVL}")
        await page.wait_for_load_state("networkidle")
        await page.screenshot(path=str(OUT / "bom_search_by_nvl.png"),
                              full_page=True)
        print("saved bom_search_by_nvl.png")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
