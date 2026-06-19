"""'Có gì mới' (what's new) changelog page.

Feature brief: .ai/features/2026-06-07-co-app-versioning-changelog/brief.md
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import changelog
from app import version as appver
from app.main import app


def test_whats_new_requires_auth_in_prod(monkeypatch):
    # When auth is enforced (prod), the page is guarded like the rest of the
    # app — anonymous request redirects to the Data Hub SSO login.
    monkeypatch.setenv("CO_AUTH_REQUIRED", "1")
    r = TestClient(app).get("/whats-new", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/auth/login?next=/whats-new"


def test_whats_new_renders_release_and_running_version():
    # Default test mode: auth off → page is open.
    with TestClient(app) as c:
        r = c.get("/whats-new")
    assert r.status_code == 200
    # current running version is shown
    assert appver.version_info()["version"] in r.text
    # at least one changelog release renders (seed CHANGELOG has 0.1.0)
    assert "0.1.0" in r.text


def test_whats_new_escapes_bullet_html(monkeypatch):
    monkeypatch.setattr(changelog, "load_changelog", lambda: [
        {"version": "9.9.9", "date": "2026-06-07", "unreleased": False,
         "sections": [{"title": "Mới", "entries": ["<script>alert(1)</script>"]}]},
    ])
    with TestClient(app) as c:
        r = c.get("/whats-new")
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_whats_new_renders_bold_markdown(monkeypatch):
    monkeypatch.setattr(changelog, "load_changelog", lambda: [
        {"version": "9.9.9", "date": "2026-06-07", "unreleased": False,
         "sections": [{"title": "Mới", "entries": ["**Tính năng**: mô tả <b>x</b>"]}]},
    ])
    with TestClient(app) as c:
        r = c.get("/whats-new")
    assert "<strong>Tính năng</strong>" in r.text
    assert "**Tính năng**" not in r.text          # markers consumed
    assert "<b>x</b>" not in r.text                # inline HTML still escaped
    assert "&lt;b&gt;x&lt;/b&gt;" in r.text


def test_bold_md_filter_escapes_each_segment():
    from app.web.templating import bold_md
    assert str(bold_md("**a** b")) == "<strong>a</strong> b"
    assert str(bold_md("no bold here")) == "no bold here"
    # HTML in both bold and plain segments is escaped; only our tags survive.
    assert str(bold_md("x <i>y</i> **<b>z</b>**")) == "x &lt;i&gt;y&lt;/i&gt; <strong>&lt;b&gt;z&lt;/b&gt;</strong>"
    # Unmatched ** stays as escaped literal.
    assert str(bold_md("a ** b")) == "a ** b"
