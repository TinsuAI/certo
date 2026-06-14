"""Upload detail view + original-file download + first-rows preview, plus the
client nav redesign (3 domain groups; Đề xuất nested under BOM; whole-row
click-to-detail)."""
from __future__ import annotations

import io
import uuid

import openpyxl
from fastapi.testclient import TestClient

from app.auth.session import SESSION_COOKIE, create_session
from app.database import connect
from app.main import app
from app.storage import get_backend

CLIENT = "growatt-vn"


def _dev_client() -> TestClient:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select user_id from hub.users where role='dev' "
                    "and status='active' limit 1")
        uid = cur.fetchone()[0]
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, create_session(uid))
    return c


def _xlsx_blob() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Vật tư"
    ws.append(["Mã", "Tên hàng", "SL"])
    ws.append(["A1", "Linh kiện A", 10])
    ws.append(["B2", "Linh kiện B", 20])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _insert_upload(*, blob: bytes, filename: str, mime: str,
                   module: str = "materials", status: str = "done",
                   row_count: int | None = 2) -> str:
    stored = get_backend().put(
        blob, key=f"test_uploads/{uuid.uuid4().hex}_{filename}")
    upload_id = "up_t_" + uuid.uuid4().hex[:14]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """insert into hub.file_uploads
               (upload_id, client_id, module, original_filename, stored_path,
                storage_backend, content_sha256, size_bytes, mime_type,
                parse_status, row_count)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (upload_id, CLIENT, module, filename, stored.path, stored.backend,
             stored.content_sha256, stored.size_bytes, mime, status, row_count))
    return upload_id


def _cleanup(upload_id: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select stored_path from hub.file_uploads where upload_id=%s",
                    (upload_id,))
        row = cur.fetchone()
        cur.execute("delete from hub.file_uploads where upload_id=%s", (upload_id,))
    if row and row[0]:
        try:
            get_backend().delete(row[0])
        except Exception:  # noqa: BLE001
            pass


# ── Upload detail + preview ───────────────────────────────────────────

def test_upload_detail_renders_metadata_and_xlsx_preview():
    c = _dev_client()
    uid = _insert_upload(
        blob=_xlsx_blob(), filename="danh_muc.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    try:
        r = c.get(f"/clients/{CLIENT}/uploads/{uid}")
        assert r.status_code == 200, r.status_code
        assert "danh_muc.xlsx" in r.text
        assert "SHA-256" in r.text                 # metadata block
        assert "Xem trước nội dung file" in r.text  # preview section
        # Cell content from the sheet made it into the preview table.
        assert "Linh kiện A" in r.text
        assert 'class="dh-table preview-table"' in r.text
    finally:
        _cleanup(uid)


def test_upload_download_returns_original_bytes():
    c = _dev_client()
    blob = _xlsx_blob()
    uid = _insert_upload(
        blob=blob, filename="danh mục.xlsx",  # non-ASCII filename
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    try:
        r = c.get(f"/clients/{CLIENT}/uploads/{uid}/download")
        assert r.status_code == 200
        assert r.content == blob
        cd = r.headers["content-disposition"]
        assert "attachment" in cd
        assert "filename*=UTF-8''" in cd  # unicode-safe disposition
    finally:
        _cleanup(uid)


def test_upload_csv_preview():
    c = _dev_client()
    csv_blob = "code,name,qty\nA1,Alpha,5\nB2,Beta,7\n".encode()
    uid = _insert_upload(blob=csv_blob, filename="codes.csv", mime="text/csv",
                         module="code_mappings")
    try:
        r = c.get(f"/clients/{CLIENT}/uploads/{uid}")
        assert r.status_code == 200
        assert "Alpha" in r.text and "Beta" in r.text
        assert 'class="dh-table preview-table"' in r.text
    finally:
        _cleanup(uid)


def test_upload_detail_unknown_404():
    c = _dev_client()
    r = c.get(f"/clients/{CLIENT}/uploads/up_does_not_exist")
    assert r.status_code == 404


def test_uploads_list_has_uploader_col_and_row_links():
    c = _dev_client()
    uid = _insert_upload(
        blob=_xlsx_blob(), filename="bom.xlsx", module="bom",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    try:
        r = c.get(f"/clients/{CLIENT}/uploads")
        assert r.status_code == 200
        assert "Người tải" in r.text  # new uploader column
        assert f'data-row-href="/clients/{CLIENT}/uploads/{uid}"' in r.text
    finally:
        _cleanup(uid)


# ── Nav redesign ──────────────────────────────────────────────────────

def test_client_nav_three_domain_groups_with_proposals_under_bom():
    c = _dev_client()
    r = c.get(f"/clients/{CLIENT}/bcct")
    assert r.status_code == 200
    # Three domain group summaries.
    assert "Hải quan" in r.text
    assert "Định mức (BOM)" in r.text       # BOM-list item inside BOM group
    assert "Danh mục vật tư" in r.text       # catalog item inside Danh mục group
    # Đề xuất is present and points at the proposals route (now under BOM).
    assert f'href="/clients/{CLIENT}/proposals"' in r.text
    assert "Đề xuất" in r.text
    # Hải quan group nests Tờ khai (declarations).
    assert f'href="/clients/{CLIENT}/declarations"' in r.text
    # Global row-link behaviour shipped on every page.
    assert "/static/js/row-link.js" in r.text


def test_bcct_active_tab_highlights_customs_group():
    c = _dev_client()
    r = c.get(f"/clients/{CLIENT}/bcct")
    assert r.status_code == 200
    assert "tab-link-active" in r.text  # Hải quan group highlighted on BCCT


def test_bcct_rows_clickable_when_present():
    c = _dev_client()
    r = c.get(f"/clients/{CLIENT}/bcct")
    assert r.status_code == 200
    # If the seed gave growatt BCCT rows, each row must carry the detail href.
    if "/bcct/history/" in r.text:
        assert f'data-row-href="/clients/{CLIENT}/bcct/history/' in r.text
