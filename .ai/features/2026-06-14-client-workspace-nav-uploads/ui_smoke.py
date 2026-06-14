"""UI smoke: client-workspace nav redesign + upload detail/preview + clickable
data-table rows.

Captures:
  1. nav bar (3 domain groups) with the BOM dropdown open (Đề xuất nested)
  2. nav bar with the Hải quan dropdown open (BCCT + Tờ khai)
  3. BCCT list — whole-row click-to-detail
  4. Uploads list — uploader column + localized status badges + clickable rows
  5. Upload detail — full metadata + first-rows file preview

Inserts a throwaway upload (real xlsx blob) so the detail/preview render
deterministically, then cleans it up. Run with the dev server up on :8754
(local-socket DB):
    uv run python .ai/features/2026-06-14-client-workspace-nav-uploads/ui_smoke.py
"""
from __future__ import annotations

import asyncio
import io
import sys
import uuid
from pathlib import Path

from playwright.async_api import async_playwright

# Feature folder is .ai/features/<slug>/ → repo root is parents[3].
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import openpyxl  # noqa: E402

from app.database import connect  # noqa: E402
from app.storage import get_backend  # noqa: E402

BASE = "http://127.0.0.1:8754"
EMAIL = "admin@data-hub.local"
PASSWORD = "admin123"
CLIENT = "growatt-vn"
OUT = Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def _xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Danh mục NVL"
    ws.append(["Mã vật tư", "Tên hàng", "ĐVT", "Số lượng"])
    for i in range(1, 30):
        ws.append([f"NVL-{i:04d}", f"Linh kiện mẫu {i}", "PCS", i * 3])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _insert() -> str:
    stored = get_backend().put(_xlsx(), key=f"test_uploads/smoke_{uuid.uuid4().hex}.xlsx")
    uid = "up_smoke_" + uuid.uuid4().hex[:12]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """insert into hub.file_uploads
               (upload_id, client_id, module, original_filename, stored_path,
                storage_backend, content_sha256, size_bytes, mime_type,
                parse_status, row_count, result)
               values (%s,%s,'materials','danh_muc_nvl.xlsx',%s,%s,%s,%s,
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                       'done',29,'{"inserted":29,"updated":0}')""",
            (uid, CLIENT, stored.path, stored.backend, stored.content_sha256,
             stored.size_bytes))
    return uid


def _cleanup(uid: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select stored_path from hub.file_uploads where upload_id=%s", (uid,))
        row = cur.fetchone()
        cur.execute("delete from hub.file_uploads where upload_id=%s", (uid,))
    if row and row[0]:
        try:
            get_backend().delete(row[0])
        except Exception:
            pass


async def main() -> None:
    uid = _insert()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
            await ctx.add_cookies([{"name": "data_hub_lang", "value": "vi", "url": BASE}])
            page = await ctx.new_page()
            await page.goto(f"{BASE}/login")
            await page.fill('input[name="email"]', EMAIL)
            await page.fill('input[name="password"]', PASSWORD)
            await page.click('button[type="submit"]')
            await page.wait_for_url(f"{BASE}/clients", timeout=8000)

            await page.goto(f"{BASE}/clients/{CLIENT}/bcct")
            await page.wait_for_load_state("networkidle")

            # Nav dropdowns (clipped to the bar for legibility).
            await page.click('details.nav-menu summary:text-is("BOM")')
            await page.wait_for_timeout(250)
            await page.screenshot(path=str(OUT / "01_nav_bom_open.png"),
                                  clip={"x": 0, "y": 70, "width": 1280, "height": 330})
            await page.click('details.nav-menu summary:text-is("Hải quan")')
            await page.wait_for_timeout(250)
            await page.screenshot(path=str(OUT / "02_nav_customs_open.png"),
                                  clip={"x": 0, "y": 70, "width": 1280, "height": 330})

            # BCCT list — clickable rows.
            await page.keyboard.press("Escape")
            await page.screenshot(path=str(OUT / "03_bcct_rows.png"), full_page=True)

            # Uploads list — uploader column + clickable rows.
            await page.goto(f"{BASE}/clients/{CLIENT}/uploads")
            await page.wait_for_load_state("networkidle")
            await page.screenshot(path=str(OUT / "04_uploads_list.png"), full_page=True)

            # Upload detail — metadata + file preview.
            await page.goto(f"{BASE}/clients/{CLIENT}/uploads/{uid}")
            await page.wait_for_load_state("networkidle")
            await page.screenshot(path=str(OUT / "05_upload_detail.png"), full_page=True)

            await browser.close()
            print(f"saved 5 screenshots to {OUT}")
    finally:
        _cleanup(uid)


if __name__ == "__main__":
    asyncio.run(main())
