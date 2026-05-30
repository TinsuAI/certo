"""Data Hub is the source of truth: when it is disabled and the local fallback
is not explicitly allowed, CO must fail loudly (503) instead of silently
serving local backup data.

See app/portfolio.py:get_portfolio_service + the 503 handler in app/main.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.portfolio as portfolio
from app.main import app


@pytest.fixture(autouse=True)
def _reset_portfolio_cache():
    portfolio._PORTFOLIO_SERVICE_CACHE = None
    yield
    portfolio._PORTFOLIO_SERVICE_CACHE = None


def test_get_portfolio_service_raises_when_dh_off_and_local_not_allowed(monkeypatch):
    monkeypatch.delenv("DATA_HUB_ENABLED", raising=False)
    monkeypatch.delenv("CO_ALLOW_LOCAL_SOURCE", raising=False)
    with pytest.raises(portfolio.SourceBackendUnavailable):
        portfolio.get_portfolio_service()


def test_get_portfolio_service_allows_local_with_flag(monkeypatch):
    monkeypatch.delenv("DATA_HUB_ENABLED", raising=False)
    monkeypatch.setenv("CO_ALLOW_LOCAL_SOURCE", "1")
    assert isinstance(portfolio.get_portfolio_service(), portfolio.PortfolioService)


def test_source_dependent_route_returns_503_when_backend_unavailable(monkeypatch):
    monkeypatch.delenv("DATA_HUB_ENABLED", raising=False)
    monkeypatch.delenv("CO_ALLOW_LOCAL_SOURCE", raising=False)
    # /clients lists clients via portfolio_service → hits the guard.
    resp = TestClient(app, raise_server_exceptions=False).get("/clients")
    assert resp.status_code == 503
    assert "Data Hub" in resp.text
