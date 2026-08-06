from __future__ import annotations

import types

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app import co_auth


def _request(scheme: str = "http", headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "scheme": scheme,
        "headers": raw_headers,
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "server": ("testserver", 443 if scheme == "https" else 80),
    }
    return Request(scope)


def _cookie(response: Response, name: str) -> str:
    for header in response.headers.getlist("set-cookie"):
        if header.startswith(f"{name}="):
            return header
    raise AssertionError(f"cookie {name!r} not set: {response.headers.getlist('set-cookie')!r}")


def _session_and_refresh(request: Request) -> tuple[str, str]:
    response = Response()
    co_auth.set_session_cookie(response, "access-token", request=request)
    co_auth.set_refresh_cookie(response, "refresh-token", request=request)
    return _cookie(response, co_auth.CO_SESSION_COOKIE), _cookie(response, co_auth.CO_REFRESH_COOKIE)


@pytest.fixture
def no_force(monkeypatch):
    """CO_FORCE_HTTPS_COOKIE off, so Secure is driven purely by request scheme."""
    monkeypatch.setattr(
        co_auth,
        "data_hub_link_settings",
        lambda: types.SimpleNamespace(force_https_cookie=False),
    )


def test_https_request_issues_both_cookies_secure(no_force):
    session, refresh = _session_and_refresh(_request(scheme="https"))
    assert "Secure" in session
    assert "Secure" in refresh


def test_forwarded_proto_https_issues_both_cookies_secure(no_force):
    # Prod terminates TLS at the proxy and forwards over http with this header.
    session, refresh = _session_and_refresh(
        _request(scheme="http", headers={"x-forwarded-proto": "https"})
    )
    assert "Secure" in session
    assert "Secure" in refresh


def test_plain_http_local_dev_not_secure(no_force):
    session, refresh = _session_and_refresh(_request(scheme="http"))
    assert "Secure" not in session
    assert "Secure" not in refresh


def test_force_flag_forces_secure_over_plain_http(monkeypatch):
    monkeypatch.setattr(
        co_auth,
        "data_hub_link_settings",
        lambda: types.SimpleNamespace(force_https_cookie=True),
    )
    session, refresh = _session_and_refresh(_request(scheme="http"))
    assert "Secure" in session
    assert "Secure" in refresh


def test_httponly_and_samesite_lax_preserved(no_force):
    session, refresh = _session_and_refresh(_request(scheme="https"))
    for cookie in (session, refresh):
        assert "HttpOnly" in cookie
        assert "samesite=lax" in cookie.lower()
