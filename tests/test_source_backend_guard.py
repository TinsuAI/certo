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


def test_route_returns_503_when_dh_enabled_but_unreachable(monkeypatch):
    """DH on but the API is down (connection refused) → 503, never a raw 500 and
    never local backup data."""
    monkeypatch.setenv("DATA_HUB_ENABLED", "1")
    monkeypatch.delenv("CO_ALLOW_LOCAL_SOURCE", raising=False)
    monkeypatch.setenv("DATA_HUB_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("DATA_HUB_API_BASE_URL", "http://127.0.0.1:9")
    resp = TestClient(app, raise_server_exceptions=False).get("/clients")
    assert resp.status_code == 503
    # Must not have leaked local file-store client data.
    assert "johnson health" not in resp.text.lower()


def test_data_hub_transport_error_maps_to_503():
    """The httpx.TransportError handler turns a Data Hub outage into a clean 503."""
    import httpx

    @app.get("/_test_dh_transport_boom")
    async def _boom():  # pragma: no cover - registered only for this test
        raise httpx.ConnectError("data hub unreachable")

    try:
        resp = TestClient(app, raise_server_exceptions=False).get("/_test_dh_transport_boom")
        assert resp.status_code == 503
        assert "Data Hub" in resp.text
    finally:
        app.router.routes = [
            r for r in app.router.routes
            if getattr(r, "path", None) != "/_test_dh_transport_boom"
        ]


def test_data_hub_error_status_maps_to_502():
    """An unhandled Data Hub error status surfaces as 502 (bad gateway)."""
    import httpx

    @app.get("/_test_dh_status_boom")
    async def _boom():  # pragma: no cover - registered only for this test
        request = httpx.Request("GET", "http://hub.test/v1/hub/x")
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError("boom", request=request, response=response)

    try:
        resp = TestClient(app, raise_server_exceptions=False).get("/_test_dh_status_boom")
        assert resp.status_code == 502
        assert "Data Hub" in resp.text
    finally:
        app.router.routes = [
            r for r in app.router.routes
            if getattr(r, "path", None) != "/_test_dh_status_boom"
        ]
