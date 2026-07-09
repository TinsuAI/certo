"""SSO API: Data Hub as JWT issuer for cross-app authentication.

Three endpoints:

- POST /v1/auth/token — exchange email+password for an access token.
- GET  /v1/auth/authorize — browser SSO start for sister apps.
- POST /v1/auth/exchange — exchange a browser SSO code for a JWT
  (+ a refresh token, when the SSO session can be bound).
- POST /v1/auth/refresh — trade a refresh token for a fresh access token
  without user interaction. Rotating: the presented token is spent.
- GET  /v1/auth/jwks  — public-key set so consumers (BCQT, CO) can
  verify tokens locally.
- GET  /v1/auth/validate — debug / one-shot validate; consumers should
  prefer local verification via jwks for hot-path requests.
"""
from __future__ import annotations

import logging
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app import auth
from app import jwt_issuer
from app.auth.session import verify_password
from app.database import connect
from app.stores import sso_codes, sso_refresh

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth")


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


def _origin_of(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _with_query(url: str, values: dict[str, str]) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(values)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _visible_clients_for(*, user_id: str, email: str, role: str, display_name: str) -> list[str] | None:
    """Live per-client ACL for a user. `None` means every client."""
    return auth.visible_clients(auth.User(
        user_id=user_id,
        email=email,
        display_name=display_name,
        role=role,
        status="active",
    ))


def _issue_user_token(
    *,
    user_id: str,
    email: str,
    role: str,
    display_name: str,
    client_scope: list[str] | None,
) -> dict:
    extra_claims = {"all_clients": True} if client_scope is None else {"client_ids": client_scope}
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
    return _issue_user_token(
        user_id=user_id,
        email=email,
        role=role,
        display_name=display_name,
        client_scope=_visible_clients_for(
            user_id=user_id, email=email, role=role, display_name=display_name,
        ),
    )


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

    code = sso_codes.issue(
        user_id=user.user_id,
        email=user.email,
        role=user.role,
        display_name=user.display_name,
        redirect_uri=redirect_uri,
        # Rides through to /exchange so the refresh token can be bound to the
        # SSO session that authorized it. Logging out of Data Hub then kills
        # the consumer's silent renewal too.
        session_id=request.cookies.get(auth.SESSION_COOKIE),
    )
    return RedirectResponse(_with_query(redirect_uri, {"code": code, "state": state}), status_code=303)


@router.post("/exchange")
async def exchange_code(request: Request):
    payload = await _request_payload(request)
    code = str(payload.get("code") or "")
    if not code:
        raise HTTPException(400, "code required")
    redirect_uri = str(payload.get("redirect_uri") or "")
    if not redirect_uri:
        raise HTTPException(401, "invalid redirect_uri")
    redirect_uri = _safe_redirect_uri(redirect_uri)

    # Single-use consume. Two exchanges racing on one code leave exactly one
    # winner; a redirect_uri mismatch rolls back and leaves the code spendable.
    try:
        row = sso_codes.consume(code, redirect_uri=redirect_uri)
    except sso_codes.SsoCodeRedirectMismatch:
        raise HTTPException(401, "invalid redirect_uri")
    except sso_codes.SsoCodeInvalid:
        raise HTTPException(401, "invalid or expired code")

    client_scope = _visible_clients_for(
        user_id=row["user_id"],
        email=row["email"],
        role=row["role"],
        display_name=row["display_name"],
    )
    token = _issue_user_token(
        user_id=row["user_id"],
        email=row["email"],
        role=row["role"],
        display_name=row["display_name"],
        client_scope=client_scope,
    )

    # A refresh token has to be bound to an SSO session. `/authorize`
    # cannot mint a code without a live one, so this is only ever None in
    # tests that stub out `current_user`. Degrade to an access-token-only
    # response rather than failing the exchange.
    session_id = row.get("session_id")
    if session_id:
        try:
            issued = sso_refresh.issue(
                user_id=row["user_id"],
                session_id=session_id,
                granted_role=row["role"],
                granted_client_ids=client_scope,
                redirect_origin=_origin_of(redirect_uri),
            )
            token["refresh_token"] = issued["refresh_token"]
        except sso_refresh.RefreshTokenInvalid:
            logger.warning(
                "exchange: sso session %s vanished before refresh token could be bound",
                session_id,
            )
    return token


@router.post("/refresh")
async def refresh_token(request: Request):
    """Trade a refresh token for a fresh access token, with no user
    interaction. The refresh token is the only proof required — the
    caller's access token has, by definition, already expired.

    Claims are rebuilt from live DB state via the same path `/exchange`
    uses, so an ACL that shrank between issue and refresh is reflected
    here and a refresh can never broaden the visible-client set.

    400 malformed body; 401 unknown/expired/revoked/spent token (consumer
    falls back to interactive SSO); 403 token still valid but the user may
    no longer authenticate.
    """
    payload = await _request_payload(request)
    presented = payload.get("refresh_token")
    if not isinstance(presented, str) or not presented.strip():
        raise HTTPException(400, "refresh_token required")
    presented = presented.strip()

    # An access token handed to /refresh must never be hashed against the
    # store, let alone accepted. Reject on shape, before it touches the DB.
    if sso_refresh.looks_like_jwt(presented):
        raise HTTPException(401, "invalid refresh token")

    try:
        rotated = sso_refresh.rotate(presented)
    except sso_refresh.UserNotPermitted:
        raise HTTPException(403, "user is no longer permitted")
    except sso_refresh.RefreshTokenInvalid:
        raise HTTPException(401, "invalid refresh token")

    user = rotated["user"]
    # The live ACL is read against the user's CURRENT role (the ACL table
    # differs per role), then intersected with the scope frozen at login.
    # Revocations land immediately; a widened grant does not.
    live_scope = _visible_clients_for(
        user_id=user["user_id"],
        email=user["email"],
        role=user["role"],
        display_name=user["display_name"],
    )
    token = _issue_user_token(
        user_id=user["user_id"],
        email=user["email"],
        role=sso_refresh.narrow_role(rotated["granted_role"], user["role"]),
        display_name=user["display_name"],
        client_scope=sso_refresh.narrow_client_scope(rotated["granted_client_ids"], live_scope),
    )
    token["refresh_token"] = rotated["refresh_token"]
    return token


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
