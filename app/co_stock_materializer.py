"""Materialize CO stock pool into CO's own `co_stock_rows` table.

Background: BCCT is canonical in Data Hub. CO derives "tồn CO" by applying
client_config (lot_policy + allocation_code) to BCCT import rows via
`co_stock_rows_from_bcct()`. On big clients (Johnson: 65k BCCT) that
derivation cost ~10s per page load in Data Hub mode because we re-paginated
the full BCCT on every request and re-derived in memory.

This module persists the derived snapshot into CO's local `co_stock_rows`
table (schema from migration 001). Reads on /co-stock then become indexed
SQL selects (sub-second on 60k+ rows). Refresh is explicit — operator
clicks "Refresh từ Data Hub" or it runs lazily on first page load when
the table is empty for the client.

Adjustments + ledger claims are still applied on top of the materialized
snapshot at query time (they live in `co_stock_adjustments` /
`co_stock_claims` and change per case lock).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Iterable

from psycopg.types.json import Jsonb

from app.database import DatabaseUnavailable, connect, database_url
from app.source_index_store import build_co_stock_index_records

LOGGER = logging.getLogger(__name__)


def _store_available() -> bool:
    return bool(database_url())


def refresh_co_stock_for_client(client: dict, derive_rows) -> dict:
    """Wipe + insert co_stock_rows for one client from a derivation callable.

    `derive_rows()` returns the freshly-derived list[dict] of stock rows
    (shape: `co_stock_rows_from_bcct` output). Pulling BCCT + running the
    derivation is the caller's responsibility so this module stays free of
    portfolio_service / Data Hub imports.
    """
    summary = {
        "client_id": str(client.get("id", "")),
        "rows_persisted": 0,
        "took_seconds": 0.0,
        "last_refresh_at": None,
        "errors": [],
    }
    if not _store_available():
        summary["errors"].append("BARRY_DATABASE_URL not configured")
        return summary
    client_id = summary["client_id"]
    if not client_id:
        summary["errors"].append("client.id missing")
        return summary
    t0 = time.time()
    try:
        rows = list(derive_rows() or [])
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock refresh derive failed for %s: %s", client_id, exc)
        summary["errors"].append(f"derive: {exc}")
        return summary
    records = build_co_stock_index_records(client_id, rows)
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from co_stock_rows where client_id = %s", (client_id,))
            if records:
                cur.executemany(
                    """insert into co_stock_rows (
                        client_id, source_row, transaction_key, import_declaration_no,
                        line_no, declaration_type, customs_item_code, allocation_code,
                        eligibility_status, remaining_qty, payload
                       ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
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
                        for row in records
                    ],
                )
    except DatabaseUnavailable:
        summary["errors"].append("database unavailable")
        return summary
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock refresh persist failed for %s: %s", client_id, exc)
        summary["errors"].append(str(exc))
        return summary
    summary["rows_persisted"] = len(records)
    summary["took_seconds"] = round(time.time() - t0, 2)
    summary["last_refresh_at"] = datetime.utcnow().isoformat()
    return summary


def read_co_stock_rows(client_id: str) -> list[dict]:
    """Read all stock rows for a client from the materialized table.

    Returns the raw `payload` dicts (shape from co_stock_rows_from_bcct).
    Empty list when the table has no rows for this client.
    """
    if not _store_available():
        return []
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """select payload from co_stock_rows
                   where client_id = %s
                   order by import_declaration_no, line_no, customs_item_code, source_row""",
                (client_id,),
            )
            # payload is a JSONB column psycopg returns as a dict already; skip dict()
            # copy (saves ~0.3s on 60k rows). Callers should treat the result as
            # read-only or copy explicitly.
            return [row[0] for row in cur.fetchall()]
    except DatabaseUnavailable:
        return []
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock read failed for %s: %s", client_id, exc)
        return []


_SORTABLE_COLUMNS = {
    # public key -> SQL column expression
    "source_row": "source_row",
    "import_declaration_no": "import_declaration_no",
    "line_no": "line_no",
    "declaration_type": "declaration_type",
    "customs_item_code": "customs_item_code",
    "allocation_code": "allocation_code",
}

STATUS_FILTERS = {
    "inactive": "(eligibility_status = 'inactive')",
    "review_required": (
        "(eligibility_status <> 'inactive'"
        " and coalesce(payload->>'allocation_code_status', '') <> 'resolved')"
    ),
    "depleted": (
        "(eligibility_status <> 'inactive'"
        " and coalesce(payload->>'allocation_code_status', '') = 'resolved'"
        " and remaining_qty in ('', '0', '0.0', '0.00'))"
    ),
    "available": (
        "(eligibility_status <> 'inactive'"
        " and coalesce(payload->>'allocation_code_status', '') = 'resolved'"
        " and remaining_qty not in ('', '0', '0.0', '0.00'))"
    ),
}


def read_co_stock_page(
    client_id: str,
    *,
    q: str = "",
    status: str = "",
    sort: str = "import_declaration_no",
    direction: str = "asc",
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    """SQL-paginated read for /co-stock table.

    Pushes search (q), status filter, sort + LIMIT/OFFSET to the DB so the
    page renders in milliseconds even on 60k-row clients. Returns
    (page_rows, total_filtered_count).
    """
    if not _store_available():
        return [], 0
    sort_col = _SORTABLE_COLUMNS.get(sort, _SORTABLE_COLUMNS["import_declaration_no"])
    direction_sql = "desc" if str(direction).lower() == "desc" else "asc"
    where: list[str] = ["client_id = %s"]
    params: list = [client_id]
    if q:
        q_param = f"%{q}%"
        where.append(
            "(import_declaration_no ilike %s or line_no ilike %s or customs_item_code ilike %s"
            " or allocation_code ilike %s or coalesce(payload->>'material_description','') ilike %s"
            " or coalesce(payload->>'hs_code','') ilike %s)"
        )
        params.extend([q_param] * 6)
    if status and status in STATUS_FILTERS:
        where.append(STATUS_FILTERS[status])
    where_clause = " and ".join(where)
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(f"select count(*) from co_stock_rows where {where_clause}", params)
            total = int(cur.fetchone()[0])
            cur.execute(
                f"""select payload from co_stock_rows
                    where {where_clause}
                    order by {sort_col} {direction_sql}, source_row asc
                    limit %s offset %s""",
                [*params, int(limit), int(offset)],
            )
            page_rows = [row[0] for row in cur.fetchall()]
            return page_rows, total
    except DatabaseUnavailable:
        return [], 0
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock page read failed for %s: %s", client_id, exc)
        return [], 0


def row_count(client_id: str) -> int:
    if not _store_available():
        return 0
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("select count(*) from co_stock_rows where client_id = %s", (client_id,))
            return int(cur.fetchone()[0])
    except Exception:  # noqa: BLE001
        return 0


def registration_dates_for_source_rows(client_id: str, source_rows: list[str]) -> dict[str, str]:
    """Batch lookup `payload->>'registration_date'` for a set of source_row ids.

    Used at export time to backfill `import_declaration_date` on materials
    that were saved before the materializer started copying registration_date
    out of the BCCT payload — re-calculating a locked sheet would clear its
    material_overrides, so we hydrate the missing date here instead.
    """
    if not _store_available() or not client_id or not source_rows:
        return {}
    flat: list[str] = []
    for entry in source_rows:
        text = str(entry or "").strip()
        if not text:
            continue
        for part in text.split(","):
            piece = part.strip()
            if piece:
                flat.append(piece)
    if not flat:
        return {}
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "select source_row, payload->>'registration_date' "
                "from co_stock_rows where client_id = %s and source_row = ANY(%s)",
                (client_id, flat),
            )
            return {row[0]: (row[1] or "") for row in cur.fetchall()}
    except Exception:  # noqa: BLE001
        return {}


def last_refresh_at(client_id: str) -> str:
    """Newest indexed_at for the client (proxy for last refresh wall-clock)."""
    if not _store_available():
        return ""
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "select max(indexed_at) from co_stock_rows where client_id = %s",
                (client_id,),
            )
            value = cur.fetchone()[0]
            return value.isoformat() if value else ""
    except Exception:  # noqa: BLE001
        return ""


def record_refresh_state(
    client_id: str,
    *,
    snapshot_row_count: int,
    bcct_row_count_at_refresh: int,
    bcct_indexed_at_at_refresh=None,
) -> None:
    if not _store_available() or not client_id:
        return
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """insert into co_stock_refresh_state (
                    client_id, snapshot_row_count, bcct_row_count_at_refresh,
                    bcct_indexed_at_at_refresh, refreshed_at
                   ) values (%s, %s, %s, %s, now())
                   on conflict (client_id) do update set
                     snapshot_row_count = excluded.snapshot_row_count,
                     bcct_row_count_at_refresh = excluded.bcct_row_count_at_refresh,
                     bcct_indexed_at_at_refresh = excluded.bcct_indexed_at_at_refresh,
                     refreshed_at = now()""",
                (client_id, int(snapshot_row_count), int(bcct_row_count_at_refresh), bcct_indexed_at_at_refresh),
            )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock refresh state write failed for %s: %s", client_id, exc)


def read_refresh_state(client_id: str) -> dict | None:
    if not _store_available() or not client_id:
        return None
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """select snapshot_row_count, bcct_row_count_at_refresh,
                          bcct_indexed_at_at_refresh, refreshed_at
                   from co_stock_refresh_state where client_id = %s""",
                (client_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "snapshot_row_count": int(row[0] or 0),
                "bcct_row_count_at_refresh": int(row[1] or 0),
                "bcct_indexed_at_at_refresh": row[2].isoformat() if row[2] else "",
                "refreshed_at": row[3].isoformat() if row[3] else "",
            }
    except Exception:  # noqa: BLE001
        return None


def compute_sync_status(client_id: str, current_bcct_row_count: int) -> dict:
    """Return {status, snapshot_rows, snapshot_bcct_rows, bcct_now_rows, refreshed_at, delta}.

    status:
      - "no_snapshot": never refreshed (table empty for client)
      - "in_sync": snapshot's recorded BCCT row count matches current
      - "stale": BCCT row count diverged since last refresh
    """
    state = read_refresh_state(client_id)
    if not state or state["snapshot_row_count"] == 0:
        return {
            "status": "no_snapshot",
            "snapshot_rows": 0,
            "snapshot_bcct_rows": 0,
            "bcct_now_rows": int(current_bcct_row_count or 0),
            "refreshed_at": "",
            "delta": int(current_bcct_row_count or 0),
        }
    snapshot_bcct = state["bcct_row_count_at_refresh"]
    delta = int(current_bcct_row_count or 0) - snapshot_bcct
    return {
        "status": "in_sync" if delta == 0 else "stale",
        "snapshot_rows": state["snapshot_row_count"],
        "snapshot_bcct_rows": snapshot_bcct,
        "bcct_now_rows": int(current_bcct_row_count or 0),
        "refreshed_at": state["refreshed_at"],
        "delta": delta,
    }
