"""Playwright screenshots for the BCCT mapping-flow overhaul (2026-06-05).

Captures the full flow:
  01 upload page
  02 mapping page (non-standard header → manual map; auto-guess count +
     'cần chọn' flag + scrollable preview)
  03 clean preview (standard headers auto-mapped → straight to Diff)
  04 anomaly preview (price-column inversion → hard gate + ack)
  05 admin per-client column-alias config

Bypasses login with a direct session cookie. Self-contained: sets up a
throwaway client + sample alias, captures, cleans up. Dev server must be
running on :8754.
"""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import httpx
from openpyxl import Workbook
from playwright.async_api import async_playwright

from app.auth.session import SESSION_COOKIE, create_session
from app.database import connect

BASE = "http://127.0.0.1:8754"
CLIENT = "shots-mapping"
ADMIN = "u_31151f0497094109"  # admin@data-hub.local (role=dev)
OUT = Path(".ai/features/2026-06-05-bcct-mapping-flow-overhaul/screenshots")
OUT.mkdir(parents=True, exist_ok=True)


def _xlsx(rows) -> bytes:
    wb = Workbook(); ws = wb.active; ws.title = "BCCT"
    for r in rows:
        ws.append(r)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def _write(path: str, blob: bytes):
    Path(path).write_bytes(blob)
    return path


def _db_setup():
    with connect() as c, c.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s,%s) "
            "on conflict (client_id) do nothing", (CLIENT, "Screenshot Mapping Co"))
        cur.execute(
            "insert into hub.client_column_aliases "
            "(client_id, module, field, alias, enabled, created_by) "
            "values (%s,'bcct','customs_code','Mã Cty XYZ',true,%s) "
            "on conflict do nothing", (CLIENT, ADMIN))


def _db_stash_anomaly() -> str:
    pid = "shots_anom_pending"
    rows = [{
        "transaction_key": f"SHOT_{i}", "line_no": "1",
        "declaration_no": f"30849019{i:04d}", "declaration_type": "E42",
        "direction": "export", "registration_date": "2026-05-18",
        "customs_code": f"MFW0506-{i}", "goods_name": "Ghế tập đẩy tạ",
        "currency_nt": "EUR", "exchange_rate": 30377.72,
        "unit_price": 380.7, "unit_price_nt": 10136289.92,  # swapped!
        "total_value": 5111658.94, "total_value_nt": 168.27,
    } for i in range(1, 6)]
    summary = {"new": len(rows), "noop": 0, "diff": [], "orphan": [],
               "total": len(rows)}
    with connect() as c, c.cursor() as cur:
        cur.execute(
            "insert into hub.file_uploads (upload_id, client_id, module, "
            "original_filename, stored_path, content_sha256, size_bytes, "
            "uploader_user_id) values ('shots_upl',%s,'bcct','tk.xlsx',"
            "'/tmp/tk.xlsx','sha',1,%s) on conflict (upload_id) do nothing",
            (CLIENT, ADMIN))
        cur.execute(
            "insert into hub.upload_pending (pending_id, client_id, module, "
            "upload_id, parsed_rows, diff_summary, created_by, expires_at) "
            "values (%s,%s,'bcct','shots_upl',%s::jsonb,%s::jsonb,%s, "
            "now()+interval '1 day') on conflict (pending_id) do update set "
            "parsed_rows=excluded.parsed_rows, diff_summary=excluded.diff_summary",
            (pid, CLIENT, json.dumps(rows), json.dumps(summary), ADMIN))
    return pid


def _db_cleanup():
    with connect() as c, c.cursor() as cur:
        for t in ("upload_pending", "file_uploads", "bcct_rows",
                  "client_column_aliases"):
            cur.execute(f"delete from hub.{t} where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


async def _shot(page, slug):
    await page.wait_for_timeout(400)
    out = OUT / f"{slug}.png"
    await page.screenshot(path=str(out), full_page=True)
    print(f"  saved {out}")


def _upload_get_location(sid: str, blob: bytes) -> str:
    """POST a BCCT upload server-side; return the redirect Location (the
    mapping or preview URL). Decouples screenshotting from browser form
    mechanics."""
    r = httpx.post(
        f"{BASE}/clients/{CLIENT}/bcct/upload",
        cookies={SESSION_COOKIE: sid},
        files={"file": ("t.xlsx", blob,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False, timeout=30,
    )
    assert r.status_code == 303, f"upload failed: {r.status_code} {r.text[:200]}"
    return r.headers["location"]


async def main():
    _db_setup()
    sid = create_session(ADMIN)
    anom_pid = _db_stash_anomaly()

    # Server-side uploads → grab the mapping/preview URLs to screenshot.
    mapping_url = _upload_get_location(sid, _xlsx([
        ("Số tờ khai", "Ngày đăng ký", "Mã Cty Lạ", "Tên hàng", "Đơn giá",
         "Đơn giá tính thuế", "Nguyên tệ", "Tỷ giá"),
        ("308400001", "2026-05-18", "PE-1", "Polyethylene", 380.7,
         11564000, "EUR", 30377),
    ]))
    preview_url = _upload_get_location(sid, _xlsx([
        ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký", "Mã NPL/SP",
         "Tên hàng", "Tổng số lượng", "ĐVT", "Trị giá", "Nguyên tệ"),
        ("308400002", 1, "E11", "2026-05-18", "PE-CLEAN", "Polyethylene",
         100.0, "kg", 250.0, "USD"),
    ]))
    print("  mapping_url ->", mapping_url)
    print("  preview_url ->", preview_url)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
            await ctx.add_cookies([
                {"name": SESSION_COOKIE, "value": sid, "url": BASE},
                {"name": "data_hub_lang", "value": "vi", "url": BASE},
            ])
            page = await ctx.new_page()

            await page.goto(f"{BASE}/clients/{CLIENT}/bcct/upload")
            await _shot(page, "01_bcct_upload")

            await page.goto(f"{BASE}{mapping_url}")
            await _shot(page, "02_mapping_page")

            await page.goto(f"{BASE}{preview_url}")
            await _shot(page, "03_preview_clean")

            await page.goto(f"{BASE}/clients/{CLIENT}/bcct/upload/preview/{anom_pid}")
            await _shot(page, "04_preview_anomaly")

            await page.goto(f"{BASE}/clients/{CLIENT}/column-aliases?module=bcct")
            await _shot(page, "05_column_aliases")

            await browser.close()
    finally:
        _db_cleanup()


if __name__ == "__main__":
    asyncio.run(main())
