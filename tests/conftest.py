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


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_suite_database():
    """Prepare the throwaway database the suite reads through Data Hub.

    The suite now runs the backend production runs, so the client ids the tests
    address have to exist as Data Hub clients rather than as directories in a
    file store. Seeded once per session; the rows are inert scaffolding, and
    each test still creates whatever cases and BOM data it needs.
    """
    os.environ.setdefault(
        "DATA_HUB_DATABASE_URL",
        os.environ.get("CO_SUITE_DATABASE_URL", "postgresql:///co_suite?host=/var/run/postgresql"),
    )
    from hub.app.database import apply_migrations, connect

    apply_migrations()
    # CO's own schema too: co_stock_rows and the claims ledger are Postgres-only,
    # so any test that calculates or locks needs them. Tests opt in per-test with
    # BARRY_DATABASE_URL — the default stays file-mode so the case-store fixtures
    # that seed via save_state keep working.
    os.environ.setdefault("CO_SUITE_DATABASE_URL", "postgresql:///co_suite?host=/var/run/postgresql")
    _prev = os.environ.get("BARRY_DATABASE_URL")
    os.environ["BARRY_DATABASE_URL"] = os.environ["CO_SUITE_DATABASE_URL"]
    try:
        from app.database import apply_migrations as apply_co_migrations

        apply_co_migrations()
    finally:
        if _prev is None:
            os.environ.pop("BARRY_DATABASE_URL", None)
        else:
            os.environ["BARRY_DATABASE_URL"] = _prev
    with connect() as conn, conn.cursor() as cur:
        for client_id, name in (
            ("growatt", "Growatt"),
            ("growatt-vn", "Growatt VN"),
            ("johnson", "Johnson"),
            ("johnson-vn", "Johnson VN"),
            ("do-thanh", "Do Thanh"),
            ("hub-only", "Hub Only Client"),
        ):
            cur.execute(
                "insert into hub.clients (client_id, name) values (%s, %s) "
                "on conflict (client_id) do nothing",
                (client_id, name),
            )
        conn.commit()
    yield


@pytest.fixture(autouse=True)
def isolate_data_hub_runtime_config(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_HUB_CONFIG_PATH", str(tmp_path / "data-hub-link.json"))
    # The suite runs against the backend production runs: Data Hub in-process.
    # It used to run the local file-store backend, so for years the tests
    # exercised the one implementation prod never executes — the drift risk the
    # consolidation exists to remove.
    #
    # DATA_HUB_DATABASE_URL is set FIRST and unconditionally. Data Hub's
    # connect() otherwise defaults to the live `data_hub` database, and the
    # guard that prevents that lives in hub/tests/conftest.py, which does not
    # cover this suite.
    monkeypatch.setenv(
        "DATA_HUB_DATABASE_URL",
        os.environ.get("CO_SUITE_DATABASE_URL", "postgresql:///co_suite?host=/var/run/postgresql"),
    )
    monkeypatch.setenv("DATA_HUB_ENABLED", "1")
    monkeypatch.setenv("DATA_HUB_INPROCESS", "1")
    monkeypatch.delenv("CO_ALLOW_LOCAL_SOURCE", raising=False)
    yield


def seed_hub_bom(client_id: str, product_code: str, materials: list[tuple[str, float]]) -> str:
    """Publish a BOM for `product_code` straight into Data Hub's tables.

    Tests used to build their world by POSTing a workbook to CO's own
    /bom/upload. That route was the local file-store backend and is gone, so
    fixtures seed the source of truth directly. Returns the artifact id.
    """
    import secrets

    from hub.app.database import connect

    artifact_id = f"art_{secrets.token_hex(6)}"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (client_id, client_id),
        )
        # Field values mirror a manual_flat agency upload — the shape the real
        # seeder produces, so downstream code sees nothing unusual.
        cur.execute(
            """insert into hub.bom_artifacts
               (artifact_id, client_id, product_code, artifact_no, status, actor, intent,
                context, normalized_hash, row_count, diff_summary, source_bom_kind,
                flatten_status, flatten_strategy, source_channel, lineage, flatten_method,
                flatten_method_version, lineage_root_id, published_at)
               values (%s,%s,%s,1,'published','agency_staff','asserted_technical',
                       '{"seed": true, "profile": "manual_flat"}', %s, %s, '{}', 'manual_flat',
                       'not_applicable','manual_flat_as_provided','agency_upload','{}',
                       'none',0,%s, now())
               on conflict (artifact_id) do nothing""",
            (artifact_id, client_id, product_code, secrets.token_hex(32),
             len(materials), artifact_id),
        )
        for row_index, (code, qty) in enumerate(materials, start=1):
            cur.execute(
                """insert into hub.bom_artifact_rows
                   (artifact_id, row_index, material_code, qty_per_unit, uom, payload)
                   values (%s, %s, %s, %s, %s, '{}')""",
                (artifact_id, row_index, code, qty, "PCS"),
            )
        # The materials must exist too, or the catalog join drops these rows.
        for code, _ in materials:
            cur.execute(
                "insert into hub.materials (client_id, material_code, name, category, status, uom) "
                "values (%s,%s,%s,'nvl','active','PCS') on conflict do nothing",
                (client_id, code, code),
            )
        conn.commit()
    return artifact_id


def seed_hub_bcct(client_id: str, rows: list[dict]) -> None:
    """Insert BCCT lines directly. `year` is a generated column — never set it."""
    from hub.app.database import connect

    with connect() as conn, conn.cursor() as cur:
        for r in rows:
            cur.execute(
                """insert into hub.bcct_rows
                   (client_id, transaction_key, line_no, declaration_no, declaration_type,
                    direction, registration_date, customs_code, goods_name, quantity,
                    unit, unit_price, total_value, origin, invoice_ref, consignee_name)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict do nothing""",
                (
                    client_id, r["transaction_key"], str(r.get("line_no", 1)),
                    r["declaration_no"], r.get("declaration_type", "E11"),
                    r["direction"], r.get("registration_date", "2026-01-15"),
                    r["customs_code"], r.get("goods_name", r["customs_code"]),
                    r.get("quantity", 100), r.get("unit", "PCS"),
                    r.get("unit_price", 1), r.get("total_value", 100),
                    r.get("origin", "CHINA"), r.get("invoice_ref", ""),
                    r.get("consignee_name", ""),
                ),
            )
        conn.commit()


def refresh_co_stock(client_id: str) -> dict:
    """Build CO's co_stock snapshot from whatever BCCT rows are seeded.

    Uploading BCCT through CO used to do this as a side effect. Seeding Data
    Hub directly skips it, so fixtures that need tồn — anything that calculates
    or locks — call this after seeding.
    """
    from app import co_stock_materializer
    from app.data_hub_client import normalize_bcct_row
    from app.portfolio import portfolio_service
    from app.source_store import _safe_customs_fx_rows, co_stock_rows_from_bcct
    from app.web.client_context import resolve_client

    client = resolve_client(client_id)
    client_config = portfolio_service.get_client_config(client)
    rows = portfolio_service.data_hub.list_bcct(client_id)
    derived = co_stock_rows_from_bcct(
        [normalize_bcct_row(r) for r in rows],
        client_config,
        customs_fx_rows=_safe_customs_fx_rows(),
    )
    return co_stock_materializer.refresh_co_stock_for_client(
        client, lambda: derived, mode="full"
    )
