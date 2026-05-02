from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient

from app.main import app


def _jwk_from_public_key(public_key, kid: str = "k-test") -> dict:
    raw = public_key.public_bytes_raw()
    x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return {"kty": "OKP", "crv": "Ed25519", "use": "sig", "alg": "EdDSA", "kid": kid, "x": x}


def _token(
    private_key,
    *,
    issuer: str = "https://hub.test",
    kid: str = "k-test",
    subject: str = "u-test",
    role: str = "staff",
    extra_claims: dict | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "iss": issuer,
            "sub": subject,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
            "email": "operator@example.test",
            "role": role,
            "name": "Operator",
            **(extra_claims or {}),
        },
        private_key,
        algorithm="EdDSA",
        headers={"kid": kid, "typ": "JWT"},
    )


def test_data_hub_token_verifier_accepts_jwks_signed_token():
    from app.co_auth import DataHubTokenVerifier

    private_key = ed25519.Ed25519PrivateKey.generate()
    token = _token(private_key)
    verifier = DataHubTokenVerifier(
        issuer="https://hub.test",
        jwks_provider=lambda: {"keys": [_jwk_from_public_key(private_key.public_key())]},
    )

    user = verifier.verify(token)

    assert user.user_id == "u-test"
    assert user.email == "operator@example.test"
    assert user.role == "staff"


def test_auth_required_redirects_clients_without_data_hub_session(monkeypatch):
    monkeypatch.setenv("CO_AUTH_REQUIRED", "1")

    response = TestClient(app).get("/clients", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login?next=/clients"


def test_auth_required_redirects_root_without_data_hub_session(monkeypatch):
    monkeypatch.setenv("CO_AUTH_REQUIRED", "1")

    response = TestClient(app).get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login?next=/"


def test_auth_required_allows_valid_data_hub_session(monkeypatch):
    from app import co_auth

    private_key = ed25519.Ed25519PrivateKey.generate()
    token = _token(private_key)
    monkeypatch.setenv("CO_AUTH_REQUIRED", "1")
    monkeypatch.setenv("DATA_HUB_ISSUER_URL", "https://hub.test")
    monkeypatch.setattr(
        co_auth,
        "fetch_data_hub_jwks",
        lambda _url: {"keys": [_jwk_from_public_key(private_key.public_key())]},
    )

    client = TestClient(app)
    client.cookies.set(co_auth.CO_SESSION_COOKIE, token)
    response = client.get("/clients")

    assert response.status_code == 200
    assert "Danh mục công ty" in response.text


def test_auth_required_rejects_client_outside_jwt_acl(monkeypatch):
    from app import co_auth

    private_key = ed25519.Ed25519PrivateKey.generate()
    token = _token(private_key, extra_claims={"client_ids": ["allowed-client"]})
    monkeypatch.setenv("CO_AUTH_REQUIRED", "1")
    monkeypatch.setenv("DATA_HUB_ISSUER_URL", "https://hub.test")
    monkeypatch.setattr(
        co_auth,
        "fetch_data_hub_jwks",
        lambda _url: {"keys": [_jwk_from_public_key(private_key.public_key())]},
    )

    client = TestClient(app)
    client.cookies.set(co_auth.CO_SESSION_COOKIE, token)
    response = client.get("/clients/growatt")

    assert response.status_code == 403


def test_auth_required_rejects_expired_data_hub_session(monkeypatch):
    from app import co_auth

    private_key = ed25519.Ed25519PrivateKey.generate()
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "iss": "https://hub.test",
            "sub": "u-test",
            "iat": int((now - timedelta(minutes=20)).timestamp()),
            "exp": int((now - timedelta(minutes=10)).timestamp()),
        },
        private_key,
        algorithm="EdDSA",
        headers={"kid": "k-test"},
    )
    monkeypatch.setenv("CO_AUTH_REQUIRED", "1")
    monkeypatch.setenv("DATA_HUB_ISSUER_URL", "https://hub.test")
    monkeypatch.setattr(
        co_auth,
        "fetch_data_hub_jwks",
        lambda _url: {"keys": [_jwk_from_public_key(private_key.public_key())]},
    )

    client = TestClient(app)
    client.cookies.set(co_auth.CO_SESSION_COOKIE, token)
    response = client.get("/clients", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login?next=/clients"


def test_auth_callback_exchanges_code_sets_session_cookie(monkeypatch):
    from app import co_auth

    private_key = ed25519.Ed25519PrivateKey.generate()
    token = _token(private_key, role="admin")
    monkeypatch.setenv("DATA_HUB_ISSUER_URL", "https://hub.test")
    monkeypatch.setattr(co_auth, "exchange_data_hub_sso_code", lambda _code, **_kwargs: {"access_token": token, "expires_in": 300})
    monkeypatch.setattr(
        co_auth,
        "fetch_data_hub_jwks",
        lambda _url: {"keys": [_jwk_from_public_key(private_key.public_key())]},
    )

    response = TestClient(app).get("/auth/callback?code=c1&state=/clients", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/clients"
    assert co_auth.CO_SESSION_COOKIE in response.headers["set-cookie"]


def test_data_hub_client_uses_bearer_token_and_normalizes_clients():
    from app.data_hub_client import DataHubClient

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "client_id": "growatt-vn",
                        "name": "Growatt VN",
                        "tax_code": "0312345678",
                        "status": "active",
                    }
                ]
            },
        )

    client = DataHubClient(
        base_url="https://hub.test",
        token="secret-token",
        transport=httpx.MockTransport(handler),
    )

    assert client.list_clients()[0] == {
        "id": "growatt-vn",
        "name": "Growatt VN",
        "code": "growatt-vn",
        "tax_code": "0312345678",
        "status": "active",
        "contact": "",
    }
    assert seen == [("GET", "/v1/hub/dncxs", "Bearer secret-token")]


def test_data_hub_client_prefers_current_user_token_when_available():
    from app.data_hub_client import DataHubClient

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"items": []})

    client = DataHubClient(
        base_url="https://hub.test",
        token="service-token",
        token_provider=lambda: "user-token",
        transport=httpx.MockTransport(handler),
    )

    assert client.list_clients() == []
    assert seen == ["Bearer user-token"]


def test_data_hub_client_follows_cursor_pagination():
    from app.data_hub_client import DataHubClient

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        if cursor == "page-2":
            return httpx.Response(200, json={"items": [{"customs_code": "NVL-2"}]})
        return httpx.Response(
            200,
            json={"items": [{"customs_code": "NVL-1"}], "next_cursor": "page-2"},
        )

    client = DataHubClient(
        base_url="https://hub.test",
        token="secret-token",
        transport=httpx.MockTransport(handler),
    )

    assert client.list_materials("growatt-vn") == [{"customs_code": "NVL-1"}, {"customs_code": "NVL-2"}]


def test_data_hub_portfolio_service_uses_data_hub_source_summary():
    from app.data_hub_client import DataHubPortfolioService

    class FakeDataHubClient:
        def source_summary(self, _client_id: str):
            return {
                "client_config": {"config_version": 9, "config_hash": "hub-cfg", "co_stock": {"lot_policy": "line_level"}, "bcct": {"eligible_import_declaration_types": []}, "allocation_code": {"strategy": "same_as_customs_code"}},
                "material_catalog": {"published_row_count": 1, "latest_version": {}},
                "product_catalog": {"published_row_count": 1, "latest_version": {}},
                "bcct": {"published_row_count": 2, "reviewed_row_count": 2, "latest_version": {}},
                "co_stock_row_count": 1,
            }

    service = DataHubPortfolioService(FakeDataHubClient())

    summary, backend = service.source_summary({"id": "growatt-vn"})

    assert backend == "data-hub"
    assert summary["client_config"]["config_version"] == 9
    assert summary["material_catalog"]["published_row_count"] == 1
    assert summary["product_catalog"]["published_row_count"] == 1
    assert summary["bcct"]["published_row_count"] == 2
    assert summary["co_stock_row_count"] == 1


def test_data_hub_portfolio_service_uses_invoice_lookup_api():
    from app.data_hub_client import DataHubPortfolioService

    class FakeDataHubClient:
        def source_summary(self, _client_id: str):
            return {
                "client_config": {
                    "config_version": 1,
                    "config_hash": "hub-cfg",
                    "co_stock": {"lot_policy": "line_level"},
                    "bcct": {"eligible_import_declaration_types": [], "relevant_export_declaration_types": ["E42"]},
                    "allocation_code": {"strategy": "same_as_customs_code"},
                },
                "material_catalog": {"published_row_count": 0, "latest_version": {}},
                "product_catalog": {"published_row_count": 0, "latest_version": {}},
                "bcct": {"published_row_count": 3, "reviewed_row_count": 3, "latest_version": {}},
                "co_stock_row_count": 0,
            }

        def invoice_matches(self, client_id: str, invoice_no: str, declaration_types: list[str]):
            assert client_id == "growatt-vn"
            assert invoice_no == "INV-001"
            assert declaration_types == ["E42"]
            return [{"declaration_no": "XK1", "invoice_ref": "INV-001"}]

    service = DataHubPortfolioService(FakeDataHubClient())

    context = service.co_case_source_context({"id": "growatt-vn"}, {"shipment": {"invoice_no": "INV-001"}})

    assert context["source_backend"] == "data-hub"
    assert context["invoice_matches"] == [{"declaration_no": "XK1", "invoice_ref": "INV-001"}]


def test_clients_page_uses_portfolio_service_boundary(monkeypatch):
    from app import main as main_module

    class FakePortfolioService:
        def clients(self):
            return [
                {
                    "id": "hub-only",
                    "name": "Hub Only Client",
                    "code": "hub-only",
                    "tax_code": "000",
                    "contact": "",
                    "counts": {"products": 0, "materials": 0, "bom_lines": 0, "co_stock": 0, "bcct": 0},
                }
            ]

    monkeypatch.setattr(main_module, "portfolio_service", FakePortfolioService())

    response = TestClient(app).get("/clients")

    assert response.status_code == 200
    assert "Hub Only Client" in response.text


def test_client_detail_uses_portfolio_service_boundary(monkeypatch):
    from app import main as main_module

    empty_state = {
        "published_rows": [],
        "latest_version": {},
        "versions": [],
        "uploads": [],
        "correction_candidates": [],
        "audit_events": [],
    }

    class FakePortfolioService:
        def client(self, client_id: str):
            if client_id != "hub-only":
                raise KeyError(client_id)
            return {"id": "hub-only", "name": "Hub Only Client", "code": "hub-only", "tax_code": ""}

        def source_workspace(self, _client: dict):
            return {
                "client_config": {"config_version": 1, "config_hash": "cfg", "co_stock": {"lot_policy": "line_level"}, "bcct": {"eligible_import_declaration_types": []}, "allocation_code": {"strategy": "same_as_customs_code"}},
                "material_catalog": {"module": "material_catalog", **empty_state},
                "product_catalog": {"module": "product_catalog", **empty_state},
                "bcct": {"module": "bcct", **empty_state},
                "co_stock_rows": [],
            }, "data-hub"

    monkeypatch.setattr(main_module, "portfolio_service", FakePortfolioService())

    response = TestClient(app).get("/clients/hub-only")

    assert response.status_code == 200
    assert "Hub Only Client" in response.text


def test_clients_page_filters_by_jwt_client_claims(monkeypatch):
    from app import co_auth
    from app import main as main_module

    class FakePortfolioService:
        def clients(self):
            return [
                {"id": "hub-only", "name": "Hub Only Client", "code": "hub-only", "tax_code": "", "contact": "", "counts": {}},
                {"id": "hidden", "name": "Hidden Client", "code": "hidden", "tax_code": "", "contact": "", "counts": {}},
            ]

    private_key = ed25519.Ed25519PrivateKey.generate()
    token = _token(private_key, extra_claims={"client_ids": ["hub-only"]})
    monkeypatch.setenv("CO_AUTH_REQUIRED", "1")
    monkeypatch.setenv("DATA_HUB_ISSUER_URL", "https://hub.test")
    monkeypatch.setattr(main_module, "portfolio_service", FakePortfolioService())
    monkeypatch.setattr(
        co_auth,
        "fetch_data_hub_jwks",
        lambda _url: {"keys": [_jwk_from_public_key(private_key.public_key())]},
    )

    client = TestClient(app)
    client.cookies.set(co_auth.CO_SESSION_COOKIE, token)
    response = client.get("/clients")

    assert response.status_code == 200
    assert "Hub Only Client" in response.text
    assert "Hidden Client" not in response.text


def test_data_hub_mode_blocks_local_shared_source_uploads(monkeypatch):
    monkeypatch.setenv("DATA_HUB_ENABLED", "1")

    response = TestClient(app).post(
        "/clients/growatt/bcct/upload",
        files={"file": ("bcct.xlsx", b"not-an-xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 409
    assert "Shared source data is read-only in CO" in response.text
