"""Postgres connectivity + connection pool.

`connect()` is the single entrypoint used by ~178 call sites across
routes, stores, and scripts. Returns a context-manager that yields a
psycopg connection. On exit, returns it to the pool (clean) or
rolls/closes (error).

Pool design notes:

- Default URL → pooled. Custom URL → ad-hoc, no pool. Tests can pass
  url=database_url() to keep pool behavior; tests targeting a sandbox
  pass a different URL and bypass.
- `reset` callback runs on every check-in (putconn) and clears
  `app.user_id` GUC. SESSION-scoped GUCs would otherwise leak across
  requests when a connection is reused. The bcct_row_history trigger
  reads this GUC to attribute changes — leaks would mis-attribute
  edits to the wrong user.
- Pool max_size=16 covers single-worker dev (~3-4 in flight) plus
  multi-worker prod (4 workers × 4 conn). Bumped via env if needed.
- Lazy init: pool is created on first use, not at import. Tests that
  need different settings call `_reconfigure_pool_for_test`.
- `apply_migrations()` opens its own ad-hoc connection — runs at
  app boot before pool is ready, and never holds a pool slot.
"""
from __future__ import annotations

import os
from pathlib import Path

DATABASE_URL_ENV = "DATA_HUB_DATABASE_URL"
DEFAULT_URL = "postgresql:///data_hub"
MIGRATIONS_ROOT = Path(__file__).resolve().parent.parent / "db" / "migrations"

POOL_MIN_SIZE_ENV = "DATA_HUB_DB_POOL_MIN"
POOL_MAX_SIZE_ENV = "DATA_HUB_DB_POOL_MAX"
DEFAULT_POOL_MIN = 2
DEFAULT_POOL_MAX = 16


class DatabaseUnavailable(RuntimeError):
    pass


def database_url() -> str:
    return os.environ.get(DATABASE_URL_ENV, DEFAULT_URL).strip() or DEFAULT_URL


# ── Pool internals ──────────────────────────────────────────────────────

_pool = None  # populated on first connect() call against the default URL


def _reset_session_state(conn) -> None:
    """Called by the pool on every check-in (putconn). Clears the
    `app.user_id` GUC so SESSION-scoped state from one request can't
    leak into the next when the same physical connection is reused."""
    with conn.cursor() as cur:
        cur.execute("select set_config('app.user_id', '', false)")


def _open_pool(*, min_size: int, max_size: int):
    try:
        from psycopg_pool import ConnectionPool
    except ImportError as exc:
        raise DatabaseUnavailable(
            "psycopg-pool not installed; pip install psycopg-pool",
        ) from exc
    pool = ConnectionPool(
        conninfo=database_url(),
        min_size=min_size,
        max_size=max_size,
        reset=_reset_session_state,
        # `open=False` + manual `.open()` so we control init explicitly.
        open=False,
    )
    pool.open()
    return pool


def _get_pool():
    global _pool
    if _pool is None:
        min_size = int(os.environ.get(POOL_MIN_SIZE_ENV, DEFAULT_POOL_MIN))
        max_size = int(os.environ.get(POOL_MAX_SIZE_ENV, DEFAULT_POOL_MAX))
        _pool = _open_pool(min_size=min_size, max_size=max_size)
    return _pool


def close_pool() -> None:
    """Shut the pool down cleanly. Called from FastAPI lifespan
    on shutdown, and from tests that reconfigure pool state."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def _reconfigure_pool_for_test(*, min_size: int, max_size: int) -> None:
    """Test-only: tear down the current pool and rebuild with new
    sizes. Used by tests that need a single-connection pool to verify
    state-leak guarantees deterministically."""
    close_pool()
    global _pool
    _pool = _open_pool(min_size=min_size, max_size=max_size)


# ── Connection acquisition ──────────────────────────────────────────────


class _PooledConnection:
    """Context-manager facade: __enter__ acquires from pool (or opens
    ad-hoc if URL differs from default); __exit__ releases. Mirrors
    psycopg's `with conn:` transaction semantics — commits on clean
    exit, rolls back on exception."""

    def __init__(self, *, url: str | None, user_id: str | None):
        self._url = url
        self._user_id = user_id
        self._cm = None
        self._conn = None
        self._adhoc = False

    def __enter__(self):
        if self._url is None or self._url == database_url():
            pool = _get_pool()
            self._cm = pool.connection()
            self._conn = self._cm.__enter__()
        else:
            try:
                import psycopg
            except ImportError as exc:
                raise DatabaseUnavailable(
                    "Install psycopg to use Postgres.",
                ) from exc
            self._conn = psycopg.connect(self._url)
            self._adhoc = True
        if self._user_id:
            with self._conn.cursor() as cur:
                cur.execute(
                    "select set_config('app.user_id', %s, false)",
                    (self._user_id,),
                )
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        if self._cm is not None:
            return self._cm.__exit__(exc_type, exc, tb)
        # Ad-hoc path: mirror psycopg's `with conn:` transaction commit
        # semantic, then close the connection (no pool to return to).
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._conn.close()
        return False


def connect(url: str | None = None, *, user_id: str | None = None):
    """Open a Postgres connection.

    Returns a context-manager. Default URL routes through the pool;
    custom URL opens an ad-hoc connection.

    `user_id`: optional. When supplied, sets the SESSION GUC
    `app.user_id` so the AFTER UPDATE/DELETE trigger on
    `hub.bcct_rows` records who made each change. The pool's `reset`
    callback clears this GUC on check-in so it can't leak to the next
    request. Ad-hoc connections close at scope exit so leaks aren't
    possible there.
    """
    return _PooledConnection(url=url, user_id=user_id)


# ── Migrations ──────────────────────────────────────────────────────────


def apply_migrations(url: str | None = None) -> None:
    """Migrations open their own ad-hoc connection — they run at app
    boot before the pool is initialized, and shouldn't hold a pool
    slot. We bypass the pool entirely here."""
    try:
        import psycopg
    except ImportError as exc:
        raise DatabaseUnavailable("Install psycopg to use Postgres.") from exc
    with psycopg.connect(url or database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                create schema if not exists hub;
                """
            )
            cursor.execute(
                """
                create table if not exists hub.schema_migrations (
                  filename text primary key,
                  applied_at timestamptz not null default now()
                )
                """
            )
            for path in sorted(MIGRATIONS_ROOT.glob("*.sql")):
                cursor.execute(
                    "select 1 from hub.schema_migrations where filename = %s",
                    (path.name,),
                )
                if cursor.fetchone():
                    continue
                for statement in split_sql(path.read_text(encoding="utf-8")):
                    cursor.execute(statement)
                cursor.execute(
                    "insert into hub.schema_migrations (filename) values (%s)",
                    (path.name,),
                )


def split_sql(sql: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    in_func = 0
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") and not buf:
            continue
        buf.append(line)
        upper = stripped.upper()
        if "$$" in line:
            in_func ^= line.count("$$") % 2
        if not in_func and stripped.endswith(";"):
            chunk = "\n".join(buf).strip().rstrip(";").strip()
            if chunk:
                statements.append(chunk)
            buf = []
    tail = "\n".join(buf).strip().rstrip(";").strip()
    if tail:
        statements.append(tail)
    return statements
