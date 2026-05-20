"""Catalog detail — per-material BCCT time-series screenshot smoke.

Captures the new "Biến động theo thời gian" section against a Johnson
material with known unit drift (1000469833 — SETS↔PIECES across 6
runs in 2025–2026).

Saves to .ai/features/2026-05-20-catalog-detail-time-series/screenshots/.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"

OUT = Path(".ai/features/2026-05-20-catalog-detail-time-series/screenshots")
OUT.mkdir(parents=True, exist_ok=True)


async def login(page) -> None:
    await page.goto(f"{BASE}/login")
    await page.fill('input[name="email"]', EMAIL)
    await page.fill('input[name="password"]', PASSWORD)
    await page.click('button[type="submit"]')
    await page.wait_for_load_state("networkidle")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()
        await login(page)

        await page.goto(
            f"{BASE}/clients/johnson-vn/catalog/1000469833/detail#timeline",
        )
        await page.wait_for_load_state("networkidle")
        # Expand all timeline blocks (collapsed by default for non-critical).
        await page.evaluate(
            "document.querySelectorAll('.timeline-block').forEach(e => e.open = true)"
        )
        await page.wait_for_timeout(200)
        # Capture each timeline-block separately. The shared parent
        # is the full detail-page `<section>` which contains BCCT
        # references + BOM tables below — too tall to be useful.
        for idx, block_id in enumerate(
            ["timeline-unit", "timeline-declaration_type"], start=1,
        ):
            loc = page.locator(f"#{block_id}")
            if await loc.count() == 0:
                continue
            await loc.scroll_into_view_if_needed()
            await page.wait_for_timeout(200)
            path = OUT / f"{idx:02d}_{block_id}.png"
            await loc.screenshot(path=str(path))
            print(f"saved {path}")

        # Quarterly stats block has no anchor id; grab the last
        # .timeline-block on the page which is the quarterly one.
        last_block = page.locator(".timeline-block").last
        await last_block.scroll_into_view_if_needed()
        await page.wait_for_timeout(200)
        await last_block.screenshot(
            path=str(OUT / "03_quarterly_stats.png"),
        )
        print(f"saved {OUT / '03_quarterly_stats.png'}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
