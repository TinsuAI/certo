"""Screenshot walk for the paginated/sorted/filtered list views.

Captures 4 modules x 4 states each:
  1. page 1 (default sort/filter)
  2. page 2 (default sort)
  3. sorted by a non-default column
  4. filtered (search box + chip if applicable)

Output: .ai/features/2026-05-04-data-views-pagination/screenshots/<module>_<state>.png

Run with the dev server live on 127.0.0.1:8754:
    uv run python scripts/screenshot_paginated_views.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright, Page


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT = "growatt-vn"

OUT = Path(".ai/features/2026-05-04-data-views-pagination/screenshots")
OUT.mkdir(parents=True, exist_ok=True)


async def login(page: Page) -> None:
    await page.goto(f"{BASE}/login")
    await page.fill('input[name="email"]', EMAIL)
    await page.fill('input[name="password"]', PASSWORD)
    await page.click('button[type="submit"]')
    await page.wait_for_url(f"{BASE}/clients", timeout=5000)


async def shoot(page: Page, *, url: str, name: str) -> None:
    await page.goto(url)
    # Wait for the .pager footer to appear (when total > 0). For empty
    # states, settle on networkidle.
    try:
        await page.wait_for_selector(".pager", timeout=2500)
    except Exception:
        await page.wait_for_load_state("networkidle")
    out = OUT / f"{name}.png"
    await page.screenshot(path=str(out), full_page=True)
    size = out.stat().st_size
    print(f"  ok {out.name}  ({size:,} bytes)")


async def walk(page: Page) -> None:
    plans = [
        # (module, default_sort_col, alt_sort_col, alt_dir, q_filter)
        ("bcct",    "registration_date", "customs_code", "asc", "Solar"),
        ("catalog", "customs_code",      "name",         "asc", "Solar"),
        ("bqd",     "internal_code",     "customs_code", "asc", "BIENTAN"),
        ("bom",     "last_published",    "product_code", "asc", "B700"),
    ]
    for module, _default_col, alt_col, alt_dir, q in plans:
        print(f"\n# {module}")
        base = f"{BASE}/clients/{CLIENT}/{module}"
        await shoot(page, url=f"{base}",                                name=f"{module}_01_page1_default")
        await shoot(page, url=f"{base}?page=2",                          name=f"{module}_02_page2")
        await shoot(page, url=f"{base}?sort={alt_col}&dir={alt_dir}",    name=f"{module}_03_sort_{alt_col}_{alt_dir}")
        await shoot(page, url=f"{base}?q={q}",                           name=f"{module}_04_filter_q")


async def main() -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()
        await login(page)
        await walk(page)
        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
