"""A.4.4 UI smoke — capture the 4-state convertibility-aware UoM panel
on real Growatt materials. Run with the dev server up on :8754.

  uv run python .ai/features/2026-06-07-convertibility-aware-uom/ui_smoke.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT = "growatt-vn"
OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

# (slug, material_code, what it demonstrates)
CASES = [
    ("01_equivalent_plus_unconfirmed", "033.0024500",
     "PIECES official; PIECES=equivalent, SETS=tier-A unconfirmed (amber)"),
    ("02_equivalent_plus_incompatible", "GIAY-CD",
     "PIECES official; PIECES=equivalent, METRES=incompatible (red)"),
    ("03_alias_equivalent", "B700.0192500",
     "ST official; PIECES=equivalent via alias (no false 'lệch')"),
]


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_cookies([
            {"name": "data_hub_lang", "value": "vi", "url": BASE},
        ])
        page = await ctx.new_page()
        await page.goto(f"{BASE}/login")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(f"{BASE}/clients", timeout=5000)

        for slug, code, desc in CASES:
            url = f"{BASE}/clients/{CLIENT}/catalog/{code}/detail"
            await page.goto(url)
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            heading = page.get_by_role("heading", name="Đơn vị tính")
            try:
                await heading.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            out = OUT / f"{slug}.png"
            await page.screenshot(path=str(out))  # viewport (focused)
            print(f"  saved {out}  — {desc}")

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
