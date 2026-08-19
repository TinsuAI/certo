"""UI smoke for the 2026-08 redesign — logs into the running Data Hub dev
server and screenshots the shell on the pages Phase A touched.

Run: uv run python .ai/features/2026-08-20-ui-redesign/ui_smoke.py
The dev server must already be up on http://127.0.0.1:8754.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "screenshots"
BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT = "demo-furniture"

PAGES = [
    ("clients-list", "/clients"),
    ("client-overview", f"/clients/{CLIENT}"),
    ("client-catalog", f"/clients/{CLIENT}/catalog"),
    ("client-bcct", f"/clients/{CLIENT}/bcct"),
    ("client-bom", f"/clients/{CLIENT}/bom"),
    ("client-config", f"/clients/{CLIENT}/edit"),
    ("admin-users", "/admin/users"),
    ("admin-uom", "/admin/uom"),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        # The dev box has no route to Google Fonts; without this the load
        # event never fires and every goto() times out at 30s.
        page.route("**://fonts.googleapis.com/**", lambda r: r.abort())
        page.route("**://fonts.gstatic.com/**", lambda r: r.abort())
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.fill('input[name="email"]', EMAIL)
        page.fill('input[name="password"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_load_state("domcontentloaded")
        failed = []
        for name, path in PAGES:
            resp = page.goto(f"{BASE}{path}", wait_until="domcontentloaded")
            page.wait_for_load_state("domcontentloaded")
            if resp is None or resp.status >= 400:
                failed.append((path, resp.status if resp else "no response"))
            page.screenshot(path=str(OUT / f"{name}.png"))
            print(f"{path} -> {resp.status if resp else '?'}")
        browser.close()
    if failed:
        print("FAILED:", failed)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
