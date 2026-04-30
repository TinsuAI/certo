from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import auth
from app.database import apply_migrations
from app.routes import bcct, bom, code_mappings, dncxs, materials

ROOT = Path(__file__).resolve().parent
THEME_COOKIE = "data_hub_theme"
SUPPORTED_THEMES = {"light", "dark"}


def normalize_theme(value: str | None) -> str:
    return value if value in SUPPORTED_THEMES else "light"


def template_context(request: Request) -> dict:
    theme = normalize_theme(request.cookies.get(THEME_COOKIE))
    user = auth.current_user(request)
    return {
        "theme": theme,
        "next_theme": "dark" if theme == "light" else "light",
        "user": user,
        "active": "",
        "flash": None,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    apply_migrations()
    seed_email = os.environ.get("DATA_HUB_SEED_EMAIL", "admin@data-hub.local")
    seed_password = os.environ.get("DATA_HUB_SEED_PASSWORD", "admin123")
    seeded = auth.seed_admin_if_empty(email=seed_email, password=seed_password)
    if seeded:
        print(f"[seed] Admin user created: {seed_email}")
    yield


app = FastAPI(title="Data Hub", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates", context_processors=[template_context])

# Make `templates` accessible to routers.
app.state.templates = templates

# Mount entity routers.
app.include_router(dncxs.router)
app.include_router(materials.router)
app.include_router(code_mappings.router)
app.include_router(bcct.router)
app.include_router(bom.router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = auth.current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/dncxs", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None, email: str | None = None):
    user = auth.current_user(request)
    if user:
        return RedirectResponse(url="/dncxs", status_code=302)
    return templates.TemplateResponse(
        request,
        "login.html",
        { "error": error, "email": email},
    )


@app.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    user = auth.authenticate(email, password)
    if not user:
        return templates.TemplateResponse(
        request,
        "login.html",
        { "error": "Email hoặc mật khẩu không đúng.", "email": email},
            status_code=401,
        )
    session_id = auth.create_session(
        user.user_id,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    response = RedirectResponse(url="/dncxs", status_code=303)
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
