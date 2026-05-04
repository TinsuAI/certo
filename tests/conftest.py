"""Pytest bootstrap: apply migrations + seed dev admin once per session.

Tests that drive the app via TestClient pick up migrations through the
lifespan startup. Tests that hit `connect()` directly in fixtures
don't — they need the schema to exist before the first cursor opens.
This session-scoped autouse fixture closes that gap so the test
suite works against a fresh database (e.g. the postgres service
container in CI).

A seeded `admin@data-hub.local` user with role='dev' is also required
by fixtures that look up "the dev user" (single-dev invariant from
migration 008). Migration 008's promotion `update set role='dev'` only
fires when the user already exists at migration time — on a fresh
CI DB the user is created by `seed_admin_if_empty` AFTER all
migrations, so we explicitly bump the role here."""
from __future__ import annotations

import pytest

from app import auth
from app.database import apply_migrations, connect


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_schema():
    apply_migrations()
    auth.seed_admin_if_empty(email="admin@data-hub.local", password="admin123")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.users set role='dev' where email=%s and role <> 'dev'",
            ("admin@data-hub.local",),
        )
    yield
