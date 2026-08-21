"""Admin service-account UI — list, dev-gate, mint (one-time reveal),
validation, delete, revoke-jti."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import jwt_issuer
from app.auth.session import SESSION_COOKIE, create_session, hash_password
from app.database import connect
from app.main import app
from app.stores import service_accounts as sa_store

ADMIN_ID = "u_sa_admin"
ADMIN_EMAIL = "sa-admin@test.local"
TEST_CLIENT = "sa_test_client"


@pytest.fixture(autouse=True)
def isolated_keys_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_HUB_KEYS_DIR", d)
        yield Path(d)


@pytest.fixture(autouse=True)
def setup():
    # Only one dev user is allowed (uq_users_single_dev) — reuse the
    # existing seeded dev rather than inserting another.
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select user_id, email from hub.users where role='dev' limit 1")
        dev_row = cur.fetchone()
        assert dev_row, "no seeded dev user to run admin tests against"
        dev_id, dev_email = dev_row
        cur.execute(
            "insert into hub.users (user_id, email, display_name, password_hash,"
            " role, status) values (%s, %s, 'SA Admin', %s, 'admin', 'active')"
            " on conflict (user_id) do update set role='admin', status='active'",
            (ADMIN_ID, ADMIN_EMAIL, hash_password("test-pw")),
        )
        cur.execute(
            "insert into hub.clients (client_id, name, status) values (%s, 'SA Test Co', 'active')"
            " on conflict (client_id) do nothing",
            (TEST_CLIENT,),
        )
        cur.execute("delete from hub.service_accounts where name like 'sa_ui_%'")
    dev_sess = create_session(dev_id)
    admin_sess = create_session(ADMIN_ID)
    yield {"dev": dev_sess, "admin": admin_sess, "dev_email": dev_email}
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.service_accounts where name like 'sa_ui_%'")
        cur.execute("delete from hub.revoked_service_tokens where revoked_by = %s", (dev_email,))
        cur.execute("delete from hub.clients where client_id = %s", (TEST_CLIENT,))
        cur.execute("delete from hub.sessions where user_id in (%s, %s)", (dev_id, ADMIN_ID))
        cur.execute("delete from hub.users where user_id = %s", (ADMIN_ID,))


def _c(session):
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, session)
    return c


def test_list_renders_for_dev(setup):
    r = _c(setup["dev"]).get("/admin/service-accounts")
    assert r.status_code == 200
    assert "Service tokens" in r.text


def test_list_requires_dev_anon(setup):
    r = TestClient(app).get("/admin/service-accounts", follow_redirects=False)
    assert r.status_code in (302, 303, 401)


def test_list_forbidden_for_admin(setup):
    r = _c(setup["admin"]).get("/admin/service-accounts", follow_redirects=False)
    assert r.status_code == 403


def test_create_mints_and_reveals_token(setup):
    r = _c(setup["dev"]).post(
        "/admin/service-accounts/new",
        data={"name": "sa_ui_co", "description": "CO", "scopes": ["hub:read", "bom:propose"]},
    )
    assert r.status_code == 200
    row = sa_store.get_account("sa_ui_co")
    assert row is not None
    assert set(row["scopes"]) == {"hub:read", "bom:propose"}
    assert row["client_ids"] is None  # no clients picked = all
    assert row["created_by"] == setup["dev_email"]
    # Token revealed once in the response and decodes to a valid service token.
    import re
    m = re.search(r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", r.text)
    assert m, "minted token not shown in response"
    claims = jwt_issuer.verify_token(m.group(0))
    assert claims["sub"] == "svc:sa_ui_co"
    assert claims["typ"] == "service"


def test_create_default_expiry_is_1y(setup):
    from datetime import datetime, timezone
    _c(setup["dev"]).post(
        "/admin/service-accounts/new",
        data={"name": "sa_ui_defexp", "scopes": ["hub:read"]},
    )
    row = sa_store.get_account("sa_ui_defexp")
    assert row["token_expires_at"] is not None
    days = (row["token_expires_at"].astimezone(timezone.utc) - datetime.now(timezone.utc)).days
    assert 360 <= days <= 366


def test_create_with_chosen_expiry(setup):
    from datetime import datetime, timezone
    _c(setup["dev"]).post(
        "/admin/service-accounts/new",
        data={"name": "sa_ui_exp", "scopes": ["hub:read"], "expires_on": "2099-01-15"},
    )
    row = sa_store.get_account("sa_ui_exp")
    exp_utc = row["token_expires_at"].astimezone(timezone.utc)
    assert (exp_utc.year, exp_utc.month, exp_utc.day) == (2099, 1, 15)
    assert (exp_utc - datetime.now(timezone.utc)).days > 365


def test_create_rejects_past_expiry(setup):
    r = _c(setup["dev"]).post(
        "/admin/service-accounts/new",
        data={"name": "sa_ui_past", "scopes": ["hub:read"], "expires_on": "2000-01-01"},
    )
    assert r.status_code == 200
    assert "tương lai" in r.text
    assert sa_store.get_account("sa_ui_past") is None


def test_create_rejects_bad_expiry_format(setup):
    r = _c(setup["dev"]).post(
        "/admin/service-accounts/new",
        data={"name": "sa_ui_badexp", "scopes": ["hub:read"], "expires_on": "15/01/2099"},
    )
    assert r.status_code == 200
    assert "không hợp lệ" in r.text
    assert sa_store.get_account("sa_ui_badexp") is None


def test_create_with_client_whitelist(setup):
    _c(setup["dev"]).post(
        "/admin/service-accounts/new",
        data={"name": "sa_ui_scoped", "scopes": ["hub:read"], "client_ids": [TEST_CLIENT]},
    )
    row = sa_store.get_account("sa_ui_scoped")
    assert row["client_ids"] == [TEST_CLIENT]


def test_create_rejects_all_invalid_clients(setup):
    # Submitting only unknown client ids must error, not silently widen to all.
    r = _c(setup["dev"]).post(
        "/admin/service-accounts/new",
        data={"name": "sa_ui_badclient", "scopes": ["hub:read"],
              "client_ids": ["does-not-exist"]},
    )
    assert r.status_code == 200
    assert "whitelist" in r.text.lower()
    assert sa_store.get_account("sa_ui_badclient") is None


def test_create_rejects_bad_name(setup):
    r = _c(setup["dev"]).post(
        "/admin/service-accounts/new",
        data={"name": "Bad Name!", "scopes": ["hub:read"]},
    )
    assert r.status_code == 200
    assert "không hợp lệ" in r.text
    assert sa_store.get_account("Bad Name!") is None


def test_create_rejects_no_scope(setup):
    r = _c(setup["dev"]).post(
        "/admin/service-accounts/new",
        data={"name": "sa_ui_noscope"},
    )
    assert r.status_code == 200
    assert "scope" in r.text.lower()
    assert sa_store.get_account("sa_ui_noscope") is None


def test_create_rejects_duplicate(setup):
    sa_store.create_account(
        name="sa_ui_dup", description="", scopes=["hub:read"],
        client_ids=None, created_by=setup["dev_email"],
    )
    r = _c(setup["dev"]).post(
        "/admin/service-accounts/new",
        data={"name": "sa_ui_dup", "scopes": ["hub:read"]},
    )
    assert r.status_code == 200
    assert "đã tồn tại" in r.text


def test_delete_removes_account(setup):
    sa_store.create_account(
        name="sa_ui_del", description="", scopes=["hub:read"],
        client_ids=None, created_by=setup["dev_email"],
    )
    r = _c(setup["dev"]).post(
        "/admin/service-accounts/sa_ui_del/delete", follow_redirects=False)
    assert r.status_code == 303
    assert sa_store.get_account("sa_ui_del") is None


def test_revoke_jti_blacklists(setup):
    r = _c(setup["dev"]).post(
        "/admin/service-accounts/revoke-jti",
        data={"jti": "deadbeef_ui", "reason": "leak"}, follow_redirects=False,
    )
    assert r.status_code == 303
    assert sa_store.is_jti_revoked("deadbeef_ui")


def test_create_forbidden_for_admin(setup):
    r = _c(setup["admin"]).post(
        "/admin/service-accounts/new",
        data={"name": "sa_ui_x", "scopes": ["hub:read"]}, follow_redirects=False,
    )
    assert r.status_code == 403
    assert sa_store.get_account("sa_ui_x") is None
