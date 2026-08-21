"""Schema: hub.materials.status CHECK rejects under_review (issue #49).

Migration 094 narrows the constraint to `active | deprecated | tombstoned |
inactive`. This is the guarantee that no code path — route, store, script or
manual SQL — can land under_review, independent of the application checks.
"""
from __future__ import annotations

import secrets

import pytest
from psycopg import errors

from hub.app.database import connect


@pytest.fixture
def cid():
    c = "statuschk-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (c, "materials status check test"),
        )
    yield c
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.materials where client_id=%s", (c,))
        cur.execute("delete from hub.clients where client_id=%s", (c,))


def _insert(cid, status):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            " category, status) values (%s, %s, 'x', 'nvl', %s)",
            (cid, f"MAT_{status.upper()}", status),
        )


def test_check_rejects_under_review(cid):
    with pytest.raises(errors.CheckViolation):
        _insert(cid, "under_review")


@pytest.mark.parametrize(
    "status", ["active", "deprecated", "tombstoned", "inactive"]
)
def test_check_admits_the_remaining_statuses(cid, status):
    _insert(cid, status)
