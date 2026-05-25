"""CO stock ledger — Postgres-backed claim tracking across cases.

Design (2026-05-13):
- BCCT (Data Hub) owns *available_qty* per lot — read-only for CO.
- This ledger owns *consumption events* — every locked sheet allocation writes
  one claim per lot; unlock releases. Without this, two cases touching the same
  lot would over-claim because every read recomputes from raw BCCT.
- Per Data Hub docstring (`routes/api.py:332`), `co_stock.lot_policy` and
  `allocation_code.*` live in CO; consumption tracking belongs here too.

Storage: Postgres table `co_stock_claims` (migration 007) — indexed on
`(client_id, source_row, status)` so per-lot lookups are O(claims-per-lot)
not O(all-claims). When `BARRY_DATABASE_URL` is not configured (e.g., in
unit tests), all functions silently no-op so callers don't have to branch.
"""
from __future__ import annotations

import hashlib
import logging
from decimal import Decimal, InvalidOperation
from typing import Iterable

from app import co_stock_events_store
from app.database import DatabaseUnavailable, connect, database_url

LOGGER = logging.getLogger(__name__)


def _ledger_available() -> bool:
    return bool(database_url())


def _connect():
    return connect()


def claim_id_for(case_id: str, sheet_product_code: str, source_row: str, material_index: int) -> str:
    raw = f"{case_id}|{sheet_product_code}|{source_row}|{material_index}".encode("utf-8")
    return "claim_" + hashlib.sha256(raw).hexdigest()[:16]


def _normalize_qty(value) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def record_sheet_lock(
    client_id: str,
    case_id: str,
    sheet_product_code: str,
    allocations: Iterable[dict],
) -> int:
    """Mark all allocations from a sheet as locked. Returns count written.

    Idempotent: re-locking the same sheet replaces prior claims for it. Safe
    to call from any code path that transitions a sheet into the "locked"
    state — multiple calls collapse to one row per (case, sheet, source_row,
    material_index).
    """
    if not _ledger_available():
        return 0
    rows: list[tuple] = []
    new_allocs_by_claim: dict[str, dict] = {}
    for alloc in allocations:
        source_row = str(alloc.get("source_row") or "").strip()
        if not source_row:
            continue
        qty = _normalize_qty(alloc.get("claimed_qty"))
        if qty <= 0:
            continue
        cid = claim_id_for(case_id, sheet_product_code, source_row, int(alloc.get("material_index") or 0))
        decl_no = str(alloc.get("declaration_no") or "").strip()
        line_no = str(alloc.get("line_no") or "").strip()
        customs_code = str(alloc.get("customs_code") or "").strip()
        rows.append((
            cid,
            client_id,
            case_id,
            sheet_product_code,
            source_row,
            str(alloc.get("material_code") or "").strip(),
            int(alloc.get("material_index") or 0),
            qty,
            "locked",
            decl_no,
            line_no,
            customs_code,
        ))
        new_allocs_by_claim[cid] = {
            "qty": qty,
            "declaration_no": decl_no,
            "line_no": line_no,
            "customs_code": customs_code,
        }
    prior_claims: list[tuple] = []
    try:
        with _connect() as conn, conn.cursor() as cur:
            # Snapshot prior claims so we can emit release events for any that
            # get replaced (re-lock of an already-locked sheet).
            cur.execute(
                """select claim_id, declaration_no, line_no, customs_code, claimed_qty
                   from co_stock_claims
                   where client_id = %s and case_id = %s and sheet_product_code = %s
                     and status = 'locked'""",
                (client_id, case_id, sheet_product_code),
            )
            prior_claims = cur.fetchall()
            # Replace any prior claims for this case+sheet so the active
            # allocation set is exactly what the sheet currently holds.
            cur.execute(
                """delete from co_stock_claims
                   where client_id = %s and case_id = %s and sheet_product_code = %s""",
                (client_id, case_id, sheet_product_code),
            )
            if rows:
                cur.executemany(
                    """insert into co_stock_claims (
                        claim_id, client_id, case_id, sheet_product_code,
                        source_row, material_code, material_index, claimed_qty, status,
                        declaration_no, line_no, customs_code
                       ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       on conflict (claim_id) do update set
                         claimed_qty = excluded.claimed_qty,
                         material_code = excluded.material_code,
                         material_index = excluded.material_index,
                         status = 'locked',
                         locked_at = now(),
                         released_at = null,
                         declaration_no = excluded.declaration_no,
                         line_no = excluded.line_no,
                         customs_code = excluded.customs_code""",
                    rows,
                )
    except DatabaseUnavailable:
        return 0
    except Exception as exc:  # noqa: BLE001 — never block the lock action
        LOGGER.warning("co_stock_ledger lock failed for %s/%s/%s: %s", client_id, case_id, sheet_product_code, exc)
        return 0

    # Emit audit events outside the lock transaction.
    event_rows: list[dict] = []
    for claim_id, decl_no, line_no, customs_code, claimed_qty in prior_claims:
        if not (decl_no and line_no and customs_code):
            continue
        new_info = new_allocs_by_claim.get(claim_id)
        # Skip release events for claims whose key didn't change (re-lock with
        # same allocation is a no-op from the audit perspective).
        if new_info and (
            new_info["declaration_no"] == decl_no
            and new_info["line_no"] == line_no
            and new_info["customs_code"] == customs_code
            and new_info["qty"] == Decimal(str(claimed_qty))
        ):
            continue
        event_rows.append({
            "client_id": client_id,
            "declaration_no": decl_no,
            "line_no": line_no,
            "customs_code": customs_code,
            "event_type": "claim_release",
            "qty_delta": -Decimal(str(claimed_qty)),
            "case_id": case_id,
            "sheet_product_code": sheet_product_code,
            "actor": "ledger:relock",
            "notes": "Replaced by re-lock",
        })
    for claim_id, alloc in new_allocs_by_claim.items():
        if not (alloc["declaration_no"] and alloc["line_no"] and alloc["customs_code"]):
            continue
        # Skip lock events for claims that exactly match a prior claim (re-lock
        # of identical allocation).
        prior = next((p for p in prior_claims if p[0] == claim_id), None)
        if prior and prior[1] == alloc["declaration_no"] and prior[2] == alloc["line_no"] \
                and prior[3] == alloc["customs_code"] and Decimal(str(prior[4])) == alloc["qty"]:
            continue
        event_rows.append({
            "client_id": client_id,
            "declaration_no": alloc["declaration_no"],
            "line_no": alloc["line_no"],
            "customs_code": alloc["customs_code"],
            "event_type": "claim_lock",
            "qty_delta": alloc["qty"],
            "case_id": case_id,
            "sheet_product_code": sheet_product_code,
            "actor": "ledger:lock",
        })
    if event_rows:
        co_stock_events_store.record_events(event_rows)
    return len(rows)


def record_sheet_release(client_id: str, case_id: str, sheet_product_code: str) -> int:
    """Mark all locked claims for the sheet as released. Returns count released."""
    if not _ledger_available():
        return 0
    released: list[tuple] = []
    try:
        with _connect() as conn, conn.cursor() as cur:
            # Snapshot the claims about to be released for the audit log.
            cur.execute(
                """select declaration_no, line_no, customs_code, claimed_qty
                   from co_stock_claims
                   where client_id = %s and case_id = %s
                     and sheet_product_code = %s and status = 'locked'""",
                (client_id, case_id, sheet_product_code),
            )
            released = cur.fetchall()
            cur.execute(
                """update co_stock_claims
                   set status = 'released', released_at = now()
                   where client_id = %s and case_id = %s
                     and sheet_product_code = %s and status = 'locked'""",
                (client_id, case_id, sheet_product_code),
            )
            count = cur.rowcount or 0
    except DatabaseUnavailable:
        return 0
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock_ledger release failed for %s/%s/%s: %s", client_id, case_id, sheet_product_code, exc)
        return 0
    event_rows: list[dict] = []
    for decl_no, line_no, customs_code, claimed_qty in released:
        if not (decl_no and line_no and customs_code):
            continue
        event_rows.append({
            "client_id": client_id,
            "declaration_no": decl_no,
            "line_no": line_no,
            "customs_code": customs_code,
            "event_type": "claim_release",
            "qty_delta": -Decimal(str(claimed_qty)),
            "case_id": case_id,
            "sheet_product_code": sheet_product_code,
            "actor": "ledger:unlock",
        })
    if event_rows:
        co_stock_events_store.record_events(event_rows)
    return count


def used_qty_by_lot(client_id: str) -> dict[str, Decimal]:
    """Return `source_row -> total locked qty` for one client.

    Hot path for substitute modal; backed by the
    `co_stock_claims_client_lot_status_idx` index for an indexed group-by.
    """
    if not _ledger_available():
        return {}
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                """select source_row, sum(claimed_qty)
                   from co_stock_claims
                   where client_id = %s and status = 'locked'
                   group by source_row""",
                (client_id,),
            )
            return {row[0]: Decimal(str(row[1])) for row in cur.fetchall()}
    except DatabaseUnavailable:
        return {}
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock_ledger used_qty_by_lot failed for %s: %s", client_id, exc)
        return {}


def claims_for_lot(client_id: str, source_row: str) -> list[dict]:
    """All locked claims against a single lot — for audit / display."""
    if not _ledger_available():
        return []
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                """select claim_id, case_id, sheet_product_code, source_row,
                          material_code, material_index, claimed_qty, status,
                          locked_at, released_at
                   from co_stock_claims
                   where client_id = %s and source_row = %s and status = 'locked'
                   order by locked_at""",
                (client_id, source_row),
            )
            return [_row_to_dict(row) for row in cur.fetchall()]
    except DatabaseUnavailable:
        return []
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock_ledger claims_for_lot failed for %s: %s", client_id, exc)
        return []


def claims_for_case(client_id: str, case_id: str) -> list[dict]:
    """All claims for a case (locked + released) — for case detail audit."""
    if not _ledger_available():
        return []
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                """select claim_id, case_id, sheet_product_code, source_row,
                          material_code, material_index, claimed_qty, status,
                          locked_at, released_at
                   from co_stock_claims
                   where client_id = %s and case_id = %s
                   order by locked_at""",
                (client_id, case_id),
            )
            return [_row_to_dict(row) for row in cur.fetchall()]
    except DatabaseUnavailable:
        return []
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("co_stock_ledger claims_for_case failed for %s/%s: %s", client_id, case_id, exc)
        return []


def _row_to_dict(row: tuple) -> dict:
    return {
        "claim_id": row[0],
        "case_id": row[1],
        "sheet_product_code": row[2],
        "source_row": row[3],
        "material_code": row[4],
        "material_index": row[5],
        "claimed_qty": str(row[6]),
        "status": row[7],
        "locked_at": row[8].isoformat() if row[8] else None,
        "released_at": row[9].isoformat() if row[9] else None,
    }


def apply_used_qty(stock_rows: list[dict], used_by_lot: dict[str, Decimal]) -> list[dict]:
    """Decorate stock rows with `used_qty` and `remaining_qty` from the ledger.

    Mutates each row in-place and returns it for chaining. `available_qty`
    stays as the BCCT raw qty; `used_qty` and `remaining_qty` reflect
    cross-case ledger state.
    """
    for row in stock_rows:
        source_row = str(row.get("source_row") or "")
        used = used_by_lot.get(source_row, Decimal("0"))
        try:
            available = Decimal(str(row.get("available_qty") or "0"))
        except (InvalidOperation, ValueError):
            available = Decimal("0")
        remaining = available - used
        if remaining < 0:
            remaining = Decimal("0")
        row["used_qty"] = str(used)
        row["remaining_qty"] = str(remaining)
        row["ledger_overclaim"] = used > available
    return stock_rows
