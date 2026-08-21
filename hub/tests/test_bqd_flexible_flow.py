"""Slice 2 integration tests — BQD upload through the unified mapping flow.

Mirror of test_catalog_flexible_flow.py for the BQD module. Covers:
  - upload submit → mapping page (cache miss)
  - mapping POST validates required_mapped_fields (BOTH internal_code + customs_code)
  - parse → preview, confirm → ingest
  - skipped row missing customs_code surfaces in preview
  - inline-edit promotion of skipped row
  - reject path
  - second-upload cache hit
"""
from __future__ import annotations

import io
import re

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from hub.app.auth.session import create_session, hash_password, SESSION_COOKIE
from hub.app.database import connect
from hub.app.main import app


CLIENT = "flex_bqd_test"
USER_ID = "u_flex_bqd"
USER_EMAIL = "flex-bqd@test.local"


@pytest.fixture(autouse=True)
def isolated_files_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(tmp_path / "files"))
    import hub.app.storage as storage_mod
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
                (CLIENT, "flex bqd test"),
            )
            cur.execute(
                """
                insert into hub.users
                  (user_id, email, display_name, password_hash, role, status)
                values (%s, %s, 'BQD Tester', %s, 'admin', 'active')
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
                "delete from hub.parser_mappings where client_id = %s and module = 'bqd'",
                (CLIENT,),
            )
            cur.execute(
                "delete from hub.code_mappings where client_id = %s", (CLIENT,),
            )
            cur.execute(
                "delete from hub.file_uploads where uploader_user_id = %s",
                (USER_ID,),
            )
            cur.execute("delete from hub.sessions where user_id = %s", (USER_ID,))
            cur.execute("delete from hub.clients where client_id = %s", (CLIENT,))
            cur.execute("delete from hub.users where user_id = %s", (USER_ID,))


def _xlsx(rows: list[tuple], sheet_title: str = "BQD NVL") -> bytes:
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


def _upload(c, blob: bytes, *, filename="bqd.xlsx"):
    return c.post(
        f"/clients/{CLIENT}/bqd/upload",
        files={"file": (filename, blob, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
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

def test_upload_routes_to_mapping_page_on_first_use(http):
    blob = _xlsx([
        ("ERP_CODE", "HQ_CODE"),
        ("INT-1", "HQ-1"),
        ("INT-2", "HQ-2"),
    ])
    r = _upload(http, blob)
    assert r.status_code == 303, r.text
    assert "/upload/mapping/" in r.headers["location"]
    upload_id = _extract_upload_id(r.headers["location"])

    g = http.get(f"/clients/{CLIENT}/bqd/upload/mapping/{upload_id}")
    assert g.status_code == 200
    body = g.text
    assert "ERP_CODE" in body
    assert "HQ_CODE" in body
    # Identifier rule advertised on the page (BQD requires both).
    assert "internal_code" in body
    assert "customs_code" in body


# ── Form validation: BQD requires BOTH ───────────────────────────────────

def test_mapping_parse_rejects_when_only_internal_mapped(http):
    blob = _xlsx([
        ("ERP_CODE", "HQ_CODE"),
        ("INT-1", "HQ-1"),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/bqd/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "internal_code", "col_0__header": "ERP_CODE",
            # customs_code intentionally NOT mapped
        },
        follow_redirects=False,
    )
    assert parse.status_code == 400
    assert "customs_code" in parse.text


def test_mapping_parse_succeeds_with_both_mapped(http):
    blob = _xlsx([
        ("ERP_CODE", "HQ_CODE", "Loại"),
        ("INT-1", "HQ-1", "nvl"),
        ("INT-2", "HQ-2", "nvl"),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/bqd/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "internal_code", "col_0__header": "ERP_CODE",
            "col_1__field": "customs_code",  "col_1__header": "HQ_CODE",
            "col_2__field": "category",      "col_2__header": "Loại",
        },
        follow_redirects=False,
    )
    assert parse.status_code == 303
    pending_id = _extract_pending_id(parse.headers["location"])

    conf = http.post(
        f"/clients/{CLIENT}/bqd/preview/{pending_id}/confirm",
        follow_redirects=False,
    )
    assert conf.status_code == 303
    assert "ingested=2" in conf.headers["location"]

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select internal_code, customs_code from hub.code_mappings where client_id=%s "
            "order by internal_code",
            (CLIENT,),
        )
        rows = cur.fetchall()
    assert rows == [("INT-1", "HQ-1"), ("INT-2", "HQ-2")]


# ── Skipped row missing one of the pair ──────────────────────────────────

def test_skipped_row_when_customs_code_empty(http):
    blob = _xlsx([
        ("ERP_CODE", "HQ_CODE"),
        ("INT-1", "HQ-1"),
        ("INT-2", ""),       # missing customs_code
        ("INT-3", "HQ-3"),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/bqd/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "internal_code", "col_0__header": "ERP_CODE",
            "col_1__field": "customs_code",  "col_1__header": "HQ_CODE",
        },
        follow_redirects=False,
    )
    pending_id = _extract_pending_id(parse.headers["location"])
    prev = http.get(f"/clients/{CLIENT}/bqd/preview/{pending_id}")
    assert prev.status_code == 200
    assert "missing_required:customs_code" in prev.text


def test_skipped_row_promoted_via_inline_edit(http):
    blob = _xlsx([
        ("ERP_CODE", "HQ_CODE"),
        ("INT-1", "HQ-1"),
        ("INT-2", ""),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/bqd/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "internal_code", "col_0__header": "ERP_CODE",
            "col_1__field": "customs_code",  "col_1__header": "HQ_CODE",
        },
        follow_redirects=False,
    )
    pending_id = _extract_pending_id(parse.headers["location"])

    conf = http.post(
        f"/clients/{CLIENT}/bqd/preview/{pending_id}/confirm",
        data={
            "include_skipped[]": "0",
            "skipped[0][customs_code]": "HQ-2-FILLED",
        },
        follow_redirects=False,
    )
    assert conf.status_code == 303
    assert "ingested=2" in conf.headers["location"]

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select internal_code, customs_code from hub.code_mappings where client_id=%s "
            "order by internal_code",
            (CLIENT,),
        )
        rows = cur.fetchall()
    assert rows == [("INT-1", "HQ-1"), ("INT-2", "HQ-2-FILLED")]


def test_promote_skipped_without_filling_customs_code_returns_400(http):
    blob = _xlsx([
        ("ERP_CODE", "HQ_CODE"),
        ("INT-1", "HQ-1"),
        ("INT-2", ""),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/bqd/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "internal_code", "col_0__header": "ERP_CODE",
            "col_1__field": "customs_code",  "col_1__header": "HQ_CODE",
        },
        follow_redirects=False,
    )
    pending_id = _extract_pending_id(parse.headers["location"])
    conf = http.post(
        f"/clients/{CLIENT}/bqd/preview/{pending_id}/confirm",
        data={"include_skipped[]": "0"},  # no inline-edit
        follow_redirects=False,
    )
    assert conf.status_code == 400


# ── Reject ────────────────────────────────────────────────────────────────

def test_reject_discards_pending(http):
    blob = _xlsx([
        ("ERP_CODE", "HQ_CODE"),
        ("INT-1", "HQ-1"),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/bqd/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "internal_code", "col_0__header": "ERP_CODE",
            "col_1__field": "customs_code",  "col_1__header": "HQ_CODE",
        },
        follow_redirects=False,
    )
    pending_id = _extract_pending_id(parse.headers["location"])
    rej = http.post(
        f"/clients/{CLIENT}/bqd/preview/{pending_id}/reject",
        follow_redirects=False,
    )
    assert rej.status_code == 303
    assert "rejected=1" in rej.headers["location"]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.code_mappings where client_id=%s", (CLIENT,),
        )
        assert cur.fetchone()[0] == 0


# ── Cache hit on second upload ────────────────────────────────────────────

def test_second_upload_with_same_shape_is_cache_hit(http):
    blob = _xlsx([
        ("ERP_CODE", "HQ_CODE"),
        ("INT-1", "HQ-1"),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/bqd/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "internal_code", "col_0__header": "ERP_CODE",
            "col_1__field": "customs_code",  "col_1__header": "HQ_CODE",
        },
        follow_redirects=False,
    )
    pending_id = _extract_pending_id(parse.headers["location"])
    conf = http.post(
        f"/clients/{CLIENT}/bqd/preview/{pending_id}/confirm",
        follow_redirects=False,
    )
    assert conf.status_code == 303

    r2 = _upload(http, blob, filename="bqd2.xlsx")
    assert r2.status_code == 303
    assert "/preview/" in r2.headers["location"]
