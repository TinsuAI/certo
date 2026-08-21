"""End-to-end smoke for the BCCT upload mapping flow, using REAL johnson-vn
rows pulled from the DB. Exercises every flow path and asserts the actual
ingested outcome (not just HTTP status):

  A  standard headers -> auto-map -> clean preview -> apply (prices land in
     the right VND/nguyên-tệ columns)
  B  swapped đơn-giá columns -> anomaly hard gate (block without ack, apply
     with ack)
  C  no header row -> picker auto-suggests "Không có header" -> positional
     parse keeps ALL rows
  D  non-standard headers -> manual mapping -> cache -> repeat upload is a
     cache hit (skips the mapping page)

Drives the live dev server on :8754 with a session cookie, against a
throwaway client (wiped between flows). Exits non-zero on any failure, so
it can run in CI.

Run: uv run python scripts/smoke_bcct_flows.py
"""
from __future__ import annotations

import io
import sys

import httpx
from openpyxl import Workbook

from hub.app.auth.session import SESSION_COOKIE, create_session
from hub.app.database import connect

BASE = "http://127.0.0.1:8754"
CLIENT = "smoke-flows"
ADMIN = "u_31151f0497094109"  # admin@data-hub.local

HEADERS = ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký", "Mã NPL/SP",
           "Tên hàng", "Tổng số lượng", "ĐVT", "Tổng trị giá", "Đơn giá",
           "Đơn giá tính thuế", "Trị giá NT", "Nguyên tệ", "Tỷ giá")
NONSTD = ("DocNo", "Ln", "Type", "RegDate", "Code", "Goods", "Qty", "U",
          "Val", "UpNt", "Up", "ValNt", "Cur", "Rate")
FIELDS = ["declaration_no", "line_no", "declaration_type", "registration_date",
          "customs_code", "goods_name", "quantity", "unit", "total_value",
          "unit_price_nt", "unit_price", "total_value_nt", "currency_nt",
          "exchange_rate"]

_SID = create_session(ADMIN)
_COOKIES = {SESSION_COOKIE: _SID}


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


def _upload(blob):
    return httpx.post(
        f"{BASE}/clients/{CLIENT}/bcct/upload", cookies=_COOKIES,
        files={"file": ("t.xlsx", blob,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False, timeout=30)


def _confirm(pid, **data):
    return httpx.post(
        f"{BASE}/clients/{CLIENT}/bcct/upload/preview/{pid}/confirm",
        cookies=_COOKIES, data=data, follow_redirects=False, timeout=30)


def _get(path):
    return httpx.get(f"{BASE}{path}", cookies=_COOKIES, follow_redirects=False)


def _wipe():
    with connect() as c, c.cursor() as cur:
        for t in ("upload_pending", "file_uploads", "bcct_rows", "parser_mappings"):
            cur.execute(f"delete from hub.{t} where client_id=%s", (CLIENT,))


def _count():
    with connect() as c, c.cursor() as cur:
        cur.execute("select count(*) from hub.bcct_rows where client_id=%s", (CLIENT,))
        return cur.fetchone()[0]


def _usd_prices():
    with connect() as c, c.cursor() as cur:
        cur.execute("select unit_price, unit_price_nt from hub.bcct_rows "
                    "where client_id=%s and currency_nt='USD' limit 1", (CLIENT,))
        return cur.fetchone()


def _parse(uid, data):
    return httpx.post(
        f"{BASE}/clients/{CLIENT}/bcct/upload/mapping/{uid}/parse",
        cookies=_COOKIES, data=data, follow_redirects=False, timeout=30)


def main() -> int:
    with connect() as c, c.cursor() as cur:
        cur.execute("insert into hub.clients (client_id,name) values (%s,'Smoke Flows') "
                    "on conflict do nothing", (CLIENT,))
    rows = _real_rows()
    if len(rows) != 8:
        print(f"FATAL: need 8 real johnson-vn rows, got {len(rows)}")
        return 2
    results = []
    try:
        # A — auto-map standard -> clean preview -> apply
        _wipe()
        r = _upload(_xlsx(rows)); loc = r.headers.get("location", "")
        a1 = r.status_code == 303 and "/upload/preview/" in loc and "/mapping/" not in loc
        pid = loc.rsplit("/", 1)[-1]
        cf = _confirm(pid, confirm_diffs="on", confirm_orphans="on")
        up, upnt = _usd_prices()
        a2 = cf.status_code == 303 and _count() == 8 and float(up) > float(upnt)
        results.append(("A auto-map→clean→apply", a1 and a2,
                        f"preview={a1} ingested={_count()} up({up})>up_nt({upnt})"))

        # B — anomaly advisory (warning shown, does NOT block save)
        _wipe()
        r = _upload(_xlsx(rows, swap=True)); pid = r.headers["location"].rsplit("/", 1)[-1]
        pg = _get(f"/clients/{CLIENT}/bcct/upload/preview/{pid}")
        b1 = "Lưu ý" in pg.text and "không chặn lưu" in pg.text \
            and 'name="confirm_anomalies"' not in pg.text
        cf = _confirm(pid, confirm_diffs="on", confirm_orphans="on")
        b2 = cf.status_code == 303 and _count() == 8
        results.append(("B anomaly advisory (warn, not blocking)", b1 and b2,
                        f"warn={b1} confirmed_ingested={_count()}"))

        # C — no-header positional
        _wipe()
        r = _upload(_xlsx(rows, header=False)); loc = r.headers.get("location", "")
        c1 = r.status_code == 303 and "/upload/mapping/" in loc
        uid = loc.rsplit("/", 1)[-1]
        mp = _get(f"/clients/{CLIENT}/bcct/upload/mapping/{uid}")
        c2 = "đã chọn sẵn" in mp.text
        data = {"header_row_override": "0", "extra_required_fields": ""}
        for i, f in enumerate(FIELDS):
            data[f"col_{i}__field"] = f
        pr = _parse(uid, data)
        c3 = pr.status_code == 303 and "/upload/preview/" in pr.headers.get("location", "")
        pid = pr.headers["location"].rsplit("/", 1)[-1]
        cf = _confirm(pid, confirm_diffs="on", confirm_orphans="on")
        c4 = cf.status_code == 303 and _count() == 8
        results.append(("C no-header positional→apply", c1 and c2 and c3 and c4,
                        f"mapping={c1} suggest={c2} parsed={c3} ingested={_count()}/8"))

        # D — non-standard headers -> manual map -> cache hit
        _wipe()
        r = _upload(_xlsx(rows, headers=NONSTD)); loc = r.headers.get("location", "")
        d1 = "/upload/mapping/" in loc
        uid = loc.rsplit("/", 1)[-1]
        data = {"header_row_override": "1", "extra_required_fields": ""}
        for i, (h, f) in enumerate(zip(NONSTD, FIELDS)):
            data[f"col_{i}__field"] = f
            data[f"col_{i}__header"] = h
        pr = _parse(uid, data)
        d2 = pr.status_code == 303 and "/upload/preview/" in pr.headers.get("location", "")
        r2 = _upload(_xlsx(rows, headers=NONSTD)); loc2 = r2.headers.get("location", "")
        d3 = r2.status_code == 303 and "/upload/preview/" in loc2 and "/mapping/" not in loc2
        results.append(("D non-std→map→cache→hit", d1 and d2 and d3,
                        f"map1={d1} parsed={d2} cache_hit={d3}"))
    finally:
        _wipe()
        with connect() as c, c.cursor() as cur:
            cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))

    print("\n=== REAL-DATA BCCT FLOW SMOKE (johnson-vn rows) ===")
    ok_all = True
    for name, ok, detail in results:
        ok_all = ok_all and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}  — {detail}")
    print(f"\n{'ALL FLOWS PASS' if ok_all else 'SOME FLOWS FAILED'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
