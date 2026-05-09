"""Catalog material edit — POST /clients/<id>/catalog/<code>/edit.

Permission gate: can_edit_client (admin/dev always; manager if managed;
staff iff scope='edit'). Existing infra — no new permission key needed.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.session import SESSION_COOKIE, create_session, hash_password
from app.database import connect
from app.main import app


CLIENT = "_test_edit_client"
ADMIN_ID = "u_edit_admin"
ADMIN_EMAIL = "edit-admin@test.local"
STAFF_READ_ID = "u_edit_staff_read"
STAFF_READ_EMAIL = "staff-read@test.local"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, 'edit test') "
            "on conflict do nothing",
            (CLIENT,),
        )
        cur.execute(
            "insert into hub.users (user_id, email, display_name, password_hash, "
            " role, status) values (%s, %s, 'Edit Admin', %s, 'admin', 'active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (ADMIN_ID, ADMIN_EMAIL, hash_password("test-pw")),
        )
        cur.execute(
            "insert into hub.users (user_id, email, display_name, password_hash, "
            " role, status) values (%s, %s, 'Read Only', %s, 'staff', 'active') "
            "on conflict (user_id) do update set role='staff', status='active'",
            (STAFF_READ_ID, STAFF_READ_EMAIL, hash_password("test-pw")),
        )
        cur.execute(
            "insert into hub.user_client_access (user_id, client_id, scope, granted_by) "
            "values (%s, %s, 'read', %s) "
            "on conflict (user_id, client_id) do update set scope='read'",
            (STAFF_READ_ID, CLIENT, ADMIN_ID),
        )
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            " category, status, source, code_kind) "
            "values (%s, 'TESTCODE', 'Old name', 'nvl', 'active', "
            "'client_declared', 'unified')",
            (CLIENT,),
        )

    admin_session = create_session(ADMIN_ID)
    staff_session = create_session(STAFF_READ_ID)
    yield {"admin": admin_session, "staff_read": staff_session}

    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.materials where client_id=%s", (CLIENT,))
        cur.execute(
            "delete from hub.user_client_access where user_id in (%s, %s)",
            (ADMIN_ID, STAFF_READ_ID),
        )
        cur.execute("delete from hub.sessions where user_id in (%s, %s)",
                    (ADMIN_ID, STAFF_READ_ID))
        cur.execute("delete from hub.users where user_id in (%s, %s)",
                    (ADMIN_ID, STAFF_READ_ID))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _client(session_id):
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, session_id)
    return c


def _material():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select name, category, status, uom, production_source, "
            "supplier_hint, hq_registered "
            "from hub.materials where client_id=%s and material_code='TESTCODE'",
            (CLIENT,),
        )
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row)) if row else None


# ── Edit form GET ─────────────────────────────────────────────────────────


def test_edit_form_renders_for_admin(setup):
    c = _client(setup["admin"])
    r = c.get(f"/clients/{CLIENT}/catalog/TESTCODE/edit")
    assert r.status_code == 200
    assert "TESTCODE" in r.text
    assert "Old name" in r.text


def test_edit_form_403_for_read_only_staff(setup):
    c = _client(setup["staff_read"])
    r = c.get(f"/clients/{CLIENT}/catalog/TESTCODE/edit", follow_redirects=False)
    assert r.status_code == 403


# ── Edit POST ─────────────────────────────────────────────────────────────


def test_edit_updates_material(setup):
    c = _client(setup["admin"])
    r = c.post(
        f"/clients/{CLIENT}/catalog/TESTCODE/edit",
        data={
            "name": "New name",
            "category": "tp",
            "status": "under_review",
            "uom": "PIECES",
            "production_source": "nk",
            "supplier_hint": "Supplier X",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    m = _material()
    assert m["name"] == "New name"
    assert m["category"] == "tp"
    assert m["status"] == "under_review"
    assert m["uom"] == "PIECES"
    assert m["production_source"] == "nk"
    assert m["supplier_hint"] == "Supplier X"


def test_edit_rejects_invalid_category(setup):
    c = _client(setup["admin"])
    r = c.post(
        f"/clients/{CLIENT}/catalog/TESTCODE/edit",
        data={"name": "x", "category": "BOGUS", "status": "active"},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_edit_403_for_read_only_staff(setup):
    c = _client(setup["staff_read"])
    r = c.post(
        f"/clients/{CLIENT}/catalog/TESTCODE/edit",
        data={"name": "x", "category": "nvl", "status": "active"},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_edit_404_for_unknown_material(setup):
    c = _client(setup["admin"])
    r = c.post(
        f"/clients/{CLIENT}/catalog/UNKNOWN_CODE/edit",
        data={"name": "x", "category": "nvl", "status": "active"},
        follow_redirects=False,
    )
    assert r.status_code == 404


def test_edit_emits_audit_event(setup):
    """Update fires the materials_audit_events trigger (mig 045)."""
    c = _client(setup["admin"])
    c.post(
        f"/clients/{CLIENT}/catalog/TESTCODE/edit",
        data={"name": "Audited name", "category": "nvl", "status": "active"},
        follow_redirects=False,
    )
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.material_audit_events "
            "where client_id=%s and material_code='TESTCODE'",
            (CLIENT,),
        )
        n = cur.fetchone()[0]
    assert n >= 1
