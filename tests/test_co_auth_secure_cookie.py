"""The session cookie must carry Secure whenever the connection is HTTPS.

This survived the move from JWT cookies to a server session, and it is worth
keeping: Data Hub's original `set_session_cookie` set Secure only when
DATA_HUB_FORCE_HTTPS_COOKIE=1, and both compose files default that to 0. Wiring
CO onto that cookie unchanged would have put production sessions on the wire
without Secure the moment someone forgot the flag.
"""
from __future__ import annotations

import pytest
from starlette.requests import Request
from starlette.responses import Response

from hub.app.auth import session as hub_session


def _request(scheme: str = "http", headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "scheme": scheme,
            "headers": raw_headers,
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "server": ("testserver", 443 if scheme == "https" else 80),
        }
    )


def _session_cookie(request: Request | None) -> str:
    response = Response()
    hub_session.set_session_cookie(response, "sid-test", request=request)
    for header in response.headers.getlist("set-cookie"):
        if header.startswith(f"{hub_session.SESSION_COOKIE}="):
            return header
    raise AssertionError("session cookie not set")


@pytest.fixture
def no_force(monkeypatch):
    monkeypatch.delenv("DATA_HUB_FORCE_HTTPS_COOKIE", raising=False)


def test_https_request_issues_a_secure_cookie(no_force):
    assert "Secure" in _session_cookie(_request("https"))


def test_forwarded_proto_https_issues_a_secure_cookie(no_force):
    """Behind a TLS proxy the app sees http; the forwarded header is the truth."""
    cookie = _session_cookie(_request("http", {"x-forwarded-proto": "https"}))

    assert "Secure" in cookie


def test_plain_http_local_dev_not_secure(no_force):
    """Local dev must not get Secure or the browser refuses to store it."""
    assert "Secure" not in _session_cookie(_request("http"))


def test_force_flag_forces_secure_over_plain_http(monkeypatch):
    monkeypatch.setenv("DATA_HUB_FORCE_HTTPS_COOKIE", "1")

    assert "Secure" in _session_cookie(_request("http"))


def test_unknown_scheme_fails_secure(no_force):
    """No request to read means no evidence it is safe — assume it is not."""
    assert "Secure" in _session_cookie(None)


def test_httponly_and_samesite_lax_preserved(no_force):
    cookie = _session_cookie(_request("https"))

    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie.replace("SameSite=Lax", "SameSite=lax")
