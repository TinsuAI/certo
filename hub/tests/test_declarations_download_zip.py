"""Tests for `GET /clients/{c}/declarations/download.zip`.

Cookie-session route for operator bulk download of customs files.
Per contract spec
`barry-CO-main/.ai/api-requests/2026-05-15-declaration-file-status.md`:

- Login required; unauthenticated → 303 to `/login?next=…`.
- direction + declaration_nos both required.
- ZIP contains files at root level (no per-declaration subfolders).
- Duplicate original filenames → suffixed _1, _2, …
- Always includes `DANH_SACH_TO_KHAI.txt`.
- When no files match: archive still returned with manifest +
  `NO_FILES_FOUND.txt`.
"""
from __future__ import annotations

import io
import os
import secrets
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.main import app
from app.storage import get_backend


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


def _put_backend_blob(backend, *, filename: str, blob: bytes) -> str:
    """Persist a blob via the FileBackend and return its backend_key."""
    key = f"customs_declarations/test/{secrets.token_hex(4)}_{filename}"
    backend.put(blob, key=key)
    return key


def _seed_bcct(cur, *, client_id, decl_no, direction):
    cur.execute(
        """insert into hub.bcct_rows
           (client_id, transaction_key, line_no, declaration_no,
            declaration_type, direction, registration_date,
            customs_code, goods_name, payload)
           values (%s, %s, '1', %s, %s, %s, '2026-04-21',
                   'MAT-X', 'desc', '{}'::jsonb)""",
        (client_id, f"TX-{decl_no}-{direction}", decl_no,
         "E11" if direction == "import" else "E42", direction),
    )


def _insert_file_row(cur, *, client_id, decl_no, direction,
                     backend_key, original_filename, sha256=None,
                     size_bytes=0, file_kind="pdf"):
    cur.execute(
        """insert into hub.customs_declaration_files
           (client_id, declaration_no, direction, file_kind,
            backend_key, original_filename, sha256, size_bytes)
           values (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (client_id, decl_no, direction, file_kind,
         backend_key, original_filename,
         sha256 or secrets.token_hex(32), size_bytes),
    )


@pytest.fixture
def files_root(tmp_path, monkeypatch):
    """Isolate FileBackend root per test so blobs are throwaway."""
    root = tmp_path / "files"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(root))
    # Reset module-level cached backend so it re-reads the env var.
    import app.storage as storage_mod
    storage_mod._BACKEND = None
    yield root
    storage_mod._BACKEND = None


@pytest.fixture
def seeded(files_root):
    """A client with:
      Imports:
        DEC001 — 1 file (`tk.pdf`, 8 bytes)
        DEC002 — 2 files, both named `tk.pdf` (dedupe test)
        DEC003 — 0 files (BCCT only, present in BCCT but no upload)
      Exports:
        DEC003 — 1 file (`export.pdf`)
    """
    cid = "decl-zip-" + secrets.token_hex(4)
    backend = get_backend()

    def put(name: str, blob: bytes) -> str:
        return _put_backend_blob(backend, filename=name, blob=blob)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (cid, "Decl ZIP test"),
        )
        for decl, dirn in [("DEC001", "import"), ("DEC002", "import"),
                           ("DEC003", "import"), ("DEC003", "export")]:
            _seed_bcct(cur, client_id=cid, decl_no=decl, direction=dirn)
        # DEC001 import: 1 pdf, content "DEC001-1"
        _insert_file_row(
            cur, client_id=cid, decl_no="DEC001", direction="import",
            backend_key=put("tk.pdf", b"DEC001-1"),
            original_filename="tk.pdf",
        )
        # DEC002 import: 2 pdfs with identical original_filename
        _insert_file_row(
            cur, client_id=cid, decl_no="DEC002", direction="import",
            backend_key=put("tk.pdf", b"DEC002-A"),
            original_filename="tk.pdf",
        )
        _insert_file_row(
            cur, client_id=cid, decl_no="DEC002", direction="import",
            backend_key=put("tk.pdf", b"DEC002-B"),
            original_filename="tk.pdf",
        )
        # DEC003 export: 1 pdf
        _insert_file_row(
            cur, client_id=cid, decl_no="DEC003", direction="export",
            backend_key=put("export.pdf", b"DEC003-EXP"),
            original_filename="export.pdf",
        )

    yield cid

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.customs_declaration_files where client_id=%s",
            (cid,),
        )
        cur.execute(
            "delete from hub.bcct_rows where client_id=%s", (cid,),
        )
        cur.execute(
            "delete from hub.bcct_row_history where client_id=%s", (cid,),
        )
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


# ─── Auth bounce ─────────────────────────────────────────────────────


def test_unauth_redirects_to_login(seeded):
    """No cookie → 303 to /login?next=… preserving the original URL."""
    c = _client()
    r = c.get(
        f"/clients/{seeded}/declarations/download.zip"
        "?direction=import&declaration_nos=DEC001",
        follow_redirects=False,
    )
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/login?next=")
    # The next param must encode the original path + query so the
    # operator lands back here after sign-in.
    assert "declarations" in loc
    assert "DEC001" in loc


# ─── Validation ──────────────────────────────────────────────────────


def test_missing_direction_returns_400(seeded):
    c = _client()
    _login(c)
    r = c.get(
        f"/clients/{seeded}/declarations/download.zip?declaration_nos=DEC001",
    )
    assert r.status_code == 400


def test_invalid_direction_returns_400(seeded):
    c = _client()
    _login(c)
    r = c.get(
        f"/clients/{seeded}/declarations/download.zip"
        "?direction=sideways&declaration_nos=DEC001",
    )
    assert r.status_code == 400


def test_missing_declaration_nos_returns_400(seeded):
    c = _client()
    _login(c)
    r = c.get(
        f"/clients/{seeded}/declarations/download.zip?direction=import",
    )
    assert r.status_code == 400


def test_unknown_client_returns_404(files_root):
    c = _client()
    _login(c)
    r = c.get(
        "/clients/no-such-" + secrets.token_hex(4)
        + "/declarations/download.zip?direction=import&declaration_nos=X",
    )
    assert r.status_code in (403, 404)


# ─── ZIP content ─────────────────────────────────────────────────────


def _open_zip(r) -> zipfile.ZipFile:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(r.content))


def test_zip_contains_files_at_root(seeded):
    c = _client()
    _login(c)
    r = c.get(
        f"/clients/{seeded}/declarations/download.zip"
        "?direction=import&declaration_nos=DEC001",
    )
    zf = _open_zip(r)
    names = zf.namelist()
    assert "tk.pdf" in names
    # Manifest always present.
    assert "DANH_SACH_TO_KHAI.txt" in names
    # No subfolders.
    assert all("/" not in n for n in names)


def test_zip_dedupes_duplicate_filenames(seeded):
    """DEC002 has 2 files both named `tk.pdf` — second should land
    at `tk_1.pdf` so neither overwrites the other."""
    c = _client()
    _login(c)
    r = c.get(
        f"/clients/{seeded}/declarations/download.zip"
        "?direction=import&declaration_nos=DEC002",
    )
    zf = _open_zip(r)
    names = sorted(zf.namelist())
    pdf_names = [n for n in names if n.endswith(".pdf")]
    assert len(pdf_names) == 2
    assert set(pdf_names) == {"tk.pdf", "tk_1.pdf"}
    # Content of both members is preserved.
    contents = {zf.read(n) for n in pdf_names}
    assert contents == {b"DEC002-A", b"DEC002-B"}


def test_manifest_lists_present_and_missing(seeded):
    """DEC001 has files, DEC003 (import) has none — manifest counts +
    sections must reflect this."""
    c = _client()
    _login(c)
    r = c.get(
        f"/clients/{seeded}/declarations/download.zip"
        "?direction=import&declaration_nos=DEC001,DEC003",
    )
    zf = _open_zip(r)
    manifest = zf.read("DANH_SACH_TO_KHAI.txt").decode("utf-8")
    assert "Tổng tờ khai yêu cầu: 2" in manifest
    assert "Đã có file: 1" in manifest
    assert "Thiếu file: 1" in manifest
    assert "DEC001" in manifest
    assert "DEC003" in manifest
    # The "missing" section names DEC003 specifically.
    missing_section = manifest.split("== Tờ khai thiếu file ==")[1]
    assert "DEC003" in missing_section
    assert "DEC001" not in missing_section


def test_zip_with_no_matching_files_has_marker(seeded):
    """Requesting only declarations that have zero files yields a
    ZIP containing only the manifest + `NO_FILES_FOUND.txt`."""
    c = _client()
    _login(c)
    r = c.get(
        f"/clients/{seeded}/declarations/download.zip"
        "?direction=import&declaration_nos=DEC003",
    )
    zf = _open_zip(r)
    names = sorted(zf.namelist())
    assert names == ["DANH_SACH_TO_KHAI.txt", "NO_FILES_FOUND.txt"]
    marker = zf.read("NO_FILES_FOUND.txt").decode("utf-8")
    assert "DANH_SACH_TO_KHAI" in marker


def test_zip_respects_direction_identity(seeded):
    """DEC003 has 0 import files but 1 export file; the same decl_no
    must yield different archives depending on direction."""
    c = _client()
    _login(c)
    r_import = c.get(
        f"/clients/{seeded}/declarations/download.zip"
        "?direction=import&declaration_nos=DEC003",
    )
    r_export = c.get(
        f"/clients/{seeded}/declarations/download.zip"
        "?direction=export&declaration_nos=DEC003",
    )
    zf_i = _open_zip(r_import)
    zf_e = _open_zip(r_export)
    assert "NO_FILES_FOUND.txt" in zf_i.namelist()
    assert "export.pdf" in zf_e.namelist()
    assert "NO_FILES_FOUND.txt" not in zf_e.namelist()


def test_archive_filename_param_honored(seeded):
    """The optional `filename` param shapes Content-Disposition."""
    c = _client()
    _login(c)
    r = c.get(
        f"/clients/{seeded}/declarations/download.zip"
        "?direction=import&declaration_nos=DEC001&filename=TKX_DEC001",
    )
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert "TKX_DEC001.zip" in cd


def test_archive_filename_sanitized(seeded):
    """Caller cannot inject path separators / quotes via filename."""
    c = _client()
    _login(c)
    r = c.get(
        f"/clients/{seeded}/declarations/download.zip"
        '?direction=import&declaration_nos=DEC001&filename=../../etc/passwd',
    )
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert ".." not in cd
    assert "/" not in cd.split("filename=")[1]
