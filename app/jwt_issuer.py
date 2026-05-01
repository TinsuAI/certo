"""SSO JWT issuer for cross-app authentication.

Data Hub holds the private key(s); BCQT-System and CO verify tokens
locally using the JWKS endpoint. Ed25519 by default — small signatures,
fast verify, no padding-mode footguns.

Keys live on disk under `keys/` (gitignored). Each keypair is named by
its `kid` (e.g. `k1.private.pem` + `k1.public.pem`). The active kid
used for signing is stored in `hub.app_settings.sso_active_kid`. JWKS
publishes ALL keys present on disk so rotation works smoothly: drop a
new keypair → wait for consumer cache to refresh → flip active_kid.

For dev / first-run: if no keypair exists, `bootstrap_dev_key()`
generates one named `k1`. Production should use admin-curated keys.
"""
from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from app import settings_store

logger = logging.getLogger(__name__)


# Where keypairs live. Override via DATA_HUB_KEYS_DIR env var for tests.
def _keys_dir() -> Path:
    return Path(os.environ.get("DATA_HUB_KEYS_DIR",
                               Path(__file__).resolve().parent.parent / "keys"))


def _key_paths(kid: str) -> tuple[Path, Path]:
    d = _keys_dir()
    return d / f"{kid}.private.pem", d / f"{kid}.public.pem"


def _load_or_create_keypair(kid: str) -> tuple[
    ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey,
]:
    priv_p, pub_p = _key_paths(kid)
    if not priv_p.exists():
        # First run / dev: generate.
        priv_p.parent.mkdir(parents=True, exist_ok=True)
        priv = ed25519.Ed25519PrivateKey.generate()
        priv_p.write_bytes(priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        pub = priv.public_key()
        pub_p.write_bytes(pub.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
        try:
            os.chmod(priv_p, 0o400)
        except OSError:
            pass
        logger.info("jwt_issuer: generated new keypair %s at %s", kid, priv_p)

    priv = serialization.load_pem_private_key(
        priv_p.read_bytes(), password=None,
    )
    pub = serialization.load_pem_public_key(pub_p.read_bytes())
    return priv, pub


def _list_kids_on_disk() -> list[str]:
    d = _keys_dir()
    if not d.exists():
        return []
    return sorted(p.stem.removesuffix(".private")
                  for p in d.glob("*.private.pem"))


def get_active_kid() -> str:
    return settings_store.get("sso_active_kid") or "k1"


def get_issuer_url() -> str:
    return settings_store.get("sso_issuer_url") or "http://localhost:8754"


def get_token_ttl_seconds() -> int:
    return settings_store.get_int("sso_token_ttl_seconds", 600)


def make_token(*, user_id: str, email: str, role: str,
               display_name: str) -> dict:
    """Issue a fresh access token for a user. Returns dict matching
    OAuth2 token-response shape (access_token + token_type + expires_in)."""
    kid = get_active_kid()
    priv, _ = _load_or_create_keypair(kid)
    ttl = get_token_ttl_seconds()
    now = datetime.now(timezone.utc)
    payload = {
        "iss": get_issuer_url(),
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "email": email,
        "role": role,
        "name": display_name,
    }
    encoded = jwt.encode(
        payload, priv, algorithm="EdDSA",
        headers={"kid": kid, "typ": "JWT"},
    )
    return {
        "access_token": encoded,
        "token_type": "Bearer",
        "expires_in": ttl,
    }


def verify_token(token: str, *, leeway_seconds: int = 60) -> dict:
    """Verify a token's signature + claims. Raises jwt.InvalidTokenError
    family on failure. Returns the decoded payload."""
    headers = jwt.get_unverified_header(token)
    kid = headers.get("kid")
    if not kid:
        raise jwt.InvalidTokenError("missing kid")
    if kid not in _list_kids_on_disk():
        raise jwt.InvalidTokenError(f"unknown kid: {kid}")
    _, pub = _load_or_create_keypair(kid)
    return jwt.decode(
        token, pub, algorithms=["EdDSA"],
        issuer=get_issuer_url(),
        leeway=leeway_seconds,
        options={"require": ["exp", "iat", "iss", "sub"]},
    )


def jwks() -> dict:
    """Public-key set in standard JWK format. Includes EVERY kid on disk
    so rotation can publish two keys simultaneously. First call on a
    fresh install bootstraps the active kid so consumers don't see an
    empty JWKS during the very first /jwks request."""
    # Ensure the active kid exists so JWKS isn't empty on first call.
    active = get_active_kid()
    try:
        _load_or_create_keypair(active)
    except Exception:  # noqa: BLE001
        logger.exception("jwks bootstrap: failed to load/create %s", active)

    keys: list[dict] = []
    for kid in _list_kids_on_disk():
        try:
            _, pub = _load_or_create_keypair(kid)
        except Exception:  # noqa: BLE001
            logger.exception("jwks: failed to load %s", kid)
            continue
        # Ed25519 raw public key bytes → base64url
        raw = pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        keys.append({
            "kty": "OKP",
            "crv": "Ed25519",
            "use": "sig",
            "alg": "EdDSA",
            "kid": kid,
            "x": x,
        })
    return {"keys": keys}
