"""UI smoke: BOM adapter module-management (B.0).

Captures the three new surfaces:
  1. /admin/bom-adapters       — read-only adapter registry + binding matrix
  2. /clients/<c>/material-group-map — per-client map CRUD + banner/re-run button
  3. /clients/<c>/bom/upload    — upload form with per-client default-adapter

Run with the dev server up on :8754 (local-socket DB):
    uv run python .ai/features/2026-06-14-bom-adapter-module-management/ui_smoke.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT = "johnson-vn"
OUT = Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

SHOTS = [
    ("01_adapter_registry", "/admin/bom-adapters"),
    ("02_material_group_map", f"/clients/{CLIENT}/material-group-map"),
    ("03_bom_upload_binding", f"/clients/{CLIENT}/bom/upload"),
]


async def main():
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
        for slug, path in SHOTS:
            await page.goto(f"{BASE}{path}")
            await page.wait_for_load_state("networkidle")
            await page.screenshot(path=str(OUT / f"{slug}.png"), full_page=True)
            print(f"saved {slug}.png")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
