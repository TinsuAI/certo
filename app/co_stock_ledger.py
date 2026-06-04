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
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Iterable

from app import co_stock_events_store
from app.database import DatabaseUnavailable, connect, database_url

LOGGER = logging.getLogger(__name__)


class StockOverclaimError(Exception):
    """Raised when a lock would push one or more lots past their available qty.

    `violations` is a list of dicts: source_row, claimed, available,
    bcct_remaining, other_claims (all qty fields are pre-stringified Decimals).
    """

    def __init__(self, violations: list[dict]):
        self.violations = list(violations)
        summary = "; ".join(
            f"{v.get('source_row', '?')} (cần {v.get('claimed', '?')}, còn {v.get('available', '?')})"
            for v in self.violations[:5]
        )
        super().__init__(f"Vượt tồn ở {len(self.violations)} lot: {summary}")


def _ledger_available() -> bool:
    return bool(database_url())


def _connect():
    return connect()


def claim_id_for(
    case_id: str,
    sheet_product_code: str,
    source_row: str,
    material_code: str = "",
    material_index: int = 0,
) -> str:
    """Stable identity for a consumption claim.

    Keyed on the material *code*, not its position in the sheet, so reordering
    the BOM doesn't change the id of a physically-identical claim (which used to
    churn the audit log and break re-lock no-op detection). Falls back to the
    positional index only when the material has no code, so unnamed materials on
    the same lot still get distinct ids.
    """
    material_key = (material_code or "").strip() or f"#{int(material_index or 0)}"
    raw = f"{case_id}|{sheet_product_code}|{source_row}|{material_key}".encode("utf-8")
    return "claim_" + hashlib.sha256(raw).hexdigest()[:16]


def _build_claim_rows(
    client_id: str,
    case_id: str,
    sheet_product_code: str,
    allocations: Iterable[dict],
) -> tuple[list[tuple], dict[str, dict], dict[str, Decimal]]:
    """Aggregate allocations into one claim row per stable claim_id.

    Two allocation lines that resolve to the same claim_id (same case, sheet,
    lot, material) are summed rather than overwritten — a stable claim_id makes
    split/duplicate BOM lines collide on purpose, and the lot only cares about
    total qty consumed. Returns (rows, new_allocs_by_claim, new_by_lot) where
    `rows` matches the INSERT column order in record_sheet_lock.
    """
    by_claim: dict[str, dict] = {}
    new_by_lot: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for alloc in allocations:
        source_row = str(alloc.get("source_row") or "").strip()
        if not source_row:
            continue
        qty = _normalize_qty(alloc.get("claimed_qty"))
        if qty <= 0:
            continue
        material_code = str(alloc.get("material_code") or "").strip()
        material_index = int(alloc.get("material_index") or 0)
        cid = claim_id_for(case_id, sheet_product_code, source_row, material_code, material_index)
        existing = by_claim.get(cid)
        if existing:
            existing["qty"] += qty
        else:
            by_claim[cid] = {
                "qty": qty,
                "source_row": source_row,
                "material_code": material_code,
                "material_index": material_index,
                "declaration_no": str(alloc.get("declaration_no") or "").strip(),
                "line_no": str(alloc.get("line_no") or "").strip(),
                "customs_code": str(alloc.get("customs_code") or "").strip(),
            }
        new_by_lot[source_row] += qty
    rows = [
        (
            cid,
            client_id,
            case_id,
            sheet_product_code,
            c["source_row"],
            c["material_code"],
            c["material_index"],
            c["qty"],
            "locked",
            c["declaration_no"],
            c["line_no"],
            c["customs_code"],
        )
        for cid, c in by_claim.items()
    ]
    new_allocs_by_claim = {
        cid: {
            "qty": c["qty"],
            "declaration_no": c["declaration_no"],
            "line_no": c["line_no"],
            "customs_code": c["customs_code"],
        }
        for cid, c in by_claim.items()
    }
    return rows, new_allocs_by_claim, new_by_lot


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

    Raises:
        StockOverclaimError: if any source_row would be claimed past
            (co_stock_rows.remaining_qty - sum_of_other_active_claims). The
            full transaction is aborted; no claims are written.
        DatabaseUnavailable is treated as a no-op so unit tests that don't
            configure BARRY_DATABASE_URL keep working. All other database
            errors propagate to the caller — silent failure would let the
            sheet appear locked while the ledger has no claim, which would
            in turn let other cases over-claim the same lots.
    """
    if not _ledger_available():
        return 0
    rows, new_allocs_by_claim, new_by_lot = _build_claim_rows(
        client_id, case_id, sheet_product_code, allocations
    )
    prior_claims: list[tuple] = []
    try:
        with _connect() as conn, conn.cursor() as cur:
            # Availability pre-check: for each distinct source_row we're about
            # to claim, look up the materialized remaining_qty — which is now
            # the trừ-lùi-FOLDED tồn (opening − agency "Đã xuất"), not raw BCCT —
            # and subtract all OTHER active claims (excluding this case+sheet
            # since we replace those below). Abort if any lot would go negative.
            # Folding the adjustment baseline into remaining_qty is what closes
            # the old gap where a lot the agency marked fully-consumed could
            # still be over-claimed here.
            #
            # If the client has NO materialized snapshot at all (e.g. a fresh
            # workspace or a unit test that bypasses /refresh), we can't
            # validate against BCCT here — skip the check and trust the
            # allocator's calculate-time check. We do NOT skip the check for
            # individual missing source_rows when a snapshot exists: an
            # allocation referencing a lot that's not in the snapshot is a
            # legitimate violation (the lot doesn't exist or was filtered out).
            if new_by_lot:
                cur.execute(
                    "select exists(select 1 from co_stock_rows where client_id = %s)",
                    (client_id,),
                )
                snapshot_exists = bool(cur.fetchone()[0])
                if snapshot_exists:
                    source_rows = list(new_by_lot.keys())
                    cur.execute(
                        r"""select s.source_row,
                                   case when s.remaining_qty ~ '^-?\d+(\.\d+)?$'
                                        then s.remaining_qty::numeric else 0::numeric end,
                                   coalesce(sum(case
                                     when c.status = 'locked'
                                       and not (c.case_id = %s and c.sheet_product_code = %s)
                                     then c.claimed_qty else 0::numeric
                                   end), 0::numeric)
                              from co_stock_rows s
                              left join co_stock_claims c
                                on c.client_id = s.client_id and c.source_row = s.source_row
                             where s.client_id = %s and s.source_row = any(%s)
                             group by s.source_row, s.remaining_qty""",
                        (case_id, sheet_product_code, client_id, source_rows),
                    )
                    availability = {
                        row[0]: (Decimal(str(row[1])), Decimal(str(row[2])))
                        for row in cur.fetchall()
                    }
                    violations: list[dict] = []
                    for source_row, claimed in new_by_lot.items():
                        if source_row not in availability:
                            violations.append({
                                "source_row": source_row,
                                "claimed": str(claimed),
                                "available": "0",
                                "bcct_remaining": "lot không có trong snapshot",
                                "other_claims": "0",
                            })
                            continue
                        bcct_remaining, other_claims = availability[source_row]
                        net = bcct_remaining - other_claims
                        if claimed > net:
                            violations.append({
                                "source_row": source_row,
                                "claimed": str(claimed),
                                "available": str(net),
                                "bcct_remaining": str(bcct_remaining),
                                "other_claims": str(other_claims),
                            })
                    if violations:
                        raise StockOverclaimError(violations)

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
    """Mark all locked claims for the sheet as released. Returns count released.

    DatabaseUnavailable is treated as a no-op for unit tests. Other database
    errors propagate so the caller can keep the sheet locked (consistent
    with the ledger still holding the claim) instead of silently leaking it.
    """
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


def claims_summary_for_case(client_id: str, case_id: str) -> dict:
    """Quick probe: how many locked claims + distinct lots for a case.

    Used by the delete-case flow to (a) decide whether to require explicit
    operator confirmation, and (b) show a concrete count in the warning
    modal so the operator knows what's about to be released.
    """
    if not _ledger_available():
        return {"count": 0, "lots": 0}
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                """select count(*), count(distinct source_row)
                   from co_stock_claims
                   where client_id = %s and case_id = %s and status = 'locked'""",
                (client_id, case_id),
            )
            count, lots = cur.fetchone()
            return {"count": int(count or 0), "lots": int(lots or 0)}
    except DatabaseUnavailable:
        return {"count": 0, "lots": 0}


def release_all_claims_for_case(client_id: str, case_id: str) -> int:
    """Release every locked claim belonging to a case, across all sheets.

    Used by `delete_case_record` so deleting a case never leaves orphan
    `co_stock_claims` rows pointing at a dead `case_id` (audit gap HIGH #2).
    Identical semantics to `record_sheet_release` but unscoped per-sheet —
    a single DB round trip touches every sheet of the case at once.
    """
    if not _ledger_available():
        return 0
    released: list[tuple] = []
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                """select sheet_product_code, declaration_no, line_no,
                          customs_code, claimed_qty
                   from co_stock_claims
                   where client_id = %s and case_id = %s and status = 'locked'""",
                (client_id, case_id),
            )
            released = cur.fetchall()
            cur.execute(
                """update co_stock_claims
                   set status = 'released', released_at = now()
                   where client_id = %s and case_id = %s and status = 'locked'""",
                (client_id, case_id),
            )
            count = cur.rowcount or 0
    except DatabaseUnavailable:
        return 0
    event_rows: list[dict] = []
    for sheet_code, decl_no, line_no, customs_code, claimed_qty in released:
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
            "sheet_product_code": sheet_code,
            "actor": "ledger:case_delete",
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


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def apply_used_qty(stock_rows: list[dict], used_by_lot: dict[str, Decimal]) -> list[dict]:
    """Overlay LIVE ledger claims onto already-folded stock rows.

    This is the single read-time stock derivation. The static layers (BCCT
    opening + manual trừ-lùi adjustments) are folded into the materialized
    snapshot ahead of time, so each row carries:
      - opening_qty:        effective opening (BCCT qty, or trừ-lùi override)
      - baseline_used_qty:  trừ-lùi "Đã xuất" already consumed off-app
    and this function adds only the cross-case ledger locks. It decorates each
    row (in-place) with:
      - used_qty:            baseline_used_qty + live ledger locks
      - remaining_signed_qty: opening_qty - used_qty (may be negative)
      - remaining_qty:       max(0, remaining_signed_qty) — clamped for display
      - ledger_overclaim:    True when the signed remaining is negative

    Backward compatible with un-folded rows (file-mode / demo fixtures): when
    opening_qty / baseline_used_qty are absent it falls back to available_qty
    with a zero baseline, matching the legacy `available - ledger` behaviour.
    """
    for row in stock_rows:
        source_row = str(row.get("source_row") or "")
        ledger_used = used_by_lot.get(source_row, Decimal("0"))
        baseline_used = _dec(row.get("baseline_used_qty"))
        opening = _dec(row.get("opening_qty") if row.get("opening_qty") not in (None, "")
                       else row.get("available_qty"))
        used_total = baseline_used + ledger_used
        remaining_signed = opening - used_total
        row["used_qty"] = str(used_total)
        row["remaining_signed_qty"] = str(remaining_signed)
        row["remaining_qty"] = str(remaining_signed if remaining_signed > 0 else Decimal("0"))
        row["ledger_overclaim"] = remaining_signed < 0
    return stock_rows
