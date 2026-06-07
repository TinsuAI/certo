"""CO stock events — audit log per (client_id, declaration_no, line_no, customs_code).

Every mutation to a lot's used_qty / opening_qty_override / lifecycle state
writes one row here. The Tồn CO UI surfaces these via a per-lot history modal.

Storage: Postgres table `co_stock_events` (migration 009). When
`BARRY_DATABASE_URL` is not configured, all functions silently no-op so
callers don't have to branch.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable

from app.database import DatabaseUnavailable, connect, database_url

LOGGER = logging.getLogger(__name__)

EVENT_TYPES = {
    "adjustment_import_insert",
    "adjustment_import_update",
    "adjustment_void",
    "claim_lock",
    "claim_release",
    "snapshot_row_added",
    "snapshot_row_removed",
    "snapshot_row_updated",
}


def _store_available() -> bool:
    return bool(database_url())


def _event_id() -> str:
    return "evt_" + secrets.token_hex(10)


def _decimal_or_none(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def record_event(
    *,
    client_id: str,
    declaration_no: str,
    line_no: str,
    customs_code: str,
    event_type: str,
    qty_delta=None,
    qty_before=None,
    qty_after=None,
    opening_qty_before=None,
    opening_qty_after=None,
    source_co_no: str = "",
    case_id: str = "",
    sheet_product_code: str = "",
    source_file_ref: str = "",
    batch_id: str = "",
    actor: str = "system",
    notes: str = "",
) -> str | None:
    """Insert one event row. Returns event_id or None when DB unavailable."""
    if not _store_available():
        return None
    if event_type not in EVENT_TYPES:
        LOGGER.warning("co_stock_events: unknown event_type %r — skipping", event_type)
        return None
    if not (declaration_no and line_no and customs_code):
        # Without the lot key we can't index the event — skip rather than corrupt.
        return None
    eid = _event_id()
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """insert into co_stock_events (
                    event_id, client_id, declaration_no, line_no, customs_code,
                    event_type, qty_delta, qty_before, qty_after,
                    opening_qty_before, opening_qty_after,
                    source_co_no, case_id, sheet_product_code,
                    source_file_ref, batch_id, actor, notes
                   ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                             %s, %s, %s, %s, %s, %s, %s)""",
                (
                    eid,
                    client_id,
                    declaration_no,
                    line_no,
                    customs_code,
                    event_type,
                    _decimal_or_none(qty_delta),
                    _decimal_or_none(qty_before),
                    _decimal_or_none(qty_after),
                    _decimal_or_none(opening_qty_before),
                    _decimal_or_none(opening_qty_after),
                    _text(source_co_no),
                    _text(case_id),
                    _text(sheet_product_code),
                    _text(source_file_ref),
                    _text(batch_id),
                    _text(actor) or "system",
                    _text(notes),
                ),
            )
    except DatabaseUnavailable:
        return None
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock_events insert failed: %s", exc)
        return None
    return eid


def record_events(rows: Iterable[dict]) -> int:
    """Batch insert. Each dict must contain the same kwargs as record_event."""
    if not _store_available():
        return 0
    payload = []
    for row in rows:
        if not (row.get("declaration_no") and row.get("line_no") and row.get("customs_code")):
            continue
        if row.get("event_type") not in EVENT_TYPES:
            continue
        payload.append((
            _event_id(),
            row.get("client_id", ""),
            _text(row.get("declaration_no")),
            _text(row.get("line_no")),
            _text(row.get("customs_code")),
            row["event_type"],
            _decimal_or_none(row.get("qty_delta")),
            _decimal_or_none(row.get("qty_before")),
            _decimal_or_none(row.get("qty_after")),
            _decimal_or_none(row.get("opening_qty_before")),
            _decimal_or_none(row.get("opening_qty_after")),
            _text(row.get("source_co_no")),
            _text(row.get("case_id")),
            _text(row.get("sheet_product_code")),
            _text(row.get("source_file_ref")),
            _text(row.get("batch_id")),
            _text(row.get("actor")) or "system",
            _text(row.get("notes")),
        ))
    if not payload:
        return 0
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.executemany(
                """insert into co_stock_events (
                    event_id, client_id, declaration_no, line_no, customs_code,
                    event_type, qty_delta, qty_before, qty_after,
                    opening_qty_before, opening_qty_after,
                    source_co_no, case_id, sheet_product_code,
                    source_file_ref, batch_id, actor, notes
                   ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                             %s, %s, %s, %s, %s, %s, %s)""",
                payload,
            )
    except DatabaseUnavailable:
        return 0
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock_events batch insert failed: %s", exc)
        return 0
    return len(payload)


def events_for_lot(
    client_id: str,
    declaration_no: str,
    line_no: str,
    customs_code: str,
    *,
    limit: int = 200,
) -> list[dict]:
    if not _store_available():
        return []
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """select event_id, event_type, qty_delta, qty_before, qty_after,
                          opening_qty_before, opening_qty_after,
                          source_co_no, case_id, sheet_product_code,
                          source_file_ref, batch_id, actor, notes, recorded_at
                   from co_stock_events
                   where client_id = %s and declaration_no = %s
                     and line_no = %s and customs_code = %s
                   order by recorded_at desc, event_id desc
                   limit %s""",
                (client_id, declaration_no, line_no, customs_code, int(limit)),
            )
            cols = [d[0] for d in cur.description]
            return [_row_to_dict(cols, row) for row in cur.fetchall()]
    except DatabaseUnavailable:
        return []
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock_events events_for_lot failed: %s", exc)
        return []


def events_for_case(client_id: str, case_id: str, *, limit: int = 500) -> list[dict]:
    if not _store_available():
        return []
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """select event_id, declaration_no, line_no, customs_code,
                          event_type, qty_delta, sheet_product_code, actor,
                          notes, recorded_at
                   from co_stock_events
                   where client_id = %s and case_id = %s
                   order by recorded_at desc, event_id desc
                   limit %s""",
                (client_id, case_id, int(limit)),
            )
            cols = [d[0] for d in cur.description]
            return [_row_to_dict(cols, row) for row in cur.fetchall()]
    except DatabaseUnavailable:
        return []
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock_events events_for_case failed: %s", exc)
        return []


CLAIM_EVENT_TYPES = {"claim_lock", "claim_release"}


def _event_effect(ev: dict) -> Decimal:
    """One event's effect on remaining tồn, matching the modal's display
    convention: a Lock consumes the lot (−qty), a Release returns it (+qty),
    an adjustment moves it by Δopening − Δused. Mirrors the raw modal's
    `effectOf` so folded net and per-event walk stay consistent.
    """
    if ev.get("event_type") in CLAIM_EVENT_TYPES:
        return -(_decimal_or_none(ev.get("qty_delta")) or Decimal("0"))
    opening_after = _decimal_or_none(ev.get("opening_qty_after")) or Decimal("0")
    opening_before = _decimal_or_none(ev.get("opening_qty_before")) or Decimal("0")
    qty_delta = _decimal_or_none(ev.get("qty_delta")) or Decimal("0")
    return (opening_after - opening_before) - qty_delta


def fold_lot_events(events: list[dict]) -> list[dict]:
    """Collapse a lot's raw event log (newest-first) into one row per claim
    stream — keyed by (case_id, sheet_product_code) — so the
    chốt→mở-chốt→chốt churn reads as a single net holding instead of N noisy
    rows.

    Each claim group nets the per-event effects: a still-holding stream shows a
    negative net (= held qty, status "holding"); a fully released one nets to 0
    (status "released"). Non-claim events (manual workbook adjustments) carry no
    case identity and are passed through as singleton groups so their detail
    survives. Order follows newest activity first, matching the raw modal.

    Display-only: the underlying `co_stock_events` rows are untouched — the raw
    log is still served via the same response for the "Chi tiết" toggle.
    """
    groups: dict = {}
    order: list = []
    for ev in events:
        etype = ev.get("event_type") or ""
        case_id = (ev.get("case_id") or "").strip()
        sheet = (ev.get("sheet_product_code") or "").strip()
        if etype in CLAIM_EVENT_TYPES and case_id:
            key = ("claim", case_id, sheet)
        else:
            # Adjustments / un-attributed events keep one row each.
            key = ("event", ev.get("event_id") or len(order))
        grp = groups.get(key)
        if grp is None:
            grp = {
                "kind": "claim" if key[0] == "claim" else etype,
                "case_id": case_id,
                "sheet_product_code": sheet,
                "_net": Decimal("0"),
                "event_count": 0,
                "lock_count": 0,
                "release_count": 0,
                "latest_at": ev.get("recorded_at") or "",
                "earliest_at": ev.get("recorded_at") or "",
                "actor": ev.get("actor") or "",
                "notes": ev.get("notes") or "",
                "source_file_ref": ev.get("source_file_ref") or "",
                "batch_id": ev.get("batch_id") or "",
            }
            groups[key] = grp
            order.append(key)
        grp["_net"] += _event_effect(ev)
        grp["event_count"] += 1
        if etype == "claim_lock":
            grp["lock_count"] += 1
        elif etype == "claim_release":
            grp["release_count"] += 1
        recorded = ev.get("recorded_at") or ""
        if recorded:
            if not grp["latest_at"] or recorded > grp["latest_at"]:
                grp["latest_at"] = recorded
            if not grp["earliest_at"] or recorded < grp["earliest_at"]:
                grp["earliest_at"] = recorded
    out = []
    for key in order:
        grp = groups[key]
        net = grp.pop("_net")
        if grp["kind"] == "claim":
            if net < 0:
                grp["status"] = "holding"
                grp["held_qty"] = str(-net)
            elif net == 0:
                grp["status"] = "released"
                grp["held_qty"] = "0"
            else:
                # Net positive shouldn't happen (more released than locked); flag
                # rather than hide it.
                grp["status"] = "anomaly"
                grp["held_qty"] = "0"
        else:
            grp["status"] = ""
            grp["held_qty"] = ""
        grp["net_delta"] = str(net)
        out.append(grp)
    return out


def _row_to_dict(cols: list[str], row: tuple) -> dict:
    out: dict = {}
    for col, value in zip(cols, row):
        if isinstance(value, datetime):
            out[col] = value.isoformat()
        elif isinstance(value, Decimal):
            out[col] = str(value)
        else:
            out[col] = value
    return out
