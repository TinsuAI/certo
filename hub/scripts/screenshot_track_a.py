"""Track A vocab cleanup — capture screenshots for feature folder.

Visits 4 BOM pages on Johnson VN (which has both default and non-default
variant artifacts) to demonstrate:
- list page: 'Bản lưu' header (was 'Versions'), no '×N variants' badge
- artifacts page: '#N' badges (was 'vN'), 'Đợt' column visible
- artifact detail: '#N' h2 badge, Provenance 'Đợt' row when non-default
- presets page: option text uses '#N', non-default batch shown

Authenticate via session cookie (admin@data-hub.local). Saves to
.ai/features/2026-05-10-bom-vocab-3shape-uom-gate/screenshots/.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT_ID = "johnson-vn"

OUT = Path(".ai/features/2026-05-10-bom-vocab-3shape-uom-gate/screenshots")
OUT.mkdir(parents=True, exist_ok=True)


async def login(page):
    await page.goto(f"{BASE}/login")
    await page.fill('input[name="email"]', EMAIL)
    await page.fill('input[name="password"]', PASSWORD)
    await page.click('button[type="submit"]')
    await page.wait_for_url(f"{BASE}/clients", timeout=5000)


async def capture(page, url: str, slug: str):
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    out = OUT / f"{slug}.png"
    await page.screenshot(path=str(out), full_page=True)
    print(f"  saved {out}")


async def pick_product(page) -> tuple[str, str]:
    """Return (product_code, artifact_id) from Johnson's bom list."""
    import psycopg
    conn = psycopg.connect("host=/var/run/postgresql user=vp dbname=data_hub")
    with conn.cursor() as cur:
        cur.execute(
            "select product_code, artifact_id from hub.bom_artifacts "
            "where client_id=%s and tombstoned_at is null "
            "order by published_at desc limit 1",
            (CLIENT_ID,),
        )
        row = cur.fetchone()
    conn.close()
    return row[0], row[1]


async def main():
    pcode = aid = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()
        await login(page)
        pcode, aid = await pick_product(page)
        print(f"using product {pcode!r}, artifact {aid!r}")
        await capture(page,
                      f"{BASE}/clients/{CLIENT_ID}/bom",
                      "01_bom_list")
        await capture(page,
                      f"{BASE}/clients/{CLIENT_ID}/bom/{pcode}/artifacts",
                      "02_bom_artifacts")
        await capture(page,
                      f"{BASE}/clients/{CLIENT_ID}/bom/artifact/{aid}",
                      "03_bom_artifact_detail")
        await capture(page,
                      f"{BASE}/clients/{CLIENT_ID}/bom/{pcode}/presets",
                      "04_bom_presets")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
