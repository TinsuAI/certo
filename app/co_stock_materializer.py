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

The STATIC trừ-lùi adjustments (`co_stock_adjustments`) are FOLDED into the
snapshot here, so `remaining_qty` is the true tồn-after-reconciliation. Only
the LIVE cross-case ledger (`co_stock_claims`, changes per case lock) is still
overlaid at query time via `co_stock_ledger.apply_used_qty`. Re-fold on every
refresh and on adjustment import/void keeps the snapshot authoritative.
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


def refresh_co_stock_for_client(
    client: dict,
    derive_rows,
    *,
    mode: str = "full",
    tombstone_source_rows: list[str] | None = None,
) -> dict:
    """Incremental refresh of co_stock_rows from a derivation callable.

    Replaces the legacy DELETE+INSERT wipe with an UPSERT + targeted DELETE
    pattern (option B per `.ai/features/2026-05-28-co-stock-refresh-audit.md`):

      1. Snapshot the current rows by `source_row` (with payload, for diff).
      2. UPSERT every row from `derive_rows()` — INSERT new, UPDATE changed,
         no-op identical. Track which keys are new vs touched.
      3. Compute removed:
         - mode="full" (default): removed = old_keys - new_keys. The derive
           callback returns the complete snapshot; anything missing is
           presumed deleted upstream.
         - mode="delta": removed = explicit tombstone_source_rows. The
           derive callback returns ONLY the changed/added rows from a
           Data Hub `since` pull; untouched rows in the existing snapshot
           stay. Untracked source_rows are NEVER deleted in delta mode.
      4. Filter out lots that have active claims in `co_stock_claims` — they
         stay (orphan-safe); summary.blocked_lots surfaces them.
      5. Targeted DELETE for the cleared removed set.
      6. Emit per-lot `snapshot_row_added / _removed / _updated` events to
         `co_stock_events` so the audit log has provenance for every change.
    """
    summary = {
        "client_id": str(client.get("id", "")),
        "mode": mode,
        "rows_persisted": 0,
        "rows_added": 0,
        "rows_updated": 0,
        "rows_removed": 0,
        "rows_blocked_by_claims": 0,
        "blocked_lots": [],
        "took_seconds": 0.0,
        "last_refresh_at": None,
        "errors": [],
    }
    if mode not in {"full", "delta"}:
        summary["errors"].append(f"unknown mode: {mode}")
        return summary
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
    # Fold the static trừ-lùi layer into the freshly-derived rows so the
    # persisted `remaining_qty` is the true tồn-after-reconciliation. In delta
    # mode only changed rows are present; their adjustments still fold here, and
    # untouched lots keep the fold from their last refresh / import re-fold.
    from app import co_stock_adjustments_store

    adjustments = co_stock_adjustments_store.aggregate_by_lookup_key(client_id)
    co_stock_adjustments_store.fold_baseline(rows, adjustments or {})
    records = build_co_stock_index_records(client_id, rows)
    new_by_key = {row["source_row"]: row for row in records}

    try:
        with connect() as conn, conn.cursor() as cur:
            old_payloads, old_lot_keys = _load_existing_snapshot(cur, client_id)
            added, updated, identical = _classify_changes(new_by_key, old_payloads)
            removed, abort_wipe = _plan_removed_keys(
                mode,
                new_keys=set(new_by_key.keys()),
                old_keys=set(old_payloads.keys()),
                tombstone_source_rows=tombstone_source_rows,
            )
            if abort_wipe:
                # Suspicious empty full pull over a populated snapshot — almost
                # certainly a transient upstream/pagination failure, not a real
                # mass deletion. Preserve the snapshot and let the caller skip
                # advancing refresh_state / server_time.
                summary["aborted_empty_full_pull"] = True
                summary["errors"].append("empty full pull over non-empty snapshot; snapshot preserved")
                summary["rows_persisted"] = len(old_payloads)
                return summary
            _upsert_records(cur, records)
            blocked = _claims_blocking_removal(cur, client_id, removed)
            removable = sorted(removed - blocked)
            if removable:
                cur.execute(
                    "delete from co_stock_rows where client_id = %s and source_row = any(%s)",
                    (client_id, removable),
                )
            _emit_diff_events(client_id, added, updated, removable, new_by_key, old_lot_keys)
            if blocked:
                summary["blocked_lots"] = [old_lot_keys.get(k) or {"source_row": k} for k in sorted(blocked)]
    except DatabaseUnavailable:
        summary["errors"].append("database unavailable")
        return summary
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock refresh persist failed for %s: %s", client_id, exc)
        summary["errors"].append(str(exc))
        return summary
    summary["rows_persisted"] = len(records)
    summary["rows_added"] = len(added)
    summary["rows_updated"] = len(updated)
    summary["rows_removed"] = len(removable)
    summary["rows_blocked_by_claims"] = len(blocked)
    summary["took_seconds"] = round(time.time() - t0, 2)
    summary["last_refresh_at"] = datetime.utcnow().isoformat()
    return summary


def refold_adjustment_lots(client_id: str, keys) -> int:
    """Re-fold the trừ-lùi layer for specific lots without a full BCCT refresh.

    Call after an adjustment import (the touched lookup keys) or a void (the
    voided keys — fold then reverts opening to `bcct_qty` and baseline to 0,
    since those keys are no longer in the active aggregate). Bounded: only the
    matching `co_stock_rows` are recomputed and re-persisted. Returns the count
    of rows updated.
    """
    if not _store_available():
        return 0
    keyset = {(str(k[0]), str(k[1]), str(k[2])) for k in keys}
    if not keyset:
        return 0
    from app import co_stock_adjustments_store

    adjustments = co_stock_adjustments_store.aggregate_by_lookup_key(client_id)
    decls = sorted({k[0] for k in keyset})
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """select source_row, payload from co_stock_rows
                   where client_id = %s and import_declaration_no = any(%s)""",
                (client_id, decls),
            )
            to_update = []
            for source_row, payload in cur.fetchall():
                key = (
                    str(payload.get("import_declaration_no") or ""),
                    str(payload.get("line_no") or ""),
                    str(payload.get("customs_item_code") or ""),
                )
                if key not in keyset:
                    continue
                co_stock_adjustments_store.fold_baseline([payload], adjustments or {})
                to_update.append(
                    (str(payload.get("remaining_qty", "")), Jsonb(payload), client_id, source_row)
                )
            if to_update:
                # Lock rows in source_row order to match record_sheet_lock's
                # `... order by source_row for update`, so a concurrent claim
                # and this refresh can't deadlock on overlapping lots.
                to_update.sort(key=lambda row: row[3])
                cur.executemany(
                    """update co_stock_rows
                       set remaining_qty = %s, payload = %s, indexed_at = now()
                       where client_id = %s and source_row = %s""",
                    to_update,
                )
    except DatabaseUnavailable:
        return 0
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock refold failed for %s: %s", client_id, exc)
        return 0
    invalidate_co_stock_rows_cache(client_id)
    return len(to_update)


def refold_all_adjustments(client_id: str) -> int:
    """Backfill: re-fold every lot that currently has an active trừ-lùi
    adjustment. Run once after deploying the fold change so existing snapshots
    stop carrying the legacy `remaining_qty == opening` value."""
    from app import co_stock_adjustments_store

    adjustments = co_stock_adjustments_store.aggregate_by_lookup_key(client_id)
    if not adjustments:
        return 0
    return refold_adjustment_lots(client_id, list(adjustments.keys()))


def _load_existing_snapshot(cur, client_id: str) -> tuple[dict, dict]:
    """Return (source_row → payload, source_row → lot_key dict) for the
    current snapshot. Lot key is the (decl_no, line_no, customs_code) tuple
    used by co_stock_claims, kept separately so audit events can carry it."""
    cur.execute(
        """select source_row, payload, import_declaration_no, line_no, customs_item_code
           from co_stock_rows where client_id = %s""",
        (client_id,),
    )
    payloads: dict[str, dict] = {}
    lot_keys: dict[str, dict] = {}
    for source_row, payload, decl_no, line_no, customs_code in cur.fetchall():
        payloads[source_row] = dict(payload or {})
        lot_keys[source_row] = {
            "source_row": source_row,
            "declaration_no": decl_no or "",
            "line_no": line_no or "",
            "customs_code": customs_code or "",
        }
    return payloads, lot_keys


def _classify_changes(new_by_key: dict, old_payloads: dict) -> tuple[list[str], list[str], list[str]]:
    """Bucket keys into added / updated / identical for event emission.

    Identical rows still get UPSERTed (no-op on the DB side, simpler code)
    but are excluded from event emission to keep the audit log meaningful.

    Volatile audit fields (`eligibility_config_*`) are stripped before the
    comparison: they encode which client_config_version produced the row,
    not anything about the lot itself. `get_client_config` regenerates
    `updated_at` on every call (pre-existing quirk in client_config_store
    that bumps config_hash even when the config content is unchanged) so
    including these in the diff would flag every row as updated on every
    refresh.
    """
    added: list[str] = []
    updated: list[str] = []
    identical: list[str] = []
    for key, row in new_by_key.items():
        existing = old_payloads.get(key)
        if existing is None:
            added.append(key)
        elif _payload_for_diff(existing) != _payload_for_diff(row["payload"]):
            updated.append(key)
        else:
            identical.append(key)
    return added, updated, identical


_DIFF_IGNORED_PAYLOAD_KEYS = frozenset({
    "eligibility_config_version",
    "eligibility_config_hash",
})


def _payload_for_diff(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k not in _DIFF_IGNORED_PAYLOAD_KEYS}


def _upsert_records(cur, records: list[dict]) -> None:
    if not records:
        return
    # Acquire row locks in source_row order to match record_sheet_lock's
    # `... order by source_row for update`, avoiding a deadlock when a refresh
    # and a concurrent sheet-lock touch overlapping lots.
    records = sorted(records, key=lambda row: row["source_row"])
    cur.executemany(
        """insert into co_stock_rows (
            client_id, source_row, transaction_key, import_declaration_no,
            line_no, declaration_type, customs_item_code, allocation_code,
            eligibility_status, remaining_qty, payload
           ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (client_id, source_row) do update set
             transaction_key = excluded.transaction_key,
             import_declaration_no = excluded.import_declaration_no,
             line_no = excluded.line_no,
             declaration_type = excluded.declaration_type,
             customs_item_code = excluded.customs_item_code,
             allocation_code = excluded.allocation_code,
             eligibility_status = excluded.eligibility_status,
             remaining_qty = excluded.remaining_qty,
             payload = excluded.payload,
             indexed_at = now()""",
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


def _plan_removed_keys(
    mode: str,
    *,
    new_keys: set[str],
    old_keys: set[str],
    tombstone_source_rows: list[str] | None,
) -> tuple[set[str], bool]:
    """Decide which snapshot keys to delete, and whether to ABORT the refresh.

    Returns `(removed, abort_wipe)`.

    - delta: removed = explicit tombstones that exist in the snapshot. The derive
      callback returned ONLY changed rows; untracked rows are never swept. Never
      aborts (an empty delta is normal — nothing changed upstream).
    - full: removed = old_keys - new_keys (anything missing is presumed deleted
      upstream). BUT an empty full pull over a NON-empty snapshot is treated as a
      transient failure, not a mass deletion — `abort_wipe=True` so the caller
      preserves the snapshot. Empty-over-empty is a legit no-op (abort_wipe=False).
    """
    if mode == "delta":
        return ({k for k in (tombstone_source_rows or []) if k in old_keys}, False)
    if not new_keys and old_keys:
        return (set(), True)
    return (old_keys - new_keys, False)


def _claims_blocking_removal(cur, client_id: str, removed_keys: set[str]) -> set[str]:
    """Return the subset of removed_keys that still have active locked claims.

    Those lots stay in `co_stock_rows` — deleting them would orphan a
    case's claim. The operator must release the case (or have Data Hub
    explain the upstream change) before the next refresh can clean them up.
    """
    if not removed_keys:
        return set()
    cur.execute(
        """select distinct source_row from co_stock_claims
           where client_id = %s and status = 'locked' and source_row = any(%s)""",
        (client_id, sorted(removed_keys)),
    )
    return {row[0] for row in cur.fetchall()}


def _emit_diff_events(
    client_id: str,
    added: list[str],
    updated: list[str],
    removed: list[str],
    new_by_key: dict,
    old_lot_keys: dict,
) -> None:
    """Best-effort: write `snapshot_row_*` events for each classified change.
    Failures here must not abort the refresh — events are audit-only."""
    if not (added or updated or removed):
        return
    try:
        from app import co_stock_events_store

        payload = []
        for key in added:
            row = new_by_key[key]
            payload.append({
                "client_id": client_id,
                "declaration_no": row["import_declaration_no"],
                "line_no": row["line_no"],
                "customs_code": row["customs_item_code"],
                "event_type": "snapshot_row_added",
                "notes": f"materializer:{row['source_row']}",
            })
        for key in updated:
            row = new_by_key[key]
            payload.append({
                "client_id": client_id,
                "declaration_no": row["import_declaration_no"],
                "line_no": row["line_no"],
                "customs_code": row["customs_item_code"],
                "event_type": "snapshot_row_updated",
                "notes": f"materializer:{row['source_row']}",
            })
        for key in removed:
            lot = old_lot_keys.get(key, {})
            payload.append({
                "client_id": client_id,
                "declaration_no": lot.get("declaration_no", ""),
                "line_no": lot.get("line_no", ""),
                "customs_code": lot.get("customs_code", ""),
                "event_type": "snapshot_row_removed",
                "notes": f"materializer:{key}",
            })
        if payload:
            co_stock_events_store.record_events(payload)
    except Exception as exc:  # noqa: BLE001 — audit log failure must never block refresh
        LOGGER.warning("co_stock refresh event emit failed for %s: %s", client_id, exc)


# In-process snapshot cache keyed by client_id. Cache entry holds
# (max_indexed_at_marker, rows). The marker is `max(indexed_at)` from
# co_stock_rows — advances only when the materializer UPSERTs or DELETEs
# something, so a no-op delta refresh leaves the marker untouched and
# the cache stays valid. Cap on number of clients prevents one worker
# from holding multiple 250MB snapshots indefinitely.
_CO_STOCK_ROWS_CACHE: dict[str, tuple[tuple[str, int], list[dict]]] = {}
_CO_STOCK_ROWS_CACHE_MAX_CLIENTS = 4


def _snapshot_marker(client_id: str) -> tuple[str, int]:
    """`(max_indexed_at, row_count)` — cache invalidation key.

    `max(indexed_at)` catches INSERT/UPDATE because the materializer's
    UPSERT sets `indexed_at = now()` on every row it touches. `count`
    catches pure DELETE — if we removed a row but the most-recent
    indexed_at belonged to an untouched row, max(indexed_at) would not
    advance, so row_count is the second axis the cache checks on.
    """
    if not _store_available():
        return ("", 0)
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "select max(indexed_at), count(*) from co_stock_rows where client_id = %s",
                (client_id,),
            )
            value, count = cur.fetchone()
            return (value.isoformat() if value else "", int(count or 0))
    except Exception:  # noqa: BLE001
        return ("", 0)


def read_co_stock_rows_cached(client_id: str) -> list[dict]:
    """Cached read of `co_stock_rows` for a client.

    Skips the 2-3s JSONB deserialize round trip on every /calculate when
    upstream BCCT didn't change (the common case during an editing
    session). Invalidates automatically when the materializer touches
    any row for this client via the snapshot marker.
    """
    if not _store_available():
        return []
    marker = _snapshot_marker(client_id)
    cached = _CO_STOCK_ROWS_CACHE.get(client_id)
    if cached and cached[0] == marker and marker[1] > 0:
        return cached[1]
    rows = read_co_stock_rows(client_id)
    _CO_STOCK_ROWS_CACHE[client_id] = (marker, rows)
    while len(_CO_STOCK_ROWS_CACHE) > _CO_STOCK_ROWS_CACHE_MAX_CLIENTS:
        evict = next(iter(_CO_STOCK_ROWS_CACHE))
        if evict == client_id:
            evict = next((k for k in _CO_STOCK_ROWS_CACHE if k != client_id), None)
        if evict is None:
            break
        _CO_STOCK_ROWS_CACHE.pop(evict, None)
    return rows


def invalidate_co_stock_rows_cache(client_id: str = "") -> None:
    """Clear the in-process snapshot cache. Pass a client_id to drop a
    single entry; empty clears all (used by tests + admin flows)."""
    if client_id:
        _CO_STOCK_ROWS_CACHE.pop(client_id, None)
    else:
        _CO_STOCK_ROWS_CACHE.clear()


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
    # `remaining_qty` is folded (opening - trừ-lùi baseline), so an
    # over-reconciled lot can be <= 0; treat any non-positive folded remaining
    # as depleted. The numeric cast guards the legacy "" / text rows.
    "depleted": (
        "(eligibility_status <> 'inactive'"
        " and coalesce(payload->>'allocation_code_status', '') = 'resolved'"
        r" and (remaining_qty in ('', '0', '0.0', '0.00')"
        r"      or (remaining_qty ~ '^-?\d+(\.\d+)?$' and remaining_qty::numeric <= 0)))"
    ),
    "available": (
        "(eligibility_status <> 'inactive'"
        " and coalesce(payload->>'allocation_code_status', '') = 'resolved'"
        r" and remaining_qty ~ '^-?\d+(\.\d+)?$' and remaining_qty::numeric > 0)"
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


_NUMERIC_RE = r"^-?\d+(\.\d+)?$"


def _summary_decimal(value) -> "Decimal | None":
    from decimal import Decimal, InvalidOperation

    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _summary_in_range(reg_date, date_from: str, date_to: str) -> bool:
    """ISO YYYY-MM-DD string comparison. A row without a registration date is
    excluded whenever a bound is set (can't place it in the period)."""
    text = str(reg_date if reg_date is not None else "").strip()
    if date_from:
        if not text or text < date_from:
            return False
    if date_to:
        if not text or text > date_to:
            return False
    return True


def _empty_stock_summary(date_from: str = "", date_to: str = "") -> dict:
    return {
        "code_count": 0,
        "lot_count": 0,
        "total_qty": "0",
        "total_value_vnd": "0",
        "currency": "VND",
        "date_from": date_from,
        "date_to": date_to,
        "filtered": bool(date_from or date_to),
    }


def summarize_stock_value_rows(
    rows,
    claimed_by_source_row: dict | None = None,
    *,
    date_from: str = "",
    date_to: str = "",
) -> dict:
    """Pure aggregation of free-remaining CO stock value (VND) + counts.

    Free remaining per lot = folded `remaining_qty` − live locked claims for
    that `source_row` (matches the Tồn CO table + substitute panel, which both
    overlay the ledger). Only eligible, allocation-resolved lots with positive
    free remaining count. Value = free × unit_value × exchange_rate_to_vnd
    (fx defaults to 1 — missing/non-positive — so all-VND clients are exact and
    foreign-currency lots still convert). `date_from`/`date_to` filter on the
    import declaration's `registration_date` (ISO YYYY-MM-DD).

    This is the testable reference for the SQL in `co_stock_summary`; keep the
    two in sync.
    """
    from decimal import Decimal, ROUND_HALF_UP

    claimed_by_source_row = claimed_by_source_row or {}
    total = Decimal("0")
    total_qty = Decimal("0")
    codes: set[str] = set()
    lot_count = 0
    for row in rows:
        if str(row.get("eligibility_status") or "") == "inactive":
            continue
        if str(row.get("allocation_code_status") or "") != "resolved":
            continue
        if not _summary_in_range(row.get("registration_date"), date_from, date_to):
            continue
        remaining = _summary_decimal(row.get("remaining_qty"))
        if remaining is None:
            continue
        claimed = claimed_by_source_row.get(str(row.get("source_row") or "")) or Decimal("0")
        free = remaining - claimed
        if free <= 0:
            continue
        lot_count += 1
        total_qty += free
        code = str(row.get("allocation_code") or row.get("material_code") or "").strip()
        if code:
            codes.add(code)
        unit_value = _summary_decimal(row.get("unit_value")) or Decimal("0")
        fx = _summary_decimal(row.get("exchange_rate_to_vnd"))
        if fx is None or fx <= 0:
            fx = Decimal("1")
        total += free * unit_value * fx
    return {
        "code_count": len(codes),
        "lot_count": lot_count,
        # Raw sum of free remaining across ALL units of measure (kg + cái + m …).
        # Unit-agnostic by design — a rough scale figure, not a physical total.
        # 6-dp matches the stored qty precision so SQL and this reference agree.
        "total_qty": format(total_qty.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f"),
        # VND has no minor unit — round to whole đồng. This also erases the
        # sub-10^-15 tail where Python Decimal and Postgres numeric disagree,
        # keeping this reference and the SQL path byte-identical.
        "total_value_vnd": format(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP), "f"),
        "currency": "VND",
        "date_from": date_from,
        "date_to": date_to,
        "filtered": bool(date_from or date_to),
    }


def co_stock_summary(client_id: str, date_from: str = "", date_to: str = "") -> dict:
    """Free-remaining CO stock value (VND) + code/lot counts for one client,
    optionally restricted to a registration-date window.

    SQL aggregate (single indexed scan on `client_id`) so the làm-CO page and
    its date filter stay fast even on 60k-row clients. Mirrors
    `summarize_stock_value_rows`; returns a zeroed summary when no DB is
    configured or the client has no materialized snapshot.
    """
    date_from = str(date_from or "").strip()
    date_to = str(date_to or "").strip()
    if not _store_available():
        return _empty_stock_summary(date_from, date_to)
    num = _NUMERIC_RE
    sql = f"""
        with claims as (
            select source_row, sum(claimed_qty) as claimed
            from co_stock_claims
            where client_id = %s and status = 'locked'
            group by source_row
        ),
        lots as (
            select
                nullif(coalesce(nullif(r.allocation_code, ''),
                                nullif(r.payload->>'material_code', '')), '') as code,
                greatest(
                    r.remaining_qty::numeric - coalesce(c.claimed, 0), 0
                ) as free,
                case when r.payload->>'unit_value' ~ '{num}'
                     then (r.payload->>'unit_value')::numeric else 0 end as unit_value,
                case when r.payload->>'exchange_rate_to_vnd' ~ '{num}'
                          and (r.payload->>'exchange_rate_to_vnd')::numeric > 0
                     then (r.payload->>'exchange_rate_to_vnd')::numeric else 1 end as fx
            from co_stock_rows r
            left join claims c on c.source_row = r.source_row
            where r.client_id = %s
              and r.eligibility_status <> 'inactive'
              and coalesce(r.payload->>'allocation_code_status', '') = 'resolved'
              and r.remaining_qty ~ '{num}'
              and (%s = '' or (r.payload->>'registration_date') >= %s)
              and (%s = '' or (r.payload->>'registration_date') <= %s)
        )
        select
            count(*) filter (where free > 0) as lot_count,
            count(distinct code) filter (where free > 0) as code_count,
            coalesce(sum(case when free > 0 then free else 0 end), 0) as total_qty,
            coalesce(sum(case when free > 0 then free * unit_value * fx else 0 end), 0) as total_value
        from lots
    """
    params = [client_id, client_id, date_from, date_from, date_to, date_to]
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            lot_count, code_count, total_qty, total_value = cur.fetchone()
        from decimal import Decimal, ROUND_HALF_UP

        total = Decimal(str(total_value or "0")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        qty = Decimal(str(total_qty or "0")).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        return {
            "code_count": int(code_count or 0),
            "lot_count": int(lot_count or 0),
            "total_qty": format(qty, "f"),
            "total_value_vnd": format(total, "f"),
            "currency": "VND",
            "date_from": date_from,
            "date_to": date_to,
            "filtered": bool(date_from or date_to),
        }
    except DatabaseUnavailable:
        return _empty_stock_summary(date_from, date_to)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock_summary failed for %s: %s", client_id, exc)
        return _empty_stock_summary(date_from, date_to)


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
    last_bcct_server_time: str = "",
) -> None:
    if not _store_available() or not client_id:
        return
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """insert into co_stock_refresh_state (
                    client_id, snapshot_row_count, bcct_row_count_at_refresh,
                    bcct_indexed_at_at_refresh, last_bcct_server_time, refreshed_at
                   ) values (%s, %s, %s, %s, %s, now())
                   on conflict (client_id) do update set
                     snapshot_row_count = excluded.snapshot_row_count,
                     bcct_row_count_at_refresh = excluded.bcct_row_count_at_refresh,
                     bcct_indexed_at_at_refresh = excluded.bcct_indexed_at_at_refresh,
                     last_bcct_server_time = case
                       when excluded.last_bcct_server_time = '' then co_stock_refresh_state.last_bcct_server_time
                       else excluded.last_bcct_server_time end,
                     refreshed_at = now()""",
                (
                    client_id,
                    int(snapshot_row_count),
                    int(bcct_row_count_at_refresh),
                    bcct_indexed_at_at_refresh,
                    last_bcct_server_time or "",
                ),
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
                          bcct_indexed_at_at_refresh, refreshed_at, last_bcct_server_time
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
                "last_bcct_server_time": row[4] or "",
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
