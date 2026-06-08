"""DB-backed parity: the over-claim the fix prevents, proven against the REAL
ledger (co_stock_ledger.record_sheet_lock). Needs BARRY_DATABASE_URL.

A material edit makes recalculate_origin_sheet_edits re-allocate the whole
sheet. Pre-fix it allocated against RAW BCCT (remaining_qty == quantity);
post-fix against the trừ-lùi-FOLDED snapshot. record_sheet_lock validates each
claim against the FOLDED co_stock_rows.remaining_qty − other-case claims. So on
the same lot:
  - a RAW-sized claim (what pre-fix produced)  must be REJECTED, and
  - a FOLDED-sized claim (what post-fix produces) must be ACCEPTED.

This is the lock-side half of the invariant; test_recalc_stock_source_parity
backstops the allocation-side (recalc now reads the folded snapshot). Together
they prove calculate-time tồn == lock-time tồn for an edited sheet — the johnson
co-case-a4e1dbbdb0f5 / MFW0507-39 "vượt tồn ở 47 lot" regression.
"""
from __future__ import annotations

import pytest

from app.database import connect, database_url

CLIENT = "zzz-recalc-parity"
CASE = "case-parity"
SHEET = "P1"
LOT = "LOT-PARITY-1"
FOLDED_REMAINING = "10"  # trừ-lùi folded this lot down from a raw BCCT qty of 100


def _require_db():
    if not database_url():
        pytest.skip("needs BARRY_DATABASE_URL (DB-backed parity test)")


def _cleanup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from co_stock_claims where client_id=%s", (CLIENT,))
        cur.execute("delete from co_stock_events where client_id=%s", (CLIENT,))
        cur.execute("delete from co_stock_rows where client_id=%s", (CLIENT,))
        cur.execute("delete from co_cases where client_id=%s", (CLIENT,))


@pytest.fixture
def folded_lot():
    _require_db()
    _cleanup()
    with connect() as conn, conn.cursor() as cur:
        # co_stock_claims has an ON DELETE CASCADE FK to co_cases, so the case
        # must exist before record_sheet_lock can insert a claim.
        cur.execute(
            "insert into co_cases (client_id, case_id, payload) values (%s,%s,%s)",
            (CLIENT, CASE, "{}"),
        )
        cur.execute(
            "insert into co_stock_rows (client_id, source_row, remaining_qty, payload) "
            "values (%s,%s,%s,%s)",
            (CLIENT, LOT, FOLDED_REMAINING, "{}"),
        )
    yield
    _cleanup()


def _claim(qty: str) -> list[dict]:
    return [
        {
            "source_row": LOT,
            "material_code": "MATX",
            "material_index": 0,
            "claimed_qty": qty,
            "declaration_no": "D1",
            "line_no": "1",
            "customs_code": "",
        }
    ]


def test_raw_sized_claim_is_rejected_against_folded_lot(folded_lot):
    """What the PRE-FIX recalc produced: allocate against raw (100) → claim 50.
    The lock must reject it because the folded lot only holds 10."""
    from app import co_stock_ledger

    with pytest.raises(co_stock_ledger.StockOverclaimError) as exc:
        co_stock_ledger.record_sheet_lock(CLIENT, CASE, SHEET, _claim("50"))
    violation = exc.value.violations[0]
    assert violation["source_row"] == LOT
    assert violation["available"] == "10"  # folded remaining, not raw 100


def test_folded_sized_claim_locks_clean(folded_lot):
    """What the POST-FIX recalc produces: allocate against folded (10) → claim
    10. The lock accepts it and persists exactly one locked claim."""
    from app import co_stock_ledger

    written = co_stock_ledger.record_sheet_lock(CLIENT, CASE, SHEET, _claim("10"))
    assert written == 1
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select claimed_qty from co_stock_claims where client_id=%s and status='locked'",
            (CLIENT,),
        )
        rows = cur.fetchall()
    assert len(rows) == 1
