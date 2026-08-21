"""Refresh-token flow: POST /v1/auth/exchange -> refresh_token, and
POST /v1/auth/refresh -> a fresh access token with no user interaction.

These drive real SSO sessions (a row in `hub.sessions` plus the cookie)
rather than stubbing `current_user`, because the refresh token is bound to
the session and that binding is half of what is under test.
"""
from __future__ import annotations

import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from hub.app import auth
from hub.app import jwt_issuer
from hub.app.database import connect
from hub.app.main import app
from hub.app.stores import sso_refresh

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
def operator():
    """A staff user with read access to client A only, plus a live SSO
    session. Client B exists but is not granted — it is what a later
    widening of the ACL grants."""
    user_id = "u_refresh_staff"
    client_a, client_b = "refresh-client-a", "refresh-client-b"
    _purge_operator(user_id, (client_a, client_b))
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.users (user_id, email, display_name, password_hash, role)
                values (%s, 'refresh-staff@example.test', 'Refresh Staff', %s, 'staff')
                """,
                (user_id, auth.hash_password("test")),
            )
            for client_id in (client_a, client_b):
                cur.execute(
                    "insert into hub.clients (client_id, name) values (%s, %s)",
                    (client_id, client_id),
                )
            cur.execute(
                """
                insert into hub.user_client_access (user_id, client_id, scope, granted_by)
                values (%s, %s, 'read', %s)
                """,
                (user_id, client_a, user_id),
            )
    session_id = auth.create_session(user_id)
    try:
        yield SimpleNamespace(
            user_id=user_id,
            session_id=session_id,
            client_a=client_a,
            client_b=client_b,
        )
    finally:
        _purge_operator(user_id, (client_a, client_b))


def _purge_operator(user_id: str, client_ids: tuple[str, ...]) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.sso_refresh_tokens where user_id = %s", (user_id,))
            cur.execute("delete from hub.user_client_access where user_id = %s", (user_id,))
            cur.execute("delete from hub.sessions where user_id = %s", (user_id,))
            cur.execute("delete from hub.users where user_id = %s", (user_id,))
            cur.execute("delete from hub.clients where client_id = any(%s)", (list(client_ids),))


def _client(session_id: str) -> TestClient:
    client = TestClient(app)
    client.cookies.set(auth.SESSION_COOKIE, session_id)
    return client


def _exchange(client: TestClient) -> dict:
    authorize = client.get(
        f"/v1/auth/authorize?redirect_uri={REDIRECT}&state=/clients",
        follow_redirects=False,
    )
    assert authorize.status_code == 303, authorize.text
    code = parse_qs(urlsplit(authorize.headers["location"]).query)["code"][0]
    response = client.post(
        "/v1/auth/exchange", json={"code": code, "redirect_uri": REDIRECT}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _refresh(client: TestClient, refresh_token: str):
    return client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})


def _row(refresh_token: str) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select family_id, expires_at, absolute_expires_at, used_at, revoked_at
                from hub.sso_refresh_tokens where token_hash = %s
                """,
                (sso_refresh._hash(refresh_token),),
            )
            row = cur.fetchone()
    assert row is not None
    return dict(zip(("family_id", "expires_at", "absolute_expires_at", "used_at", "revoked_at"), row))


# ── exchange ────────────────────────────────────────────────────────────


def test_exchange_returns_refresh_token(operator):
    body = _exchange(_client(operator.session_id))

    assert body["access_token"]
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == jwt_issuer.get_token_ttl_seconds()
    assert body["refresh_token"]
    # Opaque, not a JWT — CO must never try to decode it.
    assert body["refresh_token"].count(".") != 2


def test_exchange_stores_only_a_hash_of_the_refresh_token(operator):
    body = _exchange(_client(operator.session_id))

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) from hub.sso_refresh_tokens where token_hash = %s",
                (body["refresh_token"],),
            )
            (plaintext_hits,) = cur.fetchone()

    assert plaintext_hits == 0
    assert _row(body["refresh_token"])["family_id"]


# ── refresh happy path ──────────────────────────────────────────────────


def test_refresh_issues_new_access_token_with_identical_claims(operator):
    client = _client(operator.session_id)
    original = _exchange(client)
    original_claims = jwt_issuer.verify_token(original["access_token"])

    refreshed = _refresh(client, original["refresh_token"])

    assert refreshed.status_code == 200, refreshed.text
    body = refreshed.json()
    claims = jwt_issuer.verify_token(body["access_token"])
    assert claims["sub"] == original_claims["sub"] == operator.user_id
    assert claims["role"] == original_claims["role"] == "staff"
    assert claims["client_ids"] == original_claims["client_ids"] == [operator.client_a]
    assert "all_clients" not in claims
    assert body["expires_in"] == jwt_issuer.get_token_ttl_seconds()


def test_refresh_returns_a_rotated_refresh_token(operator):
    client = _client(operator.session_id)
    original = _exchange(client)

    body = _refresh(client, original["refresh_token"]).json()

    assert body["refresh_token"] != original["refresh_token"]
    # Same family, so revoking one revokes the lineage.
    assert _row(body["refresh_token"])["family_id"] == _row(original["refresh_token"])["family_id"]


def test_refresh_chains_across_several_rotations(operator):
    client = _client(operator.session_id)
    token = _exchange(client)["refresh_token"]

    for _ in range(3):
        body = _refresh(client, token).json()
        token = body["refresh_token"]

    assert jwt_issuer.verify_token(body["access_token"])["sub"] == operator.user_id


# ── rotation + replay ───────────────────────────────────────────────────


def test_spent_refresh_token_is_rejected(operator):
    client = _client(operator.session_id)
    original = _exchange(client)

    first = _refresh(client, original["refresh_token"])
    second = _refresh(client, original["refresh_token"])

    assert first.status_code == 200
    assert second.status_code == 401


def test_replay_within_grace_window_keeps_the_family_alive(operator):
    """A lost rotation race, or CO retrying a timed-out refresh, must not
    log the operator out."""
    client = _client(operator.session_id)
    original = _exchange(client)
    successor = _refresh(client, original["refresh_token"]).json()["refresh_token"]

    replay = _refresh(client, original["refresh_token"])

    assert replay.status_code == 401
    assert _row(successor)["revoked_at"] is None
    assert _refresh(client, successor).status_code == 200


def test_replay_past_grace_window_revokes_the_whole_family(operator):
    client = _client(operator.session_id)
    original = _exchange(client)
    successor = _refresh(client, original["refresh_token"]).json()["refresh_token"]

    # Backdate the rotation so the replay lands outside the grace window,
    # where it stops looking like a retry and starts looking like theft.
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.sso_refresh_tokens set used_at = now() - interval '10 minutes' "
                "where token_hash = %s",
                (sso_refresh._hash(original["refresh_token"]),),
            )

    replay = _refresh(client, original["refresh_token"])

    assert replay.status_code == 401
    assert _row(successor)["revoked_at"] is not None
    # The live token the attacker did not have is dead too.
    assert _refresh(client, successor).status_code == 401


def test_concurrent_refresh_yields_exactly_one_winner(operator):
    client = _client(operator.session_id)
    token = _exchange(client)["refresh_token"]

    barrier = threading.Barrier(2)

    def attempt() -> int:
        # Each thread needs its own TestClient: one ASGI portal apiece, so
        # the two refreshes genuinely overlap inside Postgres.
        local = _client(operator.session_id)
        barrier.wait(timeout=10)
        return _refresh(local, token).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(f.result() for f in [pool.submit(attempt), pool.submit(attempt)])

    assert results == [200, 401]


def test_rotation_never_extends_the_absolute_deadline(operator):
    client = _client(operator.session_id)
    original = _exchange(client)

    successor = _refresh(client, original["refresh_token"]).json()["refresh_token"]

    first, second = _row(original["refresh_token"]), _row(successor)
    assert second["absolute_expires_at"] == first["absolute_expires_at"]
    # ...while the sliding idle deadline does move forward.
    assert second["expires_at"] >= first["expires_at"]


# ── negatives ───────────────────────────────────────────────────────────


def test_refresh_without_body_is_400(operator):
    response = _client(operator.session_id).post("/v1/auth/refresh", json={})

    assert response.status_code == 400


def test_refresh_with_blank_token_is_400(operator):
    response = _refresh(_client(operator.session_id), "   ")

    assert response.status_code == 400


def test_refresh_rejects_an_access_token(operator):
    client = _client(operator.session_id)
    original = _exchange(client)

    response = _refresh(client, original["access_token"])

    assert response.status_code == 401
    # Rejected on shape, so the real refresh token is untouched.
    assert _refresh(client, original["refresh_token"]).status_code == 200


def test_refresh_with_unknown_token_is_401(operator):
    response = _refresh(_client(operator.session_id), "not-a-real-token")

    assert response.status_code == 401


def test_refresh_with_expired_token_is_401(operator):
    client = _client(operator.session_id)
    original = _exchange(client)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.sso_refresh_tokens set expires_at = now() - interval '1 minute' "
                "where token_hash = %s",
                (sso_refresh._hash(original["refresh_token"]),),
            )

    assert _refresh(client, original["refresh_token"]).status_code == 401


def test_refresh_past_absolute_deadline_is_401(operator):
    client = _client(operator.session_id)
    original = _exchange(client)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.sso_refresh_tokens set absolute_expires_at = now() - interval '1 minute' "
                "where token_hash = %s",
                (sso_refresh._hash(original["refresh_token"]),),
            )

    assert _refresh(client, original["refresh_token"]).status_code == 401


def test_refresh_with_revoked_token_is_401(operator):
    client = _client(operator.session_id)
    original = _exchange(client)
    sso_refresh.revoke_for_session(operator.session_id)

    assert _refresh(client, original["refresh_token"]).status_code == 401


def test_refresh_dies_with_the_sso_session(operator):
    """Logging out of Data Hub must stop silent renewal in CO."""
    client = _client(operator.session_id)
    original = _exchange(client)

    auth.revoke_session(operator.session_id)

    assert _refresh(client, original["refresh_token"]).status_code == 401


def test_refresh_for_deactivated_user_is_403(operator):
    client = _client(operator.session_id)
    original = _exchange(client)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.users set status = 'disabled' where user_id = %s", (operator.user_id,)
            )

    response = _refresh(client, original["refresh_token"])

    assert response.status_code == 403
    # 403 rolls back, so the token is not burned — reactivating the user
    # lets the same token work again rather than forcing a re-login.
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.users set status = 'active' where user_id = %s", (operator.user_id,)
            )
    assert _refresh(client, original["refresh_token"]).status_code == 200


# ── ACL movement ────────────────────────────────────────────────────────


def test_refresh_reflects_revoked_client_access(operator):
    client = _client(operator.session_id)
    original = _exchange(client)
    assert jwt_issuer.verify_token(original["access_token"])["client_ids"] == [operator.client_a]

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from hub.user_client_access where user_id = %s", (operator.user_id,)
            )

    body = _refresh(client, original["refresh_token"]).json()

    assert jwt_issuer.verify_token(body["access_token"])["client_ids"] == []


def test_refresh_never_broadens_the_client_scope(operator):
    """The ACL widened after login. A refresh must not pick that up — RFC
    6749 §6. CO gets the new client only after a fresh /authorize."""
    client = _client(operator.session_id)
    original = _exchange(client)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.user_client_access (user_id, client_id, scope, granted_by)
                values (%s, %s, 'read', %s)
                """,
                (operator.user_id, operator.client_b, operator.user_id),
            )

    body = _refresh(client, original["refresh_token"]).json()
    claims = jwt_issuer.verify_token(body["access_token"])

    assert claims["client_ids"] == [operator.client_a]
    assert operator.client_b not in claims["client_ids"]

    # ...but a fresh interactive SSO round does grant it.
    assert sorted(jwt_issuer.verify_token(_exchange(client)["access_token"])["client_ids"]) == sorted(
        [operator.client_a, operator.client_b]
    )


def test_refresh_never_escalates_role(operator):
    client = _client(operator.session_id)
    original = _exchange(client)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.users set role = 'admin' where user_id = %s", (operator.user_id,)
            )

    claims = jwt_issuer.verify_token(_refresh(client, original["refresh_token"]).json()["access_token"])

    assert claims["role"] == "staff"
    # The promotion must not smuggle in all-clients either.
    assert "all_clients" not in claims
    assert claims["client_ids"] == [operator.client_a]


def test_refresh_reflects_role_demotion(operator):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.users set role = 'admin' where user_id = %s", (operator.user_id,)
            )
    client = _client(operator.session_id)
    original = _exchange(client)
    assert jwt_issuer.verify_token(original["access_token"])["all_clients"] is True

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.users set role = 'staff' where user_id = %s", (operator.user_id,)
            )

    claims = jwt_issuer.verify_token(_refresh(client, original["refresh_token"]).json()["access_token"])

    assert claims["role"] == "staff"
    assert claims["client_ids"] == [operator.client_a]


# ── narrowing helpers ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "granted, live, expected",
    [
        (None, None, None),               # admin stays admin
        (None, ["a"], ["a"]),             # demoted to staff: live ACL binds
        (["a"], None, ["a"]),             # promoted to admin: no broadening
        (["a"], ["a", "b"], ["a"]),       # ACL widened: no broadening
        (["a", "b"], ["a"], ["a"]),       # ACL narrowed: reflected
        (["a"], [], []),                  # all access revoked
    ],
)
def test_narrow_client_scope(granted, live, expected):
    assert sso_refresh.narrow_client_scope(granted, live) == expected


@pytest.mark.parametrize(
    "granted, live, expected",
    [
        ("staff", "staff", "staff"),
        ("staff", "admin", "staff"),   # promotion needs a fresh login
        ("admin", "staff", "staff"),   # demotion lands immediately
        ("manager", "dev", "manager"),
        ("dev", "manager", "manager"),
    ],
)
def test_narrow_role(granted, live, expected):
    assert sso_refresh.narrow_role(granted, live) == expected
