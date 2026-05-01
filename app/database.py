from __future__ import annotations

import os
from pathlib import Path

DATABASE_URL_ENV = "DATA_HUB_DATABASE_URL"
DEFAULT_URL = "postgresql:///data_hub"
MIGRATIONS_ROOT = Path(__file__).resolve().parent.parent / "db" / "migrations"


class DatabaseUnavailable(RuntimeError):
    pass


def database_url() -> str:
    return os.environ.get(DATABASE_URL_ENV, DEFAULT_URL).strip() or DEFAULT_URL


def connect(url: str | None = None, *, user_id: str | None = None):
    """Open a Postgres connection.

    `user_id`: optional. When supplied, sets the session GUC `app.user_id`
    so the AFTER UPDATE/DELETE trigger on `hub.bcct_rows` records who
    made each change. Use the request user's id from write paths; ad-hoc
    sessions can leave it None and the trigger writes 'system'.
    """
    try:
        import psycopg
    except ImportError as exc:
        raise DatabaseUnavailable("Install psycopg to use Postgres.") from exc
    conn = psycopg.connect(url or database_url())
    if user_id:
        with conn.cursor() as cur:
            # SET needs a literal in its DDL syntax; use set_config() to
            # parameterize safely. is_local=false → outlives the txn.
            cur.execute("select set_config('app.user_id', %s, false)", (user_id,))
    return conn


def apply_migrations(url: str | None = None) -> None:
    with connect(url) as connection:
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
