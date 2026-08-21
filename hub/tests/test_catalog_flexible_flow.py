"""Slice 1 integration tests — catalog upload through unified mapping flow.

Drives the FastAPI route end-to-end with httpx.TestClient. Covers:
  - upload submit → mapping page (cache miss)
  - mapping page GET renders raw rows + column map + identifier hints
  - mapping POST parses with overrides + 303 → preview
  - preview shows skipped rows when required field missing
  - confirm with no skipped → ingests
  - confirm with included skipped + inline-edit promotes the row
  - confirm without identifier on included skipped → 400
  - reject → rejected
  - second upload with same shape → cache hit (skip mapping page)
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


CLIENT = "flex_catalog_test"
USER_ID = "u_flex_test"
USER_EMAIL = "flex@test.local"


@pytest.fixture(autouse=True)
def isolated_files_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(tmp_path / "files"))
    # Storage backend is module-level singleton — reset it.
    import app.storage as storage_mod
    storage_mod._BACKEND = None
    yield
    storage_mod._BACKEND = None


@pytest.fixture(autouse=True)
def setup_client_and_user():
    """Provision a client + dev-role user + a live session cookie."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.clients (client_id, name)
                values (%s, %s) on conflict (client_id) do nothing
                """,
                (CLIENT, "flex catalog test"),
            )
            cur.execute(
                """
                insert into hub.users
                  (user_id, email, display_name, password_hash, role, status)
                values (%s, %s, 'Flex Tester', %s, 'admin', 'active')
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
                "delete from hub.upload_pending where client_id = %s", (CLIENT,),
            )
            cur.execute(
                "delete from hub.parser_mappings where client_id = %s and module = 'catalog'",
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


def _xlsx(rows: list[tuple], sheet_title: str = "DM NVL") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
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


def _upload(c, blob: bytes, *, filename="flex.xlsx", is_hq="1"):
    """POST /upload, return the (no-follow) response."""
    return c.post(
        f"/clients/{CLIENT}/catalog/upload",
        files={"file": (filename, blob, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"is_hq_registered": is_hq},
        follow_redirects=False,
    )


def _extract_upload_id(redirect_url: str) -> str:
    m = re.search(r"/upload/mapping/([^/?]+)", redirect_url)
    assert m, f"no upload_id in {redirect_url}"
    return m.group(1)


def _extract_pending_id(redirect_url: str) -> str:
    m = re.search(r"/preview/([^/?]+)", redirect_url)
    assert m, f"no pending_id in {redirect_url}"
    return m.group(1)


# ── Cache miss → mapping page ────────────────────────────────────────────

def test_upload_with_unrecognized_headers_routes_to_mapping_page(http):
    """Even when rigid parser would fail, file goes to mapping page so
    staff can pick the right column→field map."""
    blob = _xlsx([
        ("MaSP", "TenSP", "DonVi", "Loai"),  # non-standard headers
        ("FOO-1", "Foo widget", "kg", "nvl"),
        ("FOO-2", "Bar widget", "pcs", "nvl"),
    ])
    r = _upload(http, blob)
    assert r.status_code == 303, r.text
    assert "/upload/mapping/" in r.headers["location"], r.headers
    upload_id = _extract_upload_id(r.headers["location"])

    g = http.get(f"/clients/{CLIENT}/catalog/upload/mapping/{upload_id}")
    assert g.status_code == 200, g.text
    body = g.text
    assert "MaSP" in body
    assert "TenSP" in body
    assert "customs_code" in body
    assert "internal_code" in body


def test_upload_with_recognized_headers_also_routes_to_mapping_page_first(http):
    """Cache miss → mapping page even when rigid would succeed (Plan B
    UX: staff always reviews on first upload)."""
    blob = _xlsx([
        ("Mã HQ", "Tên", "Loại", "ĐVT"),
        ("OK-1", "Alpha", "nvl", "kg"),
    ])
    r = _upload(http, blob)
    assert r.status_code == 303
    assert "/upload/mapping/" in r.headers["location"]


# ── Mapping POST → preview ───────────────────────────────────────────────

def test_mapping_parse_creates_pending_and_redirects_to_preview(http):
    blob = _xlsx([
        ("MaSP", "TenSP", "DonVi", "Loai"),
        ("X-1", "Alpha", "kg", "nvl"),
        ("X-2", "Beta",  "pcs", "tp"),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])

    parse = http.post(
        f"/clients/{CLIENT}/catalog/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "internal_code", "col_0__header": "MaSP",
            "col_1__field": "name",          "col_1__header": "TenSP",
            "col_2__field": "unit",          "col_2__header": "DonVi",
            "col_3__field": "category",      "col_3__header": "Loai",
        },
        follow_redirects=False,
    )
    assert parse.status_code == 303, parse.text
    assert "/preview/" in parse.headers["location"]
    pending_id = _extract_pending_id(parse.headers["location"])

    conf = http.post(
        f"/clients/{CLIENT}/catalog/preview/{pending_id}/confirm",
        follow_redirects=False,
    )
    assert conf.status_code == 303, conf.text
    assert "ingested=2" in conf.headers["location"]

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select material_code from hub.materials where client_id=%s order by material_code",
            (CLIENT,),
        )
        codes = [r[0] for r in cur.fetchall()]
    assert codes == ["X-1", "X-2"]


def test_mapping_parse_without_identifier_returns_400(http):
    blob = _xlsx([
        ("Header_A", "Header_B"),
        ("a", "b"),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/catalog/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "name", "col_0__header": "Header_A",
            "col_1__field": "unit", "col_1__header": "Header_B",
        },
        follow_redirects=False,
    )
    assert parse.status_code == 400


# ── Skipped-row inline edit ──────────────────────────────────────────────

def test_skipped_row_appears_in_preview_when_unit_required(http):
    blob = _xlsx([
        ("MaSP", "TenSP", "DonVi"),
        ("X-1", "alpha", "kg"),
        ("X-2", "beta", ""),    # missing unit
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/catalog/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "internal_code", "col_0__header": "MaSP",
            "col_1__field": "name",          "col_1__header": "TenSP",
            "col_2__field": "unit",          "col_2__header": "DonVi",
            "extra_required_fields": "unit",
        },
        follow_redirects=False,
    )
    assert parse.status_code == 303
    pending_id = _extract_pending_id(parse.headers["location"])

    prev = http.get(f"/clients/{CLIENT}/catalog/preview/{pending_id}")
    assert prev.status_code == 200
    body = prev.text
    assert "missing_required:unit" in body
    assert "skipped" in body.lower()


def test_skipped_row_can_be_promoted_via_inline_edit(http):
    blob = _xlsx([
        ("MaSP", "TenSP", "DonVi"),
        ("X-1", "alpha", "kg"),
        ("X-2", "beta",  ""),    # missing unit
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/catalog/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "internal_code", "col_0__header": "MaSP",
            "col_1__field": "name",          "col_1__header": "TenSP",
            "col_2__field": "unit",          "col_2__header": "DonVi",
            "extra_required_fields": "unit",
        },
        follow_redirects=False,
    )
    pending_id = _extract_pending_id(parse.headers["location"])

    conf = http.post(
        f"/clients/{CLIENT}/catalog/preview/{pending_id}/confirm",
        data={
            "include_skipped[]": "0",
            "skipped[0][unit]": "PCS",
        },
        follow_redirects=False,
    )
    assert conf.status_code == 303, conf.text
    assert "ingested=2" in conf.headers["location"]

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select material_code, uom from hub.materials where client_id=%s order by material_code",
            (CLIENT,),
        )
        rows = cur.fetchall()
    assert rows == [("X-1", "kg"), ("X-2", "PCS")]


def test_promote_skipped_without_identifier_returns_400(http):
    """Staff includes a skipped row but identifier is still empty after
    edits → 400, not silent corruption."""
    blob = _xlsx([
        ("MaSP", "TenSP"),
        ("X-1", "alpha"),
        ("",    "no id"),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/catalog/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "internal_code", "col_0__header": "MaSP",
            "col_1__field": "name",          "col_1__header": "TenSP",
        },
        follow_redirects=False,
    )
    pending_id = _extract_pending_id(parse.headers["location"])
    conf = http.post(
        f"/clients/{CLIENT}/catalog/preview/{pending_id}/confirm",
        data={"include_skipped[]": "0"},
        follow_redirects=False,
    )
    assert conf.status_code == 400


# ── Reject ────────────────────────────────────────────────────────────────

def test_reject_discards_pending_and_marks_rejected(http):
    blob = _xlsx([
        ("MaSP", "TenSP"),
        ("X-1", "alpha"),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/catalog/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "internal_code", "col_0__header": "MaSP",
            "col_1__field": "name",          "col_1__header": "TenSP",
        },
        follow_redirects=False,
    )
    pending_id = _extract_pending_id(parse.headers["location"])
    rej = http.post(
        f"/clients/{CLIENT}/catalog/preview/{pending_id}/reject",
        follow_redirects=False,
    )
    assert rej.status_code == 303
    assert "rejected=1" in rej.headers["location"]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.upload_pending where pending_id=%s",
            (pending_id,),
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            "select count(*) from hub.materials where client_id=%s", (CLIENT,),
        )
        assert cur.fetchone()[0] == 0


# ── Cache hit on second upload ───────────────────────────────────────────

def test_second_upload_with_same_shape_is_cache_hit(http):
    """First upload trains the mapping. Second upload of the same shape
    SKIPS the mapping page and goes straight to preview."""
    blob = _xlsx([
        ("MaSP", "TenSP", "DonVi"),
        ("X-1", "alpha", "kg"),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/catalog/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "internal_code", "col_0__header": "MaSP",
            "col_1__field": "name",          "col_1__header": "TenSP",
            "col_2__field": "unit",          "col_2__header": "DonVi",
        },
        follow_redirects=False,
    )
    pending_id = _extract_pending_id(parse.headers["location"])
    conf = http.post(
        f"/clients/{CLIENT}/catalog/preview/{pending_id}/confirm",
        follow_redirects=False,
    )
    assert conf.status_code == 303

    r2 = _upload(http, blob, filename="flex2.xlsx")
    assert r2.status_code == 303
    assert "/preview/" in r2.headers["location"], (
        f"expected preview redirect, got {r2.headers['location']}"
    )
