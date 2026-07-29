from __future__ import annotations

import os

import pytest

from app.database import (
    DATABASE_SCHEMA_ENV,
    apply_migrations,
    database_schema,
    database_url,
)


# Schemas that hold real / shared data and must NEVER be used or dropped by the
# test suite. `co` is the live dev schema; `public` is stale legacy data.
_PROTECTED_SCHEMAS = frozenset({"", "co", "public", "information_schema", "pg_catalog"})

# All disposable test schemas share this prefix. The drop helper refuses to
# touch anything that does not start with it, so the suite can only ever create
# and destroy its own throwaway schema.
_TEST_SCHEMA_PREFIX = "co_test_"


def _disposable_schema_name() -> str:
    # Stable per run (no random / timestamp — see feature brief constraint).
    # Under pytest-xdist each worker gets its own schema; otherwise "master".
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master").strip() or "master"
    # Keep it identifier-safe.
    safe = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in worker)
    return f"{_TEST_SCHEMA_PREFIX}{safe}"


def _drop_test_schema(url: str, schema: str) -> None:
    # Hard safety gate: only ever drop a schema we own. Any other name — most
    # importantly `co` or `public` — raises instead of running DROP.
    if not schema.startswith(_TEST_SCHEMA_PREFIX) or schema in _PROTECTED_SCHEMAS:
        raise RuntimeError(
            f"refusing to drop non-test schema {schema!r}; "
            f"test teardown only drops {_TEST_SCHEMA_PREFIX}* schemas"
        )
    import psycopg
    from psycopg import sql

    with psycopg.connect(url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(schema))
            )


@pytest.fixture(scope="session", autouse=True)
def isolate_db_schema():
    """Route DB-mode tests into a disposable schema instead of the shared `co`.

    File-mode (no `BARRY_DATABASE_URL`): no-op, tests run exactly as before.

    DB-mode (`BARRY_DATABASE_URL` set, i.e. `.env` sourced): force
    `BARRY_DATABASE_SCHEMA` to `co_test_<worker>`, migrate into it, and drop it
    cascade at the end of the session so nothing accumulates in `co`.
    """
    url = database_url()
    if not url:
        # No database configured — file-mode. Isolation does not engage.
        yield
        return

    schema = _disposable_schema_name()

    previous = os.environ.get(DATABASE_SCHEMA_ENV)
    os.environ[DATABASE_SCHEMA_ENV] = schema

    # Guard: never let the suite operate against a protected schema. This also
    # catches a misconfigured `.env` that pins BARRY_DATABASE_SCHEMA=co.
    effective = database_schema()
    if effective in _PROTECTED_SCHEMAS or effective != schema:
        if previous is None:
            os.environ.pop(DATABASE_SCHEMA_ENV, None)
        else:
            os.environ[DATABASE_SCHEMA_ENV] = previous
        raise RuntimeError(
            f"DB-mode tests refuse to run against schema {effective!r}; "
            f"expected disposable schema {schema!r}"
        )

    # Start from a clean disposable schema, then migrate into it.
    _drop_test_schema(url, schema)
    apply_migrations(url)

    try:
        yield
    finally:
        _drop_test_schema(url, schema)
        if previous is None:
            os.environ.pop(DATABASE_SCHEMA_ENV, None)
        else:
            os.environ[DATABASE_SCHEMA_ENV] = previous


@pytest.fixture(autouse=True)
def isolate_data_hub_runtime_config(monkeypatch, tmp_path):
    from app import co_auth

    co_auth.clear_jwks_cache()
    monkeypatch.setenv("DATA_HUB_CONFIG_PATH", str(tmp_path / "data-hub-link.json"))
    # Tests exercise the local file-store backend (DATA_HUB_ENABLED off). In a
    # real deployment that now raises SourceBackendUnavailable; opt into the
    # local fallback for the suite. DH-mode tests set DATA_HUB_ENABLED=1 anyway.
    monkeypatch.setenv("CO_ALLOW_LOCAL_SOURCE", "1")
    yield
    co_auth.clear_jwks_cache()
