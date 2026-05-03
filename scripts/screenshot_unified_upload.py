"""Screenshot walk for the unified upload flow (slices 1-5).

Drives the live web UI through key cases per module, captures the
mapping page + preview screenshots, then rejects the pending so the DB
stays clean.

Output: .ai/features/2026-05-04-flexible-catalog-intake/screenshots/<module>_<step>.png

Run:
    uv run python scripts/screenshot_unified_upload.py

Pre-reqs:
- Server live on 127.0.0.1:8754.
- Login admin@data-hub.local / admin123.
- Fixtures present at data/manual_test/.
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

OUT = Path(".ai/features/2026-05-04-flexible-catalog-intake/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

FIXTURES = Path("data/manual_test")


async def login(page: Page) -> None:
    await page.goto(f"{BASE}/login")
    await page.fill('input[name="email"]', EMAIL)
    await page.fill('input[name="password"]', PASSWORD)
    await page.click('button[type="submit"]')
    await page.wait_for_url(f"{BASE}/clients", timeout=5000)


async def upload_and_capture(
    page: Page, *,
    module: str,           # 'catalog' | 'bqd' | 'bom' | 'bcct'
    fixture: Path,
    label: str,
    extra_form: dict | None = None,
):
    """Upload one fixture, capture mapping page + preview, reject."""
    upload_url = f"{BASE}/clients/{CLIENT}/{module}/upload"
    print(f"  → uploading {fixture.name} via {upload_url}")
    await page.goto(upload_url)

    # Set the file input.
    await page.set_input_files('input[type="file"]', str(fixture))

    # Apply any module-specific form knobs (e.g. BOM profile).
    if extra_form:
        for name, value in extra_form.items():
            try:
                await page.select_option(f'select[name="{name}"]', value)
            except Exception:
                pass

    # Click the upload-form submit button (NOT the notification widget,
    # which also lives on the page and has its own submit).
    await page.locator(
        'form[enctype="multipart/form-data"] button[type="submit"]'
    ).first.click()
    await page.wait_for_load_state("networkidle", timeout=15_000)

    url = page.url
    if "/upload/mapping/" in url:
        path = OUT / f"{module}_{label}_01_mapping_page.png"
        await page.screenshot(path=str(path), full_page=True)
        print(f"     mapping page → {path.name}")

        # Submit the mapping form using rigid auto-match defaults.
        # Use a text match that's stable across modules.
        await page.locator(
            'button[type="submit"]:has-text("Lưu mapping")'
        ).first.click()
        await page.wait_for_load_state("networkidle", timeout=15_000)
        url = page.url

    if "/preview/" in url or "/upload/preview/" in url:
        path = OUT / f"{module}_{label}_02_preview.png"
        await page.screenshot(path=str(path), full_page=True)
        print(f"     preview        → {path.name}")

        # Reject so DB stays clean.
        try:
            page.once("dialog", lambda d: d.accept())
            await page.click('button:has-text("Reject")')
            await page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception as e:
            print(f"     reject failed (non-fatal): {e}")
    elif "flatten-preview" in url:
        path = OUT / f"{module}_{label}_02_flatten_preview.png"
        await page.screenshot(path=str(path), full_page=True)
        print(f"     flatten-preview → {path.name}")
    else:
        path = OUT / f"{module}_{label}_99_unexpected.png"
        await page.screenshot(path=str(path), full_page=True)
        print(f"     unexpected URL ({url}) → {path.name}")


async def capture_landing_pages(page: Page) -> None:
    """One screenshot per module landing page for orientation."""
    for module, label in [
        ("catalog", "00_landing"),
        ("bqd", "00_landing"),
        ("bom", "00_landing"),
        ("bcct", "00_landing"),
    ]:
        await page.goto(f"{BASE}/clients/{CLIENT}/{module}")
        await page.wait_for_load_state("networkidle", timeout=5_000)
        path = OUT / f"{module}_{label}.png"
        await page.screenshot(path=str(path), full_page=True)
        print(f"  → {path.name}")


async def main() -> int:
    if not (FIXTURES / "06_catalog_basic_rigid.xlsx").exists():
        print(f"FAIL: fixtures missing under {FIXTURES}/", file=sys.stderr)
        return 2

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            ignore_https_errors=True,
        )
        page = await ctx.new_page()

        print("Logging in…")
        await login(page)

        print("Capturing landing pages…")
        await capture_landing_pages(page)

        cases = [
            # (module, fixture, label, extra_form)
            ("catalog", "06_catalog_basic_rigid.xlsx", "rigid", None),
            ("catalog", "07_catalog_llm_english.xlsx", "english_headers", None),
            ("bqd",     "04_bqd_basic_rigid.xlsx",     "rigid", None),
            ("bqd",     "05_bqd_llm_english.xlsx",     "english_headers", None),
            ("bom",     "08_bom_manual_flat_rigid.xlsx", "rigid",
             {"profile": "manual_flat"}),
            ("bom",     "09_bom_llm_english.xlsx",     "english_headers",
             {"profile": "manual_flat"}),
            ("bcct",    "01_stage_AB_full_co_bcct.xlsx", "full_co",  None),
            ("bcct",    "10_bcct_all_new_phase2.xlsx",   "all_new", None),
        ]

        for module, fixture_name, label, extra in cases:
            print(f"\n[{module}] {label} ({fixture_name})")
            try:
                await upload_and_capture(
                    page,
                    module=module,
                    fixture=FIXTURES / fixture_name,
                    label=label,
                    extra_form=extra,
                )
            except Exception as e:
                print(f"  WARN: case failed: {e}")
                path = OUT / f"{module}_{label}_99_error.png"
                try:
                    await page.screenshot(path=str(path), full_page=True)
                    print(f"     error snapshot → {path.name}")
                except Exception:
                    pass

        await browser.close()
    print(f"\nDone. Screenshots in {OUT}/")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
