"""SSO API: Data Hub as JWT issuer for cross-app authentication.

Three endpoints:

- POST /v1/auth/token — exchange email+password for an access token.
- GET  /v1/auth/jwks  — public-key set so consumers (BCQT, CO) can
  verify tokens locally.
- GET  /v1/auth/validate — debug / one-shot validate; consumers should
  prefer local verification via jwks for hot-path requests.
"""
from __future__ import annotations

import logging

import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Request, Response

from app import jwt_issuer
from app.auth.session import verify_password
from app.database import connect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth")


@router.post("/token")
async def issue_token(request: Request):
    """Exchange email+password for a JWT access token.

    Body: JSON `{"email": str, "password": str}` OR form-encoded same.
    Returns: `{"access_token": str, "token_type": "Bearer", "expires_in": int}`.
    401 on bad creds (no leak about whether email exists)."""
    payload: dict
    ct = (request.headers.get("content-type") or "").lower()
    if "json" in ct:
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(400, "invalid JSON body")
    else:
        form = await request.form()
        payload = dict(form)

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
    return jwt_issuer.make_token(
        user_id=user_id, email=email, role=role,
        display_name=display_name,
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
