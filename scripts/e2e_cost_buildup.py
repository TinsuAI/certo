"""End-to-end test of the cost-buildup UI: login via Data Hub, open a CO case,
fill the cost-buildup inputs, take screenshots.

Uses the Playwright CLI's bundled chromium via the playwright Python package
(not currently installed in the project venv) — fallback to invoking the CLI
through `playwright codegen`/`playwright open` is impractical here, so we
import via the user-level install at /home/vp/.local/bin/playwright.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Ensure user-level playwright lib is importable.
USER_SITE = Path.home() / ".local/lib"
for candidate in USER_SITE.glob("python*/site-packages"):
    sys.path.insert(0, str(candidate))

from playwright.async_api import async_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / ".ai/screenshots/cost-buildup-ui"
SHOTS.mkdir(parents=True, exist_ok=True)

CO_BASE = os.environ.get("CO_BASE", "http://127.0.0.1:8001")
DATA_HUB_BASE = os.environ.get("DATA_HUB_BASE", "http://127.0.0.1:8754")
EMAIL = os.environ.get("DATA_HUB_EMAIL", "admin@data-hub.local")
PASSWORD = os.environ.get("DATA_HUB_PASSWORD", "local_test_password")
CASE_URL = os.environ.get(
    "CO_CASE_URL",
    f"{CO_BASE}/clients/growatt/co-case/co-case-b1e2602f0d8d/origin",
)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page = await ctx.new_page()

        # 1) Navigate to a protected CO URL → redirects to Data Hub login.
        await page.goto(CASE_URL, wait_until="domcontentloaded")
        print(f"[1] Landed at: {page.url}")

        # 2) Fill the Data Hub login form (if we ended up there).
        if "login" in page.url:
            await page.fill('input[name="email"]', EMAIL)
            await page.fill('input[name="password"]', PASSWORD)
            await page.click('button[type="submit"]')
            await page.wait_for_load_state("networkidle")
            print(f"[2] After login: {page.url}")

        # 3) Wait until we land on the case origin tab (callback consumes the
        # one-shot OAuth code, then 303-redirects to the target case URL).
        try:
            await page.wait_for_url("**/co-case/**", timeout=10000)
        except Exception:
            pass
        print(f"[3] Final URL: {page.url}")

        # Wait for cost-buildup block.
        try:
            await page.wait_for_selector(".cost-buildup-block", timeout=10000, state="attached")
        except Exception as exc:
            print(f"[!] cost-buildup block not found within 10s: {exc}")
            html_dump = SHOTS / "e2e-dump.html"
            html_dump.write_text(await page.content(), encoding="utf-8")
            print(f"[!] Saved page HTML to {html_dump}")
            await page.screenshot(path=str(SHOTS / "e2e-debug.png"), full_page=True)
            await browser.close()
            return

        # Dump HTML for debug.
        (SHOTS / "e2e-dump.html").write_text(await page.content(), encoding="utf-8")
        # Ensure the <details> is open (in case product isn't LVC-flagged).
        await page.evaluate(
            "document.querySelectorAll('details.cost-buildup-block').forEach(el => el.open = true)"
        )
        await page.wait_for_timeout(200)
        # 4) Screenshot 1: state on load.
        await page.locator(".cost-buildup-block").first.scroll_into_view_if_needed()
        await page.screenshot(path=str(SHOTS / "e2e-01-loaded.png"), full_page=False)
        print(f"[4] Saved e2e-01-loaded.png")

        # 5) Fill the 4 inputs.
        inputs = {
            "labor":    "350.00",
            "overhead": "880.00",
            "profit":   "3680.00",
            "other":    "40.00",
        }
        for key, value in inputs.items():
            sel = f'input[name$="_cost_buildup_{key}"]'
            await page.fill(sel, value)
        await page.locator("body").click()  # blur to trigger recompute
        await page.wait_for_timeout(300)

        # 6) Screenshot 2: after fill (hint should be green-OK).
        await page.locator(".cost-buildup-block").first.scroll_into_view_if_needed()
        await page.screenshot(path=str(SHOTS / "e2e-02-filled.png"), full_page=False)
        print(f"[6] Saved e2e-02-filled.png")

        # 7) Force a warning state (sum > FOB).
        for key in inputs:
            await page.fill(f'input[name$="_cost_buildup_{key}"]', "2000")
        await page.locator("body").click()
        await page.wait_for_timeout(300)
        await page.locator(".cost-buildup-block").first.scroll_into_view_if_needed()
        await page.screenshot(path=str(SHOTS / "e2e-03-warning.png"), full_page=False)
        print(f"[7] Saved e2e-03-warning.png")

        await browser.close()
        print("[done]")


if __name__ == "__main__":
    asyncio.run(main())
