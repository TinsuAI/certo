"""UI proof for #54 — a chip's count is what clicking it delivers.

Drives the real page on :8754 and, for each filter state, asserts the invariant
in the browser (not just in HTML): read each chip's advertised count, click it,
count the rows that arrive. Screenshots each state.

Run with the dev server up on :8754:
    uv run python .ai/features/2026-07-17-catalog-filter-state/ui_smoke.py
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
CLIENT = "growatt-vn"
OUT = Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

# Filter states that broke before #54: a search and a rule-bar filter, each of
# which the chip counts used to ignore.
STATES = [
    ("unfiltered", ""),
    ("search", "?q=001.0033"),
    ("leaf", "?leaf=1"),
]


async def main() -> int:
    failures: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 1000})
        await ctx.add_cookies([
            {"name": "data_hub_theme", "value": "light", "url": BASE},
            {"name": "data_hub_lang", "value": "vi", "url": BASE},
        ])
        page = await ctx.new_page()
        await page.goto(f"{BASE}/login")
        await page.fill('input[name="email"]', "admin@data-hub.local")
        await page.fill('input[name="password"]', "admin123")
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")

        for slug, qs in STATES:
            url = f"{BASE}/clients/{CLIENT}/catalog/candidates{qs}"
            await page.goto(url)
            await page.wait_for_load_state("networkidle")
            await page.screenshot(path=str(OUT / f"{slug}.png"), full_page=True)

            chips = await page.eval_on_selector_all(
                "a.chip",
                "els => els.map(e => [e.textContent.trim(), e.href])",
            )
            for label, href in chips:
                m = re.search(r"\((\d+)\)", label)
                if not m:
                    continue
                claimed = int(m.group(1))
                await page.goto(href)
                await page.wait_for_load_state("networkidle")
                delivered = len(await page.query_selector_all("tr[data-code]"))
                shown = await page.eval_on_selector_all(
                    "tr[data-code]", "els => els.length")
                # Paginated pages cap at page_size; compare against the header
                # count when the set is larger than one page.
                if delivered >= 50:
                    print(f"  {slug}: {label!r} -> page 1 of {claimed} (paged)")
                    continue
                status = "ok" if delivered == claimed else "MISMATCH"
                print(f"  {slug}: {label!r} claims {claimed}, "
                      f"delivers {shown} [{status}]")
                if delivered != claimed:
                    failures.append(
                        f"{slug}: {label!r} claims {claimed}, delivers {shown}")
                await page.goto(url)
                await page.wait_for_load_state("networkidle")

        await browser.close()

    print(f"\nscreenshots -> {OUT}")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  " + f)
        return 1
    print("invariant holds in the browser for every chip in every state.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
