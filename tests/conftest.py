from __future__ import annotations

import os
import shutil
from pathlib import Path

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


# --------------------------------------------------------------------------- #
# File-store isolation                                                         #
# --------------------------------------------------------------------------- #
# `data/` is a symlink to the live app data directory, and every one of these
# roots defaults inside it. Before this fixture, a plain `uv run pytest` wrote
# BCCT/BOM uploads and snapshots into the shared `growatt` store and rewrote
# `co-cases/clients/growatt/cases.json` and a client's `config.json` — 39 files
# per run, growing without bound (218 accumulated BCCT uploads by 2026-08-21).
# It had already broken `test_vn_origin_resolver` once.
#
# Each root is mirrored into a throwaway tree with hardlinks, so reads still see
# the real corpus at no disk cost while every write lands on a fresh directory
# entry. The stores write with mkstemp + os.replace, which swaps the entry
# rather than the inode, so a hardlinked file cannot be modified in place.
_FILE_STORE_ROOTS = {
    "SOURCE_STORE_ROOT": "data/local/source-modules",
    "BOM_STORE_ROOT": "data/local/bom-builder",
    "CLIENT_CONFIG_ROOT": "data/local/client-config",
    "CO_CASE_STORE_ROOT": "data/local/co-cases",
}

_MIRROR_PREFIX = "pytest-store-"
_MIRROR_PARENT = "temp"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _discard_mirror(mirror: Path) -> None:
    # Same shape of guard as _drop_test_schema: refuse to delete anything that
    # is not a tree this fixture created.
    if mirror.parent.name != _MIRROR_PARENT or not mirror.name.startswith(_MIRROR_PREFIX):
        raise RuntimeError(
            f"refusing to remove {mirror!s}; the test mirror must live at "
            f"{_MIRROR_PARENT}/{_MIRROR_PREFIX}*"
        )
    shutil.rmtree(mirror, ignore_errors=True)


def _mirror_tree(source: Path, target: Path) -> None:
    for current, _dir_names, file_names in os.walk(source):
        relative = Path(current).relative_to(source)
        (target / relative).mkdir(parents=True, exist_ok=True)
        for name in file_names:
            # Lock files are opened "w", which truncates through a hardlink.
            # They carry no data; let the mirror make its own.
            if name == ".lock":
                continue
            os.link(Path(current) / name, target / relative / name)


@pytest.fixture(scope="session", autouse=True)
def isolate_file_store():
    """Point every file-mode store at a hardlink mirror instead of `data/`.

    A root already set in the environment is left alone — an explicit override
    is a deliberate choice and this fixture must not silently take it over.
    """
    repo_root = _repo_root()
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master").strip() or "master"
    safe = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in worker)
    mirror = repo_root / _MIRROR_PARENT / f"{_MIRROR_PREFIX}{safe}"
    _discard_mirror(mirror)

    previous: dict[str, str | None] = {}
    for env_name, relative in _FILE_STORE_ROOTS.items():
        previous[env_name] = os.environ.get(env_name)
        if previous[env_name] is not None:
            continue
        source = repo_root / relative
        target = mirror / Path(relative).name
        target.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            _mirror_tree(source, target)
        os.environ[env_name] = str(target)

    try:
        yield
    finally:
        for env_name, value in previous.items():
            if value is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = value
        _discard_mirror(mirror)


@pytest.fixture(autouse=True)
def isolate_data_hub_runtime_config(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_HUB_CONFIG_PATH", str(tmp_path / "data-hub-link.json"))
    # Tests exercise the local file-store backend (DATA_HUB_ENABLED off). In a
    # real deployment that now raises SourceBackendUnavailable; opt into the
    # local fallback for the suite. DH-mode tests set DATA_HUB_ENABLED=1 anyway.
    monkeypatch.setenv("CO_ALLOW_LOCAL_SOURCE", "1")
    yield
