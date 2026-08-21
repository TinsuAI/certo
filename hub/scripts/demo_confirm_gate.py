"""Demo confirm-gate UX across all 4 modules — capture preview screenshots.

Drives the live web UI through one upload per module, captures the
preview page screenshot, then rejects the pending so DB stays clean.
For BCCT, runs both the all-NEW preview and the DIFF/ORPHAN preview
(by uploading 03a as baseline first, then 03b which changes things).

Output: data/screenshots/confirm_gate_demo/<module>_<step>.png

Run:
    uv run python scripts/demo_confirm_gate.py

Server must be live on 127.0.0.1:8754. Login admin/admin123.
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

OUT = Path(__file__).resolve().parent.parent / "data" / "screenshots" / "confirm_gate_demo"
OUT.mkdir(parents=True, exist_ok=True)

FIXTURES = Path(__file__).resolve().parent.parent / "data" / "manual_test"


async def login(page: Page) -> None:
    await page.goto(f"{BASE}/login")
    await page.fill('input[name="email"]', EMAIL)
    await page.fill('input[name="password"]', PASSWORD)
    await page.click('button[type="submit"]')
    await page.wait_for_url(f"{BASE}/clients", timeout=5000)


async def upload(page: Page, *, module: str, fixture: Path,
                 extra_form_fields: dict | None = None) -> str:
    """Submit upload form, return preview URL after redirect."""
    await page.goto(f"{BASE}/clients/{CLIENT}/{module}/upload")
    if extra_form_fields:
        for sel, val in extra_form_fields.items():
            await page.select_option(sel, val)
    async with page.expect_navigation() as nav:
        await page.set_input_files('input[type="file"]', str(fixture))
        await page.click("form[action*='/upload'] button.btn-primary[type='submit']")
    await nav.value
    return page.url


async def screenshot(page: Page, name: str) -> Path:
    out = OUT / f"{name}.png"
    await page.screenshot(path=str(out), full_page=True)
    print(f"  → {out} ({out.stat().st_size // 1024} KB)")
    return out


async def reject_if_preview(page: Page) -> None:
    """If we're on a preview page, click Reject to keep DB clean."""
    if "/preview/" not in page.url:
        return
    page.on("dialog", lambda d: asyncio.create_task(d.accept()))
    # Buttons differ slightly per module; common pattern is formaction=*reject
    btn = page.locator("button[formaction*='reject']")
    if await btn.count() > 0:
        async with page.expect_navigation():
            await btn.first.click()


async def confirm_if_preview(page: Page, all_checkboxes: bool = False) -> None:
    """Click the primary save button; optionally tick all confirm checkboxes.

    BOM/BQD/Catalog: 3-button form using `formaction=`.
    BCCT: single-button form whose `action=` carries the confirm URL.
    """
    if "/preview/" not in page.url:
        return
    if all_checkboxes:
        for cb in await page.locator('input[type="checkbox"][name^="confirm_"]').all():
            await cb.check()
    btn = page.locator("button[formaction*='confirm']")
    if await btn.count() == 0:
        btn = page.locator("form[action*='confirm'] button[type='submit'].btn-primary")
    async with page.expect_navigation():
        await btn.first.click()


async def main() -> int:
    print(f"Server: {BASE}")
    print(f"Output: {OUT.resolve()}")
    print()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await ctx.new_page()
        await login(page)
        print("✓ logged in\n")

        # 1. CATALOG — first-time upload, all NEW preview
        print("--- CATALOG (file 06) ---")
        url = await upload(page, module="catalog", fixture=FIXTURES / "06_catalog_basic_rigid.xlsx")
        print(f"  preview URL: {url}")
        await screenshot(page, "1_catalog_preview")
        await reject_if_preview(page)

        # 2. BQD — first-time, all NEW + 1-to-N detection
        print("\n--- BQD (file 04) ---")
        url = await upload(page, module="bqd", fixture=FIXTURES / "04_bqd_basic_rigid.xlsx")
        print(f"  preview URL: {url}")
        await screenshot(page, "2_bqd_preview")
        await reject_if_preview(page)

        # 3. BOM — first-time, manual_flat profile
        print("\n--- BOM (file 08, profile=manual_flat) ---")
        url = await upload(
            page, module="bom",
            fixture=FIXTURES / "08_bom_manual_flat_rigid.xlsx",
            extra_form_fields={'select[name="profile"]': "manual_flat"},
        )
        print(f"  preview URL: {url}")
        await screenshot(page, "3_bom_preview")
        await reject_if_preview(page)

        # 4. BCCT all-NEW preview (file 10)
        print("\n--- BCCT all-NEW (file 10, Phase 2 gap closer) ---")
        url = await upload(page, module="bcct",
                           fixture=FIXTURES / "10_bcct_all_new_phase2.xlsx")
        print(f"  preview URL: {url}")
        await screenshot(page, "4_bcct_all_new_preview")
        await reject_if_preview(page)

        # 5. BCCT DIFF/ORPHAN preview — the interesting one
        # First, baseline: upload 03a + confirm to seed 3 rows
        print("\n--- BCCT baseline (file 03a, confirm to seed) ---")
        url = await upload(page, module="bcct",
                           fixture=FIXTURES / "03a_stage_C1_baseline.xlsx")
        await confirm_if_preview(page, all_checkboxes=True)
        print(f"  baseline ingested → {page.url}")

        # Now upload 03b which changes 1, removes 1, adds 1
        print("\n--- BCCT DIFF/ORPHAN (file 03b — most interesting preview) ---")
        url = await upload(page, module="bcct",
                           fixture=FIXTURES / "03b_stage_C1_changed.xlsx")
        print(f"  preview URL: {url}")
        await screenshot(page, "5_bcct_diff_orphan_preview")
        await reject_if_preview(page)

        await browser.close()

    print(f"\n✓ done. Screenshots in {OUT.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
