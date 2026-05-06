"""BOM v3 UI smoke — verify Provenance panel + variant/shape/source columns
on real Growatt + Johnson re-ingested data."""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ("growatt-vn", "SD00.0010600"),  # the famous 130-vs-484 product
    ("johnson-vn", "MFW0502-571"),
]


async def shoot(page, slug: str, *, full: bool = True) -> Path:
    out = OUT / f"{slug}.png"
    await page.screenshot(path=str(out), full_page=full)
    print(f"  saved {out.name}")
    return out


async def main() -> None:
    findings: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1600, "height": 1000})
        await ctx.add_cookies([
            {"name": "data_hub_lang", "value": "vi", "url": BASE},
        ])
        page = await ctx.new_page()

        await page.goto(f"{BASE}/login")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url(f"{BASE}/clients", timeout=10000)
        print("login ok")

        for client_id, product_code in TARGETS:
            slug = f"{client_id}_{product_code.replace('.', '_')}"
            print(f"--- {client_id} / {product_code} ---")

            # BOM list (per-product index)
            await page.goto(f"{BASE}/clients/{client_id}/bom")
            try:
                await page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass
            await shoot(page, f"01_{client_id}_bom_list")

            # Versions list for product (where variant/shape/source columns live)
            url = f"{BASE}/clients/{client_id}/bom/{product_code}/versions"
            await page.goto(url)
            try:
                await page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass
            await shoot(page, f"02_{slug}_versions")

            # Sniff for the new columns in the rendered HTML
            html = await page.content()
            for needle in ("variant", "shape", "source"):
                hit = needle.lower() in html.lower()
                findings.append(f"{slug} versions page: '{needle}' present={hit}")

            # Open first version detail link
            link = await page.query_selector('a[href*="/bom/version/"]')
            if not link:
                findings.append(f"{slug}: NO version detail link found")
                continue
            href = await link.get_attribute("href")
            await page.goto(f"{BASE}{href}")
            try:
                await page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass
            await shoot(page, f"03_{slug}_version_detail")
            await shoot(page, f"04_{slug}_detail_top", full=False)

            html = await page.content()
            for needle in ("Provenance", "variant", "shape", "actor", "intent"):
                hit = needle.lower() in html.lower()
                findings.append(f"{slug} detail: '{needle}' present={hit}")

        await browser.close()

    print("\n=== FINDINGS ===")
    for line in findings:
        print(line)


if __name__ == "__main__":
    asyncio.run(main())
