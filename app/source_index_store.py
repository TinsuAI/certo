from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.co_case_store import invoice_keys


DATABASE_URL_ENV = "BARRY_DATABASE_URL"
MIGRATIONS_ROOT = Path(__file__).resolve().parent.parent / "db" / "migrations"


class SourceIndexUnavailable(RuntimeError):
    pass


def database_url() -> str:
    return os.environ.get(DATABASE_URL_ENV, "").strip()


def get_source_index_store() -> "PostgresSourceIndexStore | None":
    url = database_url()
    return PostgresSourceIndexStore(url) if url else None


def rebuild_source_index_if_configured(client: dict) -> dict | None:
    store = get_source_index_store()
    if store is None:
        return None
    return store.rebuild_client_from_files(client)


def build_bcct_index_records(client_id: str, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    bcct_records = []
    invoice_records = []
    for row in rows:
        transaction_key = row["transaction_key"]
        bcct_records.append({
            "client_id": client_id,
            "transaction_key": transaction_key,
            "direction": row.get("direction", ""),
            "review_status": row.get("review_status", ""),
            "declaration_no": row.get("declaration_no", ""),
            "line_no": row.get("line_no", ""),
            "declaration_type": row.get("declaration_type", ""),
            "item_code": row.get("item_code", ""),
            "hs_code": row.get("hs_code", ""),
            "quantity": row.get("quantity", ""),
            "unit": row.get("unit", ""),
            "invoice_ref": row.get("invoice_ref", ""),
            "payload": dict(row),
        })
        for invoice_key in sorted(invoice_keys(row.get("invoice_ref", ""))):
            invoice_records.append({
                "client_id": client_id,
                "invoice_key": invoice_key,
                "transaction_key": transaction_key,
            })
    return bcct_records, invoice_records


def build_co_stock_index_records(client_id: str, rows: list[dict]) -> list[dict]:
    return [
        {
            "client_id": client_id,
            "source_row": row["source_row"],
            "transaction_key": row.get("source_transaction_key", ""),
            "import_declaration_no": row.get("import_declaration_no", ""),
            "line_no": row.get("line_no", ""),
            "declaration_type": row.get("declaration_type", ""),
            "customs_item_code": row.get("customs_item_code", ""),
            "allocation_code": row.get("allocation_code", ""),
            "eligibility_status": row.get("eligibility_status", ""),
            "remaining_qty": row.get("remaining_qty", ""),
            "payload": dict(row),
        }
        for row in rows
    ]


class PostgresSourceIndexStore:
    def __init__(self, url: str):
        self.url = url

    def ensure_schema(self) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for path in sorted(MIGRATIONS_ROOT.glob("*.sql")):
                    for statement in split_sql(path.read_text(encoding="utf-8")):
                        cursor.execute(statement)

    def has_client(self, client_id: str) -> bool:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "select 1 from source_index_metadata where client_id = %s and module = 'bcct' limit 1",
                        (client_id,),
                    )
                    return cursor.fetchone() is not None
        except Exception:
            return False

    def source_summary(self, client_id: str, client_config: dict) -> dict:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select module, version_id, version_no, published_row_count,
                           reviewed_row_count, correction_candidate_count
                    from source_index_metadata
                    where client_id = %s
                    """,
                    (client_id,),
                )
                rows = cursor.fetchall()
        by_module = {row[0]: row for row in rows}
        return {
            "client_config": client_config,
            "material_catalog": metadata_summary(by_module.get("material_catalog"), "material_catalog"),
            "product_catalog": metadata_summary(by_module.get("product_catalog"), "product_catalog"),
            "bcct": metadata_summary(by_module.get("bcct"), "bcct"),
            "co_stock_row_count": int((by_module.get("co_stock") or [None, None, None, 0])[3] or 0),
        }

    def match_bcct_exports(self, client_id: str, invoice_no: str, relevant_types: list[str]) -> list[dict]:
        keys = sorted(invoice_keys(invoice_no))
        if not keys:
            return []
        params: list[Any] = [client_id]
        type_clause = ""
        if relevant_types:
            type_clause = "and b.declaration_type = any(%s)"
            params.append(relevant_types)
        params.append(keys)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select b.payload
                    from bcct_rows b
                    where b.client_id = %s
                      and b.direction = 'export'
                      and b.review_status = 'reviewed'
                      {type_clause}
                      and exists (
                        select 1
                        from bcct_invoice_index i
                        where i.client_id = b.client_id
                          and i.transaction_key = b.transaction_key
                          and i.invoice_key = any(%s)
                      )
                    order by b.payload->>'declaration_no', b.payload->>'line_no', b.payload->>'item_code'
                    """,
                    params,
                )
                return [dict(row[0]) for row in cursor.fetchall()]

    def co_stock_rows(self, client_id: str) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select payload
                    from co_stock_rows
                    where client_id = %s
                    order by import_declaration_no, line_no, customs_item_code, source_row
                    """,
                    (client_id,),
                )
                return [dict(row[0]) for row in cursor.fetchall()]

    def rebuild_client_from_files(self, client: dict) -> dict:
        from app.client_config_store import get_client_config
        from app.source_store import (
            co_stock_rows_from_bcct,
            load_module_state,
            state_path,
        )

        material = load_module_state(client, "material_catalog")
        product = load_module_state(client, "product_catalog")
        bcct = load_module_state(client, "bcct")
        client_config = get_client_config(client)
        stock_rows = co_stock_rows_from_bcct(bcct["published_rows"], client_config)
        bcct_records, invoice_records = build_bcct_index_records(client["id"], bcct["published_rows"])
        stock_records = build_co_stock_index_records(client["id"], stock_rows)
        metadata = [
            source_metadata_record(client["id"], "material_catalog", material, state_path(client["id"], "material_catalog")),
            source_metadata_record(client["id"], "product_catalog", product, state_path(client["id"], "product_catalog")),
            source_metadata_record(client["id"], "bcct", bcct, state_path(client["id"], "bcct")),
            {
                "client_id": client["id"],
                "module": "co_stock",
                "version_id": "",
                "version_no": 0,
                "published_row_count": len(stock_rows),
                "reviewed_row_count": 0,
                "correction_candidate_count": 0,
                "state_mtime_ns": 0,
                "config_hash": client_config.get("config_hash", ""),
            },
        ]
        self.ensure_schema()
        self.replace_client_indexes(client["id"], bcct_records, invoice_records, stock_records, metadata)
        return {
            "client_id": client["id"],
            "bcct_rows": len(bcct_records),
            "invoice_tokens": len(invoice_records),
            "co_stock_rows": len(stock_records),
        }

    def replace_client_indexes(
        self,
        client_id: str,
        bcct_records: list[dict],
        invoice_records: list[dict],
        stock_records: list[dict],
        metadata_records: list[dict],
    ) -> None:
        from psycopg.types.json import Jsonb

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("delete from bcct_invoice_index where client_id = %s", (client_id,))
                cursor.execute("delete from co_stock_rows where client_id = %s", (client_id,))
                cursor.execute("delete from bcct_rows where client_id = %s", (client_id,))
                cursor.execute("delete from source_index_metadata where client_id = %s", (client_id,))
                cursor.executemany(
                    """
                    insert into bcct_rows (
                        client_id, transaction_key, direction, review_status, declaration_no,
                        line_no, declaration_type, item_code, hs_code, quantity, unit,
                        invoice_ref, payload
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            row["client_id"],
                            row["transaction_key"],
                            row["direction"],
                            row["review_status"],
                            row["declaration_no"],
                            row["line_no"],
                            row["declaration_type"],
                            row["item_code"],
                            row["hs_code"],
                            row["quantity"],
                            row["unit"],
                            row["invoice_ref"],
                            Jsonb(row["payload"]),
                        )
                        for row in bcct_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into bcct_invoice_index (client_id, invoice_key, transaction_key)
                    values (%s, %s, %s)
                    on conflict do nothing
                    """,
                    [
                        (row["client_id"], row["invoice_key"], row["transaction_key"])
                        for row in invoice_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into co_stock_rows (
                        client_id, source_row, transaction_key, import_declaration_no,
                        line_no, declaration_type, customs_item_code, allocation_code,
                        eligibility_status, remaining_qty, payload
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            row["client_id"],
                            row["source_row"],
                            row["transaction_key"],
                            row["import_declaration_no"],
                            row["line_no"],
                            row["declaration_type"],
                            row["customs_item_code"],
                            row["allocation_code"],
                            row["eligibility_status"],
                            row["remaining_qty"],
                            Jsonb(row["payload"]),
                        )
                        for row in stock_records
                    ],
                )
                cursor.executemany(
                    """
                    insert into source_index_metadata (
                        client_id, module, version_id, version_no, published_row_count,
                        reviewed_row_count, correction_candidate_count, state_mtime_ns, config_hash
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            row["client_id"],
                            row["module"],
                            row["version_id"],
                            row["version_no"],
                            row["published_row_count"],
                            row["reviewed_row_count"],
                            row["correction_candidate_count"],
                            row["state_mtime_ns"],
                            row["config_hash"],
                        )
                        for row in metadata_records
                    ],
                )

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise SourceIndexUnavailable("Install psycopg to use Postgres source indexes.") from exc
        return psycopg.connect(self.url)


def source_metadata_record(client_id: str, module: str, state: dict, path: Path) -> dict:
    latest = state.get("latest_version") or {}
    return {
        "client_id": client_id,
        "module": module,
        "version_id": latest.get("version_id", ""),
        "version_no": int(latest.get("version_no") or 0),
        "published_row_count": len(state.get("published_rows", [])),
        "reviewed_row_count": sum(1 for row in state.get("published_rows", []) if row.get("review_status") == "reviewed"),
        "correction_candidate_count": len(state.get("correction_candidates", [])),
        "state_mtime_ns": path.stat().st_mtime_ns if path.exists() else 0,
        "config_hash": "",
    }


def metadata_summary(row, module: str) -> dict:
    if not row:
        return {
            "module": module,
            "published_row_count": 0,
            "latest_version": {},
            "version_count": 0,
            "upload_count": 0,
            "correction_candidate_count": 0,
            "reviewed_row_count": 0,
        }
    return {
        "module": module,
        "published_row_count": int(row[3] or 0),
        "latest_version": {"version_id": row[1] or "", "version_no": int(row[2] or 0)} if row[1] or row[2] else {},
        "version_count": 0,
        "upload_count": 0,
        "correction_candidate_count": int(row[5] or 0),
        "reviewed_row_count": int(row[4] or 0),
    }


def split_sql(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]
