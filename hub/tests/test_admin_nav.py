"""Shared admin nav (now the persistent sidebar, `_sidebar.html`): renders on
every admin page, self-highlights the active section, and dev-gates the
Hệ thống group."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hub.app.auth.session import create_session, hash_password, SESSION_COOKIE
from hub.app.database import connect
from hub.app.main import app


def _dev_client() -> tuple[TestClient, str]:
    """Reuse the seeded dev (single-dev invariant — a 2nd dev violates
    uq_users_single_dev)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select user_id from hub.users where role='dev' "
                    "and status='active' limit 1")
        row = cur.fetchone()
    assert row, "no seeded dev user"
    uid = row[0]
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, create_session(uid))
    return c, uid


def _admin_client() -> tuple[TestClient, str]:
    uid = "u_adminnav_admin"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.users (user_id,email,display_name,password_hash,role,status) "
            "values (%s,'adminnav-admin@t.local','Nav',%s,'admin','active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (uid, hash_password("pw")))
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, create_session(uid))
    return c, uid


def _cleanup(uid: str, *, drop_user: bool = False):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.sessions where user_id=%s", (uid,))
        if drop_user:
            cur.execute("delete from hub.users where user_id=%s", (uid,))


# Every top-level admin page → its nav-active markers.
_PAGES = {
    "/admin/users": "Người dùng",
    "/admin/declaration-types": "Dữ liệu tham chiếu",
    "/admin/client-type-presets": "Dữ liệu tham chiếu",
    "/admin/uom": "Dữ liệu tham chiếu",
    "/admin/bom-adapters": "Adapter BOM",
    "/admin/service-accounts": "Hệ thống",
    "/admin/settings/technical": "Hệ thống",
    "/admin/settings/embedding": "Hệ thống",
}


def test_admin_nav_renders_on_every_page():
    """A dev sees the same grouped sub-nav (all 3 groups + Adapter BOM) on
    every admin surface, and the active group/item is highlighted."""
    c, uid = _dev_client()
    try:
        for path in _PAGES:
            r = c.get(path)
            assert r.status_code == 200, (path, r.status_code)
            # Shared nav present.
            assert 'class="side"' in r.text, path
            assert "Dữ liệu tham chiếu" in r.text, path
            assert "Hệ thống" in r.text, path  # dev sees the system group
            # Active highlighting fired on this page.
            assert 'class="side-a on"' in r.text, path
    finally:
        _cleanup(uid)


def test_admin_nav_active_item_for_reference_group():
    """On a Dữ liệu tham chiếu page, the sidebar item is marked active."""
    c, uid = _dev_client()
    try:
        r = c.get("/admin/uom")
        assert r.status_code == 200
        assert 'class="side-a on"' in r.text  # the UoM standards entry
    finally:
        _cleanup(uid)


def test_admin_nav_hides_system_group_for_non_dev():
    """A plain admin gets the open groups but not the dev-only Hệ thống one."""
    c, uid = _admin_client()
    try:
        r = c.get("/admin/users")
        assert r.status_code == 200
        assert 'class="side"' in r.text
        assert "Dữ liệu tham chiếu" in r.text
        assert "Adapter BOM" in r.text
        assert "Hệ thống" not in r.text  # dev-only group withheld
    finally:
        _cleanup(uid, drop_user=True)
