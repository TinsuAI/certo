from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Callable, Iterable
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import httpx
import jwt
from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from app.data_hub_settings import data_hub_link_settings


CO_SESSION_COOKIE = "co_data_hub_session"
CO_REFRESH_COOKIE = "co_data_hub_refresh"
# DH is the source of truth on refresh-token validity (sliding, 7d ceiling); the
# cookie just has to outlive the short access token so the browser keeps it.
REFRESH_COOKIE_MAX_AGE = 7 * 24 * 3600
JWKS_CACHE_TTL_SECONDS = 300.0
_JWKS_CACHE: dict[str, tuple[float, dict]] = {}


@dataclass(frozen=True)
class DataHubUser:
    user_id: str
    email: str
    role: str
    name: str
    claims: dict
    access_token: str = ""


def auth_required() -> bool:
    return data_hub_link_settings().auth_required


def data_hub_source_mode_enabled() -> bool:
    return data_hub_link_settings().source_enabled


def data_hub_base_url() -> str:
    return data_hub_link_settings().data_hub_base_url


def data_hub_api_base_url() -> str:
    return data_hub_link_settings().data_hub_api_base_url


def data_hub_request_timeout_seconds() -> float:
    return data_hub_link_settings().request_timeout_seconds


def current_user(request: Request) -> DataHubUser | None:
    user = getattr(request.state, "co_user", None)
    return user if isinstance(user, DataHubUser) else None


def session_user(request: Request) -> DataHubUser | None:
    """Resolve the signed-in user from the shared server session.

    One process, one session table, one cookie. There is no longer a token to
    mint, sign, fetch a JWKS for, or verify across a network boundary — the
    session row is looked up directly. `claims` stays on the dataclass and stays
    empty: client scoping is a role query now (see `visible_client_ids`), not a
    list carried inside a token.
    """
    try:
        from hub.app.auth import session as hub_session
    except Exception:  # noqa: BLE001
        return None
    record = hub_session.current_user(request)
    if record is None:
        return None
    return DataHubUser(
        user_id=record.user_id,
        email=record.email,
        role=record.role,
        name=getattr(record, "display_name", "") or record.email,
        claims={},
    )


def load_optional_user(request: Request) -> DataHubUser | None:
    user = current_user(request)
    if user:
        return user
    user = session_user(request)
    if user is None:
        return None
    request.state.co_user = user
    return user


def guard_response(request: Request) -> RedirectResponse | JSONResponse | PlainTextResponse | None:
    if not auth_required() or not should_guard_path(request.url.path):
        return None
    user = session_user(request)
    if user is None:
        return auth_challenge(request)
    request.state.co_user = user
    client_id = client_id_from_path(request.url.path)
    if client_id and not can_view_client(user, client_id):
        return PlainTextResponse("Forbidden", status_code=403)
    return None


def should_guard_path(path: str) -> bool:
    if path.startswith(("/static", "/auth")) or path == "/settings/theme":
        return False
    return (
        path == "/"
        or path == "/clients"
        or path == "/clients-picker"
        or path.startswith("/clients/")
        or path == "/portfolio"
        or path.startswith("/portfolio/")
        or path == "/user"
        or path == "/whats-new"
        or path == "/settings"
        or path.startswith("/settings/")
    )


def client_id_from_path(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "clients":
        return parts[1]
    if len(parts) >= 4 and parts[:3] == ["portfolio", "api", "clients"]:
        return parts[3]
    return ""


def can_view_client(user: DataHubUser | None, client_id: str) -> bool:
    if not user:
        return False
    visible = visible_client_ids(user)
    return visible is None or client_id in visible


def can_view_technical_settings(user: DataHubUser | None) -> bool:
    if not auth_required():
        return True
    return bool(user and user.role == "dev")


def can_delete_co_cases(user: DataHubUser | None) -> bool:
    if not auth_required():
        return True
    return bool(user and user.role in data_hub_link_settings().co_case_delete_roles)


def filter_visible_clients(clients: Iterable[dict], user: DataHubUser | None) -> list[dict]:
    visible = visible_client_ids(user)
    if visible is None:
        return [dict(client) for client in clients]
    return [dict(client) for client in clients if str(client.get("id", "")) in visible]


def visible_client_ids(user: DataHubUser | None) -> set[str] | None:
    """Which clients this user may see; None means "all".

    Delegates to the role model that owns the answer — dev/admin see everything,
    a manager sees what they manage, staff see what they are assigned. Before
    consolidation this read a whitelist out of JWT claims, which meant the
    answer was only as fresh as the last token issued.
    """
    if not user:
        return set()
    try:
        from hub.app.auth import permissions as hub_permissions
        from hub.app.auth.session import User as HubUser
    except Exception:  # noqa: BLE001
        return None
    allowed = hub_permissions.visible_clients(
        HubUser(
            user_id=user.user_id,
            email=user.email,
            display_name=user.name,
            role=user.role,
            status="active",
        )
    )
    return None if allowed is None else set(allowed)


def bearer_token(request: Request) -> str:
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


def login_next_url(request: Request) -> str:
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return f"/auth/login?next={quote(target, safe='/')}"


def login_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse(login_next_url(request), status_code=303)


def is_xhr_request(request: Request) -> bool:
    """A background fetch/XHR vs. a top-level browser page load. Detection is
    POSITIVE: only requests that clearly announce themselves as fetch/XHR divert
    to a JSON 401 — a bare navigation still gets the SSO login redirect. XHRs
    must not get the 303, because following it to the cross-origin SSO page makes
    fetch() throw `TypeError: Failed to fetch` (the ~10-minute prod disconnect)."""
    dest = request.headers.get("sec-fetch-dest")
    if dest:
        return dest != "document"
    if request.headers.get("x-requested-with", "").lower() == "xmlhttprequest":
        return True
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept


def session_expired_json(login_url: str = "/auth/login") -> JSONResponse:
    return JSONResponse(
        {
            "detail": "Phiên đăng nhập đã hết hạn. Đăng nhập lại để tiếp tục.",
            "code": "session_expired",
            "login_url": login_url,
        },
        status_code=401,
    )


def auth_challenge(request: Request) -> RedirectResponse | JSONResponse:
    if not is_xhr_request(request):
        return login_redirect(request)
    return session_expired_json(login_next_url(request))


def safe_next_path(value: str | None, default: str = "/clients") -> str:
    if not value:
        return default
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return default
    return urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))


def loopback_url_aliases(value: str) -> list[str]:
    parsed = urlsplit(value)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return []
    alias_host = "localhost" if parsed.hostname == "127.0.0.1" else "127.0.0.1"
    netloc = alias_host
    if parsed.port:
        netloc = f"{alias_host}:{parsed.port}"
    return [urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))]


def co_public_base_url(request: Request) -> str:
    configured = data_hub_link_settings().co_public_base_url
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def request_is_https(request: Request | None) -> bool:
    """True when the browser-facing request is HTTPS. The app runs behind a
    proxy that terminates TLS and forwards over http, so trust
    `X-Forwarded-Proto` (first value if it is a comma-separated list) in
    addition to the direct request scheme."""
    if request is None:
        return False
    if request.url.scheme == "https":
        return True
    forwarded = request.headers.get("x-forwarded-proto", "")
    return forwarded.split(",")[0].strip().lower() == "https"


def cookie_secure(request: Request | None = None) -> bool:
    """Whether the auth cookies get the `Secure` flag. On by default for any
    HTTPS request so prod (behind the TLS proxy) never issues cookies without
    Secure. Plain-http local dev gets Secure off so the browser still stores the
    cookie. `CO_FORCE_HTTPS_COOKIE` is an explicit force-enable override. When
    the scheme is unknown (no request), fail secure."""
    if data_hub_link_settings().force_https_cookie:
        return True
    if request is None:
        return True
    return request_is_https(request)


def set_session_cookie(response, token: str, max_age: int = 600, *, request: Request | None = None) -> None:
    response.set_cookie(
        CO_SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(CO_SESSION_COOKIE, path="/")
    response.delete_cookie(CO_REFRESH_COOKIE, path="/")
