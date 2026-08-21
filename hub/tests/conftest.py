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

import os

import pytest

# Data Hub's connect() defaults to postgresql:///data_hub — the LIVE local dev
# database. This conftest applies migrations, seeds demo clients, resets the
# admin password and deletes clients matching `-[0-9a-f]{8}$`, so a bare
# `pytest` at the repo root would run all of that against real data. Default to
# the throwaway test database instead; CI and any deliberate run set the env var
# explicitly and are unaffected. Same class of fix as CO's store-mirror fixture.
os.environ.setdefault(
    "DATA_HUB_DATABASE_URL", "postgresql:///co_test?host=/var/run/postgresql"
)

from hub.app import auth  # noqa: E402
from hub.app.auth.session import hash_password  # noqa: E402
from hub.app.database import apply_migrations, connect  # noqa: E402
from hub.app.seed import auto_seed_demo_if_empty, seed_parser_rules_if_empty  # noqa: E402
from hub.app.seed_master_data import seed_master_data_if_empty  # noqa: E402


def _sweep_test_junk_clients() -> None:
    """Delete throwaway clients that a fixture teardown never removed —
    sessions that were killed or timed out leave their random-suffixed
    clients (and, via FK ON DELETE CASCADE, all child rows) behind, and they
    accumulate in the shared local dev DB (`connect()` defaults to
    postgresql:///data_hub; only CI overrides DATA_HUB_DATABASE_URL).

    Scoped to the fixture naming convention `<prefix>-<8 hex>` produced by
    `secrets.token_hex(4)`; semantic real clients (growatt-vn, johnson-vn,
    demo-furniture, ...) never match, so this cannot touch real data.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(r"delete from hub.clients where client_id ~ '-[0-9a-f]{8}$'")
        conn.commit()


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_schema():
    apply_migrations()
    _sweep_test_junk_clients()  # clear residue left by a prior interrupted run
    seed_master_data_if_empty()
    auth.seed_admin_if_empty(email="admin@data-hub.local", password="admin123")
    # Force admin to the test-canonical password regardless of any prior
    # seed (dev DBs may have been seeded with a different env password —
    # tests hardcode admin123 across the suite, so reset every session).
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.users set password_hash=%s, role='dev' where email=%s",
            (hash_password("admin123"), "admin@data-hub.local"),
        )
    # Lifespan in app/main.py auto-seeds Growatt + Johnson demo clients
    # when no clients exist. Many test fixtures (test_agent, test_llm_*,
    # test_co_columns, ...) rely on `growatt-vn` already existing. On a
    # fresh CI database the lifespan hasn't run yet by the time those
    # fixtures open a cursor, so reproduce the seed here.
    auto_seed_demo_if_empty()
    seed_parser_rules_if_empty()
    yield
    _sweep_test_junk_clients()  # clean up this session's throwaway clients
