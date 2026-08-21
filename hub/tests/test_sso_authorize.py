from __future__ import annotations

import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app import auth
from app import jwt_issuer
from app.database import connect
from app.main import app, safe_next_path
from app.routes import auth_api


@pytest.fixture(autouse=True)
def isolated_keys_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_HUB_KEYS_DIR", d)
        yield Path(d)


def test_authorize_redirects_to_login_when_not_authenticated(monkeypatch):
    monkeypatch.setattr(auth_api.auth, "current_user", lambda _request: None)
    monkeypatch.setenv("DATA_HUB_SSO_ALLOWED_REDIRECT_ORIGINS", "http://co.test")

    response = TestClient(app).get(
        "/v1/auth/authorize?redirect_uri=http://co.test/auth/callback&state=/clients",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


def test_safe_next_path_rejects_external_redirects():
    assert safe_next_path("https://evil.test/steal") == "/clients"
    assert safe_next_path("//evil.test/steal") == "/clients"
    assert safe_next_path("clients") == "/clients"
    assert safe_next_path("/v1/auth/authorize?state=/clients") == "/v1/auth/authorize?state=/clients"


def test_authorize_rejects_disallowed_redirect_origin(monkeypatch):
    monkeypatch.setenv("DATA_HUB_SSO_ALLOWED_REDIRECT_ORIGINS", "http://co.test")

    response = TestClient(app).get(
        "/v1/auth/authorize?redirect_uri=http://evil.test/auth/callback",
        follow_redirects=False,
    )

    assert response.status_code == 400


def test_authorize_code_exchange_issues_jwt(monkeypatch):
    monkeypatch.setenv("DATA_HUB_SSO_ALLOWED_REDIRECT_ORIGINS", "http://co.test")
    monkeypatch.setattr(
        auth_api.auth,
        "current_user",
        lambda _request: auth.User(
            user_id="u_sso",
            email="sso@example.test",
            display_name="SSO User",
            role="admin",
            status="active",
        ),
    )

    client = TestClient(app)
    authorize = client.get(
        "/v1/auth/authorize?redirect_uri=http://co.test/auth/callback&state=/clients",
        follow_redirects=False,
    )
    location = authorize.headers["location"]
    params = parse_qs(urlsplit(location).query)

    exchange = client.post(
        "/v1/auth/exchange",
        json={"code": params["code"][0], "redirect_uri": "http://co.test/auth/callback"},
    )

    assert authorize.status_code == 303
    assert location.startswith("http://co.test/auth/callback?")
    assert params["state"] == ["/clients"]
    assert exchange.status_code == 200
    assert exchange.json()["token_type"] == "Bearer"
    assert exchange.json()["access_token"]


def test_exchange_rejects_reused_code(monkeypatch):
    monkeypatch.setenv("DATA_HUB_SSO_ALLOWED_REDIRECT_ORIGINS", "http://co.test")
    monkeypatch.setattr(
        auth_api.auth,
        "current_user",
        lambda _request: auth.User(
            user_id="u_sso",
            email="sso@example.test",
            display_name="SSO User",
            role="admin",
            status="active",
        ),
    )

    client = TestClient(app)
    authorize = client.get(
        "/v1/auth/authorize?redirect_uri=http://co.test/auth/callback&state=/clients",
        follow_redirects=False,
    )
    code = parse_qs(urlsplit(authorize.headers["location"]).query)["code"][0]
    payload = {"code": code, "redirect_uri": "http://co.test/auth/callback"}

    first = client.post("/v1/auth/exchange", json=payload)
    second = client.post("/v1/auth/exchange", json=payload)

    assert first.status_code == 200
    assert second.status_code == 401


def test_exchange_rejects_wrong_redirect_uri(monkeypatch):
    monkeypatch.setenv("DATA_HUB_SSO_ALLOWED_REDIRECT_ORIGINS", "http://co.test,http://evil.test")
    monkeypatch.setattr(
        auth_api.auth,
        "current_user",
        lambda _request: auth.User(
            user_id="u_sso",
            email="sso@example.test",
            display_name="SSO User",
            role="admin",
            status="active",
        ),
    )

    client = TestClient(app)
    authorize = client.get(
        "/v1/auth/authorize?redirect_uri=http://co.test/auth/callback&state=/clients",
        follow_redirects=False,
    )
    params = parse_qs(urlsplit(authorize.headers["location"]).query)

    response = client.post(
        "/v1/auth/exchange",
        json={"code": params["code"][0], "redirect_uri": "http://evil.test/auth/callback"},
    )

    assert response.status_code == 401


def test_exchange_token_includes_visible_client_claims(monkeypatch):
    user_id = "u_sso_staff_acl"
    client_id = "sso-staff-client"
    monkeypatch.setenv("DATA_HUB_SSO_ALLOWED_REDIRECT_ORIGINS", "http://co.test")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.users (user_id, email, display_name, password_hash, role)
                values (%s, 'sso-staff@example.test', 'SSO Staff', %s, 'staff')
                on conflict (user_id) do update set role = excluded.role
                """,
                (user_id, auth.hash_password("test")),
            )
            cur.execute(
                """
                insert into hub.clients (client_id, name)
                values (%s, 'SSO Staff Client')
                on conflict (client_id) do nothing
                """,
                (client_id,),
            )
            cur.execute(
                """
                insert into hub.user_client_access (user_id, client_id, scope, granted_by)
                values (%s, %s, 'read', %s)
                on conflict (user_id, client_id) do update set scope = excluded.scope
                """,
                (user_id, client_id, user_id),
            )
    monkeypatch.setattr(
        auth_api.auth,
        "current_user",
        lambda _request: auth.User(
            user_id=user_id,
            email="sso-staff@example.test",
            display_name="SSO Staff",
            role="staff",
            status="active",
        ),
    )

    try:
        client = TestClient(app)
        authorize = client.get(
            "/v1/auth/authorize?redirect_uri=http://co.test/auth/callback&state=/clients",
            follow_redirects=False,
        )
        params = parse_qs(urlsplit(authorize.headers["location"]).query)
        exchange = client.post(
            "/v1/auth/exchange",
            json={"code": params["code"][0], "redirect_uri": "http://co.test/auth/callback"},
        )
        claims = jwt_issuer.verify_token(exchange.json()["access_token"])

        assert claims["client_ids"] == [client_id]
        assert "all_clients" not in claims
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from hub.user_client_access where user_id = %s", (user_id,))
                cur.execute("delete from hub.users where user_id = %s", (user_id,))
                cur.execute("delete from hub.clients where client_id = %s", (client_id,))
