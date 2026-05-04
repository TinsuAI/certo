from __future__ import annotations

import os
from pathlib import Path


DATABASE_URL_ENV = "BARRY_DATABASE_URL"
DATABASE_SCHEMA_ENV = "BARRY_DATABASE_SCHEMA"
DEFAULT_DATABASE_SCHEMA = "co"
MIGRATIONS_ROOT = Path(__file__).resolve().parent.parent / "db" / "migrations"


class DatabaseUnavailable(RuntimeError):
    pass


def database_url() -> str:
    return os.environ.get(DATABASE_URL_ENV, "").strip()


def connect(url: str | None = None):
    try:
        import psycopg
        from psycopg import sql
    except ImportError as exc:
        raise DatabaseUnavailable("Install psycopg to use Postgres.") from exc
    connection = psycopg.connect(url or database_url())
    schema = database_schema()
    if schema:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("create schema if not exists {}").format(sql.Identifier(schema)))
            cursor.execute(
                sql.SQL("set search_path to {}, public").format(sql.Identifier(schema))
            )
    return connection


def database_schema() -> str:
    return os.environ.get(DATABASE_SCHEMA_ENV, DEFAULT_DATABASE_SCHEMA).strip()


def apply_migrations(url: str | None = None) -> None:
    with connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("select pg_advisory_xact_lock(hashtext('barry_co_migrations'))")
            cursor.execute(
                """
                create table if not exists schema_migrations (
                  filename text primary key,
                  applied_at timestamptz not null default now()
                )
                """
            )
            for path in sorted(MIGRATIONS_ROOT.glob("*.sql")):
                cursor.execute("select 1 from schema_migrations where filename = %s", (path.name,))
                if cursor.fetchone():
                    continue
                for statement in split_sql(path.read_text(encoding="utf-8")):
                    cursor.execute(statement)
                cursor.execute("insert into schema_migrations (filename) values (%s)", (path.name,))


def split_sql(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]
