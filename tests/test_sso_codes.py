"""One-time SSO codes are Postgres-backed, not per-process memory.

The old `_SSO_CODES` dict meant /authorize and /exchange had to land on the
same uvicorn worker. These cover the properties the dict could not give:
durability across processes, and a single-use consume that survives a race.
"""
from __future__ import annotations

import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.database import connect
from app.main import app
from app.routes import auth_api
from app.stores import sso_codes

REDIRECT = "http://co.test/auth/callback"


@pytest.fixture(autouse=True)
def isolated_keys_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_HUB_KEYS_DIR", d)
        yield Path(d)


@pytest.fixture(autouse=True)
def allowed_redirect_origin(monkeypatch):
    monkeypatch.setenv("DATA_HUB_SSO_ALLOWED_REDIRECT_ORIGINS", "http://co.test")


@pytest.fixture
def stub_user(monkeypatch):
    user = auth.User(
        user_id="u_sso_codes",
        email="sso-codes@example.test",
        display_name="SSO Codes",
        role="admin",
        status="active",
    )
    monkeypatch.setattr(auth_api.auth, "current_user", lambda _request: user)
    yield user
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.sso_codes where user_id = %s", (user.user_id,))


def _authorize(client: TestClient) -> str:
    response = client.get(
        f"/v1/auth/authorize?redirect_uri={REDIRECT}&state=/clients",
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return parse_qs(urlsplit(response.headers["location"]).query)["code"][0]


def _exchange(client: TestClient, code: str, redirect_uri: str = REDIRECT):
    return client.post("/v1/auth/exchange", json={"code": code, "redirect_uri": redirect_uri})


def test_code_is_persisted_to_postgres_not_process_memory(stub_user):
    code = _authorize(TestClient(app))

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select user_id, redirect_uri, used_at from hub.sso_codes where code_hash = %s",
                (sso_codes._hash(code),),
            )
            row = cur.fetchone()

    assert row is not None, "code must survive outside the worker that minted it"
    assert row[0] == stub_user.user_id
    assert row[1] == REDIRECT
    assert row[2] is None


def test_code_plaintext_is_never_stored(stub_user):
    code = _authorize(TestClient(app))

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from hub.sso_codes where code_hash = %s", (code,))
            (hits,) = cur.fetchone()

    assert hits == 0


def test_exchange_by_a_different_client_instance_succeeds(stub_user):
    """Stand-in for `/authorize` on worker A, `/exchange` on worker B."""
    code = _authorize(TestClient(app))

    response = _exchange(TestClient(app), code)

    assert response.status_code == 200
    assert response.json()["access_token"]


def test_code_is_single_use(stub_user):
    client = TestClient(app)
    code = _authorize(client)

    first = _exchange(client, code)
    second = _exchange(client, code)

    assert first.status_code == 200
    assert second.status_code == 401


def test_concurrent_exchange_of_one_code_yields_exactly_one_winner(stub_user):
    code = _authorize(TestClient(app))
    barrier = threading.Barrier(2)

    def attempt() -> int:
        client = TestClient(app)
        barrier.wait(timeout=10)
        return _exchange(client, code).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(f.result() for f in [pool.submit(attempt), pool.submit(attempt)])

    assert results == [200, 401]


def test_expired_code_is_rejected(stub_user):
    client = TestClient(app)
    code = _authorize(client)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.sso_codes set expires_at = now() - interval '1 second' "
                "where code_hash = %s",
                (sso_codes._hash(code),),
            )

    assert _exchange(client, code).status_code == 401


def test_redirect_uri_mismatch_does_not_spend_the_code(stub_user, monkeypatch):
    """Matches the old dict behaviour: the entry was popped only after the
    redirect_uri check passed."""
    monkeypatch.setenv("DATA_HUB_SSO_ALLOWED_REDIRECT_ORIGINS", "http://co.test,http://evil.test")
    client = TestClient(app)
    code = _authorize(client)

    mismatch = _exchange(client, code, "http://evil.test/auth/callback")

    assert mismatch.status_code == 401
    assert _exchange(client, code).status_code == 200


def test_logout_invalidates_outstanding_codes():
    """A code minted from a session must die with that session."""
    user_id = "u_sso_codes_logout"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.users where user_id = %s", (user_id,))
            cur.execute(
                """
                insert into hub.users (user_id, email, display_name, password_hash, role)
                values (%s, 'sso-codes-logout@example.test', 'Logout', %s, 'admin')
                """,
                (user_id, auth.hash_password("test")),
            )
    session_id = auth.create_session(user_id)
    client = TestClient(app)
    client.cookies.set(auth.SESSION_COOKIE, session_id)
    try:
        code = _authorize(client)
        auth.revoke_session(session_id)

        assert _exchange(client, code).status_code == 401
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from hub.users where user_id = %s", (user_id,))
