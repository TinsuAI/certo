"""Playwright UI screenshots — walks the client-workspace pattern."""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"

OUT = Path("data/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

CLIENT_ID = "growatt-vn"  # auto-seed creates this with full data


async def capture(page, slug: str, theme: str = "light"):
    out = OUT / f"{slug}_{theme}.png"
    await page.screenshot(path=str(out), full_page=True)
    print(f"  saved {out}")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for theme in ("light", "dark"):
            context = await browser.new_context(viewport={"width": 1440, "height": 900})
            await context.add_cookies([{
                "name": "data_hub_theme", "value": theme, "url": BASE,
            }, {
                "name": "data_hub_lang", "value": "vi", "url": BASE,
            }])
            page = await context.new_page()
            print(f"--- {theme} ---")
            await page.goto(f"{BASE}/login")
            if theme == "light":
                await capture(page, "01_login")
            await page.fill('input[name="email"]', EMAIL)
            await page.fill('input[name="password"]', PASSWORD)
            await page.click('button[type="submit"]')
            await page.wait_for_url(f"{BASE}/clients", timeout=5000)

            paths = [
                ("02_clients_list", "/clients"),
                ("03_client_workspace", f"/clients/{CLIENT_ID}"),
                ("04_client_edit", f"/clients/{CLIENT_ID}/edit"),
                ("10_catalog", f"/clients/{CLIENT_ID}/catalog"),
                ("11_catalog_filtered", f"/clients/{CLIENT_ID}/catalog?category=nvl"),
                ("12_catalog_upload", f"/clients/{CLIENT_ID}/catalog/upload"),
                ("20_bqd", f"/clients/{CLIENT_ID}/bqd"),
                ("21_bqd_upload", f"/clients/{CLIENT_ID}/bqd/upload"),
                ("30_bcct", f"/clients/{CLIENT_ID}/bcct"),
                ("31_bcct_imports", f"/clients/{CLIENT_ID}/bcct?direction=import"),
                ("32_bcct_upload", f"/clients/{CLIENT_ID}/bcct/upload"),
                ("40_bom", f"/clients/{CLIENT_ID}/bom"),
                ("41_bom_upload", f"/clients/{CLIENT_ID}/bom/upload"),
                ("42_bom_versions", f"/clients/{CLIENT_ID}/bom/INV-3000/versions"),
                ("50_proposals", f"/clients/{CLIENT_ID}/proposals"),
                ("60_uploads", f"/clients/{CLIENT_ID}/uploads"),
            ]
            for slug, path in paths:
                if theme == "dark" and slug not in {"02_clients_list", "03_client_workspace", "10_catalog", "20_bqd", "30_bcct", "40_bom", "50_proposals"}:
                    continue
                await page.goto(f"{BASE}{path}")
                try: await page.wait_for_load_state("networkidle", timeout=3000)
                except Exception: pass
                await capture(page, slug, theme)

            # capture a BOM version detail too (need a real version_id)
            if theme == "light":
                await page.goto(f"{BASE}/clients/{CLIENT_ID}/bom/INV-3000/versions")
                try: await page.wait_for_load_state("networkidle", timeout=3000)
                except Exception: pass
                ver_link = await page.query_selector('a[href*="/bom/version/"]')
                if ver_link:
                    href = await ver_link.get_attribute("href")
                    await page.goto(f"{BASE}{href}")
                    await capture(page, "43_bom_version_detail", "light")
                # proposal detail
                await page.goto(f"{BASE}/clients/{CLIENT_ID}/proposals")
                try: await page.wait_for_load_state("networkidle", timeout=3000)
                except Exception: pass
                prop_link = await page.query_selector('a[href*="/proposals/"]')
                if prop_link:
                    href = await prop_link.get_attribute("href")
                    await page.goto(f"{BASE}{href}")
                    await capture(page, "51_proposal_detail", "light")
                # English language toggle screenshot
                await page.goto(f"{BASE}/clients")
                # Hit the lang toggle
                await page.evaluate(
                    "document.cookie = 'data_hub_lang=en; path=/'"
                )
                await page.goto(f"{BASE}/clients/{CLIENT_ID}")
                try: await page.wait_for_load_state("networkidle", timeout=3000)
                except Exception: pass
                await capture(page, "99_workspace_english", "light")

            await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
