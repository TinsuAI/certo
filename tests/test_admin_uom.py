"""Admin UoM management — list/create canonical, list/create/delete alias."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.session import SESSION_COOKIE, create_session, hash_password
from app.database import connect
from app.main import app


ADMIN_ID = "u_uom_admin"
ADMIN_EMAIL = "uom-admin@test.local"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.users (user_id, email, display_name, password_hash, "
            " role, status) values (%s, %s, 'UoM Admin', %s, 'admin', 'active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (ADMIN_ID, ADMIN_EMAIL, hash_password("test-pw")),
        )
        # Ensure cleanup of any test rows from prior failed runs
        cur.execute("delete from hub.uom_aliases where alias_norm in ('zzz_test_alias', 'zzz_a2')")
        cur.execute("delete from hub.uom_canonical where uom_code in ('zzz_test_canon')")
    sess = create_session(ADMIN_ID)
    yield {"session": sess}
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.uom_aliases where alias_norm in ('zzz_test_alias', 'zzz_a2')")
        cur.execute("delete from hub.uom_canonical where uom_code in ('zzz_test_canon')")
        cur.execute("delete from hub.sessions where user_id=%s", (ADMIN_ID,))
        cur.execute("delete from hub.users where user_id=%s", (ADMIN_ID,))


def _c(session):
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, session)
    return c


def test_uom_list_renders(setup):
    c = _c(setup["session"])
    r = c.get("/admin/uom")
    assert r.status_code == 200
    body = r.text
    # Existing canonicals from seed should appear
    assert "pcs" in body
    assert "kg" in body


def test_uom_list_requires_admin():
    c = TestClient(app)  # no session
    r = c.get("/admin/uom", follow_redirects=False)
    assert r.status_code in (302, 303, 401)


def test_create_canonical(setup):
    c = _c(setup["session"])
    r = c.post(
        "/admin/uom/canonical/new",
        data={"uom_code": "zzz_test_canon", "family": "count_packaging",
              "base_factor": "1"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select family from hub.uom_canonical where uom_code='zzz_test_canon'"
        )
        row = cur.fetchone()
    assert row == ("count_packaging",)


def test_create_canonical_invalid_family_rejected(setup):
    c = _c(setup["session"])
    r = c.post(
        "/admin/uom/canonical/new",
        data={"uom_code": "zzz_test_canon", "family": "bogus_family",
              "base_factor": "1"},
        follow_redirects=False,
    )
    # Either 400 or redirect with error
    assert r.status_code in (303, 400)
    if r.status_code == 303:
        assert "error=" in r.headers.get("location", "")


def test_create_alias(setup):
    c = _c(setup["session"])
    r = c.post(
        "/admin/uom/aliases/new",
        data={"alias_norm": "zzz_test_alias", "uom_code": "pcs"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select uom_code from hub.uom_aliases where alias_norm='zzz_test_alias'"
        )
        row = cur.fetchone()
    assert row == ("pcs",)


def test_create_alias_normalizes_input(setup):
    """Alias should be stored lowercase + trimmed, regardless of form input."""
    c = _c(setup["session"])
    r = c.post(
        "/admin/uom/aliases/new",
        data={"alias_norm": "  ZZZ_A2  ", "uom_code": "pcs"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select alias_norm from hub.uom_aliases where uom_code='pcs' "
            "and alias_norm = 'zzz_a2'"
        )
        assert cur.fetchone() is not None


def test_create_alias_rejects_unknown_canonical(setup):
    c = _c(setup["session"])
    r = c.post(
        "/admin/uom/aliases/new",
        data={"alias_norm": "zzz_test_alias", "uom_code": "no_such_canon"},
        follow_redirects=False,
    )
    assert r.status_code in (303, 400)
    if r.status_code == 303:
        assert "error=" in r.headers.get("location", "")


def test_delete_alias(setup):
    c = _c(setup["session"])
    # First create
    c.post(
        "/admin/uom/aliases/new",
        data={"alias_norm": "zzz_test_alias", "uom_code": "pcs"},
        follow_redirects=False,
    )
    # Then delete
    r = c.post(
        "/admin/uom/aliases/zzz_test_alias/delete",
        follow_redirects=False,
    )
    assert r.status_code == 303
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select 1 from hub.uom_aliases where alias_norm='zzz_test_alias'"
        )
        assert cur.fetchone() is None


def test_create_alias_clears_resolver_cache(setup):
    """After adding alias, resolve_canonical sees it without restart."""
    from app.stores.uom_standards import resolve_canonical
    c = _c(setup["session"])
    c.post(
        "/admin/uom/aliases/new",
        data={"alias_norm": "zzz_test_alias", "uom_code": "pcs"},
        follow_redirects=False,
    )
    # Resolver should now know this alias
    assert resolve_canonical("zzz_test_alias") == "pcs"
