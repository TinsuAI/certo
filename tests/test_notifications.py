"""Sprint B1: notification system."""
from __future__ import annotations

import secrets

import pytest

from app import notifications
from app.database import connect


@pytest.fixture
def two_users():
    """Two users (admin + staff). Cleanup notifs + return their ids."""
    a_id = "u_notif_admin_" + secrets.token_hex(4)
    s_id = "u_notif_staff_" + secrets.token_hex(4)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.users
                  (user_id, email, password_hash, role, status, display_name)
                values (%s, %s, 'x', 'admin', 'active', 'Admin Test'),
                       (%s, %s, 'x', 'staff', 'active', 'Staff Test')
                """,
                (a_id, f"{a_id}@test", s_id, f"{s_id}@test"),
            )
    yield a_id, s_id
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.notifications where user_id in (%s, %s)",
                        (a_id, s_id))
            cur.execute("delete from hub.users where user_id in (%s, %s)",
                        (a_id, s_id))


def test_notify_inserts_row(two_users):
    a, _ = two_users
    nid = notifications.notify(
        user_id=a, kind="test", title="Test title", body="Test body",
        link_url="/somewhere",
    )
    assert isinstance(nid, int) and nid > 0
    rows = notifications.list_for_user(a)
    assert len(rows) == 1
    assert rows[0]["title"] == "Test title"
    assert rows[0]["status"] == "unread"


def test_unread_count(two_users):
    a, _ = two_users
    notifications.notify(user_id=a, kind="x", title="A")
    notifications.notify(user_id=a, kind="x", title="B")
    notifications.notify(user_id=a, kind="x", title="C")
    assert notifications.unread_count(a) == 3


def test_mark_read_owner_only(two_users):
    """Mark-read scoped to owner — staff can't mark admin's notif."""
    a, s = two_users
    nid = notifications.notify(user_id=a, kind="x", title="A")
    # staff tries to mark admin's notif read → no row changed
    assert notifications.mark_read(user_id=s, notification_id=nid) is False
    assert notifications.unread_count(a) == 1
    # owner can
    assert notifications.mark_read(user_id=a, notification_id=nid) is True
    assert notifications.unread_count(a) == 0


def test_mark_read_idempotent(two_users):
    """Second mark on a read row returns False."""
    a, _ = two_users
    nid = notifications.notify(user_id=a, kind="x", title="A")
    assert notifications.mark_read(user_id=a, notification_id=nid) is True
    assert notifications.mark_read(user_id=a, notification_id=nid) is False


def test_mark_all_read(two_users):
    a, _ = two_users
    notifications.notify(user_id=a, kind="x", title="A")
    notifications.notify(user_id=a, kind="x", title="B")
    n = notifications.mark_all_read(a)
    assert n == 2
    assert notifications.unread_count(a) == 0


def test_get_for_user_existence_leak_protection(two_users):
    """Foreign-user lookup returns None, not 'belongs to someone else'."""
    a, s = two_users
    nid = notifications.notify(user_id=a, kind="x", title="A")
    assert notifications.get_for_user(user_id=s, notification_id=nid) is None
    assert notifications.get_for_user(user_id=a, notification_id=nid) is not None


def test_list_filter_by_status(two_users):
    a, _ = two_users
    n1 = notifications.notify(user_id=a, kind="x", title="A")
    n2 = notifications.notify(user_id=a, kind="x", title="B")
    notifications.mark_read(user_id=a, notification_id=n1)
    unread = notifications.list_for_user(a, status="unread")
    assert len(unread) == 1
    assert unread[0]["id"] == n2
    read = notifications.list_for_user(a, status="read")
    assert len(read) == 1
    assert read[0]["id"] == n1


def test_notify_many_fan_out(two_users):
    a, s = two_users
    n = notifications.notify_many(
        user_ids=[a, s], kind="alarm", title="Heads up",
        body="something happened", client_id="growatt-vn",
    )
    assert n == 2
    assert notifications.unread_count(a) == 1
    assert notifications.unread_count(s) == 1


def test_notify_many_empty_list_is_noop(two_users):
    a, _ = two_users
    n = notifications.notify_many(
        user_ids=[], kind="alarm", title="Nope",
    )
    assert n == 0


def test_staff_with_edit_access_includes_dev_admin(two_users):
    """The dev/admin always have edit access to every client."""
    user_ids = notifications.staff_with_edit_access_to_client("growatt-vn")
    # Should include the test admin + the global admin@data-hub.local
    assert any("admin" in uid.lower() or "u_" in uid for uid in user_ids)
    assert len(user_ids) >= 1


def test_list_newest_first(two_users):
    a, _ = two_users
    n1 = notifications.notify(user_id=a, kind="x", title="oldest")
    n2 = notifications.notify(user_id=a, kind="x", title="middle")
    n3 = notifications.notify(user_id=a, kind="x", title="newest")
    rows = notifications.list_for_user(a)
    assert [r["id"] for r in rows] == [n3, n2, n1]


def test_get_includes_link_url(two_users):
    a, _ = two_users
    nid = notifications.notify(
        user_id=a, kind="x", title="A", link_url="/clients/growatt-vn/bcct",
    )
    row = notifications.get_for_user(user_id=a, notification_id=nid)
    assert row["link_url"] == "/clients/growatt-vn/bcct"
