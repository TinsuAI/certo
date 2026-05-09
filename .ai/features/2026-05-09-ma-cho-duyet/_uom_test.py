"""3 UoM standardization UI test screenshots."""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"

OUT = Path(__file__).resolve().parent / "uom_test"
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

        # T1: candidate feed showing canonical UoM in row + Accept form prefill
        # Search for a candidate with UoM = pcs to verify
        await page.goto(f"{BASE}/clients/growatt-vn/catalog/candidates?q=047.0001000")
        await page.wait_for_load_state("networkidle")
        await shot(page, "T1a_feed_with_canonical_uom_kg")

        # Open Accept form inline (click the Duyệt details element)
        await page.evaluate("""
            const det = document.querySelector('details.action-details');
            if (det) det.open = true;
        """)
        await page.wait_for_timeout(300)
        await shot(page, "T1b_accept_form_uom_prefilled")

        # T3: real drift warning on 033.0024500 (PIECES vs SETS = 2 canonicals)
        await page.goto(f"{BASE}/clients/growatt-vn/catalog/033.0024500/detail")
        await page.wait_for_load_state("networkidle")
        await shot(page, "T3_real_drift_pieces_vs_sets")

        # T2: pick a material that previously may have had synonym noise.
        # Without faux-seeded data, use 047.0001000 (KG canonical) which has
        # KILO-GRAMMES alias too in some rows — verify no warning shows.
        await page.goto(f"{BASE}/clients/growatt-vn/catalog/047.0001000/detail")
        await page.wait_for_load_state("networkidle")
        await shot(page, "T2_synonym_de_noise_kg_aliases")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
