"""End-to-end test of the cost-allocation feature:
  1. Login via Data Hub SSO.
  2. Navigate to /clients/growatt/cost-allocation (admin page).
  3. Upload the GROWATT sample spreadsheet, screenshot the diff banner.
  4. Open a case origin page known to have LVC/RVC products.
  5. Click "Áp hệ số" on one product, screenshot the populated 6-input grid.
  6. Hit the resolve endpoint directly to confirm JSON shape.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

USER_SITE = Path.home() / ".local/lib"
for candidate in USER_SITE.glob("python*/site-packages"):
    sys.path.insert(0, str(candidate))

from playwright.async_api import async_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / ".ai/screenshots/cost-allocation"
SHOTS.mkdir(parents=True, exist_ok=True)

CO_BASE = os.environ.get("CO_BASE", "http://127.0.0.1:8001")
EMAIL = os.environ.get("DATA_HUB_EMAIL", "admin@data-hub.local")
PASSWORD = os.environ.get("DATA_HUB_PASSWORD", "local_test_password")
SAMPLE = ROOT / ".ai/samples/BANG-PHAN-BO-TY-LE-CHI-PHI.xlsx"
CASE_URL = os.environ.get(
    "CO_CASE_URL",
    f"{CO_BASE}/clients/growatt/co-case/co-case-b1e2602f0d8d/origin",
)


async def login(page):
    if "login" in page.url:
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")


async def main() -> None:
    if not SAMPLE.exists():
        raise SystemExit(f"Sample file missing: {SAMPLE}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()

        # 1) Login by visiting the admin page.
        admin_url = f"{CO_BASE}/clients/growatt/cost-allocation"
        await page.goto(admin_url, wait_until="domcontentloaded")
        await login(page)
        # Login redirects through /auth/callback then back to the admin URL.
        # If the callback finished but didn't bounce us all the way, push the URL again.
        if "cost-allocation" not in page.url:
            await page.goto(admin_url, wait_until="domcontentloaded")
        await page.wait_for_selector('form[action$="/cost-allocation/upload"]', timeout=10_000)
        print(f"[1] Admin page reached: {page.url}")
        await page.screenshot(path=str(SHOTS / "1-admin-empty.png"), full_page=True)

        # 2) Upload the sample.
        file_input = page.locator('input[type="file"][name="file"]')
        await file_input.set_input_files(str(SAMPLE))
        await page.locator('form[action$="/cost-allocation/upload"] button[type="submit"]').click()
        await page.wait_for_load_state("networkidle")
        print(f"[2] After upload: {page.url}")
        await page.screenshot(path=str(SHOTS / "2-admin-after-upload.png"), full_page=True)

        # Confirm 24 rows visible.
        body = await page.content()
        assert "Đã import 24 dòng" in body, "upload diff banner missing"
        assert "PV00.0048400" in body, "expected GROWATT mã SP missing"
        print("[2] Diff banner + 24 rows confirmed.")

        # 3) Resolve endpoint sanity — hit JSON directly through the same cookie jar.
        api = await ctx.request.get(
            f"{CO_BASE}/clients/growatt/cost-allocation/resolve",
            params={"product_code": "PV00.0048400", "fob": "1000"},
        )
        body = await api.json()
        print(f"[3] /resolve response: {json.dumps(body, indent=2, ensure_ascii=False)}")
        assert body["found"] is True
        assert body["matched_mode"] == "A"

        # 4) Open the case origin.
        await page.goto(CASE_URL, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector("[data-cost-buildup-apply]", timeout=10_000)
            print("[4] Cost-buildup apply button rendered on origin page.")
        except Exception as exc:
            print(f"[4] No apply button found ({exc}); may be no LVC/RVC product on this case.")
            await page.screenshot(path=str(SHOTS / "3-origin-no-apply-button.png"), full_page=True)
            await browser.close()
            return

        await page.screenshot(path=str(SHOTS / "3-origin-before-apply.png"), full_page=True)

        # 5) Click the first Áp hệ số button.
        btn = page.locator("[data-cost-buildup-apply]").first
        product_code = await btn.get_attribute("data-product-code")
        print(f"[5] Clicking Áp hệ số for {product_code}")
        # Dismiss the confirm() dialog if it pops (no existing values expected).
        page.on("dialog", lambda dlg: asyncio.create_task(dlg.accept()))
        await btn.click()
        # Wait for status text to update.
        await page.wait_for_function(
            "() => document.querySelector('[data-cost-buildup-apply-status]').textContent.trim().length > 0",
            timeout=5000,
        )
        status_text = await page.locator("[data-cost-buildup-apply-status]").first.text_content()
        print(f"[5] Status: {status_text}")
        await page.screenshot(path=str(SHOTS / "4-origin-after-apply.png"), full_page=True)

        # 6) Inspect populated inputs.
        for key in ("wages", "welfare", "rent", "depreciation", "other_mfg", "transport_storage"):
            sel = f'input[name$="cost_buildup_{key}"]'
            val = await page.locator(sel).first.input_value()
            print(f"    {key} = {val}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
