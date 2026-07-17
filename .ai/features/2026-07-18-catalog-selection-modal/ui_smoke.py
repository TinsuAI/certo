"""UI proof for #55 — per-row selection + single-row accept dialog.

Drives the real page on :8754: verifies the approve button tracks the
selection, the "select all matching" banner appears when the page is fully
checked and sets the flag, and the row «Duyệt» opens a modal prefilled from
the row. Screenshots each state. Read-only — no code is approved (the dialog
and the approve button are photographed, never submitted).

Run with the dev server up on :8754:
    uv run python .ai/features/2026-07-18-catalog-selection-modal/ui_smoke.py
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8754"
CLIENT = "growatt-vn"
EMAIL = os.environ.get("DATA_HUB_SEED_EMAIL", "admin@data-hub.local")
PASSWORD = os.environ.get("DATA_HUB_SEED_PASSWORD", "admin123")
OUT = Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


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
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        await page.goto(f"{BASE}/clients/{CLIENT}/catalog/candidates")
        await page.wait_for_load_state("networkidle")

        btn = page.locator("#bulk-approve-btn")

        # 1. Nothing selected → button disabled, "Chọn mã để duyệt".
        await page.screenshot(path=str(OUT / "1_none_selected.png"),
                              full_page=True)
        if not await btn.is_disabled():
            failures.append("approve button should start disabled")
        label0 = (await btn.text_content()).strip()
        print(f"  none selected: {label0!r}, disabled={await btn.is_disabled()}")

        # 2. Check three rows → "Duyệt 3 mã đã chọn", enabled.
        rows = page.locator(".row-check")
        for i in range(3):
            await rows.nth(i).check()
        await page.wait_for_timeout(150)
        label3 = (await btn.text_content()).strip()
        print(f"  3 checked: {label3!r}")
        if "3" not in label3:
            failures.append(f"expected '3' in button label, got {label3!r}")
        await page.screenshot(path=str(OUT / "2_three_selected.png"),
                              full_page=True)

        # 3. Select the whole page → banner offers "select all matching".
        await page.locator("#select-page").check()
        await page.wait_for_timeout(150)
        banner = page.locator("#bulk-select-banner")
        banner_visible = await banner.is_visible()
        print(f"  page selected: banner visible={banner_visible}, "
              f"btn={(await btn.text_content()).strip()!r}")
        if not banner_visible:
            failures.append("select-all-matching banner should show on full page")
        await page.screenshot(path=str(OUT / "3_page_selected_banner.png"),
                              full_page=True)

        # 4. Click "select all matching" → flag set, label switches to full set.
        await page.locator("#select-all-matching-link").click()
        await page.wait_for_timeout(150)
        flag = await page.locator("#select-all-matching").input_value()
        label_all = (await btn.text_content()).strip()
        print(f"  select-all-matching: flag={flag!r}, btn={label_all!r}")
        if flag != "1":
            failures.append("select-all-matching flag not set")
        if "111" not in label_all:
            failures.append(f"expected total 111 in label, got {label_all!r}")
        await page.screenshot(path=str(OUT / "4_all_matching.png"),
                              full_page=True)

        # 5. Clear, then open the single-row accept dialog.
        await page.locator("#clear-select-all").click()
        await page.wait_for_timeout(100)
        await page.locator(".js-accept-open").first.click()
        await page.wait_for_timeout(150)
        dialog = page.locator("#accept-dialog")
        dlg_open = await dialog.evaluate("d => d.open")
        code_in = await page.locator("#ad-code-input").input_value()
        name_in = await page.locator("#ad-name").input_value()
        print(f"  dialog open={dlg_open}, code={code_in!r}, "
              f"name={name_in[:30]!r}")
        if not dlg_open:
            failures.append("accept dialog did not open")
        if not code_in:
            failures.append("dialog code not prefilled")
        await page.screenshot(path=str(OUT / "5_accept_dialog.png"))

        await browser.close()

    print(f"\nscreenshots -> {OUT}")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  " + f)
        return 1
    print("selection + dialog behave in the browser.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
