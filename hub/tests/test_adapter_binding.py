"""Per-client default BOM adapter binding (B.0).

clients.default_bom_adapter stores a chosen adapter (null = auto-detect). The
upload form pre-selects it. A stored adapter that's no longer registered
degrades to 'auto' rather than breaking the form.
"""
from __future__ import annotations

import secrets

import pytest

from app.database import connect
from app.parsers import bom_adapters
from app.stores import adapter_binding as ab

A_VALID = "sap_indented_walk"  # a registered adapter (see bom_adapters registry)


@pytest.fixture
def cid():
    c = "bind-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("insert into hub.clients (client_id, name) values (%s,%s)",
                    (c, "binding test"))
    yield c
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id=%s", (c,))


def test_default_is_auto_when_unset(cid):
    assert ab.get_default_adapter(cid) == "auto"


def test_set_and_get(cid):
    assert A_VALID in bom_adapters.adapter_names()  # guard the fixture name
    ab.set_default_adapter(cid, A_VALID)
    assert ab.get_default_adapter(cid) == A_VALID


def test_set_auto_stores_null(cid):
    ab.set_default_adapter(cid, A_VALID)
    ab.set_default_adapter(cid, "auto")
    assert ab.get_default_adapter(cid) == "auto"
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select default_bom_adapter from hub.clients where client_id=%s",
                    (cid,))
        assert cur.fetchone()[0] is None


def test_invalid_adapter_rejected(cid):
    with pytest.raises(ValueError):
        ab.set_default_adapter(cid, "no_such_adapter")


def test_get_degrades_when_adapter_unregistered(cid):
    # Simulate an adapter that was bound then removed from the registry.
    with connect() as conn, conn.cursor() as cur:
        cur.execute("update hub.clients set default_bom_adapter='ghost_adapter' "
                    "where client_id=%s", (cid,))
    assert ab.get_default_adapter(cid) == "auto"


def test_list_bindings_flags_degraded(cid):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("update hub.clients set default_bom_adapter='ghost_adapter' "
                    "where client_id=%s", (cid,))
    row = next(r for r in ab.list_bindings() if r["client_id"] == cid)
    assert row["default_bom_adapter"] == "auto"
    assert row["degraded"] is True


def test_upload_form_preselects_bound_adapter(cid):
    from fastapi.testclient import TestClient
    from app.auth.session import create_session, hash_password, SESSION_COOKIE
    from app.main import app
    uid = "u_bind_admin"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.users (user_id,email,display_name,password_hash,role,status) "
            "values (%s,'bind-admin@t.local','A',%s,'admin','active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (uid, hash_password("pw")))
    try:
        ab.set_default_adapter(cid, A_VALID)
        c = TestClient(app)
        c.cookies.set(SESSION_COOKIE, create_session(uid))
        r = c.get(f"/clients/{cid}/bom/upload")
        assert r.status_code == 200
        # The bound adapter option is rendered selected, not the auto option.
        assert f'value="{A_VALID}" selected' in r.text
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from hub.sessions where user_id=%s", (uid,))
            cur.execute("delete from hub.users where user_id=%s", (uid,))
