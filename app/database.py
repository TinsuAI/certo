from __future__ import annotations

import os
from pathlib import Path


DATABASE_URL_ENV = "BARRY_DATABASE_URL"
MIGRATIONS_ROOT = Path(__file__).resolve().parent.parent / "db" / "migrations"


class DatabaseUnavailable(RuntimeError):
    pass


def database_url() -> str:
    return os.environ.get(DATABASE_URL_ENV, "").strip()


def connect(url: str | None = None):
    try:
        import psycopg
    except ImportError as exc:
        raise DatabaseUnavailable("Install psycopg to use Postgres.") from exc
    return psycopg.connect(url or database_url())


def apply_migrations(url: str | None = None) -> None:
    with connect(url) as connection:
        with connection.cursor() as cursor:
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
