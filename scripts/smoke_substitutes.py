"""UI smoke for Feature 4 — Vật tư thay thế panel.

Captures into `.ai/features/2026-05-10-johnson-onboarding/screenshots/`:
1. Catalog detail with substitute candidates (multi-source).
2. JSON API response sanity check.
"""
from __future__ import annotations

import asyncio
import json
import sys
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT_ID = "johnson-vn"
SAMPLE_CODE = "1000539396"  # known: 38 candidates, 2 sources

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
        ctx = await browser.new_context(viewport={"width": 1400, "height": 1100})
        page = await ctx.new_page()
        await login(page)

        await page.goto(
            f"{BASE}/clients/{CLIENT_ID}/catalog/{SAMPLE_CODE}/detail"
        )
        await page.wait_for_load_state("networkidle")
        body = await page.text_content("body")
        assert body and "Vật tư thay thế" in body, "Substitute panel missing"
        # At least one source badge should render
        assert ("Cùng HS" in body or "trgm" in body or "Manual" in body), (
            "no source badge rendered"
        )
        await page.screenshot(
            path=OUT / "09_substitute_panel.png", full_page=True,
        )
        print(f"  ✓ Saved {OUT / '09_substitute_panel.png'}")

        # Fetch session cookies for API call.
        cookies = await ctx.cookies()
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

        # API smoke
        req = urllib.request.Request(
            f"{BASE}/api/v1/clients/{CLIENT_ID}/materials/{SAMPLE_CODE}/substitutes?min_score=0",
            headers={"Cookie": cookie_str},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        assert data["count"] > 0, "API returned 0 candidates"
        assert data["material_a_code"] == SAMPLE_CODE
        item = data["items"][0]
        assert "sources" in item and item["sources"]
        assert "combined_score" in item
        print(f"  ✓ API: {data['count']} candidates, top combined_score="
              f"{item['combined_score']}, sources={item['sources']}")

        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
