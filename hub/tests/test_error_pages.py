"""Elegant error handling: UI routes render friendly pages / bounce to
login; API routes keep the raw `{"detail": ...}` JSON contract.

Global handlers live in app/main.py (StarletteHTTPException /
RequestValidationError / Exception).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from hub.app import i18n
from hub.app.main import app


def test_translate_detail_static_dynamic_and_passthrough():
    """i18n.translate_detail: exact map, dynamic prefixes (value preserved),
    unknown passthrough, and lang-awareness."""
    # exact
    assert i18n.translate_detail("forbidden", "vi") == "Không có quyền truy cập."
    assert i18n.translate_detail("Client not found", "vi") == "Không tìm thấy khách hàng."
    # dynamic prefix — remainder (value) preserved
    assert i18n.translate_detail("invalid category: 'foo'", "vi") == "Phân loại không hợp lệ: 'foo'"
    assert i18n.translate_detail("Parse error: boom", "vi") == "Lỗi phân tích: boom"
    assert i18n.translate_detail("Unknown job kind: pdf", "vi") == "Loại tác vụ không xác định: pdf"
    # unknown → unchanged
    assert i18n.translate_detail("something bespoke", "vi") == "something bespoke"
    # en → original
    assert i18n.translate_detail("forbidden", "en") == "forbidden"
    assert i18n.translate_detail("invalid category: 'foo'", "en") == "invalid category: 'foo'"


def _login(c: TestClient) -> None:
    r = c.post(
        "/login",
        data={"email": "admin@data-hub.local", "password": "admin123"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text


# ── UI routes: friendly, not raw JSON ────────────────────────────────

def test_protected_page_unauthenticated_bounces_to_login():
    with TestClient(app) as c:
        r = c.get("/clients", follow_redirects=False)
    assert r.status_code == 303, r.text
    loc = r.headers["location"]
    assert loc.startswith("/login?next="), loc
    assert "%2Fclients" in loc
    # The whole point: no raw JSON error leaks to the browser.
    assert '{"detail"' not in r.text


def test_login_bounce_preserves_query_string():
    with TestClient(app) as c:
        r = c.get("/clients?q=acme&page=2", follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert "q%3Dacme" in loc and "page%3D2" in loc, loc


def test_404_renders_html_page_not_json():
    with TestClient(app) as c:
        _login(c)
        r = c.get("/clients/does-not-exist-zzz", follow_redirects=False)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/html")
    assert '{"detail"' not in r.text
    # Friendly framing from error.html (vi default) ...
    assert "Không tìm thấy" in r.text
    assert "404" in r.text
    # ... plus the route's actual error message, surfaced to the user and
    # localized to Vietnamese (default lang).
    assert "Không tìm thấy khách hàng" in r.text
    assert "Client not found" not in r.text


# ── API routes: JSON contract preserved ──────────────────────────────

def test_api_v1_hub_keeps_json_401():
    """Sister-app Bearer surface must still get `{"detail": ...}` JSON,
    never an HTML page or a /login redirect."""
    with TestClient(app) as c:
        r = c.get("/v1/hub/dncxs", follow_redirects=False)
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")
    assert "detail" in r.json()


def test_api_v1_cookie_route_keeps_json_not_redirect():
    """Cookie-UI JSON fetch surface (`/api/v1/*`) stays JSON so client-side
    fetch callers don't receive an HTML page or a 303 to /login."""
    with TestClient(app) as c:
        r = c.get(
            "/api/v1/clients/c_x/materials/m_x/substitutes",
            follow_redirects=False,
        )
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")
    assert "detail" in r.json()


def test_404_detail_stays_english_for_en_lang():
    """Detail localization is lang-aware: an en cookie keeps the original
    English route message; vi (default) localizes it."""
    with TestClient(app) as c:
        _login(c)
        c.cookies.set("data_hub_lang", "en")
        r = c.get("/clients/does-not-exist-zzz", follow_redirects=False)
    assert r.status_code == 404
    assert "Client not found" in r.text
    assert "Không tìm thấy khách hàng" not in r.text


def test_fetch_on_ui_route_gets_json_not_html():
    """A programmatic fetch (Sec-Fetch-Mode: cors) to a non-/api/v1 UI route
    — e.g. the chat widget — gets JSON, not the HTML page, so the JS can read
    the error. Even a 401 returns JSON (no opaque redirect to the login HTML)."""
    with TestClient(app) as c:
        r = c.get(
            "/clients/c_x/agent/_widget",
            headers={"sec-fetch-mode": "cors"},
            follow_redirects=False,
        )
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")
    assert "detail" in r.json()


def test_navigation_on_ui_route_still_gets_page():
    """A top-level navigation (Sec-Fetch-Mode: navigate) to the same widget
    path still bounces to login, proving fetch-detection doesn't hijack real
    browser navigations."""
    with TestClient(app) as c:
        r = c.get(
            "/clients/c_x/agent/_widget",
            headers={"sec-fetch-mode": "navigate"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login?next=")
