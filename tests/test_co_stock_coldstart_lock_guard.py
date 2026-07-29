"""Cold-start over-claim hole (Fix F / D2): record_sheet_lock must BLOCK when
the client has NO materialized CO stock snapshot (0 rows in co_stock_rows).

The commit-time over-claim guard lives inside `if snapshot_exists:` and takes a
`FOR UPDATE` lock on the co_stock_rows lot row. When no snapshot exists there is
no row to lock and nothing to validate against, so the old code SKIPPED the
check and trusted the allocator's calculate-time check — but calculate holds no
row lock, so two dossiers for the same company could both lock and over-claim
the same lot. The fix raises StockSnapshotMissingError instead of skipping.

DB-backed suites (test_co_stock_lock_concurrency, test_recalc_lock_parity_db)
need BARRY_DATABASE_URL and skip in file-mode. This test runs in FILE-MODE by
substituting a fake connection so the DB branch executes without a real
Postgres, proving both the cold-start block and the snapshot-exists path.
"""
from __future__ import annotations

import pytest

from app import co_stock_ledger


class _FakeCursor:
    """Minimal psycopg-cursor stand-in driven by SQL substring matching."""

    def __init__(self, snapshot_exists: bool, availability_rows):
        self._snapshot_exists = snapshot_exists
        self._availability_rows = availability_rows
        self._last = ""
        self.executed: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._last = " ".join(str(sql).lower().split())
        self.executed.append(self._last)

    def executemany(self, sql, rows):
        self.executed.append("executemany")

    def fetchone(self):
        if "exists" in self._last:
            return (self._snapshot_exists,)
        return None

    def fetchall(self):
        if "group by" in self._last:
            return list(self._availability_rows)
        # prior-claims select and everything else: no rows.
        return []


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self._cursor


def _alloc(qty="10", customs_code=""):
    # customs_code left empty so no audit events are emitted (record_events only
    # fires when declaration_no + line_no + customs_code are all present),
    # keeping the test off the co_stock_events_store DB path.
    return [{
        "source_row": "LOT-1",
        "material_code": "MATX",
        "material_index": 0,
        "claimed_qty": qty,
        "declaration_no": "D1",
        "line_no": "1",
        "customs_code": customs_code,
    }]


def _patch(monkeypatch, *, snapshot_exists, availability_rows=None):
    cur = _FakeCursor(snapshot_exists, availability_rows or [])
    monkeypatch.setattr(co_stock_ledger, "_ledger_available", lambda: True)
    monkeypatch.setattr(co_stock_ledger, "_connect", lambda: _FakeConn(cur))
    return cur


def test_cold_start_lock_is_blocked(monkeypatch):
    cur = _patch(monkeypatch, snapshot_exists=False)
    with pytest.raises(co_stock_ledger.StockSnapshotMissingError) as exc:
        co_stock_ledger.record_sheet_lock("cli", "case1", "P1", _alloc())
    assert exc.value.client_id == "cli"
    assert "LOT-1" in exc.value.source_rows
    assert "Refresh" in str(exc.value)
    # No write happened: only the existence probe ran, no delete/insert.
    assert not any("delete from co_stock_claims" in q for q in cur.executed)
    assert "executemany" not in cur.executed


def test_snapshot_exists_path_still_locks(monkeypatch):
    # Lot holds 100, other claims 0 → claiming 10 is fine and persists one claim.
    cur = _patch(
        monkeypatch,
        snapshot_exists=True,
        availability_rows=[("LOT-1", "100", "0")],
    )
    written = co_stock_ledger.record_sheet_lock("cli", "case1", "P1", _alloc(qty="10"))
    assert written == 1
    assert "executemany" in cur.executed  # the insert ran


def test_snapshot_exists_still_rejects_overclaim(monkeypatch):
    # Snapshot present but the lot only holds 5; claiming 10 must raise the
    # over-claim error — NOT the snapshot-missing error — so the normal guard
    # path is unchanged.
    _patch(
        monkeypatch,
        snapshot_exists=True,
        availability_rows=[("LOT-1", "5", "0")],
    )
    with pytest.raises(co_stock_ledger.StockOverclaimError) as exc:
        co_stock_ledger.record_sheet_lock("cli", "case1", "P1", _alloc(qty="10"))
    assert exc.value.violations[0]["source_row"] == "LOT-1"
    assert exc.value.violations[0]["available"] == "5"


def test_file_mode_no_db_is_still_a_noop(monkeypatch):
    # Ledger-unavailable (file-mode default) must keep no-op'ing — the new guard
    # only fires when the DB branch runs.
    monkeypatch.setattr(co_stock_ledger, "_ledger_available", lambda: False)
    assert co_stock_ledger.record_sheet_lock("cli", "case1", "P1", _alloc()) == 0
