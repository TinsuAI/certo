"""Take screenshots of all main pages with Playwright. Saves to data/screenshots/."""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"

OUT = Path("data/screenshots")
OUT.mkdir(parents=True, exist_ok=True)


PAGES = [
    ("01_login", "/login", False),
    ("02_dncxs_list", "/dncxs", True),
    ("03_dncxs_new", "/dncxs/new", True),
    ("10_dncx_detail", "_DETAIL_", True),
    ("20_materials_list", "/materials", True),
    ("21_materials_upload", "/materials/upload", True),
    ("30_code_mappings_list", "/code-mappings", True),
    ("31_code_mappings_upload", "/code-mappings/upload", True),
    ("40_bcct_list", "/bcct", True),
    ("41_bcct_upload", "/bcct/upload", True),
    ("50_bom_list", "/bom", True),
    ("51_bom_upload", "/bom/upload", True),
    ("52_bom_versions", "_BOM_VERSIONS_", True),
    ("53_bom_version_detail", "_BOM_DETAIL_", True),
    ("60_proposals_list", "/proposals", True),
    ("61_proposal_detail", "_PROPOSAL_DETAIL_", True),
]


async def capture(page, slug: str, theme: str = "light"):
    out = OUT / f"{slug}_{theme}.png"
    await page.screenshot(path=str(out), full_page=True)
    print(f"  saved {out}")


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        # login
        print("Logging in...")
        await page.goto(f"{BASE}/login")
        await capture(page, "01_login")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(f"{BASE}/dncxs", timeout=5000)

        # find Growatt DNCX (the one with data) for detail/list previews
        links = await page.query_selector_all('.card-grid a.card')
        detail_url = None
        dncx_id = None
        for link in links:
            text = (await link.inner_text()) or ""
            if "Growatt" in text:
                href = await link.get_attribute("href")
                detail_url = f"{BASE}{href}"
                dncx_id = href.rsplit("/", 1)[-1]
                break
        if not detail_url and links:
            href = await links[0].get_attribute("href")
            detail_url = f"{BASE}{href}"
            dncx_id = href.rsplit("/", 1)[-1]

        # Discover a BOM product + version + proposal for detail screenshots
        await page.goto(f"{BASE}/bom?dncx_id={dncx_id}")
        try: await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception: pass
        bom_versions_url = None
        bom_detail_url = None
        prod_link = await page.query_selector('a[href*="/bom/"][href*="/versions"]')
        if prod_link:
            href = await prod_link.get_attribute("href")
            bom_versions_url = f"{BASE}{href}"
            await page.goto(bom_versions_url)
            try: await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception: pass
            ver_link = await page.query_selector('a[href*="/bom/version/"]')
            if ver_link:
                href = await ver_link.get_attribute("href")
                bom_detail_url = f"{BASE}{href}"

        await page.goto(f"{BASE}/proposals?dncx_id={dncx_id}")
        try: await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception: pass
        prop_detail_url = None
        prop_link = await page.query_selector('a[href*="/proposals/"]')
        if prop_link:
            href = await prop_link.get_attribute("href")
            prop_detail_url = f"{BASE}{href}"

        for slug, path, _ in PAGES[1:]:
            if path == "_DETAIL_":
                url = detail_url
            elif path == "_BOM_VERSIONS_":
                url = bom_versions_url
            elif path == "_BOM_DETAIL_":
                url = bom_detail_url
            elif path == "_PROPOSAL_DETAIL_":
                url = prop_detail_url
            elif path in ("/materials", "/code-mappings", "/bcct", "/bom", "/proposals") and dncx_id:
                url = f"{BASE}{path}?dncx_id={dncx_id}"
            else:
                url = f"{BASE}{path}"
            if url is None:
                continue
            print(f"  GET {url}")
            await page.goto(url)
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            await capture(page, slug, "light")

        # Toggle dark theme via the topnav button form, then re-shoot a few
        print("Toggling dark theme...")
        await page.goto(f"{BASE}/dncxs")
        # set cookie directly
        await context.add_cookies([{
            "name": "data_hub_theme", "value": "dark",
            "url": BASE,
        }])
        for slug, path, _ in [("02_dncxs_list", "/dncxs", True),
                              ("20_materials_list", "/materials", True),
                              ("40_bcct_list", "/bcct", True),
                              ("50_bom_list", "/bom", True)]:
            url = f"{BASE}{path}"
            if path in ("/materials", "/bcct", "/bom") and dncx_id:
                url += f"?dncx_id={dncx_id}"
            await page.goto(url)
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            await capture(page, slug, "dark")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
