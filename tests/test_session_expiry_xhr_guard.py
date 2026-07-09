"""Regression: an expired/absent CO session on an XHR/fetch request must return a
JSON 401 the browser can read — NOT a 303 cross-origin SSO redirect.

Prod bug: the substitute-candidates fetch (and every guarded /clients API call)
was answered with a 303 -> /auth/login -> {data_hub}/v1/auth/authorize. fetch()
follows the redirect cross-origin, the SSO page has no CORS headers, and the
browser aborts with `TypeError: Failed to fetch`. The user saw "Mất kết nối máy
chủ" every ~10 minutes (the co_data_hub_session cookie / DH JWT lifetime) and
lost all client-side substitute work. Dev never reproduced it because
CO_AUTH_REQUIRED is off there, so guard_response never redirects.

A top-level document navigation must still redirect (correct browser login flow).
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient

from app import co_auth
from app.main import app

# A guarded /clients API endpoint reached by fetch() — the substitute-candidates
# recommendation load from the "Tìm NVL thay thế" modal.
API_PATH = (
    "/clients/johnson-vn/co-case/CO-X/origin/sheet/PROD-1"
    "/substitute-candidates?material_code=004555-AB&row_index=0"
)
NAV_PATH = "/clients"


def _jwk_from_public_key(public_key, kid: str = "k-test") -> dict:
    raw = public_key.public_bytes_raw()
    x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return {"kty": "OKP", "crv": "Ed25519", "use": "sig", "alg": "EdDSA", "kid": kid, "x": x}


def _expired_token(private_key) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "iss": "https://hub.test",
            "sub": "u-test",
            "iat": int((now - timedelta(minutes=20)).timestamp()),
            "exp": int((now - timedelta(minutes=10)).timestamp()),
        },
        private_key,
        algorithm="EdDSA",
        headers={"kid": "k-test"},
    )


@pytest.fixture
def auth_on(monkeypatch):
    private_key = ed25519.Ed25519PrivateKey.generate()
    monkeypatch.setenv("CO_AUTH_REQUIRED", "1")
    monkeypatch.setenv("DATA_HUB_ISSUER_URL", "https://hub.test")
    monkeypatch.setattr(
        co_auth,
        "fetch_data_hub_jwks",
        lambda _url: {"keys": [_jwk_from_public_key(private_key.public_key())]},
    )
    return private_key


def test_expired_session_xhr_returns_json_401_not_redirect(auth_on):
    client = TestClient(app)
    client.cookies.set(co_auth.CO_SESSION_COOKIE, _expired_token(auth_on))

    response = client.get(
        API_PATH, headers={"Accept": "application/json"}, follow_redirects=False
    )

    assert response.status_code == 401
    body = response.json()
    assert body.get("code") == "session_expired"
    assert body.get("login_url", "").startswith("/auth/login")


def test_absent_session_xhr_returns_json_401_not_redirect(auth_on):
    response = TestClient(app).get(
        API_PATH, headers={"Accept": "application/json"}, follow_redirects=False
    )

    assert response.status_code == 401
    assert response.json().get("code") == "session_expired"


def test_expired_session_fetch_dest_empty_returns_json_401(auth_on):
    # Browsers tag background fetch/XHR with Sec-Fetch-Dest: empty even when
    # Accept is */* (fetch default). That must not be redirected either.
    client = TestClient(app)
    client.cookies.set(co_auth.CO_SESSION_COOKIE, _expired_token(auth_on))

    response = client.get(
        API_PATH,
        headers={"Accept": "*/*", "Sec-Fetch-Dest": "empty"},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json().get("code") == "session_expired"


def test_expired_session_document_navigation_still_redirects(auth_on):
    # A real top-level page load must keep the browser SSO login redirect.
    client = TestClient(app)
    client.cookies.set(co_auth.CO_SESSION_COOKIE, _expired_token(auth_on))

    response = client.get(
        NAV_PATH,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Fetch-Dest": "document",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login?next=/clients"
