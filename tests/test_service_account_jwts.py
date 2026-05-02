"""Service-account JWT tests — issuer, verifier, registry, API ACL."""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from app import auth, jwt_issuer, settings_store
from app.database import connect
from app.main import app
from app.stores import service_accounts as sa_store


@pytest.fixture(autouse=True)
def isolated_keys_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_HUB_KEYS_DIR", d)
        yield Path(d)


@pytest.fixture
def strict_mode_on():
    settings_store.set_many({"api_auth_strict": "true"})
    yield
    settings_store.set_many({"api_auth_strict": "false"})


@pytest.fixture
def cleanup_sa():
    """Remove all rows we create in service_accounts + jti blacklist
    after each test. Tests use a 'sa_test_*' name prefix."""
    yield
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.service_accounts where name like 'sa_test_%'")
            cur.execute("delete from hub.revoked_service_tokens where revoked_by = 'sa_test_runner'")


# ─── Store ──────────────────────────────────────────────────────────────

def test_create_get_delete_account(cleanup_sa):
    sa_store.create_account(
        name="sa_test_co", description="CO test", scopes=["hub:read"],
        client_ids=None, created_by="sa_test_runner",
    )
    fetched = sa_store.get_account("sa_test_co")
    assert fetched is not None
    assert fetched["name"] == "sa_test_co"
    assert fetched["scopes"] == ["hub:read"]
    assert fetched["client_ids"] is None
    assert fetched["last_used_at"] is None

    sa_store.delete_account("sa_test_co")
    assert sa_store.get_account("sa_test_co") is None


def test_revoke_jti(cleanup_sa):
    assert sa_store.is_jti_revoked("sa_test_jti_x") is False
    sa_store.revoke_jti(jti="sa_test_jti_x", revoked_by="sa_test_runner", reason="leak")
    assert sa_store.is_jti_revoked("sa_test_jti_x") is True


# ─── Issuer ─────────────────────────────────────────────────────────────

def test_make_service_token_shape(cleanup_sa):
    sa_store.create_account(
        name="sa_test_co", description="", scopes=["hub:read", "bom:propose"],
        client_ids=None, created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co",
        scopes=["hub:read", "bom:propose"],
        client_ids=None,
    )
    assert out["token_type"] == "Bearer"
    assert out["expires_in"] >= 86400  # default 30d
    assert len(out["jti"]) == 32  # uuid4 hex

    # Decode without DB lookup to inspect payload directly
    headers = pyjwt.get_unverified_header(out["access_token"])
    assert headers["kid"] == jwt_issuer.get_active_kid()
    payload = pyjwt.decode(
        out["access_token"], options={"verify_signature": False},
    )
    assert payload["typ"] == "service"
    assert payload["sub"] == "svc:sa_test_co"
    assert payload["name"] == "sa_test_co"
    assert payload["scopes"] == ["hub:read", "bom:propose"]
    assert payload["client_ids"] is None
    assert payload["jti"] == out["jti"]


def test_verify_service_token_happy_path(cleanup_sa):
    sa_store.create_account(
        name="sa_test_co", description="", scopes=["hub:read"],
        client_ids=None, created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"], client_ids=None,
    )
    claims = jwt_issuer.verify_token(out["access_token"])
    assert claims["typ"] == "service"
    assert claims["name"] == "sa_test_co"

    # touch_last_used should have populated last_used_at
    fetched = sa_store.get_account("sa_test_co")
    assert fetched["last_used_at"] is not None


def test_verify_service_token_account_deleted(cleanup_sa):
    sa_store.create_account(
        name="sa_test_co", description="", scopes=["hub:read"],
        client_ids=None, created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"], client_ids=None,
    )
    sa_store.delete_account("sa_test_co")
    with pytest.raises(pyjwt.InvalidTokenError, match="not found"):
        jwt_issuer.verify_token(out["access_token"])


def test_verify_service_token_jti_revoked(cleanup_sa):
    sa_store.create_account(
        name="sa_test_co", description="", scopes=["hub:read"],
        client_ids=None, created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"], client_ids=None,
    )
    sa_store.revoke_jti(jti=out["jti"], revoked_by="sa_test_runner", reason="leak")
    with pytest.raises(pyjwt.InvalidTokenError, match="revoked"):
        jwt_issuer.verify_token(out["access_token"])


# ─── API auth — scope enforcement ───────────────────────────────────────

def _auth_header(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def _seed_test_clients():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.clients (client_id, name) values
                  ('sa-test-allowed', 'Allowed'),
                  ('sa-test-blocked', 'Blocked')
                on conflict (client_id) do nothing
                """
            )


def test_service_token_with_hub_read_scope_can_read_dncxs(strict_mode_on, cleanup_sa):
    sa_store.create_account(
        name="sa_test_co", description="", scopes=["hub:read"],
        client_ids=None, created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"], client_ids=None,
    )
    r = TestClient(app).get("/v1/hub/dncxs", headers=_auth_header(out["access_token"]))
    assert r.status_code == 200


def test_service_token_without_required_scope_rejected(strict_mode_on, cleanup_sa):
    sa_store.create_account(
        name="sa_test_co", description="", scopes=["bom:propose"],  # NOT hub:read
        client_ids=None, created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["bom:propose"], client_ids=None,
    )
    r = TestClient(app).get("/v1/hub/dncxs", headers=_auth_header(out["access_token"]))
    assert r.status_code == 403
    assert "hub:read" in r.json()["detail"]


def test_bom_proposal_requires_bom_propose_scope(strict_mode_on, cleanup_sa):
    """A service token with only hub:read cannot POST a BOM proposal."""
    sa_store.create_account(
        name="sa_test_co", description="", scopes=["hub:read"],
        client_ids=None, created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"], client_ids=None,
    )
    r = TestClient(app).post(
        "/v1/hub/products/some-product/bom/proposals",
        headers=_auth_header(out["access_token"]),
        json={"client_id": "sa-test-allowed", "rows": [{"x": 1}]},
    )
    assert r.status_code == 403
    assert "bom:propose" in r.json()["detail"]


def test_service_token_client_whitelist_enforced(strict_mode_on, cleanup_sa):
    """Whitelisted client → 200; non-whitelisted → 403."""
    _seed_test_clients()
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["hub:read"], client_ids=["sa-test-allowed"],
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"],
        client_ids=["sa-test-allowed"],
    )

    c = TestClient(app)
    r_ok = c.get(
        "/v1/hub/dncxs/sa-test-allowed",
        headers=_auth_header(out["access_token"]),
    )
    assert r_ok.status_code == 200, r_ok.json()

    r_blocked = c.get(
        "/v1/hub/dncxs/sa-test-blocked",
        headers=_auth_header(out["access_token"]),
    )
    assert r_blocked.status_code == 403


def test_service_token_null_client_ids_means_all(strict_mode_on, cleanup_sa):
    """client_ids=null → token can hit any client."""
    _seed_test_clients()
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["hub:read"], client_ids=None,
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"], client_ids=None,
    )
    c = TestClient(app)
    for cid in ("sa-test-allowed", "sa-test-blocked"):
        r = c.get(f"/v1/hub/dncxs/{cid}", headers=_auth_header(out["access_token"]))
        assert r.status_code == 200, f"client {cid} → {r.status_code}: {r.json()}"


def test_service_token_dncxs_list_filtered_by_whitelist(strict_mode_on, cleanup_sa):
    """GET /v1/hub/dncxs with a whitelisted token returns ONLY allowed clients."""
    _seed_test_clients()
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["hub:read"], client_ids=["sa-test-allowed"],
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"],
        client_ids=["sa-test-allowed"],
    )
    r = TestClient(app).get("/v1/hub/dncxs", headers=_auth_header(out["access_token"]))
    assert r.status_code == 200
    ids = {row.get("id") or row.get("client_id") for row in r.json()["items"]}
    assert "sa-test-allowed" in ids
    assert "sa-test-blocked" not in ids


# ─── User tokens unaffected ─────────────────────────────────────────────

def test_user_token_unaffected_by_scope_arg(strict_mode_on):
    """Adding scope= to _require_token must not break user tokens —
    they're role-gated, not scope-gated."""
    out = jwt_issuer.make_token(
        user_id="u_sa_test", email="x@y", role="admin", display_name="X",
    )
    r = TestClient(app).get("/v1/hub/dncxs", headers=_auth_header(out["access_token"]))
    assert r.status_code == 200


# ─── /rev critical-fix regressions ──────────────────────────────────────

def test_sub_name_mismatch_rejected(cleanup_sa):
    """C1: a token with sub=svc:bcqt but name=co must NOT inherit co's
    registry row. Otherwise the holder masquerades as bcqt in audit
    while exercising co's privileges."""
    sa_store.create_account(
        name="sa_test_co", description="", scopes=["hub:read"],
        client_ids=None, created_by="sa_test_runner",
    )
    # Hand-craft a token with mismatched sub vs name.
    from datetime import datetime, timedelta, timezone
    kid = jwt_issuer.get_active_kid()
    priv, _ = jwt_issuer._load_or_create_keypair(kid)
    now = datetime.now(timezone.utc)
    bad = pyjwt.encode(
        {
            "iss": jwt_issuer.get_issuer_url(),
            "sub": "svc:sa_test_bcqt",          # claims to be bcqt
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=600)).timestamp()),
            "typ": "service",
            "name": "sa_test_co",                # but binds to co's row
            "scopes": ["hub:read"],
            "client_ids": None,
            "jti": "deadbeef",
        },
        priv, algorithm="EdDSA",
        headers={"kid": kid, "typ": "JWT"},
    )
    with pytest.raises(jwt_issuer.ServiceTokenInvalid, match="sub/name mismatch"):
        jwt_issuer.verify_token(bad)


def test_scopes_and_client_ids_rederived_from_registry(cleanup_sa):
    """C1 part 2: an admin who shrinks scopes must have it take effect
    immediately, not after 30d token expiry. The verifier overwrites
    claims['scopes']/['client_ids'] from the registry row."""
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["hub:read", "bom:propose"], client_ids=None,
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read", "bom:propose"],
        client_ids=None,
    )
    # Admin tightens — drop bom:propose, restrict to one client.
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.service_accounts set scopes=%s, client_ids=%s where name=%s",
                (["hub:read"], ["sa-test-only"], "sa_test_co"),
            )

    claims = jwt_issuer.verify_token(out["access_token"])
    assert claims["scopes"] == ["hub:read"]
    assert claims["client_ids"] == ["sa-test-only"]


def test_revoked_service_token_rejected_in_non_strict_mode(cleanup_sa):
    """C3: a revoked or deleted service account's token must NEVER fall
    through to permissive bearer mode — that would grant unauthenticated
    access in dev installs."""
    # Default = non-strict mode (no fixture)
    settings_store.set_many({"api_auth_strict": "false"})
    sa_store.create_account(
        name="sa_test_co", description="", scopes=["hub:read"],
        client_ids=None, created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"], client_ids=None,
    )
    sa_store.delete_account("sa_test_co")  # soft revocation
    r = TestClient(app).get("/v1/hub/dncxs", headers=_auth_header(out["access_token"]))
    assert r.status_code == 401, (
        "revoked service token must reject in non-strict mode too; "
        f"got {r.status_code}: {r.json()}"
    )
    assert "service token" in r.json()["detail"].lower()


def test_scopes_csv_string_rejected(cleanup_sa):
    """C2: hand-crafted token with scopes='hub:read,bom:propose' (string,
    not list) must NOT pass `'bom:propose' in <csv string>` — which would
    grant the scope by substring match. _require_scope type-checks."""
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["hub:read", "bom:propose"], client_ids=None,
        created_by="sa_test_runner",
    )
    from datetime import datetime, timedelta, timezone
    kid = jwt_issuer.get_active_kid()
    priv, _ = jwt_issuer._load_or_create_keypair(kid)
    now = datetime.now(timezone.utc)
    out_token = pyjwt.encode(
        {
            "iss": jwt_issuer.get_issuer_url(),
            "sub": "svc:sa_test_co",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=600)).timestamp()),
            "typ": "service",
            "name": "sa_test_co",
            "scopes": "hub:read,bom:propose",   # malformed: CSV string
            "client_ids": None,
            "jti": "csvtest",
        },
        priv, algorithm="EdDSA",
        headers={"kid": kid, "typ": "JWT"},
    )
    # _validate_service_token re-derives scopes from the registry, so the
    # CSV string in the token gets overwritten and the test of THIS
    # specific bug becomes harder to reach. Bypass by patching
    # _validate_service_token to skip the rederive step, then assert
    # that _require_scope's type check still catches it.
    settings_store.set_many({"api_auth_strict": "true"})
    try:
        # Ensure the type check fires: monkeypatch get_account to leave
        # claims unchanged (i.e. scopes stays as the malformed string).
        import app.routes.api as api
        from app.routes.api import _require_scope
        # Direct-call test: claims with scopes as a string must be rejected.
        with pytest.raises(Exception) as exc_info:
            _require_scope(
                {"typ": "service", "name": "x", "scopes": "hub:read,bom:propose"},
                "bom:propose",
            )
        assert exc_info.value.status_code == 403
        assert "malformed" in exc_info.value.detail.lower()
    finally:
        settings_store.set_many({"api_auth_strict": "false"})


def test_cli_empty_client_ids_string_rejected(cleanup_sa, capsys):
    """I1: --client-ids '' must NOT silently mean 'all clients'. An
    operator who types an empty string probably meant 'no clients';
    treat it as a typo and refuse."""
    import scripts.mint_service_token as cli
    rc = cli.main([
        "create", "--name", "sa_test_empty",
        "--scopes", "hub:read",
        "--client-ids", "",
        "--created-by", "smoke",
    ])
    assert rc == 2
    captured = capsys.readouterr()
    assert "empty" in captured.err.lower()
    assert sa_store.get_account("sa_test_empty") is None  # nothing persisted


def test_cli_omitted_client_ids_means_all(cleanup_sa):
    """Counterpart to the above: NOT passing --client-ids means 'all
    clients' (operator-trusted intent)."""
    import scripts.mint_service_token as cli
    rc = cli.main([
        "create", "--name", "sa_test_all",
        "--scopes", "hub:read",
        "--created-by", "smoke",
    ])
    assert rc == 0
    fetched = sa_store.get_account("sa_test_all")
    assert fetched is not None
    assert fetched["client_ids"] is None


def test_cli_invalid_name_rejected(cleanup_sa, capsys):
    """M2: --name must match a strict regex. Path-traversal-shaped
    names + uppercase + leading digits all rejected."""
    import scripts.mint_service_token as cli
    for bad in ("../etc", "Co", "1co", "co bad", ""):
        rc = cli.main([
            "create", "--name", bad,
            "--scopes", "hub:read",
            "--created-by", "smoke",
        ])
        assert rc == 2, f"name {bad!r} should have been rejected"
        captured = capsys.readouterr()
        assert "name" in captured.err.lower()
