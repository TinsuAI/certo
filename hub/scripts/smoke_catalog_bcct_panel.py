"""UI smoke for Feature 3 — Catalog "Phân tích từ BCCT" panel.

Captures into `.ai/features/2026-05-10-johnson-onboarding/screenshots/`:
1. Catalog list — Johnson has thousands of materials post-bootstrap.
2. Material detail with drift — material_code=1000468960 (2 distinct units → CRITICAL).
3. Material detail without drift — pick one with single unit/hs/origin.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import psycopg
from playwright.async_api import async_playwright


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT_ID = "johnson-vn"
DRIFT_CODE = "1000468960"  # known: 111 rows, 2 units → critical

OUT = Path(".ai/features/2026-05-10-johnson-onboarding/screenshots")
OUT.mkdir(parents=True, exist_ok=True)


def _find_clean_code() -> str:
    """Pick a material with single unit/hs/origin — no drift expected."""
    with psycopg.connect("host=/var/run/postgresql user=vp dbname=data_hub") as conn, \
         conn.cursor() as cur:
        cur.execute("""
            select customs_code from hub.bcct_rows
             where client_id='johnson-vn'
             group by customs_code
             having count(*) >= 3
                and count(distinct unit) = 1
                and count(distinct hs_code) = 1
                and count(distinct origin) = 1
             limit 1
        """)
        row = cur.fetchone()
        if not row:
            raise RuntimeError("could not find a clean material")
        return row[0]


async def login(page):
    await page.goto(f"{BASE}/login")
    await page.fill('input[name="email"]', EMAIL)
    await page.fill('input[name="password"]', PASSWORD)
    await page.locator(
        'form:has(input[name="password"]) button[type="submit"]'
    ).click()
    await page.wait_for_load_state("networkidle")


async def main() -> int:
    clean_code = _find_clean_code()
    print(f"clean code: {clean_code}, drift code: {DRIFT_CODE}")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()
        await login(page)

        # 1 — catalog list (Johnson has thousands of materials)
        await page.goto(f"{BASE}/clients/{CLIENT_ID}/catalog")
        await page.wait_for_load_state("networkidle")
        body = await page.text_content("body")
        assert body and "Danh mục" in body
        await page.screenshot(
            path=OUT / "05_catalog_list.png", full_page=True,
        )
        print(f"  ✓ Saved {OUT / '05_catalog_list.png'}")

        # 2 — material with drift (CRITICAL on unit)
        await page.goto(
            f"{BASE}/clients/{CLIENT_ID}/catalog/{DRIFT_CODE}/detail"
        )
        await page.wait_for_load_state("networkidle")
        body = await page.text_content("body")
        assert body and "Phân tích từ BCCT" in body, "Analysis panel missing"
        assert "Critical" in body, "Critical drift badge missing"
        assert "Đại diện" in body, "Representative callout missing"
        await page.screenshot(
            path=OUT / "06_catalog_detail_with_drift.png", full_page=True,
        )
        print(f"  ✓ Saved {OUT / '06_catalog_detail_with_drift.png'}")

        # 3 — material without drift
        await page.goto(
            f"{BASE}/clients/{CLIENT_ID}/catalog/{clean_code}/detail"
        )
        await page.wait_for_load_state("networkidle")
        body = await page.text_content("body")
        assert body and "Phân tích từ BCCT" in body
        assert "Không có drift" in body, "Clean state hint missing"
        await page.screenshot(
            path=OUT / "07_catalog_detail_no_drift.png", full_page=True,
        )
        print(f"  ✓ Saved {OUT / '07_catalog_detail_no_drift.png'}")

        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
