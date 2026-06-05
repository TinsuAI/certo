"""Playwright screenshots for the BCCT mapping-flow overhaul (2026-06-05).

Uses REAL johnson-vn BCCT rows (pulled from the DB) for every data-bearing
shot. Captures the full flow:
  01 upload page
  02 no-header mapping (header stripped → picker auto-selects "Không có
     header"; columns labelled "Cột N" by position)
  03 clean preview (standard headers auto-mapped → straight to Diff)
  04 anomaly preview (the two đơn-giá columns swapped → hard gate + ack)
  05 admin per-client column-alias config

Real values, throwaway client (clean diff), session-cookie auth, self
clean-up. Dev server must be running on :8754.
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

import httpx
from openpyxl import Workbook
from playwright.async_api import async_playwright

from app.auth.session import SESSION_COOKIE, create_session
from app.database import connect

BASE = "http://127.0.0.1:8754"
CLIENT = "shots-mapping"
ADMIN = "u_31151f0497094109"  # admin@data-hub.local
OUT = Path(".ai/features/2026-06-05-bcct-mapping-flow-overhaul/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

# Standard BCCT headers (alias-matched). Đơn giá = nguyên tệ (unit_price_nt),
# Đơn giá tính thuế = VND (unit_price).
HEADERS = ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký", "Mã NPL/SP",
           "Tên hàng", "Tổng số lượng", "ĐVT", "Tổng trị giá", "Đơn giá",
           "Đơn giá tính thuế", "Trị giá NT", "Nguyên tệ", "Tỷ giá")


def _real_rows() -> list[tuple]:
    with connect() as c, c.cursor() as cur:
        cur.execute("""
            select declaration_no, line_no, declaration_type, registration_date,
                   customs_code, goods_name, quantity, unit, total_value,
                   unit_price_nt, unit_price, total_value_nt, currency_nt, exchange_rate
            from hub.bcct_rows
            where client_id='johnson-vn' and currency_nt is not null
              and currency_nt not in ('VND','') and unit_price is not null
              and unit_price_nt is not null
            order by registration_date desc, line_no limit 8
        """)
        out = []
        for r in cur.fetchall():
            out.append(tuple("" if v is None else
                             (v.isoformat() if hasattr(v, "isoformat") else v)
                             for v in r))
        return out


def _xlsx(rows, *, header=True, swap_prices=False) -> bytes:
    wb = Workbook(); ws = wb.active; ws.title = "BCCT"
    if header:
        ws.append(list(HEADERS))
    for r in rows:
        r = list(r)
        if swap_prices:
            # swap "Đơn giá" (idx 9) <-> "Đơn giá tính thuế" (idx 10)
            r[9], r[10] = r[10], r[9]
        ws.append(r)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def _db_setup():
    with connect() as c, c.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s,%s) "
            "on conflict (client_id) do nothing", (CLIENT, "Screenshot Mapping Co"))
        cur.execute(
            "insert into hub.client_column_aliases "
            "(client_id, module, field, alias, enabled, created_by) "
            "values (%s,'bcct','goods_name','Diễn giải hàng hóa',true,%s) "
            "on conflict do nothing", (CLIENT, ADMIN))


def _db_cleanup():
    with connect() as c, c.cursor() as cur:
        for t in ("upload_pending", "file_uploads", "bcct_rows",
                  "client_column_aliases"):
            cur.execute(f"delete from hub.{t} where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _upload(sid: str, blob: bytes) -> str:
    r = httpx.post(
        f"{BASE}/clients/{CLIENT}/bcct/upload",
        cookies={SESSION_COOKIE: sid},
        files={"file": ("tk.xlsx", blob,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False, timeout=30)
    assert r.status_code == 303, f"upload failed: {r.status_code} {r.text[:200]}"
    return r.headers["location"]


async def _shot(page, slug):
    await page.wait_for_timeout(400)
    await page.screenshot(path=str(OUT / f"{slug}.png"), full_page=True)
    print(f"  saved {slug}.png")


async def main():
    _db_setup()
    sid = create_session(ADMIN)
    rows = _real_rows()
    assert rows, "no real johnson-vn rows found"

    clean_url = _upload(sid, _xlsx(rows))
    anomaly_url = _upload(sid, _xlsx(rows, swap_prices=True))
    noheader_url = _upload(sid, _xlsx(rows, header=False))
    print("  clean ->", clean_url)
    print("  anomaly ->", anomaly_url)
    print("  noheader ->", noheader_url)
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
            await page.goto(f"{BASE}{noheader_url}")
            await _shot(page, "02_no_header_mapping")
            await page.goto(f"{BASE}{clean_url}")
            await _shot(page, "03_preview_clean")
            await page.goto(f"{BASE}{anomaly_url}")
            await _shot(page, "04_preview_anomaly")
            await page.goto(f"{BASE}/clients/{CLIENT}/column-aliases?module=bcct")
            await _shot(page, "05_column_aliases")
            await browser.close()
    finally:
        _db_cleanup()


if __name__ == "__main__":
    asyncio.run(main())
