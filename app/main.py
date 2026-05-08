from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import auth, i18n, settings_store
from app.database import apply_migrations, close_pool
from app.seed_master_data import seed_master_data_if_empty
from app.routes import admin, agent, api, auth_api, bcct, bom, bqd, catalog, client_config_ui, clients, master_data, notifications as notif_routes, proposals, uploads
from app.seed import auto_seed_demo_if_empty, seed_parser_rules_if_empty

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
    chat_widget_clients: list = []
    chat_agent_enabled = True
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
        try:
            chat_agent_enabled = settings_store.chat_agent_enabled()
            if chat_agent_enabled:
                rows = clients.list_clients()
                allowed = auth.visible_clients(user)
                if allowed is not None:
                    allowed_set = set(allowed)
                    rows = [row for row in rows if row["client_id"] in allowed_set]
                chat_widget_clients = [
                    {"client_id": row["client_id"], "name": row["name"]}
                    for row in rows[:25]
                ]
        except Exception:
            pass  # chat widget is non-critical; never crash page render

    return {
        "theme": theme,
        "next_theme": "dark" if theme == "light" else "light",
        "lang": lang,
        "next_lang": "en" if lang == "vi" else "vi",
        "t": lambda key: i18n.t(key, lang),
        "user": user,
        "can_manage_staff": lambda client_id: auth.can_assign_staff_to_client(user, client_id),
        "can_edit_technical": lambda client_id: auth.can_edit_client_technical(user, client_id),
        "notif_unread_count": notif_unread,
        "notif_recent": notif_recent,
        "chat_agent_enabled": chat_agent_enabled,
        "chat_widget_clients": chat_widget_clients,
        # Note: do NOT set active_root/active_tab/message/error defaults
        # here. Starlette's context_processor output overrides the route's
        # explicit context dict, so any default we set would clobber the
        # per-route value. Routes that don't set these get Jinja's
        # undefined treated as falsy in {% if %}.
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    apply_migrations()
    if os.environ.get("DATA_HUB_API_AUTH_DISABLED", "") == "1":
        if (settings_store.get("api_auth_strict") or "").lower() in {"1", "true", "yes"}:
            print(
                "[auth] DATA_HUB_API_AUTH_DISABLED=1 ignored — "
                "api_auth_strict=true takes precedence",
            )
        else:
            print(
                "[auth] *** DEV: API auth DISABLED on /v1/hub/* — "
                "missing/empty bearer is accepted. Never set this in prod.",
            )
    seeded_master = seed_master_data_if_empty()
    if any(seeded_master.values()):
        print(f"[seed] Master data seeded: {seeded_master}")
    seed_email = os.environ.get("DATA_HUB_SEED_EMAIL", "admin@data-hub.local")
    seed_password = os.environ.get("DATA_HUB_SEED_PASSWORD", "admin123")
    seeded_admin = auth.seed_admin_if_empty(email=seed_email, password=seed_password)
    if seeded_admin:
        print(f"[seed] Admin user created: {seed_email}")
    if os.environ.get("DATA_HUB_AUTO_SEED_DEMO", "1") == "1":
        seeded_demo = auto_seed_demo_if_empty()
        if seeded_demo:
            print(f"[seed] Demo data seeded: {seeded_demo}")
    # Parser rules (mig 036/037 are no-ops on fresh DB; seed via app code).
    seed_parser_rules_if_empty()
    yield
    # On shutdown: drain and close the pool so the process exits cleanly
    # without leaving Postgres connections in TIME_WAIT.
    close_pool()


app = FastAPI(title="Data Hub", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates", context_processors=[template_context])

app.state.templates = templates


def safe_next_path(value: str | None, default: str = "/clients") -> str:
    if not value:
        return default
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return default
    return urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))


def _from_json_filter(s):
    """Jinja filter: parse a JSON string. Returns {} on failure (for
    use in templates that show legacy chat-thread tool_call args)."""
    import json as _json
    if not s:
        return {}
    if isinstance(s, dict):
        return s
    try:
        return _json.loads(s)
    except Exception:
        return {}


templates.env.filters["from_json"] = _from_json_filter

# Routers
app.include_router(clients.router)
app.include_router(catalog.router)
app.include_router(bqd.router)
app.include_router(bcct.router)
app.include_router(bom.router)
app.include_router(proposals.router)
app.include_router(uploads.router)
app.include_router(admin.router)
app.include_router(master_data.router)
app.include_router(client_config_ui.router)
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
async def login_page(request: Request, error: str | None = None, email: str | None = None, next: str = "/clients"):
    user = auth.current_user(request)
    if user:
        return RedirectResponse(url=safe_next_path(next), status_code=302)
    return templates.TemplateResponse(
        request, "login.html",
        {"error": error, "email": email, "next": safe_next_path(next)},
    )


@app.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/clients"),
):
    user = auth.authenticate(email, password)
    if not user:
        lang = i18n.normalize_lang(request.cookies.get(LANG_COOKIE))
        return templates.TemplateResponse(
            request, "login.html",
            {"error": i18n.t("auth.error_invalid", lang), "email": email, "next": safe_next_path(next)},
            status_code=401,
        )
    session_id = auth.create_session(
        user.user_id,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    response = RedirectResponse(url=safe_next_path(next), status_code=303)
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
