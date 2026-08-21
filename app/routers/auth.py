"""Sign-in for the consolidated app.

One process, one session table, one cookie. The SSO round trip this replaced —
redirect to Data Hub's /authorize, come back with a code, exchange it for a
JWT, fetch a JWKS to verify the signature, then rotate a refresh token to stay
signed in — existed only because the two halves were separate services that had
to prove identity to each other over a network. There is no network between
them any more, so the session row is simply read.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import co_auth
from app.web.templating import templates


router = APIRouter()


@router.get("/auth/login")
async def auth_login(request: Request, next: str = "/clients", error: str = ""):
    if co_auth.load_optional_user(request):
        return RedirectResponse(co_auth.safe_next_path(next), status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"next_path": co_auth.safe_next_path(next), "error": error},
        status_code=401 if error else 200,
    )


@router.post("/auth/login")
async def auth_login_submit(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    next_url: str = Form("/clients"),
):
    from hub.app.auth import session as hub_session

    next_path = co_auth.safe_next_path(next_url)
    user = hub_session.authenticate(email.strip(), password)
    if user is None:
        # Deliberately not "unknown email" vs "wrong password" — that difference
        # tells an attacker which addresses are real.
        return RedirectResponse(
            f"/auth/login?next={next_path}&error=1", status_code=303
        )
    session_id = hub_session.create_session(
        user.user_id,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    response = RedirectResponse(next_path, status_code=303)
    hub_session.set_session_cookie(response, session_id, request=request)
    return response


@router.post("/auth/logout")
async def auth_logout(request: Request, next_url: str = Form("/clients")):
    from hub.app.auth import session as hub_session

    next_path = co_auth.safe_next_path(next_url)
    session_id = request.cookies.get(hub_session.SESSION_COOKIE)
    if session_id:
        hub_session.revoke_session(session_id)
    request.state.co_user = None
    target = f"{next_path}?logged_out=1" if next_path == "/user" else next_path
    response = RedirectResponse(target, status_code=303)
    hub_session.clear_session_cookie(response)
    return response
