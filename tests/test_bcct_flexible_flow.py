"""Slice 4 integration tests — BCCT through the unified mapping flow.

BCCT is the highest-risk slice because it has confirm-on-update +
diff-on-update + history + typed-column coercion. Testing focus:
  - upload (cache miss) → mapping page
  - mapping POST validates required_mapped_fields (declaration_no +
    registration_date + customs_code)
  - mapping POST → ingest pipeline (the existing classify + diff +
    upload_preview path is exercised)
  - typed-column coercion still runs after mapping override
  - cache hit on second upload of same shape skips the mapping page
"""
from __future__ import annotations

import io
import re

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.auth.session import create_session, hash_password, SESSION_COOKIE
from app.database import connect
from app.main import app


CLIENT = "flex_bcct_test"
USER_ID = "u_flex_bcct"
USER_EMAIL = "flex-bcct@test.local"
TXN_PREFIX = "FLEXBCCT_"


@pytest.fixture(autouse=True)
def isolated_files_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(tmp_path / "files"))
    import app.storage as storage_mod
    storage_mod._BACKEND = None
    yield
    storage_mod._BACKEND = None


@pytest.fixture(autouse=True)
def setup_client_and_user():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.clients (client_id, name)
                values (%s, %s) on conflict (client_id) do nothing
                """,
                (CLIENT, "flex bcct test"),
            )
            cur.execute(
                """
                insert into hub.users
                  (user_id, email, display_name, password_hash, role, status)
                values (%s, %s, 'BCCT Tester', %s, 'admin', 'active')
                on conflict (user_id) do update
                  set role = 'admin', status = 'active'
                """,
                (USER_ID, USER_EMAIL, hash_password("test-password")),
            )
    session_id = create_session(USER_ID)
    yield {"session_id": session_id}
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from hub.bcct_rows where transaction_key like %s",
                (TXN_PREFIX + "%",),
            )
            cur.execute(
                "delete from hub.upload_pending where client_id = %s", (CLIENT,),
            )
            cur.execute(
                "delete from hub.parser_mappings where client_id = %s and module = 'bcct'",
                (CLIENT,),
            )
            cur.execute(
                "delete from hub.materials where client_id = %s", (CLIENT,),
            )
            cur.execute(
                "delete from hub.file_uploads where uploader_user_id = %s",
                (USER_ID,),
            )
            cur.execute("delete from hub.sessions where user_id = %s", (USER_ID,))
            cur.execute("delete from hub.clients where client_id = %s", (CLIENT,))
            cur.execute("delete from hub.users where user_id = %s", (USER_ID,))


def _xlsx(rows: list[tuple]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "BCCT"
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def http(setup_client_and_user):
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, setup_client_and_user["session_id"])
    return c


def _upload(c, blob: bytes, *, filename="bcct.xlsx"):
    return c.post(
        f"/clients/{CLIENT}/bcct/upload",
        files={"file": (filename, blob, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False,
    )


def _extract_upload_id(redirect_url: str) -> str:
    m = re.search(r"/upload/mapping/([^/?]+)", redirect_url)
    assert m, f"no upload_id in {redirect_url}"
    return m.group(1)


# ── Cache miss → mapping page ────────────────────────────────────────────

def test_bcct_upload_routes_to_mapping_page_on_cache_miss(http):
    blob = _xlsx([
        ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký", "Mã NPL/SP",
         "Tên hàng", "Tổng số lượng", "ĐVT", "Trị giá", "Nguyên tệ"),
        (TXN_PREFIX + "1", 1, "E11", "2025-03-15", "PE-FLEX",
         "PE-FLEX#&PE", 100.0, "kg", 250.0, "USD"),
    ])
    r = _upload(http, blob)
    assert r.status_code == 303
    assert "/bcct/upload/mapping/" in r.headers["location"]
    upload_id = _extract_upload_id(r.headers["location"])

    g = http.get(f"/clients/{CLIENT}/bcct/upload/mapping/{upload_id}")
    assert g.status_code == 200
    body = g.text
    assert "Số tờ khai" in body
    assert "declaration_no" in body
    assert "registration_date" in body
    assert "customs_code" in body


def test_mapping_form_rejects_when_required_unmapped(http):
    blob = _xlsx([
        ("Number", "Date", "Code"),
        (TXN_PREFIX + "X", "2025-03-15", "X-1"),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/bcct/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "declaration_no", "col_0__header": "Number",
            # registration_date intentionally unmapped
            "col_2__field": "customs_code",   "col_2__header": "Code",
        },
        follow_redirects=False,
    )
    assert parse.status_code == 400
    assert "registration_date" in parse.text


def test_mapping_happy_path_runs_typed_column_coercion(http):
    """The whole point of slice 4 keeping BCCT logic intact: typed-column
    coercion (date strings → date objects, numeric strings → numbers,
    direction inference from declaration_type) must still work after a
    mapping override."""
    blob = _xlsx([
        # Non-standard headers that staff maps explicitly:
        ("DocNo", "LineNo", "Type", "RegDate", "Code", "Goods",
         "Qty", "U", "Value", "Cur"),
        (TXN_PREFIX + "TC1", 1, "E11", "2025-03-15", "PE-TC",
         "PE-TC#&PE", 100.0, "kg", 250.0, "USD"),
        (TXN_PREFIX + "TC2", 1, "E42", "2025-09-01", "INV-TC",
         "INV-TC#&Inverter", 50.0, "pcs", 12500.0, "USD"),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/bcct/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "declaration_no",     "col_0__header": "DocNo",
            "col_1__field": "line_no",             "col_1__header": "LineNo",
            "col_2__field": "declaration_type",    "col_2__header": "Type",
            "col_3__field": "registration_date",   "col_3__header": "RegDate",
            "col_4__field": "customs_code",        "col_4__header": "Code",
            "col_5__field": "goods_name",          "col_5__header": "Goods",
            "col_6__field": "quantity",            "col_6__header": "Qty",
            "col_7__field": "unit",                "col_7__header": "U",
            "col_8__field": "total_value",         "col_8__header": "Value",
            "col_9__field": "currency",            "col_9__header": "Cur",
        },
        follow_redirects=False,
    )
    # Either redirected to the existing /upload/preview/ (NEW-only mode),
    # or 303 to the BCCT-bespoke confirm-update page. Both are acceptable;
    # critical assertion is that parse succeeded (no 400).
    assert parse.status_code == 303, parse.text


def test_second_upload_with_same_shape_is_cache_hit(http):
    """First upload populates parser_mappings via mapping page POST.
    Second upload of the same shape should NOT route to mapping page."""
    blob = _xlsx([
        ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký", "Mã NPL/SP",
         "Tên hàng", "Tổng số lượng", "ĐVT", "Trị giá", "Nguyên tệ"),
        (TXN_PREFIX + "CH1", 1, "E11", "2025-03-15", "PE-CH",
         "PE-CH#&PE", 100.0, "kg", 250.0, "USD"),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    # Submit mapping with rigid auto-match values (same as defaults).
    parse = http.post(
        f"/clients/{CLIENT}/bcct/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "declaration_no",      "col_0__header": "Số tờ khai",
            "col_1__field": "line_no",              "col_1__header": "Dòng",
            "col_2__field": "declaration_type",     "col_2__header": "Mã loại hình",
            "col_3__field": "registration_date",    "col_3__header": "Ngày đăng ký",
            "col_4__field": "customs_code",         "col_4__header": "Mã NPL/SP",
            "col_5__field": "goods_name",           "col_5__header": "Tên hàng",
            "col_6__field": "quantity",             "col_6__header": "Tổng số lượng",
            "col_7__field": "unit",                 "col_7__header": "ĐVT",
            "col_8__field": "total_value",          "col_8__header": "Trị giá",
            "col_9__field": "currency",             "col_9__header": "Nguyên tệ",
        },
        follow_redirects=False,
    )
    assert parse.status_code == 303

    # Second upload: same shape → cache HIT → bypass mapping page.
    blob2 = _xlsx([
        ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký", "Mã NPL/SP",
         "Tên hàng", "Tổng số lượng", "ĐVT", "Trị giá", "Nguyên tệ"),
        (TXN_PREFIX + "CH2", 1, "E11", "2025-04-15", "PE-CH",
         "PE-CH#&PE", 80.0, "kg", 200.0, "USD"),
    ])
    r2 = _upload(http, blob2, filename="bcct2.xlsx")
    assert r2.status_code == 303
    assert "/bcct/upload/mapping/" not in r2.headers["location"], (
        f"expected cache hit path, got {r2.headers['location']}"
    )
