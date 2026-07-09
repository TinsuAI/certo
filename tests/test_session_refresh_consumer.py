"""CO side of the Data Hub refresh-token flow.

DH now issues a rotating refresh_token at /v1/auth/exchange and trades it for a
fresh access token at POST /v1/auth/refresh. CO must store the refresh token,
expose a /auth/refresh route that rotates both cookies, and fall back to
session_expired when the refresh token is spent/expired. This lets an active
operator's session live (sliding, 7d ceiling) without re-login, and is what the
client keep-alive / retry-on-401 drives.
"""

from __future__ import annotations

import base64

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient

from app import co_auth
from app.main import app


def _jwk_from_public_key(public_key, kid: str = "k-test") -> dict:
    raw = public_key.public_bytes_raw()
    x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return {"kty": "OKP", "crv": "Ed25519", "use": "sig", "alg": "EdDSA", "kid": kid, "x": x}


def _access_token(private_key, issuer: str = "https://hub.test") -> str:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "iss": issuer,
            "sub": "u-test",
            "role": "staff",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
        },
        private_key,
        algorithm="EdDSA",
        headers={"kid": "k-test"},
    )


def test_callback_stores_refresh_cookie(monkeypatch):
    private_key = ed25519.Ed25519PrivateKey.generate()
    token = _access_token(private_key)
    monkeypatch.setenv("DATA_HUB_ISSUER_URL", "https://hub.test")
    monkeypatch.setattr(
        co_auth,
        "exchange_data_hub_sso_code",
        lambda _code, **_kw: {"access_token": token, "expires_in": 600, "refresh_token": "rt-abc"},
    )
    monkeypatch.setattr(
        co_auth, "fetch_data_hub_jwks",
        lambda _url: {"keys": [_jwk_from_public_key(private_key.public_key())]},
    )

    response = TestClient(app).get("/auth/callback?code=c1&state=/clients", follow_redirects=False)

    assert response.status_code == 303
    combined = response.headers["set-cookie"]
    assert co_auth.CO_SESSION_COOKIE in combined
    assert co_auth.CO_REFRESH_COOKIE in combined
    assert response.cookies.get(co_auth.CO_REFRESH_COOKIE) == "rt-abc"


def test_refresh_route_rotates_cookies_on_success(monkeypatch):
    private_key = ed25519.Ed25519PrivateKey.generate()
    new_at = _access_token(private_key)
    monkeypatch.setattr(
        co_auth,
        "refresh_data_hub_session",
        lambda _rt: {"access_token": new_at, "refresh_token": "rt-rotated", "expires_in": 600},
    )

    client = TestClient(app)
    client.cookies.set(co_auth.CO_REFRESH_COOKIE, "rt-old")
    response = client.post("/auth/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body.get("ok") is True
    assert body.get("expires_in") == 600
    assert response.cookies.get(co_auth.CO_SESSION_COOKIE) == new_at
    assert response.cookies.get(co_auth.CO_REFRESH_COOKIE) == "rt-rotated"


def test_refresh_route_without_cookie_is_session_expired(monkeypatch):
    response = TestClient(app).post("/auth/refresh")

    assert response.status_code == 401
    assert response.json().get("code") == "session_expired"


def test_refresh_route_clears_cookies_when_dh_rejects(monkeypatch):
    def _raise(_rt):
        raise httpx.HTTPStatusError(
            "401", request=httpx.Request("POST", "http://hub/v1/auth/refresh"),
            response=httpx.Response(401),
        )

    monkeypatch.setattr(co_auth, "refresh_data_hub_session", _raise)

    client = TestClient(app)
    client.cookies.set(co_auth.CO_REFRESH_COOKIE, "rt-spent")
    response = client.post("/auth/refresh", follow_redirects=False)

    assert response.status_code == 401
    assert response.json().get("code") == "session_expired"
    combined = response.headers["set-cookie"]
    assert co_auth.CO_REFRESH_COOKIE in combined and "Max-Age=0" in combined


def test_refresh_data_hub_session_posts_to_dh_refresh(monkeypatch):
    captured = {}

    def _post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT", "expires_in": 600},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(co_auth.httpx, "post", _post)
    monkeypatch.setenv("DATA_HUB_API_BASE_URL", "http://hub-api.test")

    out = co_auth.refresh_data_hub_session("rt-1")

    assert captured["url"] == "http://hub-api.test/v1/auth/refresh"
    assert captured["json"] == {"refresh_token": "rt-1"}
    assert out["access_token"] == "AT"
