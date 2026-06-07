"""Version resolver + /version endpoint.

Feature brief: .ai/features/2026-06-07-co-app-versioning-changelog/brief.md
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import version as appver
from app.main import app


def test_baked_env_takes_precedence(monkeypatch):
    monkeypatch.setenv("CO_VERSION", "9.9.9")
    monkeypatch.setenv("CO_GIT_SHA", "deadbee")
    monkeypatch.setenv("CO_BUILD_TIME", "2026-06-07T00:00:00Z")
    info = appver.version_info()
    assert info["version"] == "9.9.9"
    assert info["git_sha"] == "deadbee"
    assert info["build_time"] == "2026-06-07T00:00:00Z"
    assert info["source"] == "build"


def test_dev_fallback_reads_pyproject(monkeypatch):
    monkeypatch.delenv("CO_VERSION", raising=False)
    monkeypatch.delenv("CO_GIT_SHA", raising=False)
    monkeypatch.delenv("CO_BUILD_TIME", raising=False)
    info = appver.version_info()
    # pyproject is the source of truth in dev; whatever it says, it's a
    # non-empty semver-ish string and the source is flagged "dev".
    assert info["version"]
    assert info["version"] != "unknown"
    assert info["source"] == "dev"


def test_unknown_when_pyproject_missing(monkeypatch):
    monkeypatch.delenv("CO_VERSION", raising=False)
    monkeypatch.setattr(appver, "_read_pyproject_version", lambda: None)
    monkeypatch.setattr(appver, "_dev_git_sha", lambda: None)
    info = appver.version_info()
    assert info["version"] == "unknown"
    assert info["source"] == "unknown"


def test_version_endpoint_unauthenticated():
    with TestClient(app) as c:
        r = c.get("/version")
    assert r.status_code == 200
    body = r.json()
    assert body["app"] == "barry-co"
    for key in ("version", "git_sha", "build_time", "source"):
        assert key in body
