"""Catalog detail goods_name drift panel — before/after bucketing.

Run twice: once against running server with old code (before), once
after restart (after). Output saved into the feature folder.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = os.environ.get("DATA_HUB_DEV_PASSWORD", "admin123")

CLIENT_ID = "johnson-vn"
MATERIAL_CODE = "005485-E"

OUT = Path(".ai/features/2026-05-28-goods-name-bucketing/screenshots")


async def run(label: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        await context.add_cookies([
            {"name": "data_hub_theme", "value": "light", "url": BASE},
            {"name": "data_hub_lang", "value": "vi", "url": BASE},
        ])
        page = await context.new_page()
        await page.goto(f"{BASE}/login")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(f"{BASE}/clients", timeout=5000)

        url = f"{BASE}/clients/{CLIENT_ID}/catalog/{MATERIAL_CODE}/detail"
        await page.goto(url)
        await page.wait_for_load_state("networkidle")
        # Capture just the drift table — uniquely identified by .drift-row.
        panel = page.locator("table:has(.drift-row)").first
        await panel.scroll_into_view_if_needed()
        out = OUT / f"{label}_drift_panel.png"
        await panel.screenshot(path=str(out))
        print(f"saved {out}")
        await browser.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("label", choices=["before", "after"])
    args = ap.parse_args()
    asyncio.run(run(args.label))
