"""Phase 1 — over-claim race: record_sheet_lock must serialize on the lot row.

DB-backed (needs BARRY_DATABASE_URL); skips under the file-mode suite.

The over-claim invariant (Σ locked claims per lot ≤ remaining_qty) is enforced
by an availability pre-check inside record_sheet_lock. Without a row lock on
`co_stock_rows`, two concurrent locks for the same lot can both pass the check
before either commits its claim → over-claim. The fix adds
`SELECT ... FROM co_stock_rows ... FOR UPDATE` so any concurrent claimer (or the
materializer rewriting remaining_qty) serializes on the same lot row.

This test proves serialization deterministically: an outside transaction holds
`FOR UPDATE` on the lot row; a concurrent record_sheet_lock must BLOCK until that
transaction commits. Before the fix it does not block (race window open).
"""
from __future__ import annotations

import threading

import pytest

from app.database import connect, database_url

TESTCLIENT = "zzz-forupdate-race"
LOT = "LOT-RACE-1"


def _require_db():
    if not database_url():
        pytest.skip("needs BARRY_DATABASE_URL (DB-backed concurrency test)")


CASE = "caseB"


def _cleanup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from co_stock_claims where client_id = %s", (TESTCLIENT,))
        cur.execute("delete from co_stock_events where client_id = %s", (TESTCLIENT,))
        cur.execute("delete from co_stock_rows where client_id = %s", (TESTCLIENT,))
        cur.execute("delete from co_cases where client_id = %s", (TESTCLIENT,))


@pytest.fixture
def seeded_lot():
    _require_db()
    _cleanup()
    with connect() as conn, conn.cursor() as cur:
        # co_stock_claims has an ON DELETE CASCADE FK to co_cases (migration 016),
        # so the claimed case must exist before record_sheet_lock can insert.
        cur.execute(
            "insert into co_cases (client_id, case_id, payload) values (%s, %s, %s)",
            (TESTCLIENT, CASE, "{}"),
        )
        cur.execute(
            "insert into co_stock_rows (client_id, source_row, remaining_qty, payload) "
            "values (%s, %s, %s, %s)",
            (TESTCLIENT, LOT, "100", "{}"),
        )
    yield
    _cleanup()


def test_record_sheet_lock_serializes_on_lot_row(seeded_lot):
    from app import co_stock_ledger

    # An outside transaction holds FOR UPDATE on the lot row.
    hold = connect()
    hold_cur = hold.cursor()
    hold_cur.execute(
        "select 1 from co_stock_rows where client_id = %s and source_row = %s for update",
        (TESTCLIENT, LOT),
    )
    hold_cur.fetchall()

    done = threading.Event()
    captured: dict = {}

    def worker():
        try:
            co_stock_ledger.record_sheet_lock(
                TESTCLIENT,
                CASE,
                "P1",
                [{
                    "source_row": LOT,
                    "claimed_qty": "10",
                    "declaration_no": "D1",
                    "line_no": "1",
                    "customs_code": "C1",
                }],
            )
        except Exception as exc:  # noqa: BLE001
            captured["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    # With the FOR UPDATE fix, the worker blocks on the held row lock.
    blocked = not done.wait(timeout=1.5)
    try:
        assert blocked, "record_sheet_lock did not serialize on the lot row — over-claim window open"
    finally:
        hold.commit()  # release the lock so the worker can finish either way
        hold.close()

    assert done.wait(timeout=5.0), "worker did not finish after the lock was released"
    assert "error" not in captured, f"worker raised: {captured.get('error')!r}"

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select coalesce(sum(claimed_qty), 0) from co_stock_claims "
            "where client_id = %s and status = 'locked'",
            (TESTCLIENT,),
        )
        assert cur.fetchone()[0] == 10
