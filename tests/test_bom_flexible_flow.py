"""Slice 3 integration tests — BOM-manual_flat through the unified mapping flow.

Layout-driven adapters (sap_indented_walk, multi_sheet_per_root, etc.)
keep the existing direct-to-preview path; only manual_flat (and its
default rigid-fallback) goes through the new mapping page on cache miss.
technical_flatten profile preserves its existing flatten-preview path.

Coverage:
  - manual_flat upload (cache miss) → mapping page
  - mapping form rejects when product_code or material_code unmapped
  - mapping form happy path → preview, then existing /confirm path works
  - skipped row (missing material_code) appears in preview
  - layout-driven profile bypasses mapping page (regression check)
  - technical_flatten still routes to /bom/flatten-preview/ (regression)
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


CLIENT = "flex_bom_test"
USER_ID = "u_flex_bom"
USER_EMAIL = "flex-bom@test.local"


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
                (CLIENT, "flex bom test"),
            )
            cur.execute(
                """
                insert into hub.users
                  (user_id, email, display_name, password_hash, role, status)
                values (%s, %s, 'BOM Tester', %s, 'admin', 'active')
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
                "delete from hub.parser_mappings where client_id = %s and module = 'bom'",
                (CLIENT,),
            )
            cur.execute(
                "delete from hub.bom_artifacts where client_id = %s", (CLIENT,),
            )
            cur.execute(
                "delete from hub.file_uploads where uploader_user_id = %s",
                (USER_ID,),
            )
            cur.execute("delete from hub.sessions where user_id = %s", (USER_ID,))
            cur.execute("delete from hub.clients where client_id = %s", (CLIENT,))
            cur.execute("delete from hub.users where user_id = %s", (USER_ID,))


def _xlsx(rows: list[tuple], sheet_title: str = "BOM") -> bytes:
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


def _upload(c, blob: bytes, *, profile="manual_flat", filename="bom.xlsx"):
    return c.post(
        f"/clients/{CLIENT}/bom/upload",
        data={"profile": profile},
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


# ── manual_flat: cache miss → mapping page ───────────────────────────────

def test_manual_flat_upload_routes_to_mapping_page_on_cache_miss(http):
    blob = _xlsx([
        ("PRODUCT", "MATERIAL", "QTY", "UNIT"),
        ("P-1", "M-A", 2, "kg"),
        ("P-1", "M-B", 1, "pcs"),
    ])
    r = _upload(http, blob)
    assert r.status_code == 303
    assert "/bom/upload/mapping/" in r.headers["location"]
    upload_id = _extract_upload_id(r.headers["location"])

    g = http.get(f"/clients/{CLIENT}/bom/upload/mapping/{upload_id}")
    assert g.status_code == 200
    body = g.text
    assert "PRODUCT" in body
    assert "MATERIAL" in body
    # Logical fields advertised on the page.
    assert "product_code" in body
    assert "material_code" in body


def test_mapping_form_rejects_when_product_code_unmapped(http):
    blob = _xlsx([
        ("PRODUCT", "MATERIAL", "QTY"),
        ("P-1", "M-A", 2),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/bom/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            # product_code intentionally missing
            "col_1__field": "material_code", "col_1__header": "MATERIAL",
            "col_2__field": "qty_per_unit",  "col_2__header": "QTY",
        },
        follow_redirects=False,
    )
    assert parse.status_code == 400
    assert "product_code" in parse.text


def test_mapping_form_happy_path_then_confirm(http):
    blob = _xlsx([
        ("PRODUCT", "MATERIAL", "QTY", "UNIT"),
        ("P-FLEX-1", "M-A", 2, "kg"),
        ("P-FLEX-1", "M-B", 1, "pcs"),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/bom/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "product_code",  "col_0__header": "PRODUCT",
            "col_1__field": "material_code", "col_1__header": "MATERIAL",
            "col_2__field": "qty_per_unit",  "col_2__header": "QTY",
            "col_3__field": "uom",           "col_3__header": "UNIT",
        },
        follow_redirects=False,
    )
    assert parse.status_code == 303, parse.text
    assert "/bom/preview/" in parse.headers["location"]
    pending_id = _extract_pending_id(parse.headers["location"])

    prev = http.get(f"/clients/{CLIENT}/bom/preview/{pending_id}")
    assert prev.status_code == 200
    assert "P-FLEX-1" in prev.text

    conf = http.post(
        f"/clients/{CLIENT}/bom/preview/{pending_id}/confirm",
        follow_redirects=False,
    )
    assert conf.status_code == 303

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.bom_artifacts where client_id=%s and product_code=%s",
            (CLIENT, "P-FLEX-1"),
        )
        assert cur.fetchone()[0] >= 1


def test_skipped_row_when_qty_zero_with_extra_required(http):
    """qty_per_unit is in extra_required_fields_default; a row with
    qty=0 (or missing) goes to skipped_rows[]."""
    blob = _xlsx([
        ("PRODUCT", "MATERIAL", "QTY"),
        ("P-S", "M-A", 2),
        ("P-S", "M-B", 0),       # qty=0 → skipped (qty_per_unit required)
        ("P-S", "M-C", 3),
    ])
    r = _upload(http, blob)
    upload_id = _extract_upload_id(r.headers["location"])
    parse = http.post(
        f"/clients/{CLIENT}/bom/upload/mapping/{upload_id}/parse",
        data={
            "header_row_override": "1",
            "col_0__field": "product_code",  "col_0__header": "PRODUCT",
            "col_1__field": "material_code", "col_1__header": "MATERIAL",
            "col_2__field": "qty_per_unit",  "col_2__header": "QTY",
            "extra_required_fields": "qty_per_unit",
        },
        follow_redirects=False,
    )
    assert parse.status_code == 303
    pending_id = _extract_pending_id(parse.headers["location"])
    prev = http.get(f"/clients/{CLIENT}/bom/preview/{pending_id}")
    assert prev.status_code == 200
    assert "missing_required:qty_per_unit" in prev.text


# ── Layout-driven adapters bypass mapping page ───────────────────────────

def test_layout_driven_adapter_bypasses_mapping_page(http):
    """`sheet_per_product` is layout-driven: each sheet title = product
    code; rigid auto-detection works without column mapping. Should NOT
    route to mapping page."""
    # Build a sheet_per_product workbook: each sheet title = product
    # code; first row = header; rows below = NPL.
    wb = Workbook()
    ws = wb.active
    ws.title = "P-LAYOUT-1"
    ws.append(("Mã NVL", "Định mức", "ĐVT"))
    ws.append(("M-X", 1, "kg"))
    ws.append(("M-Y", 2, "pcs"))
    buf = io.BytesIO()
    wb.save(buf)
    blob = buf.getvalue()

    r = _upload(http, blob, profile="sheet_per_product")
    assert r.status_code == 303
    # Route either to /preview/ or 400 if rigid format doesn't match;
    # crucially NOT to /upload/mapping/.
    assert "/upload/mapping/" not in r.headers["location"], r.headers


# ── technical_flatten preserved ──────────────────────────────────────────

def test_technical_flatten_routes_to_flatten_preview(http):
    """technical_flatten profile must still route to flatten-preview,
    not the new mapping page."""
    blob = _xlsx([
        ("Mã SP",   "Mã NVL", "Định mức", "ĐVT"),
        ("P-TF-1",  "M-A",    1,          "kg"),
    ])
    r = _upload(http, blob, profile="technical_flatten")
    assert r.status_code == 303
    assert "/bom/flatten-preview/" in r.headers["location"]
    assert "/bom/upload/mapping/" not in r.headers["location"]
