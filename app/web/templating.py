from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from app import co_auth
from app import version as appver
from app.bang_ke_rows import material_render_parts


_BOLD_MD = re.compile(r"\*\*(.+?)\*\*")


def bold_md(text: str) -> Markup:
    """Render ``**bold**`` spans in changelog bullets without trusting the rest
    of the string: every segment is HTML-escaped and only the ``<strong>``
    wrappers we emit are markup (no ``|safe`` on the whole bullet). Unmatched
    ``**`` is left as escaped literal text."""
    source = str(text)
    out = Markup("")
    pos = 0
    for match in _BOLD_MD.finditer(source):
        out += escape(source[pos:match.start()])
        out += Markup("<strong>") + escape(match.group(1)) + Markup("</strong>")
        pos = match.end()
    out += escape(source[pos:])
    return out


APP_ROOT = Path(__file__).resolve().parent.parent
STATIC_ROOT = APP_ROOT / "static"

THEME_COOKIE = "co_theme"
SUPPORTED_THEMES = {"light", "dark"}


@lru_cache(maxsize=None)
def _asset_version(rel_path: str) -> str:
    """Short content hash of a static file, for cache-busting.

    Cached for the process lifetime — prod restarts on deploy and the dev
    server restarts on file change (--reload watches *.css), so the hash is
    always recomputed when the file actually changes.
    """
    try:
        data = (STATIC_ROOT / rel_path).read_bytes()
    except OSError:
        return ""
    return hashlib.sha1(data).hexdigest()[:8]


def asset_url(path: str) -> str:
    """Versioned URL for a static asset: ``/static/<path>?v=<hash>``.

    Append the content hash so CDN/browser caches fetch the new file the
    moment its contents change, instead of serving a stale copy.
    """
    rel = path.lstrip("/")
    if rel.startswith("static/"):
        rel = rel[len("static/"):]
    version = _asset_version(rel)
    return f"/static/{rel}?v={version}" if version else f"/static/{rel}"


def normalize_theme(value: str | None) -> str:
    return value if value in SUPPORTED_THEMES else "light"


def theme_context(request: Request) -> dict[str, str]:
    theme = normalize_theme(request.cookies.get(THEME_COOKIE))
    user = co_auth.current_user(request)
    return {
        "theme": theme,
        "next_theme": "light" if theme == "dark" else "dark",
        "app_version": appver.version_info(),
        "co_user": user,
        "auth_required": co_auth.auth_required(),
        "show_login": (co_auth.auth_required() or co_auth.data_hub_source_mode_enabled()) and request.url.path != "/auth/logout",
        "can_view_technical_settings": co_auth.can_view_technical_settings(user),
        "can_delete_co_cases": co_auth.can_delete_co_cases(user),
    }


templates = Jinja2Templates(directory=APP_ROOT / "templates", context_processors=[theme_context])
templates.env.globals["asset_url"] = asset_url
templates.env.globals["material_render_parts"] = material_render_parts
templates.env.filters["bold_md"] = bold_md
