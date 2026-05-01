"""Sprint C2: JWT auth on /v1/hub/* read API.

Default mode (api_auth_strict=false): accept JWT or any-non-empty (legacy).
Strict mode: JWT only.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from app import jwt_issuer, settings_store
from app.main import app


@pytest.fixture(autouse=True)
def isolated_keys_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_HUB_KEYS_DIR", d)
        yield Path(d)


@pytest.fixture
def strict_mode_off():
    """Default state. Cleanup any flag set by other tests."""
    settings_store.set_many({"api_auth_strict": "false"})
    yield
    settings_store.set_many({"api_auth_strict": "false"})


@pytest.fixture
def strict_mode_on():
    settings_store.set_many({"api_auth_strict": "true"})
    yield
    settings_store.set_many({"api_auth_strict": "false"})


# Use list_clients endpoint as a stand-in for any /v1/hub/* route.
ENDPOINT = "/v1/hub/dncxs"


def _client():
    return TestClient(app)


def test_no_bearer_returns_401():
    r = _client().get(ENDPOINT)
    assert r.status_code == 401


def test_legacy_bearer_accepted_in_default_mode(strict_mode_off):
    """Permissive default keeps existing dev callers working."""
    r = _client().get(ENDPOINT, headers={"authorization": "Bearer not-a-jwt"})
    assert r.status_code == 200


def test_legacy_bearer_rejected_in_strict_mode(strict_mode_on):
    r = _client().get(ENDPOINT, headers={"authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_valid_jwt_accepted_in_default_mode(strict_mode_off):
    out = jwt_issuer.make_token(
        user_id="u_test", email="t@e", role="admin",
        display_name="T",
    )
    r = _client().get(
        ENDPOINT, headers={"authorization": f"Bearer {out['access_token']}"},
    )
    assert r.status_code == 200


def test_valid_jwt_accepted_in_strict_mode(strict_mode_on):
    out = jwt_issuer.make_token(
        user_id="u_test", email="t@e", role="admin",
        display_name="T",
    )
    r = _client().get(
        ENDPOINT, headers={"authorization": f"Bearer {out['access_token']}"},
    )
    assert r.status_code == 200


def test_expired_jwt_always_rejected(strict_mode_off):
    """Expired tokens always 401, even in permissive default mode.

    Construct a token with iat/exp far in the past so the 60-sec leeway
    can't save it."""
    from datetime import datetime, timezone
    # Build a token by hand with explicit iat/exp.
    kid = jwt_issuer.get_active_kid()
    priv, _ = jwt_issuer._load_or_create_keypair(kid)
    long_past = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
    payload = {
        "iss": jwt_issuer.get_issuer_url(),
        "sub": "u_test", "iat": long_past, "exp": long_past + 60,
        "email": "t@e", "role": "admin", "name": "T",
    }
    expired = pyjwt.encode(payload, priv, algorithm="EdDSA",
                           headers={"kid": kid, "typ": "JWT"})
    r = _client().get(
        ENDPOINT, headers={"authorization": f"Bearer {expired}"},
    )
    assert r.status_code == 401


def test_empty_bearer_returns_401():
    r = _client().get(ENDPOINT, headers={"authorization": "Bearer "})
    assert r.status_code == 401
