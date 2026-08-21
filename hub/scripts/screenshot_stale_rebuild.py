"""UI smoke for the /bom/stale rebuild (audit 2026-05-27).

Captures the new pages + the deprecation banner on the legacy page:

  01_needs_action_johnson_all.png   — cluster page Johnson, all tab.
  02_needs_action_johnson_input.png — needs_input tab (the 20 actionable
                                       Johnson rows after mig 067-071).
  03_needs_action_growatt.png       — Growatt (1 row) for cross-tenant
                                       proof.
  04_audit_log_johnson.png          — forensic log page.

The legacy /bom/stale page was removed 2026-05-27 (308 redirect to
/needs-action); no separate screenshot needed.

Saves to .ai/features/2026-05-27-bom-stale-rebuild/screenshots/.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"

OUT = Path(".ai/features/2026-05-27-bom-stale-rebuild/screenshots")
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
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
        )
        page = await context.new_page()
        await login(page)

        await page.goto(f"{BASE}/clients/johnson-vn/bom/needs-action")
        await page.wait_for_load_state("networkidle")
        await shot(page, OUT / "01_needs_action_johnson_all.png")

        await page.goto(
            f"{BASE}/clients/johnson-vn/bom/needs-action?state=needs_input"
        )
        await page.wait_for_load_state("networkidle")
        await shot(page, OUT / "02_needs_action_johnson_input.png")

        await page.goto(f"{BASE}/clients/growatt-vn/bom/needs-action")
        await page.wait_for_load_state("networkidle")
        await shot(page, OUT / "03_needs_action_growatt.png")

        await page.goto(f"{BASE}/clients/johnson-vn/bom/audit-log")
        await page.wait_for_load_state("networkidle")
        await shot(page, OUT / "04_audit_log_johnson.png")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
