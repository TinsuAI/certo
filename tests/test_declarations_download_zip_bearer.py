"""Provider tests for the Bearer mirror of declarations download.zip.

Contract spec:
`barry-CO-main/.ai/api-requests/2026-05-28-bcct-declarations-download-bearer.md`.

Cookie route at `/clients/{c}/declarations/download.zip` stays in place
(operator-browser flow). This Bearer mirror at
`/v1/hub/clients/{c}/declarations/download.zip` is for CO's
server-to-server dossier builder.

Auth-disabled tests exercise the body shape + error paths; strict-mode
tests exercise the service-token scope + client whitelist enforcement.
"""
from __future__ import annotations

import io
import secrets
import tempfile
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import jwt_issuer, settings_store
from app.database import connect
from app.main import app
from app.storage import get_backend
from app.stores import service_accounts as sa_store


URL_TMPL = "/v1/hub/clients/{cid}/declarations/download.zip"


def _url(client_id: str) -> str:
    return URL_TMPL.format(cid=client_id)


def _client() -> TestClient:
    return TestClient(app)


def _auth_header(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def files_root(tmp_path, monkeypatch):
    root = tmp_path / "files"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_HUB_FILES_ROOT", str(root))
    import app.storage as storage_mod
    storage_mod._BACKEND = None
    yield root
    storage_mod._BACKEND = None


def _seed_files(cid: str) -> None:
    backend = get_backend()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict do nothing",
            (cid, "Bearer zip test"),
        )
        for decl, dirn, blob, name in [
            ("DEC001", "import", b"DEC001-1", "tk.pdf"),
            ("DEC002", "import", b"DEC002-A", "tk.pdf"),
            ("DEC003", "export", b"DEC003-EXP", "export.pdf"),
        ]:
            key = f"customs_declarations/test/{secrets.token_hex(4)}_{name}"
            backend.put(blob, key=key)
            cur.execute(
                """insert into hub.customs_declaration_files
                   (client_id, declaration_no, direction, file_kind,
                    backend_key, original_filename, sha256, size_bytes)
                   values (%s, %s, %s, 'pdf', %s, %s, %s, %s)""",
                (cid, decl, dirn, key, name,
                 secrets.token_hex(32), len(blob)),
            )


def _teardown(cid: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.customs_declaration_files where client_id=%s",
            (cid,),
        )
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


@pytest.fixture
def auth_disabled(monkeypatch):
    monkeypatch.setenv("DATA_HUB_API_AUTH_DISABLED", "1")


@pytest.fixture
def seeded(files_root, auth_disabled):
    cid = "bearer-zip-" + secrets.token_hex(4)
    _seed_files(cid)
    yield cid
    _teardown(cid)


# ─── Happy paths ─────────────────────────────────────────────────────


def test_returns_zip_with_files_and_manifest(seeded):
    r = _client().get(
        _url(seeded),
        params={"direction": "import", "declaration_nos": "DEC001,DEC002"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert "DANH_SACH_TO_KHAI.txt" in names
    # Two import files with colliding original_filename → deduped.
    pdfs = [n for n in names if n.endswith(".pdf")]
    assert len(pdfs) == 2


def test_default_filename_when_omitted(seeded):
    r = _client().get(
        _url(seeded),
        params={"direction": "import", "declaration_nos": "DEC001"},
    )
    assert r.status_code == 200
    # Spec: default `declarations_{client_id}_{direction}.zip`.
    cd = r.headers["content-disposition"]
    assert f'declarations_{seeded}_import.zip' in cd


def test_zero_match_returns_well_formed_zip(seeded):
    r = _client().get(
        _url(seeded),
        params={"direction": "import", "declaration_nos": "DOES-NOT-EXIST"},
    )
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert "DANH_SACH_TO_KHAI.txt" in names
    assert "NO_FILES_FOUND.txt" in names


def test_export_direction_returns_export_file(seeded):
    r = _client().get(
        _url(seeded),
        params={"direction": "export", "declaration_nos": "DEC003"},
    )
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    pdfs = [n for n in zf.namelist() if n.endswith(".pdf")]
    assert pdfs == ["export.pdf"]


# ─── Error paths ─────────────────────────────────────────────────────


def test_missing_direction_returns_400(seeded):
    r = _client().get(
        _url(seeded),
        params={"declaration_nos": "DEC001"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_direction"


def test_invalid_direction_returns_400(seeded):
    r = _client().get(
        _url(seeded),
        params={"direction": "sideways", "declaration_nos": "DEC001"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_direction"


def test_missing_declaration_nos_returns_400(seeded):
    r = _client().get(
        _url(seeded),
        params={"direction": "import"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "declaration_nos_required"


def test_too_many_declaration_nos_returns_400(seeded):
    nos = ",".join(f"D{i:04d}" for i in range(501))
    r = _client().get(
        _url(seeded),
        params={"direction": "import", "declaration_nos": nos},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "too_many_declaration_nos"


def test_unknown_client_returns_404(auth_disabled, files_root):
    r = _client().get(
        _url("does-not-exist"),
        params={"direction": "import", "declaration_nos": "DEC001"},
    )
    assert r.status_code == 404


# ─── Strict-mode auth (service token) ────────────────────────────────


@pytest.fixture
def isolated_keys_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_HUB_KEYS_DIR", d)
        yield Path(d)


@pytest.fixture
def strict_mode_on(isolated_keys_dir):
    settings_store.set_many({"api_auth_strict": "true"})
    yield
    settings_store.set_many({"api_auth_strict": "false"})


@pytest.fixture
def auth_seeded(files_root, strict_mode_on):
    cid = "bearer-zip-auth-" + secrets.token_hex(4)
    _seed_files(cid)
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.service_accounts where name like 'sa_test_%'"
        )
        cur.execute(
            "delete from hub.revoked_service_tokens "
            "where revoked_by='sa_test_runner'"
        )
    _teardown(cid)


def test_service_token_with_hub_read_returns_zip(auth_seeded):
    sa_store.create_account(
        name="sa_test_co", description="", scopes=["hub:read"],
        client_ids=None, created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"], client_ids=None,
    )
    r = _client().get(
        _url(auth_seeded),
        params={"direction": "import", "declaration_nos": "DEC001"},
        headers=_auth_header(out["access_token"]),
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"


def test_service_token_without_hub_read_rejected(auth_seeded):
    sa_store.create_account(
        name="sa_test_co", description="", scopes=["bom:propose"],
        client_ids=None, created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["bom:propose"], client_ids=None,
    )
    r = _client().get(
        _url(auth_seeded),
        params={"direction": "import", "declaration_nos": "DEC001"},
        headers=_auth_header(out["access_token"]),
    )
    assert r.status_code == 403


def test_service_token_client_whitelist_blocks_non_listed(auth_seeded):
    sa_store.create_account(
        name="sa_test_co", description="", scopes=["hub:read"],
        client_ids=["a-different-client"],
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"],
        client_ids=["a-different-client"],
    )
    r = _client().get(
        _url(auth_seeded),
        params={"direction": "import", "declaration_nos": "DEC001"},
        headers=_auth_header(out["access_token"]),
    )
    assert r.status_code == 403


def test_no_bearer_in_strict_mode_returns_401(auth_seeded):
    r = _client().get(
        _url(auth_seeded),
        params={"direction": "import", "declaration_nos": "DEC001"},
    )
    assert r.status_code == 401
