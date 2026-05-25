"""CO stock adjustments — Postgres-backed snapshot of opening/used overrides
per (client_id, declaration_no, line_no, customs_code).

Layered on top of BCCT-derived stock from Data Hub AFTER `co_stock_claims`
(see app/co_stock_ledger.py). Apply order:
  1. BCCT row -> stock_row with available_qty (Data Hub raw).
  2. apply_used_qty() subtracts ledger claims (per-case sheet locks).
  3. apply_adjustments() optionally overrides available_qty and adds the
     adjustment's used_qty to the ledger's used. Remaining is recomputed.

Snapshot model: re-upserting the same (client, decl, line, code) key replaces
the prior row. batch_id and source_file_ref preserve audit trail.

Storage: Postgres table `co_stock_adjustments` (migration 008). When
`BARRY_DATABASE_URL` is not configured, all functions no-op so callers don't
have to branch on environment.
"""
from __future__ import annotations

import hashlib
import logging
from decimal import Decimal, InvalidOperation
from typing import Iterable

from app import co_stock_events_store
from app.database import DatabaseUnavailable, connect, database_url

LOGGER = logging.getLogger(__name__)


def _store_available() -> bool:
    return bool(database_url())


def adjustment_id_for(client_id: str, declaration_no: str, line_no: str, customs_code: str) -> str:
    raw = f"{client_id}|{declaration_no}|{line_no}|{customs_code}".encode("utf-8")
    return "adj_" + hashlib.sha1(raw).hexdigest()[:20]


def _decimal_or_none(value) -> Decimal | None:
    if value in (None, "", "—"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _decimal_zero(value) -> Decimal:
    parsed = _decimal_or_none(value)
    return parsed if parsed is not None else Decimal("0")


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _date_or_none(value):
    """Pass through date/datetime objects; return None for blank-ish input.
    psycopg accepts datetime and date for date columns."""
    if value in (None, ""):
        return None
    return value


def upsert_batch(
    client_id: str,
    rows: Iterable[dict],
    *,
    batch_id: str,
    source_file_ref: str = "",
    actor: str = "import",
) -> dict:
    """Overwrite snapshot upsert. Returns {inserted, updated, skipped, errors, events}.

    Each input row must have at least `declaration_no`, `line_no`,
    `customs_code`. Other fields are optional but persisted when present.
    Skips rows missing the composite key.

    Also records audit events: one `adjustment_import_insert` event per
    new lot, one `adjustment_import_update` event per lot whose
    (used_qty | opening_qty_override) actually changed. No event on no-op
    re-imports (same values).
    """
    summary = {"inserted": 0, "updated": 0, "skipped": 0, "errors": [], "events": 0}
    if not _store_available():
        summary["errors"].append("BARRY_DATABASE_URL not configured")
        return summary
    payload: list[tuple] = []
    payload_meta: list[dict] = []  # per-row info for event diff
    for index, raw in enumerate(rows):
        declaration_no = _text(raw.get("declaration_no"))
        line_no = _text(raw.get("line_no"))
        customs_code = _text(raw.get("customs_code"))
        if not (declaration_no and line_no and customs_code):
            summary["skipped"] += 1
            summary["errors"].append(f"row {index + 1}: missing declaration_no/line_no/customs_code")
            continue
        opening_override = _decimal_or_none(raw.get("opening_qty_override") or raw.get("opening_qty"))
        used_qty = _decimal_zero(raw.get("used_qty"))
        payload_meta.append({
            "declaration_no": declaration_no,
            "line_no": line_no,
            "customs_code": customs_code,
            "new_used_qty": used_qty,
            "new_opening_qty_override": opening_override,
            "source_co_no": _text(raw.get("source_co_no")),
        })
        payload.append((
            adjustment_id_for(client_id, declaration_no, line_no, customs_code),
            client_id,
            declaration_no,
            line_no,
            customs_code,
            _text(raw.get("declaration_type")),
            _date_or_none(raw.get("registration_date")),
            _text(raw.get("hs_code")),
            _text(raw.get("goods_name")),
            _text(raw.get("origin_country")),
            _text(raw.get("unit")),
            _text(raw.get("partner")),
            _text(raw.get("invoice_no")),
            _date_or_none(raw.get("invoice_date")),
            _decimal_or_none(raw.get("unit_price")),
            _decimal_or_none(raw.get("taxable_unit_price")),
            _decimal_or_none(raw.get("exchange_rate")),
            opening_override,
            used_qty,
            _text(raw.get("source_co_no")),
            source_file_ref,
            batch_id,
            "active",
            _text(raw.get("notes")),
        ))
    if not payload:
        return summary
    event_rows: list[dict] = []
    try:
        with connect() as conn, conn.cursor() as cur:
            # Pre-fetch existing (used_qty, opening_qty_override) per key so we
            # can emit precise insert/update events with diff. One round-trip.
            keys = [(m["declaration_no"], m["line_no"], m["customs_code"]) for m in payload_meta]
            before_map: dict[tuple[str, str, str], dict] = {}
            if keys:
                cur.execute(
                    """select declaration_no, line_no, customs_code,
                              used_qty, opening_qty_override
                       from co_stock_adjustments
                       where client_id = %s
                         and (declaration_no, line_no, customs_code) in (
                             select unnest(%s::text[]), unnest(%s::text[]), unnest(%s::text[])
                         )""",
                    (
                        client_id,
                        [k[0] for k in keys],
                        [k[1] for k in keys],
                        [k[2] for k in keys],
                    ),
                )
                for r in cur.fetchall():
                    before_map[(r[0], r[1], r[2])] = {
                        "used_qty": Decimal(str(r[3])) if r[3] is not None else None,
                        "opening_qty_override": Decimal(str(r[4])) if r[4] is not None else None,
                    }

            for row, meta in zip(payload, payload_meta):
                cur.execute(
                    """insert into co_stock_adjustments (
                        adjustment_id, client_id, declaration_no, line_no, customs_code,
                        declaration_type, registration_date, hs_code, goods_name, origin_country,
                        unit, partner, invoice_no, invoice_date,
                        unit_price, taxable_unit_price, exchange_rate,
                        opening_qty_override, used_qty, source_co_no,
                        source_file_ref, batch_id, status, notes
                       ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                 %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                 %s, %s, %s, %s)
                       on conflict (client_id, declaration_no, line_no, customs_code) do update set
                         declaration_type = excluded.declaration_type,
                         registration_date = excluded.registration_date,
                         hs_code = excluded.hs_code,
                         goods_name = excluded.goods_name,
                         origin_country = excluded.origin_country,
                         unit = excluded.unit,
                         partner = excluded.partner,
                         invoice_no = excluded.invoice_no,
                         invoice_date = excluded.invoice_date,
                         unit_price = excluded.unit_price,
                         taxable_unit_price = excluded.taxable_unit_price,
                         exchange_rate = excluded.exchange_rate,
                         opening_qty_override = excluded.opening_qty_override,
                         used_qty = excluded.used_qty,
                         source_co_no = excluded.source_co_no,
                         source_file_ref = excluded.source_file_ref,
                         batch_id = excluded.batch_id,
                         status = 'active',
                         notes = excluded.notes,
                         updated_at = now()
                       returning (xmax = 0) as inserted""",
                    row,
                )
                inserted = cur.fetchone()[0]
                key = (meta["declaration_no"], meta["line_no"], meta["customs_code"])
                before = before_map.get(key) or {}
                new_used = meta["new_used_qty"] or Decimal("0")
                new_opening = meta["new_opening_qty_override"]
                if inserted:
                    summary["inserted"] += 1
                    event_rows.append({
                        "client_id": client_id,
                        "declaration_no": meta["declaration_no"],
                        "line_no": meta["line_no"],
                        "customs_code": meta["customs_code"],
                        "event_type": "adjustment_import_insert",
                        "qty_delta": new_used,
                        "qty_before": None,
                        "qty_after": new_used,
                        "opening_qty_before": None,
                        "opening_qty_after": new_opening,
                        "source_co_no": meta["source_co_no"],
                        "source_file_ref": source_file_ref,
                        "batch_id": batch_id,
                        "actor": actor,
                    })
                else:
                    summary["updated"] += 1
                    old_used = before.get("used_qty") or Decimal("0")
                    old_opening = before.get("opening_qty_override")
                    used_changed = old_used != new_used
                    opening_changed = old_opening != new_opening
                    if used_changed or opening_changed:
                        event_rows.append({
                            "client_id": client_id,
                            "declaration_no": meta["declaration_no"],
                            "line_no": meta["line_no"],
                            "customs_code": meta["customs_code"],
                            "event_type": "adjustment_import_update",
                            "qty_delta": new_used - old_used,
                            "qty_before": old_used,
                            "qty_after": new_used,
                            "opening_qty_before": old_opening,
                            "opening_qty_after": new_opening,
                            "source_co_no": meta["source_co_no"],
                            "source_file_ref": source_file_ref,
                            "batch_id": batch_id,
                            "actor": actor,
                        })
    except DatabaseUnavailable:
        summary["errors"].append("database unavailable")
        return summary
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock_adjustments upsert_batch failed for %s: %s", client_id, exc)
        summary["errors"].append(str(exc))
    # Emit events outside the upsert transaction so a failed event insert
    # doesn't rollback adjustments (events are auxiliary).
    if event_rows:
        summary["events"] = co_stock_events_store.record_events(event_rows)
    return summary


def list_for_client(
    client_id: str,
    *,
    status: str = "active",
    batch_id: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    if not _store_available():
        return []
    sql = (
        "select declaration_no, line_no, customs_code, declaration_type, registration_date, "
        "hs_code, goods_name, origin_country, unit, partner, invoice_no, invoice_date, "
        "unit_price, taxable_unit_price, exchange_rate, opening_qty_override, used_qty, "
        "source_co_no, source_file_ref, batch_id, status, notes, recorded_at, updated_at "
        "from co_stock_adjustments where client_id = %s and status = %s"
    )
    params: list = [client_id, status]
    if batch_id is not None:
        sql += " and batch_id = %s"
        params.append(batch_id)
    sql += " order by declaration_no, line_no, customs_code"
    if limit:
        sql += " limit %s"
        params.append(int(limit))
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [_row_to_dict(cols, row) for row in cur.fetchall()]
    except DatabaseUnavailable:
        return []
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock_adjustments list_for_client failed for %s: %s", client_id, exc)
        return []


def aggregate_by_lookup_key(client_id: str) -> dict[tuple[str, str, str], dict]:
    """`(decl_no, line_no, customs_code) -> {opening_qty_override, used_qty}` map.

    Hot path for stock-pool builder. Backed by `co_stock_adjustments_client_status_idx`.
    """
    if not _store_available():
        return {}
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """select declaration_no, line_no, customs_code,
                          opening_qty_override, used_qty
                   from co_stock_adjustments
                   where client_id = %s and status = 'active'""",
                (client_id,),
            )
            out: dict[tuple[str, str, str], dict] = {}
            for row in cur.fetchall():
                key = (str(row[0]), str(row[1]), str(row[2]))
                out[key] = {
                    "opening_qty_override": Decimal(str(row[3])) if row[3] is not None else None,
                    "used_qty": Decimal(str(row[4])) if row[4] is not None else Decimal("0"),
                }
            return out
    except DatabaseUnavailable:
        return {}
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock_adjustments aggregate failed for %s: %s", client_id, exc)
        return {}


def void_batch(client_id: str, batch_id: str) -> int:
    if not _store_available():
        return 0
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """update co_stock_adjustments
                   set status = 'voided', updated_at = now()
                   where client_id = %s and batch_id = %s and status = 'active'""",
                (client_id, batch_id),
            )
            return cur.rowcount or 0
    except DatabaseUnavailable:
        return 0
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock_adjustments void_batch failed for %s/%s: %s", client_id, batch_id, exc)
        return 0


def apply_adjustments(stock_rows: list[dict], adjustments: dict[tuple[str, str, str], dict]) -> list[dict]:
    """Layer adjustments onto stock rows (after apply_used_qty).

    For each row whose (import_declaration_no, line_no, customs_item_code)
    matches an adjustment:
      - If opening_qty_override is set, replace `available_qty`.
      - Add adjustment.used_qty to the row's used_qty.
      - Recompute remaining_qty = available - used (clamped to >= 0).

    Mutates in-place + returns. Tags rows so the UI can show "Adjusted"
    or "Overclaim" badges.
    """
    if not adjustments:
        return stock_rows
    for row in stock_rows:
        key = (
            str(row.get("import_declaration_no") or ""),
            str(row.get("line_no") or ""),
            str(row.get("customs_item_code") or ""),
        )
        adj = adjustments.get(key)
        if not adj:
            continue
        opening_override = adj.get("opening_qty_override")
        if opening_override is not None:
            row["available_qty"] = str(opening_override)
            row["opening_qty_adjusted"] = True
        try:
            existing_used = Decimal(str(row.get("used_qty") or "0"))
        except (InvalidOperation, ValueError):
            existing_used = Decimal("0")
        adj_used = adj.get("used_qty") or Decimal("0")
        new_used = existing_used + adj_used
        try:
            available = Decimal(str(row.get("available_qty") or "0"))
        except (InvalidOperation, ValueError):
            available = Decimal("0")
        remaining = available - new_used
        overclaim = remaining < 0
        if overclaim:
            remaining = Decimal("0")
        row["used_qty"] = str(new_used)
        row["remaining_qty"] = str(remaining)
        row["adjustment_used_qty"] = str(adj_used)
        row["adjustment_applied"] = True
        if overclaim:
            row["adjustment_overclaim"] = True
    return stock_rows


def _row_to_dict(cols: list[str], row: tuple) -> dict:
    out: dict = {}
    for col, value in zip(cols, row):
        if hasattr(value, "isoformat"):
            out[col] = value.isoformat()
        elif isinstance(value, Decimal):
            out[col] = str(value)
        else:
            out[col] = value
    return out
