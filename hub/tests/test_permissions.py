"""RBAC + per-client ACL tests."""
from __future__ import annotations

import hashlib

import pytest
import psycopg

from hub.app import auth
from hub.app.auth.session import User
from hub.app.database import connect


PREFIX = "test_perm_"


def _uid(suffix: str) -> str:
    return PREFIX + suffix


def _make_user(user_id: str, email: str, role: str) -> User:
    pw_hash = auth.hash_password("test")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.users (user_id, email, display_name, password_hash, role)
                values (%s, %s, %s, %s, %s)
                on conflict (user_id) do update set role = excluded.role
                """,
                (user_id, email, email.split("@")[0], pw_hash, role),
            )
    return User(user_id=user_id, email=email, display_name=email.split("@")[0], role=role, status="active")


def _make_client(client_id: str, name: str = "Test Client") -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.clients (client_id, name) values (%s, %s)
                on conflict (client_id) do nothing
                """,
                (client_id, name),
            )


def _grant_managed(user_id: str, client_id: str, granted_by: str) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.user_managed_clients (user_id, client_id, granted_by)
                values (%s, %s, %s) on conflict do nothing
                """,
                (user_id, client_id, granted_by),
            )


def _grant_access(user_id: str, client_id: str, scope: str, granted_by: str) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.user_client_access (user_id, client_id, scope, granted_by)
                values (%s, %s, %s, %s) on conflict (user_id, client_id) do update set scope = excluded.scope
                """,
                (user_id, client_id, scope, granted_by),
            )


def _seed_admin_as_dev() -> User:
    """Reuse the seed admin (migration 008 set role='dev') for tests requiring a dev user.
    The single-dev partial unique index forbids creating another."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select user_id, email, display_name, role, status from hub.users where role = 'dev'"
            )
            row = cur.fetchone()
    assert row is not None, "no dev user found — migration 008 should have created one"
    return User(*row)


@pytest.fixture
def fixtures():
    """Create admin/manager/staff + 2 clients; reuse seed dev. Tear down test rows."""
    dev = _seed_admin_as_dev()
    admin = _make_user(_uid("admin"), "admin@test.local", "admin")
    manager = _make_user(_uid("mgr"), "mgr@test.local", "manager")
    staff_r = _make_user(_uid("staff_r"), "staff_r@test.local", "staff")
    staff_e = _make_user(_uid("staff_e"), "staff_e@test.local", "staff")
    staff_none = _make_user(_uid("staff_none"), "staff_none@test.local", "staff")

    _make_client(_uid("c_in"), "Client In Group")
    _make_client(_uid("c_out"), "Client Out Of Group")

    _grant_managed(manager.user_id, _uid("c_in"), dev.user_id)
    _grant_access(staff_r.user_id, _uid("c_in"), "read", dev.user_id)
    _grant_access(staff_e.user_id, _uid("c_in"), "edit", dev.user_id)

    yield {
        "dev": dev,
        "admin": admin,
        "manager": manager,
        "staff_r": staff_r,
        "staff_e": staff_e,
        "staff_none": staff_none,
        "c_in": _uid("c_in"),
        "c_out": _uid("c_out"),
    }

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.user_managed_clients where user_id like %s", (PREFIX + "%",))
            cur.execute("delete from hub.user_client_access where user_id like %s", (PREFIX + "%",))
            cur.execute("delete from hub.users where user_id like %s", (PREFIX + "%",))
            cur.execute("delete from hub.clients where client_id like %s", (PREFIX + "%",))


def test_role_check_constraint_rejects_unknown_role():
    with pytest.raises(psycopg.errors.CheckViolation):
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into hub.users (user_id, email, display_name, password_hash, role)
                    values (%s, %s, %s, %s, %s)
                    """,
                    (_uid("bad"), "bad@test.local", "Bad", "x", "superuser"),
                )


def test_single_dev_invariant_blocks_second_dev(fixtures):
    """Inserting a second 'dev' user violates the partial unique index."""
    with pytest.raises(psycopg.errors.UniqueViolation):
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into hub.users (user_id, email, display_name, password_hash, role)
                    values (%s, %s, %s, %s, 'dev')
                    """,
                    (_uid("dev2"), "dev2@test.local", "Dev2", "x"),
                )


def test_can_view_client_dev_sees_all(fixtures):
    f = fixtures
    assert auth.can_view_client(f["dev"], f["c_in"])
    assert auth.can_view_client(f["dev"], f["c_out"])


def test_can_view_client_admin_sees_all(fixtures):
    f = fixtures
    assert auth.can_view_client(f["admin"], f["c_in"])
    assert auth.can_view_client(f["admin"], f["c_out"])


def test_can_view_client_manager_in_group(fixtures):
    f = fixtures
    assert auth.can_view_client(f["manager"], f["c_in"])


def test_can_view_client_manager_out_of_group(fixtures):
    f = fixtures
    assert not auth.can_view_client(f["manager"], f["c_out"])


def test_can_view_client_staff_with_access(fixtures):
    f = fixtures
    assert auth.can_view_client(f["staff_r"], f["c_in"])
    assert auth.can_view_client(f["staff_e"], f["c_in"])
    assert not auth.can_view_client(f["staff_r"], f["c_out"])


def test_can_view_client_staff_no_access_sees_nothing(fixtures):
    f = fixtures
    assert not auth.can_view_client(f["staff_none"], f["c_in"])
    assert not auth.can_view_client(f["staff_none"], f["c_out"])


def test_can_edit_client_staff_read_scope_returns_false(fixtures):
    f = fixtures
    assert not auth.can_edit_client(f["staff_r"], f["c_in"])


def test_can_edit_client_staff_edit_scope_returns_true(fixtures):
    f = fixtures
    assert auth.can_edit_client(f["staff_e"], f["c_in"])


def test_can_edit_client_manager_in_group(fixtures):
    f = fixtures
    assert auth.can_edit_client(f["manager"], f["c_in"])
    assert not auth.can_edit_client(f["manager"], f["c_out"])


def test_visible_clients_filters_correctly(fixtures):
    f = fixtures
    assert auth.visible_clients(f["dev"]) is None
    assert auth.visible_clients(f["admin"]) is None
    assert set(auth.visible_clients(f["manager"])) == {f["c_in"]}
    assert set(auth.visible_clients(f["staff_r"])) == {f["c_in"]}
    assert auth.visible_clients(f["staff_none"]) == []
    assert auth.visible_clients(None) == []


def test_can_edit_deployment_config_dev_only(fixtures):
    f = fixtures
    assert auth.can_edit_deployment_config(f["dev"])
    assert not auth.can_edit_deployment_config(f["admin"])
    assert not auth.can_edit_deployment_config(f["manager"])
    assert not auth.can_edit_deployment_config(f["staff_e"])


def test_can_edit_client_technical_dev_only(fixtures):
    f = fixtures
    assert auth.can_edit_client_technical(f["dev"], f["c_in"])
    assert not auth.can_edit_client_technical(f["admin"], f["c_in"])
    assert not auth.can_edit_client_technical(f["manager"], f["c_in"])


def test_can_manage_users_admin_and_dev(fixtures):
    f = fixtures
    assert auth.can_manage_users(f["dev"])
    assert auth.can_manage_users(f["admin"])
    assert not auth.can_manage_users(f["manager"])
    assert not auth.can_manage_users(f["staff_e"])


def test_can_assign_staff_to_client_manager_within_group(fixtures):
    f = fixtures
    assert auth.can_assign_staff_to_client(f["manager"], f["c_in"])
    assert not auth.can_assign_staff_to_client(f["manager"], f["c_out"])
    assert auth.can_assign_staff_to_client(f["admin"], f["c_out"])


def test_seed_admin_migrated_to_dev():
    """The original seed admin@data-hub.local should be role='dev' after migration 008."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select role from hub.users where email = 'admin@data-hub.local'")
            row = cur.fetchone()
    assert row is not None, "seed admin missing"
    assert row[0] == "dev"
