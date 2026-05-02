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

Two token shapes share the same signing key + kid:
- User tokens (`make_token`) — short TTL, claims include email/role/name.
- Service tokens (`make_service_token`) — long TTL (30d default), `typ`
  claim = 'service', `sub` = 'svc:<name>', plus `scopes` + optional
  `client_ids` whitelist. Verifier checks the service_accounts registry
  + revoked-jti blacklist on every call.
"""
from __future__ import annotations

import base64
import logging
import os
import uuid
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


def get_service_token_ttl_seconds() -> int:
    return settings_store.get_int("service_token_ttl_seconds", 2_592_000)  # 30d


def make_token(
    *,
    user_id: str,
    email: str,
    role: str,
    display_name: str,
    extra_claims: dict | None = None,
) -> dict:
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
    if extra_claims:
        payload.update(extra_claims)
    encoded = jwt.encode(
        payload, priv, algorithm="EdDSA",
        headers={"kid": kid, "typ": "JWT"},
    )
    return {
        "access_token": encoded,
        "token_type": "Bearer",
        "expires_in": ttl,
    }


def make_service_token(
    *,
    name: str,
    scopes: list[str],
    client_ids: list[str] | None,
    ttl_seconds: int | None = None,
) -> dict:
    """Issue a long-TTL token for a named service account.

    `name` becomes the bare-name claim; `sub` is `svc:<name>` so audit
    trails (and any sub-based filtering) can distinguish service from
    human callers. `client_ids=None` means "all clients" — pass an
    explicit list to scope the token down.

    The signing key + kid match user tokens, so consumers verify with
    the same JWKS endpoint and key-rotation flow.
    """
    kid = get_active_kid()
    priv, _ = _load_or_create_keypair(kid)
    ttl = ttl_seconds if ttl_seconds is not None else get_service_token_ttl_seconds()
    now = datetime.now(timezone.utc)
    jti = uuid.uuid4().hex
    payload = {
        "iss": get_issuer_url(),
        "sub": f"svc:{name}",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "typ": "service",
        "name": name,
        "scopes": list(scopes),
        "client_ids": list(client_ids) if client_ids is not None else None,
        "jti": jti,
    }
    encoded = jwt.encode(
        payload, priv, algorithm="EdDSA",
        headers={"kid": kid, "typ": "JWT"},
    )
    return {
        "access_token": encoded,
        "token_type": "Bearer",
        "expires_in": ttl,
        "jti": jti,
    }


def verify_token(token: str, *, leeway_seconds: int = 60) -> dict:
    """Verify a token's signature + claims. Raises jwt.InvalidTokenError
    family on failure. Returns the decoded payload.

    For service tokens (`typ=service`), additionally validates against
    the `hub.service_accounts` registry + jti blacklist. Touches
    `last_used_at` on success.
    """
    headers = jwt.get_unverified_header(token)
    kid = headers.get("kid")
    if not kid:
        raise jwt.InvalidTokenError("missing kid")
    if kid not in _list_kids_on_disk():
        raise jwt.InvalidTokenError(f"unknown kid: {kid}")
    _, pub = _load_or_create_keypair(kid)
    claims = jwt.decode(
        token, pub, algorithms=["EdDSA"],
        issuer=get_issuer_url(),
        leeway=leeway_seconds,
        options={"require": ["exp", "iat", "iss", "sub"]},
    )

    if claims.get("typ") == "service":
        _validate_service_token(claims)

    return claims


class ServiceTokenInvalid(jwt.InvalidTokenError):
    """Distinct subclass for service-account-specific validation failures.

    Callers (e.g. the API auth helper) catch this separately from generic
    `InvalidTokenError` so they NEVER fall through to permissive-bearer
    mode for a service token. A revoked or deleted service account must
    always reject — even in `api_auth_strict=false` dev mode.
    """


def _validate_service_token(claims: dict) -> None:
    """Service-token-specific checks. Mutates `claims` to overwrite
    `scopes` and `client_ids` from the authoritative registry row, so
    admin updates take effect within the next call rather than waiting
    out the 30d token TTL.

    Order:
    1. Sub/name binding — `sub` MUST equal `svc:<name>`. Prevents a
       token from claiming one name in audit (`sub`) while inheriting
       another account's registry row (`name`).
    2. JTI blacklist check — fast path for emergency revocation.
    3. Account row exists — soft revocation = delete row.
    4. Re-derive `scopes` + `client_ids` from registry. JWT body becomes
       AUTHENTICATION only; AUTHORIZATION lives in the DB row.
    5. Best-effort `last_used_at` bump.
    """
    from app.stores import service_accounts as sa_store

    name = claims.get("name") or ""
    if not name:
        raise ServiceTokenInvalid("service token missing 'name' claim")
    sub = claims.get("sub") or ""
    if sub != f"svc:{name}":
        raise ServiceTokenInvalid(
            f"service token sub/name mismatch: sub={sub!r}, name={name!r}"
        )
    jti = claims.get("jti") or ""
    if not jti:
        raise ServiceTokenInvalid("service token missing 'jti' claim")

    if sa_store.is_jti_revoked(jti):
        raise ServiceTokenInvalid(f"service token revoked: jti={jti}")

    account = sa_store.get_account(name)
    if account is None:
        raise ServiceTokenInvalid(f"service account not found: {name}")

    # Authorization comes from the registry, not the token. An admin
    # who shrinks scopes or tightens client_ids takes effect immediately;
    # a token holder cannot retain stale privileges until 30d expiry.
    claims["scopes"] = list(account.get("scopes") or [])
    claims["client_ids"] = (
        list(account["client_ids"]) if account.get("client_ids") is not None else None
    )

    try:
        sa_store.touch_last_used(name, datetime.now(timezone.utc))
    except Exception:  # noqa: BLE001
        logger.error(
            "service token: failed to touch last_used_at for %s — last_used signal will lag",
            name,
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
