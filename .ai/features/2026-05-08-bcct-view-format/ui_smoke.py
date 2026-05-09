"""UI smoke for BCCT view format + column picker.

Captures three screenshots after applying:
  - Number formatting (locale-aware thousand separators)
  - Currency-correct labels (NT vs VND columns)
  - Column-picker (localStorage-backed show/hide)

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

        # 1. BCCT export view (Growatt) — verifies USD next to ~470k FX value
        #    and VND next to ~12B-VND value.
        await page.goto(f"{BASE}/clients/growatt-vn/bcct?direction=export")
        await page.wait_for_load_state("networkidle")
        await capture(page, "01_bcct_export_currency_pair")

        # 2. Column picker open — show available toggles.
        await page.evaluate("""
            const det = document.querySelector('details.col-picker');
            if (det) det.open = true;
        """)
        await capture(page, "02_bcct_column_picker_open")

        # 3. Hide a few columns + reload to prove localStorage round-trip.
        await page.evaluate("""
            ['line_no', 'declaration_type', 'unit'].forEach(k => {
              const cb = document.querySelector(`[data-col-toggle="${k}"]`);
              if (cb && cb.checked) cb.click();
            });
        """)
        await page.reload()
        await page.wait_for_load_state("networkidle")
        await page.evaluate("""
            const det = document.querySelector('details.col-picker');
            if (det) det.open = true;
        """)
        await capture(page, "03_bcct_columns_hidden_persisted")

        # 4. Import view — different currency mix to confirm format.
        await page.goto(f"{BASE}/clients/growatt-vn/bcct?direction=import")
        await page.wait_for_load_state("networkidle")
        await capture(page, "04_bcct_import_currency_pair")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
