"""Sprint B3: JWT issuer + JWKS + token verify."""
from __future__ import annotations

import os
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt as pyjwt
import pytest

from hub.app import jwt_issuer


@pytest.fixture(autouse=True)
def isolated_keys_dir(monkeypatch):
    """Each test gets its own keys dir so generated keypairs don't
    contaminate the project's actual `keys/`."""
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_HUB_KEYS_DIR", d)
        yield Path(d)


# ─── Roundtrip ──────────────────────────────────────────────────────────

def test_make_token_and_verify_round_trip():
    """Token issued by make_token verifies with verify_token."""
    out = jwt_issuer.make_token(
        user_id="u_1", email="x@y", role="admin", display_name="X",
    )
    assert out["token_type"] == "Bearer"
    assert out["expires_in"] > 0
    assert isinstance(out["access_token"], str)
    claims = jwt_issuer.verify_token(out["access_token"])
    assert claims["sub"] == "u_1"
    assert claims["email"] == "x@y"
    assert claims["role"] == "admin"
    assert claims["name"] == "X"


def test_jwks_contains_active_kid():
    """JWKS publishes the kid that signed the token, in OKP/Ed25519 shape."""
    out = jwt_issuer.make_token(
        user_id="u_2", email="x@y", role="staff", display_name="Y",
    )
    keys = jwt_issuer.jwks()["keys"]
    assert any(k["kid"] == jwt_issuer.get_active_kid() for k in keys)
    for k in keys:
        assert k["kty"] == "OKP"
        assert k["crv"] == "Ed25519"
        assert k["alg"] == "EdDSA"
        assert k["x"]  # base64url public key bytes


def test_token_has_kid_header():
    """Tokens carry kid in protected header so consumers know which JWK
    to use during rotation windows."""
    out = jwt_issuer.make_token(
        user_id="u_3", email="x@y", role="dev", display_name="Z",
    )
    headers = pyjwt.get_unverified_header(out["access_token"])
    assert headers["kid"] == jwt_issuer.get_active_kid()
    assert headers["alg"] == "EdDSA"


# ─── Failure modes ──────────────────────────────────────────────────────

def test_verify_rejects_wrong_signature(isolated_keys_dir):
    """Token signed by an unrelated key fails verification."""
    out = jwt_issuer.make_token(
        user_id="u_4", email="x@y", role="staff", display_name="W",
    )
    # Replace the on-disk public key for the active kid with a different
    # public key. Verification should fail because the token was signed
    # against the original.
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization
    other_priv = ed25519.Ed25519PrivateKey.generate()
    other_pub = other_priv.public_key()
    pub_path = isolated_keys_dir / f"{jwt_issuer.get_active_kid()}.public.pem"
    pub_path.write_bytes(other_pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    with pytest.raises(pyjwt.InvalidSignatureError):
        jwt_issuer.verify_token(out["access_token"])


def test_verify_rejects_expired_token(monkeypatch):
    """Tokens past their exp claim raise ExpiredSignatureError."""
    monkeypatch.setattr(jwt_issuer, "get_token_ttl_seconds", lambda: 1)
    out = jwt_issuer.make_token(
        user_id="u_5", email="x@y", role="staff", display_name="V",
    )
    # Move the clock forward beyond exp + leeway.
    import time
    time.sleep(1.5)
    # Use leeway=0 to avoid the default tolerance
    with pytest.raises(pyjwt.ExpiredSignatureError):
        jwt_issuer.verify_token(out["access_token"], leeway_seconds=0)


def test_verify_rejects_missing_kid():
    """Tokens without kid header are rejected — we can't pick a key."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    priv = ed25519.Ed25519PrivateKey.generate()
    bad = pyjwt.encode(
        {"iss": jwt_issuer.get_issuer_url(),
         "sub": "u_6", "iat": 0,
         "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())},
        priv, algorithm="EdDSA",
    )
    with pytest.raises(pyjwt.InvalidTokenError):
        jwt_issuer.verify_token(bad)


def test_verify_rejects_unknown_kid():
    """A token with kid that isn't on disk → reject. Prevents accepting
    tokens from a key the operator didn't approve."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    priv = ed25519.Ed25519PrivateKey.generate()
    bad = pyjwt.encode(
        {"iss": jwt_issuer.get_issuer_url(),
         "sub": "u_7", "iat": 0,
         "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())},
        priv, algorithm="EdDSA",
        headers={"kid": "k-not-on-disk"},
    )
    with pytest.raises(pyjwt.InvalidTokenError, match="unknown kid"):
        jwt_issuer.verify_token(bad)


def test_verify_rejects_wrong_issuer():
    """Token issued by a different issuer URL → reject."""
    out = jwt_issuer.make_token(
        user_id="u_8", email="x@y", role="staff", display_name="V",
    )
    # Patch issuer; verify should now reject the previously-issued token
    real_iss = jwt_issuer.get_issuer_url
    jwt_issuer.get_issuer_url = lambda: "https://impostor.example"
    try:
        with pytest.raises(pyjwt.InvalidIssuerError):
            jwt_issuer.verify_token(out["access_token"])
    finally:
        jwt_issuer.get_issuer_url = real_iss


# ─── Rotation: two keys on disk, both verify ───────────────────────────

def test_jwks_publishes_all_kids_on_disk(isolated_keys_dir, monkeypatch):
    """Multiple kids on disk → JWKS lists every one. Allows rotation
    overlap (publish new key, wait for cache, then flip active_kid)."""
    # Create k1 (already happens via make_token); also create k2 by hand.
    monkeypatch.setattr(jwt_issuer, "get_active_kid", lambda: "k1")
    jwt_issuer.make_token(user_id="u", email="e", role="dev",
                          display_name="d")
    # Now generate a second key
    monkeypatch.setattr(jwt_issuer, "get_active_kid", lambda: "k2")
    jwt_issuer.make_token(user_id="u", email="e", role="dev",
                          display_name="d")
    keys = jwt_issuer.jwks()["keys"]
    kids = {k["kid"] for k in keys}
    assert "k1" in kids
    assert "k2" in kids
