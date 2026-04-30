from __future__ import annotations

from app.client_config_store import default_config, migrate_config, now_iso, stamp_config_hash, validate_config
from app.database import apply_migrations, connect, database_url
from app.demo_data import client_summary, clone_client


def get_app_state_store() -> "PostgresAppStateStore | None":
    url = database_url()
    return PostgresAppStateStore(url) if url else None


class PostgresAppStateStore:
    def __init__(self, url: str):
        self.url = url

    def ensure_schema(self) -> None:
        apply_migrations(self.url)

    def has_clients(self) -> bool:
        try:
            with connect(self.url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("select 1 from clients limit 1")
                    return cursor.fetchone() is not None
        except Exception:
            return False

    def clients(self) -> list[dict]:
        self.ensure_schema()
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select payload from clients order by name, id")
                return [client_summary(dict(row[0])) for row in cursor.fetchall()]

    def client(self, client_id: str) -> dict:
        self.ensure_schema()
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select payload from clients where id = %s", (client_id,))
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(client_id)
                return clone_client(dict(row[0]))

    def upsert_client(self, client: dict) -> dict:
        from psycopg.types.json import Jsonb

        payload = clone_client(client)
        self.ensure_schema()
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into clients (
                      id, name, code, status, tax_code, contact,
                      module_status, bom_source_profile, payload, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    on conflict (id) do update set
                      name = excluded.name,
                      code = excluded.code,
                      status = excluded.status,
                      tax_code = excluded.tax_code,
                      contact = excluded.contact,
                      module_status = excluded.module_status,
                      bom_source_profile = excluded.bom_source_profile,
                      payload = excluded.payload,
                      updated_at = now()
                    """,
                    (
                        payload["id"],
                        payload.get("name", ""),
                        payload.get("code", ""),
                        payload.get("status", ""),
                        payload.get("tax_code", ""),
                        payload.get("contact", ""),
                        Jsonb(payload.get("module_status", {})),
                        Jsonb(payload.get("bom_source_profile", {})),
                        Jsonb(payload),
                    ),
                )
        self.ensure_source_index(payload["id"])
        return payload

    def ensure_source_index(self, client_id: str) -> None:
        try:
            from app.source_index_store import get_source_index_store

            store = get_source_index_store()
            if store:
                store.ensure_client(client_id)
        except Exception:
            return

    def get_client_config(self, client: dict) -> dict:
        self.upsert_client(client)
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select payload from client_configs where client_id = %s", (client["id"],))
                row = cursor.fetchone()
                if row:
                    return migrate_config(dict(row[0]), client)
        config = default_config(client)
        self.upsert_client_config(client, config)
        return config

    def save_client_config(self, client: dict, config: dict) -> dict:
        existing = self.get_client_config(client)
        next_config = migrate_config(config, client)
        validate_config(next_config)
        next_config["config_version"] = int(existing.get("config_version", 1)) + 1
        next_config["updated_at"] = now_iso()
        stamp_config_hash(next_config)
        self.upsert_client_config(client, next_config)
        return next_config

    def upsert_client_config(self, client: dict, config: dict) -> dict:
        from psycopg.types.json import Jsonb

        payload = migrate_config(config, client)
        self.upsert_client(client)
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into client_configs (
                      client_id, config_version, config_hash, payload, updated_at
                    )
                    values (%s, %s, %s, %s, now())
                    on conflict (client_id) do update set
                      config_version = excluded.config_version,
                      config_hash = excluded.config_hash,
                      payload = excluded.payload,
                      updated_at = now()
                    """,
                    (
                        payload["client_id"],
                        int(payload.get("config_version", 1)),
                        payload.get("config_hash", ""),
                        Jsonb(payload),
                    ),
                )
        return payload
