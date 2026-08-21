"""Bearer-aware substitute API at /v1/hub/clients/{c}/materials/{m}/substitutes.

Sister-app entry for CO. Mirrors the cookie-auth UI route at
/api/v1/clients/{c}/materials/{m}/substitutes; same response shape.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import jwt_issuer, settings_store
from app.database import connect
from app.main import app
from app.routes.clients import upsert_client
from app.stores import service_accounts as sa_store
from app.stores.material_substitutes import insert_candidate


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
def client_id():
    cid = "subs-api-v1-client"
    upsert_client(
        client_id=cid, name="Subs API v1",
        tax_code=None, code_resolution_mode="identity",
        bom_proposal_mode="manual", bom_proposal_qty_tolerance_pct=5.0,
        bom_approver_tier="edit", status="active", notes=None,
    )
    with connect() as conn, conn.cursor() as cur:
        for code in ("A1", "A2"):
            cur.execute(
                """
                insert into hub.materials
                  (client_id, material_code, name, category, status,
                   hs_code, source, code_kind)
                values (%s, %s, %s, 'nvl', 'active', '12345678',
                        'client_declared', 'unified')
                on conflict (client_id, material_code) do nothing
                """,
                (cid, code, f"Material {code}"),
            )
    insert_candidate(
        client_id=cid, material_a_code="A1", material_b_code="A2",
        source="manual_user", confirmed_by="u1",
    )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


@pytest.fixture
def cleanup_sa():
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.service_accounts where name like 'sa_test_%'"
        )
        cur.execute(
            "delete from hub.revoked_service_tokens where revoked_by = 'sa_test_runner'"
        )


def _auth_header(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def _url(client_id: str, material: str = "A1") -> str:
    return f"/v1/hub/clients/{client_id}/materials/{material}/substitutes"


# ── No auth ─────────────────────────────────────────────────────────


def test_no_bearer_returns_401(client_id):
    r = TestClient(app).get(_url(client_id))
    assert r.status_code == 401


def test_empty_bearer_returns_401(client_id):
    r = TestClient(app).get(
        _url(client_id), headers={"authorization": "Bearer "},
    )
    assert r.status_code == 401


# ── Service token happy path ────────────────────────────────────────


def test_service_token_with_hub_read_scope_returns_200(
    strict_mode_on, client_id, cleanup_sa,
):
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["hub:read"], client_ids=None,
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"], client_ids=None,
    )
    r = TestClient(app).get(
        _url(client_id), headers=_auth_header(out["access_token"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["client_id"] == client_id
    assert body["material_a_code"] == "A1"
    assert body["count"] == 1
    assert body["items"][0]["material_b_code"] == "A2"
    assert body["items"][0]["confirmed"] is True
    assert "manual_user" in body["items"][0]["sources"]


# ── Scope enforcement ───────────────────────────────────────────────


def test_service_token_without_hub_read_scope_rejected(
    strict_mode_on, client_id, cleanup_sa,
):
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["bom:propose"], client_ids=None,
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["bom:propose"], client_ids=None,
    )
    r = TestClient(app).get(
        _url(client_id), headers=_auth_header(out["access_token"]),
    )
    assert r.status_code == 403
    assert "hub:read" in r.json()["detail"]


# ── Client whitelist ────────────────────────────────────────────────


def test_service_token_client_whitelist_blocks_non_listed(
    strict_mode_on, client_id, cleanup_sa,
):
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["hub:read"], client_ids=["a-different-client"],
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"],
        client_ids=["a-different-client"],
    )
    r = TestClient(app).get(
        _url(client_id), headers=_auth_header(out["access_token"]),
    )
    assert r.status_code == 403


def test_service_token_client_whitelist_allows_listed(
    strict_mode_on, client_id, cleanup_sa,
):
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["hub:read"], client_ids=[client_id],
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"], client_ids=[client_id],
    )
    r = TestClient(app).get(
        _url(client_id), headers=_auth_header(out["access_token"]),
    )
    assert r.status_code == 200


# ── Min score / limit ──────────────────────────────────────────────


def test_min_score_filter_returns_empty(
    strict_mode_on, client_id, cleanup_sa,
):
    sa_store.create_account(
        name="sa_test_co", description="",
        scopes=["hub:read"], client_ids=None,
        created_by="sa_test_runner",
    )
    out = jwt_issuer.make_service_token(
        name="sa_test_co", scopes=["hub:read"], client_ids=None,
    )
    r = TestClient(app).get(
        _url(client_id) + "?min_score=2.0",
        headers=_auth_header(out["access_token"]),
    )
    assert r.status_code == 200
    assert r.json()["count"] == 0
