"""Playwright shots for the BOM ingest follow-ups (backlog B). Drives the
live dev server on :8754.

  - multi-role warning panel in BOM preview (B.2.5)
  - friendly parse-error page on a garbage upload (B.3)
  - ambiguous file (Level column) resolving to the tree-aware adapter via
    detect/match_score ranking (B.1.5) — visible as `profile` in preview
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

import openpyxl
from playwright.async_api import async_playwright

from hub.app.database import connect
from hub.app.auth.session import create_session, hash_password, SESSION_COOKIE

BASE = "http://127.0.0.1:8754"
OUT = Path(".ai/features/2026-06-07-bom-ingest-followups/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

CLIENT = "bomshot-vn"
UID = "u_bomshot"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _sheet_per_product_with_exported(blob_code: str) -> bytes:
    """Layout: sheet title = product; rows = NPL. One component code is
    one that we also seed as EXPORTED in BCCT → multi-role warning."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ROOT-MR-01"
    ws.append(("Mã NVL", "Định mức", "ĐVT"))
    ws.append((blob_code, 2, "pcs"))
    ws.append(("PLAIN-NVL-1", 1, "kg"))
    ws.append(("PLAIN-NVL-2", 0.5, "m"))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _ambiguous_with_level() -> bytes:
    """product+material+qty (manual_flat sees it) AND a Level column
    (sap_exploded_levels sees it). Pre-scoring, manual_flat would grab +
    flatten; with detect ranking the tree adapter wins."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BOM"
    ws.append(("Mã SP", "Mã NVL", "Level", "Định mức", "ĐVT"))
    ws.append(("TP-AMB-1", "TP-AMB-1", 1, 0, ""))
    ws.append(("TP-AMB-1", "CỤM-A", 2, 3, "kg"))
    ws.append(("TP-AMB-1", "NVL-A", 3, 2, "pcs"))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _db_setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s,%s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "BOM Shot Co."))
        cur.execute(
            "insert into hub.users (user_id,email,display_name,password_hash,role,status) "
            "values (%s,'bomshot@local','BOM Shooter',%s,'admin','active') "
            "on conflict (user_id) do update set role='admin',status='active'",
            (UID, hash_password("x")))
        # Seed an EXPORTED BCCT row so the upload's component is multi-role.
        cur.execute("delete from hub.bcct_rows where client_id=%s", (CLIENT,))
        for line in ("1", "2", "3"):
            cur.execute(
                "insert into hub.bcct_rows "
                "(client_id, transaction_key, line_no, declaration_no, "
                " declaration_type, direction, registration_date, "
                " customs_code, goods_name, payload) "
                "values (%s,%s,%s,%s,'B11','export','2026-02-01',"
                "        'EXP-COMP-9','exported finished good','{}'::jsonb)",
                (CLIENT, f"DEXP-{line}-{line}", line, f"DEXP-{line}"))


def _db_teardown():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.upload_pending where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.bcct_rows where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.file_uploads where uploader_user_id=%s", (UID,))
        cur.execute("delete from hub.sessions where user_id=%s", (UID,))
        cur.execute("delete from hub.users where user_id=%s", (UID,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


async def _upload_to_preview(page, blob: bytes, filename: str) -> str:
    resp = await page.request.post(
        f"{BASE}/clients/{CLIENT}/bom/upload",
        multipart={"profile": "auto",
                   "file": {"name": filename, "mimeType": XLSX_MIME,
                            "buffer": blob}},
        max_redirects=0)
    assert resp.status == 303, f"{resp.status}: {await resp.text()}"
    return resp.headers["location"]


async def shot(page, slug: str):
    await page.wait_for_timeout(350)
    out = OUT / f"{slug}.png"
    await page.screenshot(path=str(out), full_page=True)
    print(f"  saved {out}")


async def main():
    _db_setup()
    sid = create_session(UID)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1280, "height": 900})
            await context.add_cookies([
                {"name": SESSION_COOKIE, "value": sid, "url": BASE},
                {"name": "data_hub_lang", "value": "vi", "url": BASE},
                {"name": "data_hub_theme", "value": "light", "url": BASE},
            ])
            page = await context.new_page()

            # 1. multi-role warning (B.2.5)
            loc = await _upload_to_preview(
                page, _sheet_per_product_with_exported("EXP-COMP-9"),
                "ROOT-MR-01.xlsx")
            await page.goto(BASE + loc)
            await shot(page, "01_multirole_warning")

            # 2. detect ranking — ambiguous file → tree adapter (B.1.5)
            loc = await _upload_to_preview(
                page, _ambiguous_with_level(), "TP-AMB-1.xlsx")
            await page.goto(BASE + loc)
            await shot(page, "02_detect_ranking_sap_exploded")

            # 3. friendly parse-error page (B.3) — POST garbage, render the
            # actual 400 HTML body (styled via <base href> so the server's
            # stylesheet resolves).
            resp = await page.request.post(
                f"{BASE}/clients/{CLIENT}/bom/upload",
                multipart={"profile": "auto",
                           "file": {"name": "garbage.xlsx", "mimeType": XLSX_MIME,
                                    "buffer": b"definitely not a spreadsheet"}},
                max_redirects=0)
            assert resp.status == 400, resp.status
            html = (await resp.text()).replace(
                "<head>", f'<head><base href="{BASE}/">', 1)
            await page.set_content(html, wait_until="networkidle")
            await shot(page, "03_friendly_parse_error")

            await browser.close()
    finally:
        _db_teardown()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
