"""'Có gì mới' (what's new) changelog page.

Feature brief: .ai/features/2026-06-07-app-versioning-changelog/brief.md
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from hub.app import changelog
from hub.app.main import app


def _login(c: TestClient) -> None:
    r = c.post(
        "/login",
        data={"email": "admin@data-hub.local", "password": "admin123",
              "next": "/whats-new"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text


def test_whats_new_requires_auth():
    with TestClient(app) as c:
        r = c.get("/whats-new", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/login" in r.headers["location"]


def test_whats_new_renders_release_and_running_version():
    with TestClient(app) as c:
        _login(c)
        r = c.get("/whats-new")
    assert r.status_code == 200
    # current running version is shown
    from hub.app import version as appver
    assert appver.version_info()["version"] in r.text
    # at least one changelog release renders (seed CHANGELOG has 0.1.0)
    assert "0.1.0" in r.text


def test_whats_new_escapes_bullet_html(monkeypatch):
    monkeypatch.setattr(changelog, "load_changelog", lambda: [
        {"version": "9.9.9", "date": "2026-06-07", "unreleased": False,
         "sections": [{"title": "Mới", "entries": ["<script>alert(1)</script>"]}]},
    ])
    with TestClient(app) as c:
        _login(c)
        r = c.get("/whats-new")
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text
