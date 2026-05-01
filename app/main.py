from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import auth, i18n
from app.database import apply_migrations
from app.routes import admin, agent, api, auth_api, bcct, bom, bqd, catalog, clients, notifications as notif_routes, proposals, uploads
from app.seed import auto_seed_demo_if_empty

ROOT = Path(__file__).resolve().parent
THEME_COOKIE = "data_hub_theme"
LANG_COOKIE = "data_hub_lang"
SUPPORTED_THEMES = {"light", "dark"}


def normalize_theme(value: str | None) -> str:
    return value if value in SUPPORTED_THEMES else "light"


def template_context(request: Request) -> dict:
    theme = normalize_theme(request.cookies.get(THEME_COOKIE))
    lang = i18n.normalize_lang(request.cookies.get(LANG_COOKIE))
    user = auth.current_user(request)

    # Bell badge data — single COUNT() per page render. Skipped when no
    # user (login page); skipped when notifications module not loaded.
    notif_unread = 0
    notif_recent: list = []
    if user is not None:
        try:
            from app import notifications as _notifs
            notif_unread = _notifs.unread_count(user.user_id)
            if notif_unread > 0:
                notif_recent = _notifs.list_for_user(
                    user.user_id, status="unread", limit=5,
                )
        except Exception:
            pass  # bell is non-critical; never crash page render

    return {
        "theme": theme,
        "next_theme": "dark" if theme == "light" else "light",
        "lang": lang,
        "next_lang": "en" if lang == "vi" else "vi",
        "t": lambda key: i18n.t(key, lang),
        "user": user,
        "can_manage_staff": lambda client_id: auth.can_assign_staff_to_client(user, client_id),
        "notif_unread_count": notif_unread,
        "notif_recent": notif_recent,
        "active_root": "",
        "active_tab": "",
        "message": None,
        "error": None,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    apply_migrations()
    seed_email = os.environ.get("DATA_HUB_SEED_EMAIL", "admin@data-hub.local")
    seed_password = os.environ.get("DATA_HUB_SEED_PASSWORD", "admin123")
    seeded_admin = auth.seed_admin_if_empty(email=seed_email, password=seed_password)
    if seeded_admin:
        print(f"[seed] Admin user created: {seed_email}")
    if os.environ.get("DATA_HUB_AUTO_SEED_DEMO", "1") == "1":
        seeded_demo = auto_seed_demo_if_empty()
        if seeded_demo:
            print(f"[seed] Demo data seeded: {seeded_demo}")
    yield


app = FastAPI(title="Data Hub", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates", context_processors=[template_context])

app.state.templates = templates

# Routers
app.include_router(clients.router)
app.include_router(catalog.router)
app.include_router(bqd.router)
app.include_router(bcct.router)
app.include_router(bom.router)
app.include_router(proposals.router)
app.include_router(uploads.router)
app.include_router(admin.router)
app.include_router(api.router)
app.include_router(notif_routes.router)
app.include_router(agent.router)
app.include_router(auth_api.router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = auth.current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/clients", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None, email: str | None = None):
    user = auth.current_user(request)
    if user:
        return RedirectResponse(url="/clients", status_code=302)
    return templates.TemplateResponse(
        request, "login.html",
        {"error": error, "email": email},
    )


@app.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    user = auth.authenticate(email, password)
    if not user:
        lang = i18n.normalize_lang(request.cookies.get(LANG_COOKIE))
        return templates.TemplateResponse(
            request, "login.html",
            {"error": i18n.t("auth.error_invalid", lang), "email": email},
            status_code=401,
        )
    session_id = auth.create_session(
        user.user_id,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    response = RedirectResponse(url="/clients", status_code=303)
    auth.set_session_cookie(response, session_id)
    return response


@app.post("/logout")
async def logout(request: Request):
    session_id = request.cookies.get(auth.SESSION_COOKIE)
    if session_id:
        auth.revoke_session(session_id)
    response = RedirectResponse(url="/login", status_code=303)
    auth.clear_session_cookie(response)
    return response


@app.post("/settings/theme")
async def settings_theme(
    request: Request,
    theme: str = Form(...),
    next_url: str = Form("/"),
):
    theme = normalize_theme(theme)
    response = RedirectResponse(url=next_url or "/", status_code=303)
    response.set_cookie(THEME_COOKIE, theme, max_age=60 * 60 * 24 * 365, path="/", samesite="lax")
    return response


@app.post("/settings/lang")
async def settings_lang(
    request: Request,
    lang: str = Form(...),
    next_url: str = Form("/"),
):
    lang = i18n.normalize_lang(lang)
    response = RedirectResponse(url=next_url or "/", status_code=303)
    response.set_cookie(LANG_COOKIE, lang, max_age=60 * 60 * 24 * 365, path="/", samesite="lax")
    return response
