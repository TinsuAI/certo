"""UI smoke for Feature 6 — Tờ khai (TKX/TKN) management.

Captures screenshots into
`.ai/features/2026-05-10-johnson-onboarding/screenshots/`:
1. Declarations index page — list with file-availability badges.
2. Filter by 'Thiếu file' showing the 4 NK / 1 XK that have no TK.
3. Declaration detail page — file list + upload form.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT_ID = "johnson-vn"

OUT = Path(".ai/features/2026-05-10-johnson-onboarding/screenshots")
OUT.mkdir(parents=True, exist_ok=True)


async def login(page):
    await page.goto(f"{BASE}/login")
    await page.fill('input[name="email"]', EMAIL)
    await page.fill('input[name="password"]', PASSWORD)
    await page.locator(
        'form:has(input[name="password"]) button[type="submit"]'
    ).click()
    await page.wait_for_load_state("networkidle")


async def main() -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()
        await login(page)

        # Step 1 — index page
        await page.goto(f"{BASE}/clients/{CLIENT_ID}/declarations")
        await page.wait_for_load_state("networkidle")
        # Sanity: at least the table rendered.
        body = await page.text_content("body")
        assert body and "Tờ khai hải quan" in body, "Index header missing"
        assert "Có TK" in body, "Có TK badge missing"
        await page.screenshot(
            path=OUT / "01_declarations_index.png", full_page=True,
        )
        print(f"  ✓ Saved {OUT / '01_declarations_index.png'}")

        # Step 2 — filter to 'Thiếu file'
        await page.goto(
            f"{BASE}/clients/{CLIENT_ID}/declarations?has_files=no"
        )
        await page.wait_for_load_state("networkidle")
        body = await page.text_content("body")
        assert body and "Thiếu TK" in body, "Thiếu TK badge missing in filter view"
        await page.screenshot(
            path=OUT / "02_declarations_filter_missing.png", full_page=True,
        )
        print(f"  ✓ Saved {OUT / '02_declarations_filter_missing.png'}")

        # Step 3 — detail page on a known declaration with files
        sample_decl = "107185157440"  # known import decl with TKN file
        await page.goto(
            f"{BASE}/clients/{CLIENT_ID}/declarations/{sample_decl}"
        )
        await page.wait_for_load_state("networkidle")
        body = await page.text_content("body")
        assert body and sample_decl in body
        assert "Tải lên file mới" in body, "Upload form missing"
        await page.screenshot(
            path=OUT / "03_declaration_detail.png", full_page=True,
        )
        print(f"  ✓ Saved {OUT / '03_declaration_detail.png'}")

        # Step 4 — standalone upload page
        await page.goto(f"{BASE}/clients/{CLIENT_ID}/declarations/upload")
        await page.wait_for_load_state("networkidle")
        body = await page.text_content("body")
        assert body and "Tải lên file tờ khai" in body
        assert "Số tờ khai" in body, "Manual decl_no field missing"
        assert "Bỏ trống nếu tên file" in body, "Auto-detect hint missing"
        await page.screenshot(
            path=OUT / "04_upload_page.png", full_page=True,
        )
        print(f"  ✓ Saved {OUT / '04_upload_page.png'}")

        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
