"""UI smoke: NXT + year-end inventory tier (slice 1).

Drives the real upload → preview → confirm flow for both modules against the
system-standard templates, capturing:
  1. NXT upload form           4. Inventory upload form
  2. NXT preview (parsed)      5. Inventory preview (parsed, variance flagged)
  3. NXT list (after confirm)  6. Inventory list (after confirm)

Run with the dev server up on :8754 (local-socket DB):
    uv run python .ai/features/2026-06-14-nxt-inventory-tier/ui_smoke.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from playwright.async_api import async_playwright  # noqa: E402

from app.parsers.nxt_adapters.system_template import (  # noqa: E402
    render_template_xlsx as render_nxt,
)
from app.parsers.inventory_adapters.system_template import (  # noqa: E402
    render_template_xlsx as render_inv,
)

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT = "growatt-vn"
OUT = Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
TMP = Path(tempfile.mkdtemp())


def _write(name: str, blob: bytes) -> str:
    p = TMP / name
    p.write_bytes(blob)
    return str(p)


async def shot(page, slug: str):
    await page.wait_for_load_state("networkidle")
    await page.screenshot(path=str(OUT / f"{slug}.png"), full_page=True)
    print(f"saved {slug}.png")


async def main():
    nxt_file = _write("mau-nxt.xlsx", render_nxt())
    inv_file = _write("mau-ton.xlsx", render_inv())
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1500, "height": 950})
        await context.add_cookies([
            {"name": "data_hub_lang", "value": "vi", "url": BASE},
            {"name": "data_hub_theme", "value": "light", "url": BASE},
        ])
        page = await context.new_page()
        await page.goto(f"{BASE}/login")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(f"{BASE}/clients", timeout=8000)

        # ── NXT ──
        await page.goto(f"{BASE}/clients/{CLIENT}/nxt/upload")
        await shot(page, "01_nxt_upload")
        await page.set_input_files('input[name="file"]', nxt_file)
        await page.fill('input[name="period_from"]', "2025-01-01")
        await page.fill('input[name="period_to"]', "2025-12-31")
        await page.click('button:has-text("Tải lên & xem trước")')
        await page.wait_for_url("**/nxt/preview/**", timeout=8000)
        await shot(page, "02_nxt_preview")
        await page.click('button:has-text("Xác nhận lưu")')
        await page.wait_for_url(f"{BASE}/clients/{CLIENT}/nxt**", timeout=8000)
        await shot(page, "03_nxt_list")

        # ── Inventory ──
        await page.goto(f"{BASE}/clients/{CLIENT}/inventory-snapshots/upload")
        await shot(page, "04_inventory_upload")
        await page.set_input_files('input[name="file"]', inv_file)
        await page.fill('input[name="snapshot_date"]', "2025-12-31")
        await page.click('button:has-text("Tải lên & xem trước")')
        await page.wait_for_url("**/inventory-snapshots/preview/**", timeout=8000)
        await shot(page, "05_inventory_preview")
        await page.click('button:has-text("Xác nhận lưu")')
        await page.wait_for_url(f"{BASE}/clients/{CLIENT}/inventory-snapshots**", timeout=8000)
        await shot(page, "06_inventory_list")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
