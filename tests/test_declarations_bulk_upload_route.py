"""Route-level smoke for the bulk-ZIP upload pair.

Drives `POST .../upload-zip` → `POST .../upload-zip/<staging_id>/commit`
end-to-end via TestClient. Pure-function pipeline is covered in
`test_declaration_zip_upload.py`; this file locks the FastAPI wiring,
the redirect contract, and the preview template render.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
import xlwt
from fastapi.testclient import TestClient

from app.database import connect
from app.main import app
from app.routes.clients import upsert_client


def _login(c: TestClient) -> None:
    r = c.post(
        "/login",
        data={"email": "admin@data-hub.local", "password": "admin123",
              "next": "/clients"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text


def _make_xls(decl_no: str) -> bytes:
    wb = xlwt.Workbook()
    ws = wb.add_sheet("TKN")
    ws.write(3, 4, decl_no)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_zip(members: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def isolated_files_root(tmp_path, monkeypatch):
    root = tmp_path / "files"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(root))
    import app.storage as storage_mod
    storage_mod._BACKEND = None
    yield root
    storage_mod._BACKEND = None


@pytest.fixture
def bulk_route_client(isolated_files_root):
    cid = "test-bulk-route-vn"
    upsert_client(
        client_id=cid, name="Test Bulk Route",
        tax_code=None, code_resolution_mode="identity",
        bom_proposal_mode="manual", bom_proposal_qty_tolerance_pct=5.0,
        bom_approver_tier="edit", status="active", notes=None,
    )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.customs_declaration_files where client_id=%s",
            (cid,),
        )
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


def test_preview_then_commit_happy_path(bulk_route_client):
    zip_bytes = _make_zip([
        ("00000001_107555000001.xls", _make_xls("107555000001")),
        ("00000002_107555000002.xls", _make_xls("107555000002")),
        ("README.txt", b"junk"),
    ])
    with TestClient(app) as tc:
        _login(tc)
        # Preview: posts ZIP, gets back HTML 200 with summary + staging_id.
        r = tc.post(
            f"/clients/{bulk_route_client}/declarations/upload-zip",
            data={"direction": "import"},
            files={"file": ("upload.zip", zip_bytes, "application/zip")},
        )
        assert r.status_code == 200, r.text
        body = r.text
        # 2 OK + 0 duplicate + 0 mismatch + 0 parse_error; README ignored.
        assert "Hợp lệ" in body
        # Pull staging_id out of the committed form action.
        import re
        m = re.search(
            r"/declarations/upload-zip/(zip-[0-9a-f-]+)/commit", body,
        )
        assert m is not None, "staging_id should appear in preview HTML"
        staging_id = m.group(1)

        # Commit: redirects to /declarations with toast query params.
        r2 = tc.post(
            f"/clients/{bulk_route_client}/declarations/upload-zip/"
            f"{staging_id}/commit",
            data={"direction": "import"},
            follow_redirects=False,
        )
        assert r2.status_code == 303, r2.text
        loc = r2.headers["location"]
        assert "bulk_inserted=2" in loc
        assert "bulk_deduped=0" in loc

        # Re-upload same ZIP → preview now shows 2 duplicate, 0 ok.
        r3 = tc.post(
            f"/clients/{bulk_route_client}/declarations/upload-zip",
            data={"direction": "import"},
            files={"file": ("upload.zip", zip_bytes, "application/zip")},
        )
        assert r3.status_code == 200
        assert "Trùng lặp" in r3.text


def test_preview_rejects_corrupt_zip(bulk_route_client):
    with TestClient(app) as tc:
        _login(tc)
        r = tc.post(
            f"/clients/{bulk_route_client}/declarations/upload-zip",
            data={"direction": "import"},
            files={"file": ("bad.zip", b"not a zip", "application/zip")},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "error=" in r.headers["location"]
        assert "/declarations/upload" in r.headers["location"]


def test_commit_with_unknown_staging_id_redirects_with_error(
    bulk_route_client,
):
    with TestClient(app) as tc:
        _login(tc)
        r = tc.post(
            f"/clients/{bulk_route_client}/declarations/upload-zip/"
            f"zip-00000000-0000-0000-0000-000000000000/commit",
            data={"direction": "import"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        loc = r.headers["location"]
        assert "/declarations/upload" in loc
        assert "error=" in loc


def test_cancel_removes_staging_and_redirects(bulk_route_client):
    zip_bytes = _make_zip([
        ("00000001_107555100001.xls", _make_xls("107555100001")),
    ])
    with TestClient(app) as tc:
        _login(tc)
        r = tc.post(
            f"/clients/{bulk_route_client}/declarations/upload-zip",
            data={"direction": "import"},
            files={"file": ("upload.zip", zip_bytes, "application/zip")},
        )
        import re
        m = re.search(
            r"/declarations/upload-zip/(zip-[0-9a-f-]+)/commit", r.text,
        )
        staging_id = m.group(1)

        # Cancel.
        r2 = tc.post(
            f"/clients/{bulk_route_client}/declarations/upload-zip/"
            f"{staging_id}/cancel",
            follow_redirects=False,
        )
        assert r2.status_code == 303
        assert r2.headers["location"].endswith("/declarations/upload")

        # Re-commit on the cancelled id → unknown staging path.
        r3 = tc.post(
            f"/clients/{bulk_route_client}/declarations/upload-zip/"
            f"{staging_id}/commit",
            data={"direction": "import"},
            follow_redirects=False,
        )
        assert r3.status_code == 303
        assert "error=" in r3.headers["location"]


def test_upload_zip_requires_valid_direction(bulk_route_client):
    zip_bytes = _make_zip([
        ("00000001_107555200001.xls", _make_xls("107555200001")),
    ])
    with TestClient(app) as tc:
        _login(tc)
        r = tc.post(
            f"/clients/{bulk_route_client}/declarations/upload-zip",
            data={"direction": "sideways"},
            files={"file": ("upload.zip", zip_bytes, "application/zip")},
        )
        assert r.status_code == 400
