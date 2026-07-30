from __future__ import annotations

from urllib.parse import quote

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from app import co_auth
from app.web.templating import templates


router = APIRouter()


@router.get("/auth/login")
async def auth_login(request: Request, next: str = "/clients"):
    redirect_uri = f"{co_auth.co_public_base_url(request)}/auth/callback"
    return RedirectResponse(
        co_auth.data_hub_authorize_url(redirect_uri=redirect_uri, state=next),
        status_code=303,
    )


@router.post("/auth/logout")
async def auth_logout(request: Request, next_url: str = Form("/clients")):
    next_path = co_auth.safe_next_path(next_url)
    if co_auth.auth_required():
        request.state.co_user = None
        response = templates.TemplateResponse(
            request=request,
            name="sso_logout.html",
            context={
                "data_hub_logout_url": co_auth.data_hub_logout_url(),
                "next_path": next_path,
            },
        )
        co_auth.clear_session_cookie(response)
        return response
    target = f"{next_path}?logged_out=1" if next_path == "/user" else next_path
    response = RedirectResponse(target, status_code=303)
    co_auth.clear_session_cookie(response)
    return response


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request, code: str = "", state: str = "/clients"):
    next_url = co_auth.safe_next_path(state)
    if not code:
        return RedirectResponse(f"/auth/login?next={quote(next_url, safe='/')}", status_code=303)
    redirect_uri = f"{co_auth.co_public_base_url(request)}/auth/callback"
    try:
        payload = co_auth.exchange_data_hub_sso_code(code, redirect_uri=redirect_uri)
        token = str(payload["access_token"])
        verifier = co_auth.DataHubTokenVerifier(
            issuer=co_auth.data_hub_issuer_urls(),
            jwks_provider=lambda: co_auth.fetch_data_hub_jwks(co_auth.data_hub_jwks_url()),
        )
        verifier.verify(token)
    except Exception:
        response = PlainTextResponse(
            "Data Hub login failed. Check Technical Settings for issuer/JWKS and Data Hub SSO config.",
            status_code=401,
        )
        co_auth.clear_session_cookie(response)
        return response
    response = RedirectResponse(next_url, status_code=303)
    co_auth.set_session_cookie(response, token, int(payload.get("expires_in") or 600), request=request)
    refresh = payload.get("refresh_token")
    if refresh:
        co_auth.set_refresh_cookie(response, str(refresh), request=request)
    return response


@router.post("/auth/refresh")
async def auth_refresh(request: Request):
    """Silent session renewal: trade the stored rotating refresh token for a
    fresh access token. Driven by the client keep-alive / retry-on-401 so an
    active operator never re-logs mid-work. On any DH rejection, clear cookies
    and report session_expired so the client shows the interactive login."""
    refresh_token = request.cookies.get(co_auth.CO_REFRESH_COOKIE)
    if not refresh_token:
        return co_auth.session_expired_json()
    try:
        payload = co_auth.refresh_data_hub_session(refresh_token)
    except (httpx.HTTPError, ValueError):
        response = co_auth.session_expired_json()
        co_auth.clear_session_cookie(response)
        return response
    expires_in = int(payload.get("expires_in") or 600)
    response = JSONResponse({"ok": True, "expires_in": expires_in})
    co_auth.set_session_cookie(response, str(payload["access_token"]), expires_in, request=request)
    rotated = payload.get("refresh_token")
    if rotated:
        co_auth.set_refresh_cookie(response, str(rotated), request=request)
    return response
