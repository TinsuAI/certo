"""SSO API: Data Hub as JWT issuer for cross-app authentication.

Three endpoints:

- POST /v1/auth/token — exchange email+password for an access token.
- GET  /v1/auth/authorize — browser SSO start for sister apps.
- POST /v1/auth/exchange — exchange a browser SSO code for a JWT.
- GET  /v1/auth/jwks  — public-key set so consumers (BCQT, CO) can
  verify tokens locally.
- GET  /v1/auth/validate — debug / one-shot validate; consumers should
  prefer local verification via jwks for hot-path requests.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app import auth
from app import jwt_issuer
from app.auth.session import verify_password
from app.database import connect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth")
SSO_CODE_TTL_SECONDS = 120
_SSO_CODES: dict[str, dict] = {}


def _request_query_path(request: Request) -> str:
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return target


def _safe_redirect_uri(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "redirect_uri must be an absolute http(s) URL")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    allowed = {
        item.strip().rstrip("/")
        for item in os.environ.get("DATA_HUB_SSO_ALLOWED_REDIRECT_ORIGINS", "").split(",")
        if item.strip()
    }
    if allowed:
        if origin not in allowed:
            raise HTTPException(400, "redirect_uri origin is not allowed")
    elif parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise HTTPException(400, "redirect_uri origin is not allowed")
    return value


def _with_query(url: str, values: dict[str, str]) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(values)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _purge_expired_sso_codes() -> None:
    now = datetime.now(timezone.utc)
    expired = [code for code, row in _SSO_CODES.items() if row["expires_at"] <= now]
    for code in expired:
        _SSO_CODES.pop(code, None)


def _issue_user_token(*, user_id: str, email: str, role: str, display_name: str) -> dict:
    user = auth.User(
        user_id=user_id,
        email=email,
        display_name=display_name,
        role=role,
        status="active",
    )
    visible_clients = auth.visible_clients(user)
    extra_claims = {"all_clients": True} if visible_clients is None else {"client_ids": visible_clients}
    return jwt_issuer.make_token(
        user_id=user_id,
        email=email,
        role=role,
        display_name=display_name,
        extra_claims=extra_claims,
    )


async def _request_payload(request: Request) -> dict:
    ct = (request.headers.get("content-type") or "").lower()
    if "json" in ct:
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(400, "invalid JSON body")
        return payload if isinstance(payload, dict) else {}
    form = await request.form()
    return dict(form)


@router.post("/token")
async def issue_token(request: Request):
    """Exchange email+password for a JWT access token.

    Body: JSON `{"email": str, "password": str}` OR form-encoded same.
    Returns: `{"access_token": str, "token_type": "Bearer", "expires_in": int}`.
    401 on bad creds (no leak about whether email exists)."""
    payload = await _request_payload(request)

    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    if not email or not password:
        raise HTTPException(400, "email and password required")

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select user_id, email, password_hash, display_name, role, status
                from hub.users where lower(email) = %s
                """,
                (email,),
            )
            row = cur.fetchone()

    # Constant-time-ish: always run verify_password even if user missing,
    # to flatten the timing signal. (Not perfect — argon2 hash lengths
    # differ — but better than skipping the call entirely.)
    sentinel = "$argon2id$v=19$m=65536,t=3,p=4$REPLACEDREPLACED$REPLACEDREPLACED"
    if row:
        _, _, pw_hash, display_name, role, status = row
        ok = verify_password(password, pw_hash) and status == "active"
    else:
        verify_password(password, sentinel)
        ok = False

    if not ok:
        raise HTTPException(401, "invalid credentials")

    user_id, _email, _pw, display_name, role, _status = row
    return _issue_user_token(user_id=user_id, email=email, role=role, display_name=display_name)


@router.get("/authorize")
async def authorize(request: Request, redirect_uri: str, state: str = ""):
    """Browser SSO start for sister apps.

    Redirects unauthenticated users through Data Hub login, then returns a
    short-lived one-time code to the consumer callback.
    """
    redirect_uri = _safe_redirect_uri(redirect_uri)
    user = auth.current_user(request)
    if not user:
        return RedirectResponse(f"/login?{urlencode({'next': _request_query_path(request)})}", status_code=303)

    _purge_expired_sso_codes()
    code = secrets.token_urlsafe(32)
    _SSO_CODES[code] = {
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role,
        "display_name": user.display_name,
        "redirect_uri": redirect_uri,
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=SSO_CODE_TTL_SECONDS),
    }
    return RedirectResponse(_with_query(redirect_uri, {"code": code, "state": state}), status_code=303)


@router.post("/exchange")
async def exchange_code(request: Request):
    payload = await _request_payload(request)
    code = str(payload.get("code") or "")
    if not code:
        raise HTTPException(400, "code required")
    _purge_expired_sso_codes()
    row = _SSO_CODES.get(code)
    if not row:
        raise HTTPException(401, "invalid or expired code")
    redirect_uri = str(payload.get("redirect_uri") or "")
    if not redirect_uri or _safe_redirect_uri(redirect_uri) != row["redirect_uri"]:
        raise HTTPException(401, "invalid redirect_uri")
    _SSO_CODES.pop(code, None)
    return _issue_user_token(
        user_id=row["user_id"],
        email=row["email"],
        role=row["role"],
        display_name=row["display_name"],
    )


@router.get("/jwks")
async def jwks_endpoint(response: Response):
    """Public JWK set. Consumer libs (PyJWKClient etc.) cache by URL."""
    response.headers["Cache-Control"] = "public, max-age=600"
    return jwt_issuer.jwks()


@router.get("/validate")
async def validate_token(request: Request):
    """Decode + verify a bearer token, return claims. Only intended for
    debug or one-shot consumer flows; prefer local verify via JWKS for
    request-rate validation."""
    auth_header = request.headers.get("authorization") or ""
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    token = auth_header[7:].strip()
    try:
        claims = jwt_issuer.verify_token(token)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(401, "token expired")
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(401, f"invalid token: {e}")
    return {
        "sub": claims.get("sub"),
        "email": claims.get("email"),
        "role": claims.get("role"),
        "name": claims.get("name"),
        "exp": claims.get("exp"),
    }
