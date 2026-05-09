"""Track C UoM drift gate — capture screenshot of preview banner.

Stages a synthetic upload_pending row with cross-family drift on
Growatt catalog codes (PV01.0105100 = PIECES, 001.0001100 = ST), then
visits the BOM preview URL with a logged-in browser.
"""
from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from playwright.async_api import async_playwright


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT_ID = "growatt-vn"

OUT = Path(".ai/features/2026-05-10-bom-vocab-3shape-uom-gate/screenshots")


def stash_pending() -> str:
    pending_id = secrets.token_urlsafe(16)
    parsed = {"products": {"DEMO_DRIFT": [
        {"material_code": "PV01.0105100", "qty_per_unit": 1.0, "uom": "kg"},
        {"material_code": "001.0001100", "qty_per_unit": 2.0, "uom": "g"},
    ]}}
    conn = psycopg.connect("host=/var/run/postgresql user=vp dbname=data_hub")
    with conn.cursor() as cur:
        cur.execute(
            "insert into hub.upload_pending (pending_id, client_id, "
            "module, parsed_rows, diff_summary, expires_at) "
            "values (%s, %s, 'bom', %s::jsonb, %s::jsonb, %s)",
            (pending_id, CLIENT_ID, json.dumps(parsed),
             '{"profile":"manual_flat"}',
             datetime.now(timezone.utc) + timedelta(hours=1)),
        )
        conn.commit()
    conn.close()
    return pending_id


def cleanup_pending(pid: str):
    conn = psycopg.connect("host=/var/run/postgresql user=vp dbname=data_hub")
    with conn.cursor() as cur:
        cur.execute("delete from hub.upload_pending where pending_id=%s",
                    (pid,))
        conn.commit()
    conn.close()


async def main():
    pid = stash_pending()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900})
            page = await context.new_page()
            await page.goto(f"{BASE}/login")
            await page.fill('input[name="email"]', EMAIL)
            await page.fill('input[name="password"]', PASSWORD)
            await page.click('button[type="submit"]')
            await page.wait_for_url(f"{BASE}/clients", timeout=5000)
            await page.goto(
                f"{BASE}/clients/{CLIENT_ID}/bom/preview/{pid}")
            await page.wait_for_load_state("networkidle")
            out = OUT / "05_uom_drift_banner.png"
            await page.screenshot(path=str(out), full_page=True)
            print(f"saved {out}")
            await browser.close()
    finally:
        cleanup_pending(pid)


if __name__ == "__main__":
    asyncio.run(main())
