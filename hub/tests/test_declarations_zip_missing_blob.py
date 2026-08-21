"""Registered-but-missing blob handling in declarations download.zip.

Regression for the prod johnson-vn defect (2026-06-04): a
`customs_declaration_files` row exists and the manifest names the file,
but the blob is absent from the storage backend. The builder used to
`except FileNotFoundError: continue` — silently dropping the file while
the manifest still reported "Đã có file: N / Thiếu file: 0". The ZIP
came back with only the manifest and the operator/CO had no signal that
content was missing.

Expected now: the missing-content file is surfaced — a manifest count
line + per-file annotation + a FILE_THIEU_NOI_DUNG.txt marker — instead
of vanishing. Both routes share `_build_declarations_zip`, so the
Bearer and cookie outputs stay byte-identical.
"""
from __future__ import annotations

import io
import secrets
import zipfile

import pytest
from fastapi.testclient import TestClient

from hub.app.database import connect
from hub.app.main import app
from hub.app.storage import get_backend


MARKER = "FILE_THIEU_NOI_DUNG.txt"
MANIFEST = "DANH_SACH_TO_KHAI.txt"
COOKIE_URL = "/clients/{cid}/declarations/download.zip"
BEARER_URL = "/v1/hub/clients/{cid}/declarations/download.zip"


def _client() -> TestClient:
    return TestClient(app)


def _login(c: TestClient) -> None:
    r = c.post(
        "/login",
        data={"email": "admin@data-hub.local", "password": "admin123",
              "next": "/clients"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text


@pytest.fixture
def files_root(tmp_path, monkeypatch):
    root = tmp_path / "files"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(root))
    import hub.app.storage as storage_mod
    storage_mod._BACKEND = None
    yield root
    storage_mod._BACKEND = None


@pytest.fixture
def auth_disabled(monkeypatch):
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")


def _insert_file_row(cur, *, cid, decl, direction, backend_key, name):
    cur.execute(
        """insert into hub.customs_declaration_files
           (client_id, declaration_no, direction, file_kind,
            backend_key, original_filename, sha256, size_bytes)
           values (%s, %s, %s, 'xls', %s, %s, %s, %s)""",
        (cid, decl, direction, backend_key, name,
         secrets.token_hex(32), 0),
    )


@pytest.fixture
def seeded(files_root, auth_disabled):
    """One import declaration MISS001 with a single file row whose blob
    is never written to the backend (registered-but-missing)."""
    cid = "miss-blob-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (cid, "Missing blob test"),
        )
        _insert_file_row(
            cur, cid=cid, decl="MISS001", direction="import",
            backend_key="customs_declarations/test/never_put_ghost.xls",
            name="ghost_107271918940.xls",
        )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.customs_declaration_files where client_id=%s",
            (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


@pytest.fixture
def seeded_mixed(files_root, auth_disabled):
    """OK001 has a real blob; MISS001 is registered-but-missing."""
    cid = "miss-mixed-" + secrets.token_hex(4)
    backend = get_backend()
    real_key = f"customs_declarations/test/{secrets.token_hex(4)}_real.xls"
    backend.put(b"REAL-CONTENT", key=real_key)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (cid, "Mixed blob test"),
        )
        _insert_file_row(cur, cid=cid, decl="OK001", direction="import",
                         backend_key=real_key, name="real.xls")
        _insert_file_row(
            cur, cid=cid, decl="MISS001", direction="import",
            backend_key="customs_declarations/test/never_put_ghost2.xls",
            name="ghost.xls")
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.customs_declaration_files where client_id=%s",
            (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


def _zip(content: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(content))


# ── missing blob is surfaced, not silently dropped (Bearer) ─────────


def test_missing_blob_surfaced_in_marker_and_manifest(seeded):
    r = _client().get(
        BEARER_URL.format(cid=seeded),
        params={"direction": "import", "declaration_nos": "MISS001"},
    )
    assert r.status_code == 200, r.text
    zf = _zip(r.content)
    names = set(zf.namelist())
    # Archive is well-formed: manifest + dedicated missing-content marker.
    assert MANIFEST in names
    assert MARKER in names, f"missing-content marker absent; names={names}"
    manifest = zf.read(MANIFEST).decode("utf-8")
    # The gap is counted and annotated, not hidden as "Thiếu file: 0".
    assert "File thiếu nội dung trên máy chủ: 1" in manifest
    assert "[THIẾU NỘI DUNG]" in manifest
    # The marker names the affected file so CO can act on it.
    marker = zf.read(MARKER).decode("utf-8")
    assert "ghost_107271918940.xls" in marker
    assert "MISS001" in marker


# ── healthy file present, ghost flagged (mixed) ─────────────────────


def test_mixed_present_blob_embedded_and_missing_flagged(seeded_mixed):
    r = _client().get(
        BEARER_URL.format(cid=seeded_mixed),
        params={"direction": "import", "declaration_nos": "OK001,MISS001"},
    )
    assert r.status_code == 200, r.text
    zf = _zip(r.content)
    names = set(zf.namelist())
    # Present blob is embedded with its bytes intact.
    assert "real.xls" in names
    assert zf.read("real.xls") == b"REAL-CONTENT"
    # Ghost is flagged, not embedded.
    assert "ghost.xls" not in names
    assert MARKER in names
    manifest = zf.read(MANIFEST).decode("utf-8")
    assert "File thiếu nội dung trên máy chủ: 1" in manifest


# ── golden: Bearer bytes == cookie bytes for the same params ────────


def test_bearer_equals_cookie_for_missing_blob(seeded):
    bearer = _client().get(
        BEARER_URL.format(cid=seeded),
        params={"direction": "import", "declaration_nos": "MISS001"},
    )
    cookie_c = _client()
    _login(cookie_c)
    cookie = cookie_c.get(
        COOKIE_URL.format(cid=seeded),
        params={"direction": "import", "declaration_nos": "MISS001"},
    )
    assert bearer.status_code == cookie.status_code == 200
    assert bearer.content == cookie.content, (
        "Bearer and cookie routes must return byte-identical archives"
    )
