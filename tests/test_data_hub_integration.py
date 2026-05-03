from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient

from app.main import app


def test_data_hub_link_settings_derives_urls_and_claim_mapping():
    from app.data_hub_settings import DataHubLinkSettings

    settings = DataHubLinkSettings.from_env({
        "DATA_HUB_ENABLED": "yes",
        "CO_AUTH_REQUIRED": "1",
        "DATA_HUB_BASE_URL": "https://hub.example.test/",
        "DATA_HUB_API_BASE_URL": "http://hub-api.internal:8754/",
        "DATA_HUB_ISSUER_URL": "https://issuer.example.test/",
        "DATA_HUB_API_TOKEN": " service-token ",
        "CO_PUBLIC_BASE_URL": "https://co.example.test/",
        "CO_FORCE_HTTPS_COOKIE": "on",
        "DATA_HUB_REQUEST_TIMEOUT_SECONDS": "3.5",
        "DATA_HUB_CLIENT_CLAIM_KEYS": "tenant_ids,dncx_ids",
        "DATA_HUB_ADMIN_ROLES": "owner support",
    })

    assert settings.source_enabled is True
    assert settings.auth_required is True
    assert settings.data_hub_base_url == "https://hub.example.test"
    assert settings.data_hub_api_base_url == "http://hub-api.internal:8754"
    assert settings.issuer_url == "https://issuer.example.test"
    assert settings.jwks_url == "https://issuer.example.test/v1/auth/jwks"
    assert settings.api_token == "service-token"
    assert settings.co_public_base_url == "https://co.example.test"
    assert settings.force_https_cookie is True
    assert settings.request_timeout_seconds == 3.5
    assert settings.client_claim_keys == ("tenant_ids", "dncx_ids")
    assert settings.admin_roles == {"owner", "support"}


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


def test_data_hub_token_verifier_accepts_localhost_loopback_alias(monkeypatch):
    from app import co_auth
    from app.co_auth import DataHubTokenVerifier

    private_key = ed25519.Ed25519PrivateKey.generate()
    token = _token(private_key, issuer="http://localhost:8754")
    monkeypatch.setenv("DATA_HUB_ISSUER_URL", "http://127.0.0.1:8754")
    verifier = DataHubTokenVerifier(
        issuer=co_auth.data_hub_issuer_urls(),
        jwks_provider=lambda: {"keys": [_jwk_from_public_key(private_key.public_key())]},
    )

    user = verifier.verify(token)

    assert user.user_id == "u-test"


def test_fetch_data_hub_jwks_uses_stale_cache_when_data_hub_is_offline(monkeypatch):
    from app import co_auth

    co_auth.clear_jwks_cache()
    jwks = {"keys": [{"kid": "k-test"}]}

    def fresh_get(url: str, **_kwargs):
        return httpx.Response(200, json=jwks, request=httpx.Request("GET", url))

    monkeypatch.setattr(co_auth.httpx, "get", fresh_get)
    assert co_auth.fetch_data_hub_jwks("http://hub.test/v1/auth/jwks") == jwks

    def offline_get(_url: str, **_kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(co_auth, "JWKS_CACHE_TTL_SECONDS", 0.0)
    monkeypatch.setattr(co_auth.httpx, "get", offline_get)
    assert co_auth.fetch_data_hub_jwks("http://hub.test/v1/auth/jwks") == jwks


def test_fetch_data_hub_jwks_rejects_non_object_response(monkeypatch):
    from app import co_auth

    co_auth.clear_jwks_cache()

    def get_list(url: str, **_kwargs):
        return httpx.Response(200, json=[], request=httpx.Request("GET", url))

    monkeypatch.setattr(co_auth.httpx, "get", get_list)

    with pytest.raises(ValueError):
        co_auth.fetch_data_hub_jwks("http://hub.test/v1/auth/jwks")


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


def test_auth_callback_verification_failure_does_not_redirect_loop(monkeypatch):
    from app import co_auth

    private_key = ed25519.Ed25519PrivateKey.generate()
    token = _token(private_key, issuer="https://wrong-issuer.test")
    monkeypatch.setenv("DATA_HUB_ISSUER_URL", "https://hub.test")
    monkeypatch.setattr(co_auth, "exchange_data_hub_sso_code", lambda _code, **_kwargs: {"access_token": token, "expires_in": 300})
    monkeypatch.setattr(
        co_auth,
        "fetch_data_hub_jwks",
        lambda _url: {"keys": [_jwk_from_public_key(private_key.public_key())]},
    )

    response = TestClient(app).get("/auth/callback?code=c1&state=/clients", follow_redirects=False)

    assert response.status_code == 401
    assert "Data Hub login failed" in response.text
    assert "location" not in response.headers
    assert "co_data_hub_session" in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_topnav_shows_login_when_data_hub_auth_required(monkeypatch):
    monkeypatch.setenv("CO_AUTH_REQUIRED", "1")

    response = TestClient(app).get("/auth/login?next=/clients", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("http://127.0.0.1:8754/v1/auth/authorize?")


def test_user_ui_loads_session_and_logout_clears_cookie(monkeypatch):
    from app import co_auth

    private_key = ed25519.Ed25519PrivateKey.generate()
    token = _token(private_key, role="dev", extra_claims={"client_ids": ["growatt"]})
    monkeypatch.setenv("DATA_HUB_ISSUER_URL", "https://hub.test")
    monkeypatch.setattr(
        co_auth,
        "fetch_data_hub_jwks",
        lambda _url: {"keys": [_jwk_from_public_key(private_key.public_key())]},
    )

    client = TestClient(app)
    client.cookies.set(co_auth.CO_SESSION_COOKIE, token)
    response = client.get("/user")

    assert response.status_code == 200
    assert "Operator" in response.text
    assert "dev" in response.text
    assert "All clients" in response.text
    assert '<summary class="user-menu-trigger"' in response.text
    assert "User profile" in response.text
    assert "Technical Settings" in response.text
    assert 'action="/auth/logout"' in response.text

    logout = client.post("/auth/logout", data={"next_url": "/user"}, follow_redirects=False)

    assert logout.status_code == 303
    assert logout.headers["location"] == "/user?logged_out=1"
    assert "co_data_hub_session" in logout.headers["set-cookie"]
    assert "Max-Age=0" in logout.headers["set-cookie"]


def test_sso_logout_clears_cookie_without_restarting_login(monkeypatch):
    monkeypatch.setenv("CO_AUTH_REQUIRED", "1")
    monkeypatch.setenv("DATA_HUB_BASE_URL", "http://hub.test")

    response = TestClient(app).post("/auth/logout", data={"next_url": "/user"}, follow_redirects=False)

    assert response.status_code == 200
    assert "location" not in response.headers
    assert 'action="http://hub.test/logout"' in response.text
    assert 'id="data-hub-logout-form"' in response.text
    assert "co_data_hub_session" in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_settings_page_links_technical_settings_for_dev(monkeypatch):
    response = TestClient(app).get("/settings")

    assert response.status_code == 200
    assert "Settings" in response.text
    assert "Technical Settings" in response.text
    assert 'href="/settings/technical"' in response.text
    assert 'href="/settings"' in response.text


def test_data_hub_settings_page_renders_config_and_masks_token(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_HUB_CONFIG_PATH", str(tmp_path / "data-hub-link.json"))
    monkeypatch.setenv("DATA_HUB_BASE_URL", "https://hub.example.test")
    monkeypatch.setenv("DATA_HUB_API_BASE_URL", "http://hub-api.internal:8754")
    monkeypatch.setenv("DATA_HUB_API_TOKEN", "super-secret-token")

    response = TestClient(app).get("/settings/technical")

    assert response.status_code == 200
    assert "Technical Settings" in response.text
    assert "https://hub.example.test" in response.text
    assert "http://hub-api.internal:8754" in response.text
    assert "Đã cấu hình" in response.text
    assert "super-secret-token" not in response.text
    assert 'href="/settings"' in response.text


def test_data_hub_settings_page_shows_env_token_source_when_env_overrides_local(monkeypatch, tmp_path):
    config_path = tmp_path / "data-hub-link.json"
    config_path.write_text(json.dumps({"DATA_HUB_API_TOKEN": "local-secret-token"}), encoding="utf-8")
    monkeypatch.setenv("DATA_HUB_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DATA_HUB_API_TOKEN", "env-secret-token")

    response = TestClient(app).get("/settings/technical")

    assert response.status_code == 200
    assert "token environment" in response.text
    assert "local-secret-token" not in response.text
    assert "env-secret-token" not in response.text


def test_data_hub_settings_page_saves_local_override(monkeypatch, tmp_path):
    from app.data_hub_settings import data_hub_link_settings

    config_path = tmp_path / "data-hub-link.json"
    monkeypatch.setenv("DATA_HUB_CONFIG_PATH", str(config_path))

    response = TestClient(app).post(
        "/settings/technical",
        data={
            "DATA_HUB_ENABLED": "1",
            "CO_AUTH_REQUIRED": "0",
            "DATA_HUB_BASE_URL": "https://hub.example.test",
            "DATA_HUB_API_BASE_URL": "http://hub-api.internal:8754",
            "DATA_HUB_ISSUER_URL": "https://issuer.example.test",
            "DATA_HUB_JWKS_URL": "https://issuer.example.test/v1/auth/jwks",
            "CO_PUBLIC_BASE_URL": "https://co.example.test",
            "DATA_HUB_REQUEST_TIMEOUT_SECONDS": "6",
            "DATA_HUB_CLIENT_CLAIM_KEYS": "tenant_ids,dncx_ids",
            "DATA_HUB_ADMIN_ROLES": "owner,support",
            "DATA_HUB_API_TOKEN": "local-service-token",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/settings/technical?saved=1"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["DATA_HUB_API_TOKEN"] == "local-service-token"
    assert payload["DATA_HUB_API_BASE_URL"] == "http://hub-api.internal:8754"
    settings = data_hub_link_settings()
    assert settings.source_enabled is True
    assert settings.data_hub_api_base_url == "http://hub-api.internal:8754"
    assert settings.client_claim_keys == ("tenant_ids", "dncx_ids")


def test_data_hub_settings_save_rejects_invalid_local_override(monkeypatch, tmp_path):
    config_path = tmp_path / "data-hub-link.json"
    monkeypatch.setenv("DATA_HUB_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DATA_HUB_REQUEST_TIMEOUT_SECONDS", "8")

    response = TestClient(app).post(
        "/settings/technical",
        data={
            "DATA_HUB_REQUEST_TIMEOUT_SECONDS": "not-a-number",
        },
    )

    assert response.status_code == 400
    assert "DATA_HUB_REQUEST_TIMEOUT_SECONDS must be a positive number." in response.text
    assert not config_path.exists()


def test_data_hub_settings_page_is_guarded_when_auth_required(monkeypatch):
    monkeypatch.setenv("CO_AUTH_REQUIRED", "1")

    response = TestClient(app).get("/settings/technical", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login?next=/settings/technical"


def test_technical_settings_requires_dev_when_auth_required(monkeypatch):
    from app import co_auth

    private_key = ed25519.Ed25519PrivateKey.generate()
    staff_token = _token(private_key, role="staff", extra_claims={"client_ids": ["growatt"]})
    admin_token = _token(private_key, role="admin")
    dev_token = _token(private_key, role="dev")
    monkeypatch.setenv("CO_AUTH_REQUIRED", "1")
    monkeypatch.setenv("DATA_HUB_ISSUER_URL", "https://hub.test")
    monkeypatch.setattr(
        co_auth,
        "fetch_data_hub_jwks",
        lambda _url: {"keys": [_jwk_from_public_key(private_key.public_key())]},
    )

    client = TestClient(app)
    client.cookies.set(co_auth.CO_SESSION_COOKIE, staff_token)
    assert client.get("/settings/technical").status_code == 403

    client.cookies.set(co_auth.CO_SESSION_COOKIE, admin_token)
    assert client.get("/settings/technical").status_code == 403

    client.cookies.set(co_auth.CO_SESSION_COOKIE, dev_token)
    response = client.get("/settings/technical")

    assert response.status_code == 200
    assert "Technical Settings" in response.text


def test_data_hub_settings_connection_check_uses_existing_adapter(monkeypatch, tmp_path):
    from app import co_auth
    from app import main as main_module

    seen = {}

    class FakeDataHubClient:
        def __init__(self, *, base_url, token, timeout):
            seen["base_url"] = base_url
            seen["token"] = token
            seen["timeout"] = timeout

        def list_clients(self):
            return [{"id": "growatt"}, {"id": "johnson"}]

        def close(self):
            seen["closed"] = True

    monkeypatch.setenv("DATA_HUB_CONFIG_PATH", str(tmp_path / "data-hub-link.json"))
    monkeypatch.setenv("DATA_HUB_ENABLED", "1")
    monkeypatch.setenv("DATA_HUB_API_BASE_URL", "http://hub-api.internal:8754")
    monkeypatch.setenv("DATA_HUB_API_TOKEN", "service-token")
    monkeypatch.setenv("DATA_HUB_REQUEST_TIMEOUT_SECONDS", "5")
    monkeypatch.setattr(co_auth, "fetch_data_hub_jwks", lambda _url: {"keys": [{"kid": "k-test"}]})
    monkeypatch.setattr(main_module, "DataHubClient", FakeDataHubClient)

    response = TestClient(app).post("/settings/technical/test")

    assert response.status_code == 200
    assert "2 clients" in response.text
    assert seen == {
        "base_url": "http://hub-api.internal:8754",
        "token": "service-token",
        "timeout": 5.0,
        "closed": True,
    }


def test_auth_exchange_uses_configured_data_hub_api_base_url(monkeypatch):
    from app import co_auth

    seen = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"access_token": "hub-user-token", "expires_in": 300}

    def fake_post(url, *, json, timeout):
        seen["url"] = url
        seen["json"] = json
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("DATA_HUB_BASE_URL", "https://hub.example.test")
    monkeypatch.setenv("DATA_HUB_API_BASE_URL", "http://hub-api.internal:8754")
    monkeypatch.setenv("DATA_HUB_REQUEST_TIMEOUT_SECONDS", "4.5")
    monkeypatch.setattr(co_auth.httpx, "post", fake_post)

    payload = co_auth.exchange_data_hub_sso_code("code-1", redirect_uri="https://co.example.test/auth/callback")

    assert payload["access_token"] == "hub-user-token"
    assert seen == {
        "url": "http://hub-api.internal:8754/v1/auth/exchange",
        "json": {"code": "code-1", "redirect_uri": "https://co.example.test/auth/callback"},
        "timeout": 4.5,
    }


def test_visible_client_ids_uses_configured_claim_keys_and_admin_roles(monkeypatch):
    from app.co_auth import DataHubUser, visible_client_ids

    monkeypatch.setenv("DATA_HUB_CLIENT_CLAIM_KEYS", "tenant_ids")
    user = DataHubUser(
        user_id="u-test",
        email="operator@example.test",
        role="staff",
        name="Operator",
        claims={"tenant_ids": ["growatt-vn"]},
    )

    assert visible_client_ids(user) == {"growatt-vn"}

    monkeypatch.setenv("DATA_HUB_ADMIN_ROLES", "ops-admin")
    admin = DataHubUser(
        user_id="u-admin",
        email="admin@example.test",
        role="ops-admin",
        name="Admin",
        claims={},
    )

    assert visible_client_ids(admin) is None


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
        "counts": {},
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


def test_data_hub_client_from_env_uses_configured_api_base_url(monkeypatch):
    from app.data_hub_client import data_hub_client_from_env

    monkeypatch.setenv("DATA_HUB_ENABLED", "1")
    monkeypatch.setenv("DATA_HUB_BASE_URL", "https://hub.example.test")
    monkeypatch.setenv("DATA_HUB_API_BASE_URL", "http://hub-api.internal:8754")
    monkeypatch.setenv("DATA_HUB_API_TOKEN", "service-token")
    monkeypatch.setenv("DATA_HUB_REQUEST_TIMEOUT_SECONDS", "7")

    client = data_hub_client_from_env()

    assert client is not None
    assert client.base_url == "http://hub-api.internal:8754"
    assert client.token == "service-token"
    client._client.close()


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


def test_data_hub_client_fetches_bom_contract_and_conflicts():
    from app.data_hub_client import DataHubBomVariantConflict, DataHubClient

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path == "/v1/hub/products":
            return httpx.Response(200, json={"items": [{"product_code": "TP-1", "n_versions": 2}]})
        if request.url.path == "/v1/hub/products/TP-1/bom/versions":
            return httpx.Response(200, json={"items": [{"version_id": "bv-1", "version_no": 1}]})
        if request.url.path == "/v1/hub/products/TP-1/bom/latest":
            return httpx.Response(
                409,
                json={
                    "error": "dual_source_variants",
                    "variants": [{"version_id": "bv-a"}, {"version_id": "bv-b"}],
                },
            )
        if request.url.path == "/v1/hub/products/TP-1/bom":
            return httpx.Response(
                200,
                json={
                    "version": {
                        "version_id": "bv-1",
                        "product_code": "TP-1",
                        "version_no": 1,
                        "flatten_status": "flattened",
                    },
                    "rows": [{"material_code": "NVL-1", "qty_per_unit": 2, "uom": "kg"}],
                    "unresolved": [],
                    "decisions": [],
                },
            )
        if request.url.path == "/v1/hub/proposals/prop-1":
            return httpx.Response(200, json={"proposal_id": "prop-1", "status": "approved"})
        return httpx.Response(404)

    client = DataHubClient(
        base_url="https://hub.test",
        token="secret-token",
        transport=httpx.MockTransport(handler),
    )

    assert client.list_bom_products("growatt-vn") == [{"product_code": "TP-1", "n_versions": 2}]
    assert client.list_bom_versions("growatt-vn", "TP-1") == [{"version_id": "bv-1", "version_no": 1}]
    with pytest.raises(DataHubBomVariantConflict) as exc:
        client.get_bom_latest("growatt-vn", "TP-1")
    assert exc.value.variants == [{"version_id": "bv-a"}, {"version_id": "bv-b"}]
    assert client.get_bom_version("growatt-vn", "TP-1", "bv-1")["rows"][0]["material_code"] == "NVL-1"
    assert client.get_bom_proposal("prop-1")["status"] == "approved"
    assert seen == [
        ("GET", "/v1/hub/products", {"client_id": "growatt-vn", "limit": "1000"}),
        ("GET", "/v1/hub/products/TP-1/bom/versions", {"client_id": "growatt-vn", "limit": "1000"}),
        ("GET", "/v1/hub/products/TP-1/bom/latest", {"client_id": "growatt-vn"}),
        ("GET", "/v1/hub/products/TP-1/bom", {"client_id": "growatt-vn", "version_id": "bv-1"}),
        ("GET", "/v1/hub/proposals/prop-1", {}),
    ]


def test_data_hub_bom_service_adapts_workspace():
    from app.bom_service import DataHubBomService

    class FakeDataHubClient:
        def list_bom_products(self, client_id: str):
            assert client_id == "growatt-vn"
            return [{"product_code": "TP-1", "n_versions": 1}]

        def get_bom_latest(self, client_id: str, product_code: str):
            assert client_id == "growatt-vn"
            assert product_code == "TP-1"
            return {
                "version": {
                    "version_id": "bv-1",
                    "client_id": "growatt-vn",
                    "product_code": "TP-1",
                    "version_no": 3,
                    "normalized_hash": "hash-1",
                    "row_count": 1,
                    "status": "published",
                    "published_at": "2026-05-03T00:00:00+08:00",
                    "source_bom_kind": "technical_flattened",
                    "flatten_status": "flattened",
                    "flatten_strategy": "technical_exploded",
                    "display_label": "TP-1 · default · v3 · technical_flattened",
                },
                "rows": [
                    {
                        "material_code": "NVL-1",
                        "bom_code": "TP-1",
                        "bom_variant_id": "default",
                        "qty_per_unit": 2.5,
                        "uom": "kg",
                        "payload": {"material_name": "Input material"},
                    }
                ],
                "unresolved": [],
                "decisions": [],
            }

    workspace = DataHubBomService(FakeDataHubClient()).workspace({"id": "growatt-vn"})

    assert workspace["backend"] == "data-hub"
    assert workspace["latest_version"]["version_id"].startswith("dhagg-")
    assert workspace["latest_version"]["product_versions"][0]["product_version_id"] == "bv-1"
    assert workspace["product_versions"][0]["flatten_status"] == "flattened"
    assert workspace["latest_rows"][0]["product_code"] == "TP-1"
    assert workspace["latest_rows"][0]["qty_per"] == 2.5
    assert workspace["product_version_options_by_code"]["TP-1"][0]["product_version_id"] == "bv-1"


def test_data_hub_bom_service_exposes_switchable_product_versions():
    from app.bom_service import DataHubBomService

    class FakeDataHubClient:
        def list_bom_products(self, client_id: str):
            assert client_id == "growatt-vn"
            return [{"product_code": "TP-1", "n_versions": 2}]

        def list_bom_versions(self, client_id: str, product_code: str):
            assert client_id == "growatt-vn"
            assert product_code == "TP-1"
            return [
                {"version_id": "bv-1", "version_no": 1, "row_count": 1, "status": "published"},
                {"version_id": "bv-2", "version_no": 2, "row_count": 1, "status": "published"},
            ]

        def get_bom_version(self, client_id: str, product_code: str, version_id: str):
            assert client_id == "growatt-vn"
            assert product_code == "TP-1"
            qty = 2 if version_id == "bv-2" else 1
            return {
                "version": {
                    "version_id": version_id,
                    "product_code": "TP-1",
                    "version_no": 2 if version_id == "bv-2" else 1,
                    "normalized_hash": version_id,
                    "row_count": 1,
                    "flatten_status": "flattened",
                },
                "rows": [{"material_code": "NVL-1", "qty_per_unit": qty, "uom": "PCS", "payload": {}}],
            }

    workspace = DataHubBomService(FakeDataHubClient()).workspace({"id": "growatt-vn"})

    options = workspace["product_version_options_by_code"]["TP-1"]
    assert [row["product_version_id"] for row in options] == ["bv-1", "bv-2"]
    assert [row["product_version_id"] for row in workspace["product_versions"] if row["status"] == "current"] == ["bv-2"]
    assert workspace["latest_rows"][0]["qty_per"] == 2


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
            return [{"declaration_no": "XK1", "line_no": "1", "item_code": "TP-001", "invoice_ref": "INV-001", "transaction_key": "XK1-1"}]

        def list_bcct(self, client_id: str):
            assert client_id == "growatt-vn"
            return [
                {
                    "direction": "export",
                    "declaration_no": "XK1",
                    "line_no": "1",
                    "item_code": "TP-001",
                    "quantity": "2",
                    "unit": "PCS",
                    "total_value": "1234",
                    "currency": "USD",
                    "invoice_ref": "INV-001",
                    "transaction_key": "XK1-1",
                },
                {
                    "direction": "import",
                    "declaration_no": "NK1",
                    "line_no": "1",
                    "item_code": "MAT-001",
                    "quantity": "100",
                    "unit": "PCS",
                    "customs_value": "1000",
                }
            ]

    service = DataHubPortfolioService(FakeDataHubClient())

    context = service.co_case_source_context({"id": "growatt-vn"}, {"shipment": {"invoice_no": "INV-001"}})

    assert context["source_backend"] == "data-hub"
    assert context["invoice_matches"][0]["declaration_no"] == "XK1"
    assert context["invoice_matches"][0]["customs_value"] == "1234"
    assert context["invoice_matches"][0]["currency"] == "USD"
    assert context["invoice_matches"][0]["value_currency"] == "VND"
    assert context["stock_rows"][0]["customs_item_code"] == "MAT-001"
    assert context["stock_rows"][0]["unit_value"] == "10"
    assert context["stock_rows"][0]["currency"] == "VND"


def test_data_hub_portfolio_service_skips_invoice_lookup_without_invoice_no():
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

        def invoice_matches(self, *_args, **_kwargs):
            raise AssertionError("blank invoices should not call Data Hub invoice-matches")

    service = DataHubPortfolioService(FakeDataHubClient())

    context = service.co_case_source_context({"id": "growatt-vn"}, {"shipment": {"invoice_no": ""}})

    assert context["source_backend"] == "data-hub"
    assert context["invoice_matches"] == []


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


def test_bom_page_uses_bom_service_boundary(monkeypatch):
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
            assert client_id == "hub-only"
            return {"id": "hub-only", "name": "Hub Only Client", "code": "hub-only", "tax_code": "", "counts": {}}

        def source_workspace(self, _client: dict):
            return {
                "client_config": {"config_version": 1, "config_hash": "cfg", "co_stock": {"lot_policy": "line_level"}, "bcct": {"eligible_import_declaration_types": []}, "allocation_code": {"strategy": "same_as_customs_code"}},
                "material_catalog": {"module": "material_catalog", **empty_state},
                "product_catalog": {"module": "product_catalog", **empty_state},
                "bcct": {"module": "bcct", **empty_state},
                "co_stock_rows": [],
            }, "data-hub"

    class FakeBomService:
        def workspace(self, _client: dict):
            return {
                "backend": "data-hub",
                "read_only": True,
                "config": {"bom_profile": "data_hub", "default_import_mode": "data_hub", "code_system_mode": "data_hub"},
                "versions": [
                    {
                        "version_id": "dhagg-1",
                        "version_no": 1,
                        "version_hash": "hash-aggregate",
                        "status": "published",
                        "row_count": 1,
                        "product_versions": [{"product_code": "TP-1", "product_version_id": "bv-1", "product_version_no": 4, "version_hash": "hash-1", "row_count": 1, "status": "current"}],
                        "diff_summary": {},
                        "published_at": "",
                    }
                ],
                "product_versions": [
                    {
                        "product_code": "TP-1",
                        "product_version_id": "bv-1",
                        "product_version_no": 4,
                        "version_hash": "hash-1",
                        "row_count": 1,
                        "status": "current",
                        "diff_summary": {},
                        "source_upload_id": "data-hub",
                    }
                ],
                "product_version_options_by_code": {"TP-1": [{"product_version_id": "bv-1", "product_version_no": 4, "row_count": 1}]},
                "product_composition": [{"product_code": "TP-1", "product_version_id": "bv-1", "product_version_no": 4, "version_hash": "hash-1", "row_count": 1, "status": "current"}],
                "uploads": [],
                "audit": [],
                "latest_version": {"version_id": "dhagg-1", "version_no": 1, "version_hash": "hash-aggregate", "status": "published", "row_count": 1, "product_versions": [{"product_code": "TP-1"}], "diff_summary": {}, "published_at": ""},
                "latest_rows": [{"product_code": "TP-1", "bom_code": "TP-1", "product_version_no": 4, "material_code": "NVL-1", "material_name": "Input", "qty_per": 2, "uom": "kg", "scrap_rate": "", "source": "technical_flattened", "row_class": "flattened"}],
                "profile_options": [],
                "upload_mode_options": [],
                "upload_scope_options": [],
                "code_system_options": [],
                "variant_conflicts": [],
            }

    monkeypatch.setattr(main_module, "portfolio_service", FakePortfolioService())
    monkeypatch.setattr(main_module, "bom_service", FakeBomService())

    response = TestClient(app).get("/clients/hub-only/bom")

    assert response.status_code == 200
    assert "BOM đang lấy từ Data Hub" in response.text
    assert "NVL-1" in response.text
    assert "Upload và so sánh" not in response.text


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


def test_data_hub_mode_blocks_local_bom_writes(monkeypatch):
    monkeypatch.setenv("DATA_HUB_ENABLED", "1")
    client = TestClient(app)

    config_response = client.post(
        "/clients/growatt/bom/config",
        data={"bom_profile": "manual_flat"},
    )
    upload_response = client.post(
        "/clients/growatt/bom/upload",
        data={"upload_mode": "direct_bom"},
        files={"file": ("bom.xlsx", b"not-an-xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert config_response.status_code == 409
    assert upload_response.status_code == 409
    assert "Shared source data is read-only in CO" in config_response.text
    assert "Shared source data is read-only in CO" in upload_response.text


def test_data_hub_mode_hides_shared_source_upload_ui(monkeypatch):
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
            assert client_id == "hub-only"
            return {
                "id": "hub-only",
                "name": "Hub Only Client",
                "code": "hub-only",
                "tax_code": "",
                "counts": {"materials": 0, "products": 0, "bom_lines": 0, "co_stock": 0, "bcct": 0},
            }

        def source_workspace(self, _client: dict):
            return {
                "client_config": {
                    "config_version": 1,
                    "config_hash": "cfg",
                    "co_stock": {"lot_policy": "line_level"},
                    "bcct": {"eligible_import_declaration_types": [], "relevant_export_declaration_types": []},
                    "allocation_code": {"strategy": "same_as_customs_code"},
                },
                "material_catalog": {"module": "material_catalog", **empty_state},
                "product_catalog": {"module": "product_catalog", **empty_state},
                "bcct": {"module": "bcct", **empty_state},
                "co_stock_rows": [],
            }, "data-hub"

    class FakeBomService:
        def workspace(self, _client: dict):
            return {
                "backend": "data-hub",
                "read_only": True,
                "config": {"bom_profile": "data_hub", "default_import_mode": "data_hub", "code_system_mode": "data_hub"},
                "versions": [],
                "product_versions": [],
                "product_version_options_by_code": {},
                "product_composition": [],
                "uploads": [],
                "audit": [],
                "latest_version": {"version_no": 0, "version_id": "", "row_count": 0, "product_versions": []},
                "latest_rows": [],
                "profile_options": [],
                "upload_mode_options": [],
                "upload_scope_options": [],
                "code_system_options": [],
                "variant_conflicts": [],
            }

    monkeypatch.setenv("DATA_HUB_ENABLED", "1")
    monkeypatch.setattr(main_module, "portfolio_service", FakePortfolioService())
    monkeypatch.setattr(main_module, "bom_service", FakeBomService())
    client = TestClient(app)

    catalog = client.get("/clients/hub-only/catalog")
    materials = client.get("/clients/hub-only/catalog/materials")
    bcct = client.get("/clients/hub-only/bcct")

    assert catalog.status_code == 200
    assert materials.status_code == 200
    assert bcct.status_code == 200
    assert "Upload danh mục" not in catalog.text
    assert "Tải template DS NVL" not in catalog.text
    assert ">Upload<" not in materials.text
    assert "Tải template DS NVL" not in materials.text
    assert "Upload BCCT" not in bcct.text
    assert "Tải template BCCT" not in bcct.text
    assert "Data Hub" in catalog.text
    assert "Data Hub" in bcct.text


def test_data_hub_mode_blocks_shared_source_templates(monkeypatch):
    monkeypatch.setenv("DATA_HUB_ENABLED", "1")
    client = TestClient(app)

    responses = [
        client.get("/clients/growatt/catalog/material-template.xlsx"),
        client.get("/clients/growatt/catalog/product-template.xlsx"),
        client.get("/clients/growatt/bcct/template.xlsx"),
    ]

    assert [response.status_code for response in responses] == [409, 409, 409]
