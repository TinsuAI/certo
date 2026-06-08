from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Callable, Iterable
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import httpx
import jwt
from fastapi import Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from app.data_hub_settings import data_hub_link_settings


CO_SESSION_COOKIE = "co_data_hub_session"
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


class DataHubTokenVerifier:
    def __init__(self, *, issuer: str | Iterable[str], jwks_provider: Callable[[], dict]):
        if isinstance(issuer, str):
            self.issuers = (issuer,)
        else:
            self.issuers = tuple(dict.fromkeys(issuer))
        self.jwks_provider = jwks_provider

    def verify(self, token: str) -> DataHubUser:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            raise jwt.InvalidTokenError("missing kid")
        jwks = self.jwks_provider()
        key = next((item for item in jwks.get("keys", []) if item.get("kid") == kid), None)
        if key is None:
            raise jwt.InvalidTokenError(f"unknown kid: {kid}")
        signing_key = jwt.PyJWK.from_dict(key).key
        last_error: jwt.InvalidTokenError | None = None
        claims = {}
        for issuer in self.issuers:
            try:
                claims = jwt.decode(
                    token,
                    signing_key,
                    algorithms=["EdDSA"],
                    issuer=issuer,
                    options={"require": ["exp", "iat", "iss", "sub"]},
                    leeway=60,
                )
                break
            except jwt.InvalidIssuerError as exc:
                last_error = exc
        else:
            raise last_error or jwt.InvalidTokenError("invalid issuer")
        return DataHubUser(
            user_id=str(claims["sub"]),
            email=str(claims.get("email", "")),
            role=str(claims.get("role", "")),
            name=str(claims.get("name", "")),
            claims=dict(claims),
            access_token=token,
        )


def auth_required() -> bool:
    return data_hub_link_settings().auth_required


def data_hub_source_mode_enabled() -> bool:
    return data_hub_link_settings().source_enabled


def data_hub_base_url() -> str:
    return data_hub_link_settings().data_hub_base_url


def data_hub_api_base_url() -> str:
    return data_hub_link_settings().data_hub_api_base_url


def data_hub_issuer_url() -> str:
    return data_hub_link_settings().issuer_url


def data_hub_issuer_urls() -> tuple[str, ...]:
    primary = data_hub_issuer_url()
    aliases = [primary, *loopback_url_aliases(primary)]
    return tuple(dict.fromkeys(aliases))


def data_hub_jwks_url() -> str:
    return data_hub_link_settings().jwks_url


def data_hub_request_timeout_seconds() -> float:
    return data_hub_link_settings().request_timeout_seconds


def fetch_data_hub_jwks(url: str) -> dict:
    now = monotonic()
    cached = _JWKS_CACHE.get(url)
    if cached and now - cached[0] <= JWKS_CACHE_TTL_SECONDS:
        return cached[1]
    try:
        response = httpx.get(url, timeout=data_hub_request_timeout_seconds())
        response.raise_for_status()
        jwks = response.json()
        if not isinstance(jwks, dict):
            raise ValueError("Data Hub JWKS response must be a JSON object.")
    except (httpx.HTTPError, ValueError):
        if cached:
            return cached[1]
        raise
    _JWKS_CACHE[url] = (now, jwks)
    return jwks


def clear_jwks_cache() -> None:
    _JWKS_CACHE.clear()


def current_user(request: Request) -> DataHubUser | None:
    user = getattr(request.state, "co_user", None)
    return user if isinstance(user, DataHubUser) else None


def verify_session_token(token: str) -> DataHubUser:
    verifier = DataHubTokenVerifier(
        issuer=data_hub_issuer_urls(),
        jwks_provider=lambda: fetch_data_hub_jwks(data_hub_jwks_url()),
    )
    return verifier.verify(token)


def load_optional_user(request: Request) -> DataHubUser | None:
    user = current_user(request)
    if user:
        return user
    token = bearer_token(request) or request.cookies.get(CO_SESSION_COOKIE)
    if not token:
        return None
    try:
        user = verify_session_token(token)
    except (jwt.InvalidTokenError, httpx.HTTPError, ValueError):
        return None
    request.state.co_user = user
    return user


def guard_response(request: Request) -> RedirectResponse | PlainTextResponse | None:
    if not auth_required() or not should_guard_path(request.url.path):
        return None
    token = bearer_token(request) or request.cookies.get(CO_SESSION_COOKIE)
    if not token:
        return login_redirect(request)
    try:
        user = verify_session_token(token)
    except (jwt.InvalidTokenError, httpx.HTTPError, ValueError):
        return login_redirect(request)
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
    if not user:
        return set()
    settings = data_hub_link_settings()
    if user.role in settings.admin_roles or user.claims.get("all_clients") is True:
        return None
    values: set[str] = set()
    for key in settings.client_claim_keys:
        values.update(claim_values(user.claims.get(key)))
    if "*" in values:
        return None
    return values


def claim_values(value) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {part.strip() for part in value.replace(",", " ").split() if part.strip()}
    if isinstance(value, dict):
        return {
            str(value[key]).strip()
            for key in ("id", "client_id", "dncx_id")
            if value.get(key)
        }
    if isinstance(value, (list, tuple, set)):
        values: set[str] = set()
        for item in value:
            values.update(claim_values(item))
        return values
    return {str(value).strip()} if str(value).strip() else set()


def bearer_token(request: Request) -> str:
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


def login_redirect(request: Request) -> RedirectResponse:
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(f"/auth/login?next={quote(target, safe='/')}", status_code=303)


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


def data_hub_login_url(next_url: str = "/clients") -> str:
    return f"{data_hub_base_url()}/login?{urlencode({'next': next_url or '/clients'})}"


def data_hub_logout_url() -> str:
    return f"{data_hub_base_url()}/logout"


def data_hub_authorize_url(*, redirect_uri: str, state: str = "/clients") -> str:
    return f"{data_hub_base_url()}/v1/auth/authorize?{urlencode({'redirect_uri': redirect_uri, 'state': safe_next_path(state)})}"


def exchange_data_hub_sso_code(code: str, *, redirect_uri: str = "") -> dict:
    payload = {"code": code}
    if redirect_uri:
        payload["redirect_uri"] = redirect_uri
    response = httpx.post(
        f"{data_hub_api_base_url()}/v1/auth/exchange",
        json=payload,
        timeout=data_hub_request_timeout_seconds(),
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("access_token"):
        raise ValueError("Data Hub exchange did not return an access token.")
    return payload


def set_session_cookie(response, token: str, max_age: int = 600) -> None:
    response.set_cookie(
        CO_SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=data_hub_link_settings().force_https_cookie,
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(CO_SESSION_COOKIE, path="/")
