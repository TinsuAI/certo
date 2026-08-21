"""UI smoke for bulk declaration ZIP upload.

Drives the new flow end-to-end in a real browser against
http://127.0.0.1:8754 and captures four screenshots:

  01_upload_form_with_zip_tab.png  — upload page, bulk tab active
  02_preview_with_summary.png      — preview after staging a 4-file ZIP
                                     (2 OK · 1 mismatch · 1 parse_error)
  03_after_confirm.png             — declarations index with toast
                                     "Đã thêm 2 file mới, 1 sai khớp …"
  04_invalid_zip_rejected.png      — upload page with the error toast
                                     from posting non-ZIP bytes

Uses a throwaway client `bulk-zip-demo-vn` so counts are deterministic.
Client is created at the start and DB rows are cleaned at the end.

Run with the dev server up on :8754.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import zipfile
from pathlib import Path

# Allow running directly from feature folder.
sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[3]))

import xlwt
from playwright.async_api import async_playwright

from app.database import connect
from app.routes.clients import upsert_client


BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT_ID = "bulk-zip-demo-vn"

OUT = Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def _make_xls(decl_no: str) -> bytes:
    wb = xlwt.Workbook()
    ws = wb.add_sheet("TKN")
    ws.write(3, 4, decl_no)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_demo_zip() -> bytes:
    """2 OK + 1 mismatch + 1 parse_error + 1 ignored (README)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "00000001_107900100001.xls", _make_xls("107900100001"),
        )
        zf.writestr(
            "00000002_107900100002.xls", _make_xls("107900100002"),
        )
        # mismatch: filename says one number, content has another
        zf.writestr(
            "00000003_107900100003.xls", _make_xls("999999999999"),
        )
        # parse_error: filename matches pattern, content is junk
        zf.writestr(
            "00000004_107900100004.xls", b"this is not a valid XLS file",
        )
        # ignored (does not match supported filename pattern)
        zf.writestr("README.txt", b"explanation")
    return buf.getvalue()


def _setup_client() -> None:
    upsert_client(
        client_id=CLIENT_ID, name="Bulk ZIP Demo",
        tax_code=None, code_resolution_mode="identity",
        bom_proposal_mode="manual", bom_proposal_qty_tolerance_pct=5.0,
        bom_approver_tier="edit", status="active", notes=None,
    )


def _cleanup_client() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.customs_declaration_files where client_id=%s",
            (CLIENT_ID,),
        )
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT_ID,))


async def capture(page, slug: str) -> None:
    out = OUT / f"{slug}.png"
    await page.screenshot(path=str(out), full_page=True)
    print(f"  saved {out.relative_to(Path.cwd())}")


async def main() -> None:
    _setup_client()
    print(f"client {CLIENT_ID} created")
    zip_bytes = _make_demo_zip()
    print(f"demo zip: {len(zip_bytes)} bytes")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
            )
            await context.add_cookies([
                {"name": "data_hub_theme", "value": "light", "url": BASE},
                {"name": "data_hub_lang", "value": "vi", "url": BASE},
            ])
            page = await context.new_page()
            await page.goto(f"{BASE}/login")
            await page.fill('input[name="email"]', EMAIL)
            await page.fill('input[name="password"]', PASSWORD)
            await page.click('button[type="submit"]')
            await page.wait_for_url(f"{BASE}/clients", timeout=5000)

            # ── 1. Upload form, bulk tab activated ─────────────────────
            await page.goto(
                f"{BASE}/clients/{CLIENT_ID}/declarations/upload#bulk",
            )
            await page.wait_for_load_state("networkidle")
            await page.click("#tab-bulk")
            await capture(page, "01_upload_form_with_zip_tab")

            # ── 2. Submit ZIP → preview ────────────────────────────────
            # Scope selectors to #panel-bulk: both panels share
            # input[name="file"] / select[name="direction"], so an
            # un-scoped selector hits the single-file form first.
            await page.set_input_files(
                '#panel-bulk input[name="file"]',
                files=[{
                    "name": "demo.zip",
                    "mimeType": "application/zip",
                    "buffer": zip_bytes,
                }],
            )
            await page.select_option(
                '#panel-bulk select[name="direction"]', "import",
            )
            await page.click('#panel-bulk button[type="submit"]')
            await page.wait_for_url(
                "**/declarations/upload-zip", timeout=15000,
            )
            await page.wait_for_load_state("networkidle")
            await capture(page, "02_preview_with_summary")

            # ── 3. Confirm commit → declarations index with toast ──────
            await page.click('button:has-text("Xác nhận tải lên")')
            await page.wait_for_url(
                "**/declarations?**bulk_inserted**", timeout=15000,
            )
            await page.wait_for_load_state("networkidle")
            await capture(page, "03_after_confirm")

            # ── 4. Invalid ZIP → upload page with error toast ──────────
            await page.goto(
                f"{BASE}/clients/{CLIENT_ID}/declarations/upload#bulk",
            )
            await page.click("#tab-bulk")
            await page.set_input_files(
                '#panel-bulk input[name="file"]',
                files=[{
                    "name": "bad.zip",
                    "mimeType": "application/zip",
                    "buffer": b"these bytes are definitely not a zip",
                }],
            )
            await page.select_option(
                '#panel-bulk select[name="direction"]', "import",
            )
            await page.click('#panel-bulk button[type="submit"]')
            await page.wait_for_url(
                "**/declarations/upload?error=**", timeout=15000,
            )
            await page.wait_for_load_state("networkidle")
            # Re-activate bulk tab so the error toast appears above the
            # bulk form rather than the single-file form.
            await page.click("#tab-bulk")
            await capture(page, "04_invalid_zip_rejected")

            await browser.close()
    finally:
        _cleanup_client()
        print(f"client {CLIENT_ID} cleaned up")


if __name__ == "__main__":
    asyncio.run(main())
