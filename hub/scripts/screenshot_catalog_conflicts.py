"""A.2 catalog conflicts page — UI smoke screenshot.

Captures three views against real Growatt + Johnson data:
  - 01_nav_banner.png      — catalog list with the "X dòng cần review"
                              banner pointing to /catalog/conflicts.
  - 02_conflicts_all.png   — conflicts page default (`type=all`) for
                              Johnson, showing 1 declared_observed_conflict.
  - 03_conflicts_sourcing.png — Growatt conflicts page with `type=sourcing`
                              filter, showing the 1 sourcing_confirmation
                              conflict and the inline editor.

Saves to .ai/features/2026-05-15-catalog-conflicts-page/screenshots/.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"

OUT = Path(".ai/features/2026-05-15-catalog-conflicts-page/screenshots")
OUT.mkdir(parents=True, exist_ok=True)


async def login(page) -> None:
    await page.goto(f"{BASE}/login")
    await page.fill('input[name="email"]', EMAIL)
    await page.fill('input[name="password"]', PASSWORD)
    await page.click('button[type="submit"]')
    await page.wait_for_load_state("networkidle")


async def shot(page, path: Path) -> None:
    await page.screenshot(path=str(path), full_page=True)
    print(f"  saved {path}")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()
        await login(page)

        await page.goto(f"{BASE}/clients/growatt-vn/catalog")
        await page.wait_for_load_state("networkidle")
        await shot(page, OUT / "01_nav_banner.png")

        await page.goto(f"{BASE}/clients/johnson-vn/catalog/conflicts")
        await page.wait_for_load_state("networkidle")
        await shot(page, OUT / "02_conflicts_all.png")

        await page.goto(
            f"{BASE}/clients/growatt-vn/catalog/conflicts?type=sourcing",
        )
        await page.wait_for_load_state("networkidle")
        await shot(page, OUT / "03_conflicts_sourcing.png")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
