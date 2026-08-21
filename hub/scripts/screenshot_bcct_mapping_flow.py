"""Playwright screenshots for the BCCT mapping-flow overhaul (2026-06-05).

Full coverage of every flow stage, using REAL johnson-vn BCCT rows pulled
from the DB:
  01 upload page
  02 clean preview        (A: standard headers auto-mapped → Diff)
  03 list after apply     (A: real rows ingested into the BCCT list)
  04 anomaly gate         (B: two đơn-giá columns swapped → hard gate + ack)
  05 no-header mapping     (C: header stripped → picker auto-selects "Không
                              có header", columns labelled "Cột N")
  06 no-header preview     (C: positional parse → all rows kept → Diff)
  07 non-standard mapping  (D: unrecognised headers → manual map page)
  08 cache-hit preview     (D: same shape re-upload skips the mapping page)
  09 column-alias config   (admin per-client alias)

Throwaway client (wiped between flows), session-cookie auth, self cleanup.
Dev server must be running on :8754.
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

import httpx
from openpyxl import Workbook
from playwright.async_api import async_playwright

from hub.app.auth.session import SESSION_COOKIE, create_session
from hub.app.database import connect

BASE = "http://127.0.0.1:8754"
CLIENT = "shots-mapping"
ADMIN = "u_31151f0497094109"
OUT = Path(".ai/features/2026-06-05-bcct-mapping-flow-overhaul/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

HEADERS = ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký", "Mã NPL/SP",
           "Tên hàng", "Tổng số lượng", "ĐVT", "Tổng trị giá", "Đơn giá",
           "Đơn giá tính thuế", "Trị giá NT", "Nguyên tệ", "Tỷ giá")
NONSTD = ("DocNo", "Ln", "Type", "RegDate", "Code", "Goods", "Qty", "U",
          "Val", "UpNt", "Up", "ValNt", "Cur", "Rate")
FIELDS = ["declaration_no", "line_no", "declaration_type", "registration_date",
          "customs_code", "goods_name", "quantity", "unit", "total_value",
          "unit_price_nt", "unit_price", "total_value_nt", "currency_nt",
          "exchange_rate"]

SID = create_session(ADMIN)
COOKIES = {SESSION_COOKIE: SID}


def _real_rows() -> list[tuple]:
    with connect() as c, c.cursor() as cur:
        cur.execute(
            "select declaration_no, line_no, declaration_type, registration_date, "
            "customs_code, goods_name, quantity, unit, total_value, unit_price_nt, "
            "unit_price, total_value_nt, currency_nt, exchange_rate "
            "from hub.bcct_rows where client_id='johnson-vn' "
            "and currency_nt is not null and currency_nt not in ('VND','') "
            "and unit_price is not null and unit_price_nt is not null "
            "order by registration_date desc, line_no limit 8")
        return [tuple("" if v is None else
                      (v.isoformat() if hasattr(v, "isoformat") else v)
                      for v in r) for r in cur.fetchall()]


def _xlsx(rows, *, headers=HEADERS, header=True, swap=False) -> bytes:
    wb = Workbook(); ws = wb.active
    if header:
        ws.append(list(headers))
    for r in rows:
        r = list(r)
        if swap:
            r[9], r[10] = r[10], r[9]
        ws.append(r)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def _upload(blob) -> str:
    r = httpx.post(f"{BASE}/clients/{CLIENT}/bcct/upload", cookies=COOKIES,
                   files={"file": ("tk.xlsx", blob,
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                   follow_redirects=False, timeout=30)
    assert r.status_code == 303, f"upload: {r.status_code} {r.text[:200]}"
    return r.headers["location"]


def _parse(uid, data) -> str:
    r = httpx.post(f"{BASE}/clients/{CLIENT}/bcct/upload/mapping/{uid}/parse",
                   cookies=COOKIES, data=data, follow_redirects=False, timeout=30)
    assert r.status_code == 303, f"parse: {r.status_code} {r.text[:200]}"
    return r.headers["location"]


def _confirm(pid, **data):
    httpx.post(f"{BASE}/clients/{CLIENT}/bcct/upload/preview/{pid}/confirm",
               cookies=COOKIES, data=data, follow_redirects=False, timeout=30)


def _db_setup():
    with connect() as c, c.cursor() as cur:
        cur.execute("insert into hub.clients (client_id,name) values (%s,%s) "
                    "on conflict (client_id) do nothing", (CLIENT, "Screenshot Mapping Co"))
        cur.execute("insert into hub.client_column_aliases "
                    "(client_id,module,field,alias,enabled,created_by) "
                    "values (%s,'bcct','goods_name','Diễn giải hàng hóa',true,%s) "
                    "on conflict do nothing", (CLIENT, ADMIN))


def _wipe_data():
    with connect() as c, c.cursor() as cur:
        for t in ("upload_pending", "file_uploads", "bcct_rows", "parser_mappings"):
            cur.execute(f"delete from hub.{t} where client_id=%s", (CLIENT,))


def _db_cleanup():
    _wipe_data()
    with connect() as c, c.cursor() as cur:
        cur.execute("delete from hub.client_column_aliases where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


async def _shot(page, slug):
    await page.wait_for_timeout(400)
    await page.screenshot(path=str(OUT / f"{slug}.png"), full_page=True)
    print(f"  saved {slug}.png")


async def main():
    _db_setup()
    rows = _real_rows()
    assert rows, "no real johnson-vn rows found"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
            await ctx.add_cookies([
                {"name": SESSION_COOKIE, "value": SID, "url": BASE},
                {"name": "data_hub_lang", "value": "vi", "url": BASE},
            ])
            page = await ctx.new_page()

            await page.goto(f"{BASE}/clients/{CLIENT}/bcct/upload")
            await _shot(page, "01_bcct_upload")

            # Flow A — auto-map clean → preview → apply → list
            _wipe_data()
            prev = _upload(_xlsx(rows))
            await page.goto(f"{BASE}{prev}")
            await _shot(page, "02_preview_clean")
            _confirm(prev.rsplit("/", 1)[-1], confirm_diffs="on", confirm_orphans="on")
            await page.goto(f"{BASE}/clients/{CLIENT}/bcct")
            await _shot(page, "03_list_after_apply")

            # Flow B — anomaly gate
            _wipe_data()
            prev = _upload(_xlsx(rows, swap=True))
            await page.goto(f"{BASE}{prev}")
            await _shot(page, "04_preview_anomaly")

            # Flow C — no-header positional
            _wipe_data()
            mapping = _upload(_xlsx(rows, header=False))
            await page.goto(f"{BASE}{mapping}")
            await _shot(page, "05_no_header_mapping")
            uid = mapping.rsplit("/", 1)[-1]
            data = {"header_row_override": "0", "extra_required_fields": ""}
            for i, f in enumerate(FIELDS):
                data[f"col_{i}__field"] = f
            prev = _parse(uid, data)
            await page.goto(f"{BASE}{prev}")
            await _shot(page, "06_no_header_preview")

            # Flow D — non-standard headers → manual map → cache hit
            _wipe_data()
            mapping = _upload(_xlsx(rows, headers=NONSTD))
            await page.goto(f"{BASE}{mapping}")
            await _shot(page, "07_non_standard_mapping")
            uid = mapping.rsplit("/", 1)[-1]
            data = {"header_row_override": "1", "extra_required_fields": ""}
            for i, (h, f) in enumerate(zip(NONSTD, FIELDS)):
                data[f"col_{i}__field"] = f
                data[f"col_{i}__header"] = h
            _parse(uid, data)
            prev = _upload(_xlsx(rows, headers=NONSTD))  # same shape → cache hit
            assert "/preview/" in prev, f"expected cache hit, got {prev}"
            await page.goto(f"{BASE}{prev}")
            await _shot(page, "08_cache_hit_preview")

            # Admin column-alias config
            await page.goto(f"{BASE}/clients/{CLIENT}/column-aliases?module=bcct")
            await _shot(page, "09_column_aliases")

            await browser.close()
    finally:
        _db_cleanup()


if __name__ == "__main__":
    asyncio.run(main())
