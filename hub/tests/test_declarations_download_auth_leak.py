"""Regression tests for the 2026-06-06 auth-bypass leak.

Prod was running with `DATA_HUB_API_AUTH_DISABLED=1` and
`api_auth_strict=false`, so the dev kill-switch disabled every bearer
check on `/v1/hub/*` — the declaration download.pdf / download.zip /
metadata endpoints returned real customs documents to anonymous callers.
Secondarily, Cloudflare cached the `.pdf`/`.zip` 200s by extension.

These tests pin the enforced behavior under strict mode (the prod
config after the fix) and assert the `Cache-Control: no-store` header
that stops CDN caching. Spec:
`.ai/api-requests/2026-06-06-declarations-download-unauthenticated-leak.md`.
"""
from __future__ import annotations

import secrets
import tempfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from hub.app import jwt_issuer, settings_store
from hub.app.database import connect
from hub.app.main import app
from hub.app.storage import get_backend, sha256_bytes
from hub.app.stores import service_accounts as sa_store

PDF_URL = "/v1/hub/clients/{cid}/declarations/download.pdf"
ZIP_URL = "/v1/hub/clients/{cid}/declarations/download.zip"
META_URL = "/v1/hub/clients/{cid}/declarations"


def _client() -> TestClient:
    return TestClient(app)


def _auth(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def _blank_pdf() -> bytes:
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = BytesIO()
    w.write(buf)
    return buf.getvalue()


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
def seeded(files_root, strict_mode_on):
    cid = "leak-" + secrets.token_hex(4)
    backend = get_backend()
    blob = _blank_pdf()
    key = f"customs_declarations/{cid}/{secrets.token_hex(4)}_tk.pdf"
    backend.put(blob, key=key)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s,%s)",
            (cid, "Leak regression"),
        )
        cur.execute(
            """insert into hub.bcct_rows
               (client_id, transaction_key, line_no, declaration_no,
                declaration_type, direction, registration_date,
                customs_code, goods_name, payload)
               values (%s,%s,'1','DEC1','E11','import','2026-04-21',
                       'MAT-X','desc','{}'::jsonb)""",
            (cid, f"TX-{cid}"),
        )
        cur.execute(
            """insert into hub.customs_declaration_files
               (client_id, declaration_no, direction, file_kind,
                backend_key, original_filename, sha256, size_bytes)
               values (%s,'DEC1','import','pdf',%s,'tk.pdf',%s,%s)""",
            (cid, key, sha256_bytes(blob), len(blob)),
        )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.customs_declaration_files where client_id=%s", (cid,))
        cur.execute("delete from hub.bcct_rows where client_id=%s", (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))
        cur.execute("delete from hub.service_accounts where name like 'sa_leak_%'")


def _token(*, name, client_ids):
    sa_store.create_account(
        name=name, description="", scopes=["hub:read"],
        client_ids=client_ids, created_by="sa_leak_runner",
    )
    return jwt_issuer.make_service_token(
        name=name, scopes=["hub:read"], client_ids=client_ids,
    )["access_token"]


def _params():
    return {"direction": "import", "declaration_nos": "DEC1"}


# ─── The leak: anonymous must be 401, not 200 ────────────────────────


@pytest.mark.parametrize("url_tmpl", [PDF_URL, ZIP_URL, META_URL])
def test_anonymous_is_401(seeded, url_tmpl):
    r = _client().get(url_tmpl.format(cid=seeded), params=_params())
    assert r.status_code == 401, f"{url_tmpl} leaked: {r.status_code}"
    # Standard FastAPI HTTPException shape — the exact contract CO checks.
    assert r.json() == {"detail": "bearer token required"}
    # Whatever the status, an unauthenticated response must never carry
    # document bytes.
    assert not r.content.startswith(b"%PDF")
    assert not r.content.startswith(b"PK\x03\x04")


@pytest.mark.parametrize("url_tmpl", [PDF_URL, ZIP_URL, META_URL])
def test_garbage_bearer_is_401(seeded, url_tmpl):
    r = _client().get(
        url_tmpl.format(cid=seeded), params=_params(),
        headers=_auth("not-a-real-jwt"),
    )
    assert r.status_code == 401


@pytest.mark.parametrize("url_tmpl", [PDF_URL, ZIP_URL, META_URL])
def test_wrong_client_bearer_is_403(seeded, url_tmpl):
    tok = _token(name="sa_leak_other", client_ids=["a-different-client"])
    r = _client().get(
        url_tmpl.format(cid=seeded), params=_params(), headers=_auth(tok),
    )
    assert r.status_code == 403
    # Cross-tenant guard: a token for client A must get NO file bytes of
    # client B — the body is the JSON error, not a document.
    assert r.headers.get("content-type", "").startswith("application/json")
    assert not r.content.startswith(b"%PDF")
    assert not r.content.startswith(b"PK\x03\x04")


def test_authorized_bearer_gets_pdf_and_zip(seeded):
    tok = _token(name="sa_leak_ok", client_ids=[seeded])
    c = _client()
    rp = c.get(PDF_URL.format(cid=seeded), params=_params(), headers=_auth(tok))
    assert rp.status_code == 200
    assert rp.headers["content-type"] == "application/pdf"
    rz = c.get(ZIP_URL.format(cid=seeded), params=_params(), headers=_auth(tok))
    assert rz.status_code == 200
    assert rz.headers["content-type"] == "application/zip"


# ─── Cloudflare-cache mitigation: no-store on the document responses ──


def test_download_responses_are_no_store(seeded):
    tok = _token(name="sa_leak_ns", client_ids=[seeded])
    c = _client()
    for url in (PDF_URL, ZIP_URL, META_URL):
        r = c.get(url.format(cid=seeded), params=_params(), headers=_auth(tok))
        assert r.status_code == 200
        assert "no-store" in r.headers.get("cache-control", ""), url
