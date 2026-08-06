"""Batched claim-summary probe parity — `claims_summary_for_cases`.

The case-list index used to call `claims_summary_for_case` once per dossier
(N+1 on the index page). `claims_summary_for_cases` folds those into one query.
This suite proves the batched result equals calling the single-case probe N
times, for the same client + claim data.

Two layers of coverage:
- File-mode (always runs): monkeypatches `_connect`/`_ledger_available` with an
  in-memory fake cursor that emulates the count / count-distinct aggregation, so
  the mapping, defaulting, and per-case shape are exercised without a database.
  Coverage gap: the fake reproduces the aggregation semantics, not the literal
  Postgres SQL (`any(%s)` + `group by`).
- DB-mode (skips without BARRY_DATABASE_URL): seeds real claims via
  `record_sheet_lock` and compares batched vs single through the real SQL.
"""
from __future__ import annotations

import pytest

from app import co_stock_ledger

CLIENT = "zzz-claims-batch"


# --- in-memory fake DB (file-mode) ------------------------------------------

class _FakeCursor:
    def __init__(self, rows: list[dict], stats: dict):
        self._rows = rows
        self._stats = stats
        self._result: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params):
        norm = " ".join(sql.split()).lower()
        self._stats["executes"] += 1
        if "group by case_id" in norm:
            client_id, ids = params
            wanted = set(ids)
            groups: dict[str, dict] = {}
            for r in self._rows:
                if (
                    r["client_id"] == client_id
                    and r["status"] == "locked"
                    and r["case_id"] in wanted
                ):
                    g = groups.setdefault(r["case_id"], {"count": 0, "lots": set()})
                    g["count"] += 1
                    g["lots"].add(r["source_row"])
            self._result = [
                (cid, g["count"], len(g["lots"])) for cid, g in groups.items()
            ]
        else:
            client_id, case_id = params
            count = 0
            lots: set = set()
            for r in self._rows:
                if (
                    r["client_id"] == client_id
                    and r["status"] == "locked"
                    and r["case_id"] == case_id
                ):
                    count += 1
                    lots.add(r["source_row"])
            self._result = [(count, len(lots))]

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)


class _FakeConn:
    def __init__(self, rows: list[dict], stats: dict):
        self._rows = rows
        self._stats = stats

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        self._stats["cursors"] += 1
        return _FakeCursor(self._rows, self._stats)


def _claim(case_id: str, source_row: str, *, status: str = "locked", client: str = CLIENT):
    return {"client_id": client, "case_id": case_id, "source_row": source_row, "status": status}


@pytest.fixture
def fake_ledger(monkeypatch):
    rows: list[dict] = []
    stats = {"cursors": 0, "executes": 0}
    monkeypatch.setattr(co_stock_ledger, "_ledger_available", lambda: True)
    monkeypatch.setattr(co_stock_ledger, "_connect", lambda: _FakeConn(rows, stats))
    return rows, stats


def test_batched_matches_single_per_case(fake_ledger):
    rows, _ = fake_ledger
    # caseA: 3 claims across 2 distinct lots; caseB: 1 claim, 1 lot;
    # caseC: only a released claim (not locked) → zero; caseD: no rows at all.
    rows += [
        _claim("caseA", "lot1"),
        _claim("caseA", "lot1"),
        _claim("caseA", "lot2"),
        _claim("caseB", "lot9"),
        _claim("caseC", "lot3", status="released"),
    ]
    ids = ["caseA", "caseB", "caseC", "caseD"]

    batched = co_stock_ledger.claims_summary_for_cases(CLIENT, ids)

    assert batched["caseA"] == {"count": 3, "lots": 2}
    assert batched["caseB"] == {"count": 1, "lots": 1}
    assert batched["caseC"] == {"count": 0, "lots": 0}
    assert batched["caseD"] == {"count": 0, "lots": 0}
    for cid in ids:
        assert batched[cid] == co_stock_ledger.claims_summary_for_case(CLIENT, cid)


def test_batched_is_single_round_trip(fake_ledger):
    rows, stats = fake_ledger
    rows += [_claim("c1", "l1"), _claim("c2", "l2"), _claim("c3", "l3")]
    co_stock_ledger.claims_summary_for_cases(CLIENT, ["c1", "c2", "c3"])
    assert stats["cursors"] == 1
    assert stats["executes"] == 1


def test_every_requested_id_is_a_key_including_duplicates_and_blanks(fake_ledger):
    rows, _ = fake_ledger
    rows += [_claim("c1", "l1")]
    out = co_stock_ledger.claims_summary_for_cases(CLIENT, ["c1", "c1", "", "missing"])
    assert set(out) == {"c1", "", "missing"}
    assert out["c1"] == {"count": 1, "lots": 1}
    assert out[""] == {"count": 0, "lots": 0}
    assert out["missing"] == {"count": 0, "lots": 0}


def test_other_client_claims_do_not_leak(fake_ledger):
    rows, _ = fake_ledger
    rows += [_claim("c1", "l1"), _claim("c1", "l2", client="other-client")]
    out = co_stock_ledger.claims_summary_for_cases(CLIENT, ["c1"])
    assert out["c1"] == {"count": 1, "lots": 1}


def test_empty_case_ids_returns_empty(fake_ledger):
    _, stats = fake_ledger
    assert co_stock_ledger.claims_summary_for_cases(CLIENT, []) == {}
    assert stats["cursors"] == 0  # no DB round trip for an empty request


def test_ledger_unavailable_defaults_all_and_matches_single(monkeypatch):
    # No DB configured → both probes no-op to the zero default, per case.
    monkeypatch.setattr(co_stock_ledger, "_ledger_available", lambda: False)
    ids = ["c1", "c2"]
    out = co_stock_ledger.claims_summary_for_cases(CLIENT, ids)
    assert out == {"c1": {"count": 0, "lots": 0}, "c2": {"count": 0, "lots": 0}}
    for cid in ids:
        assert out[cid] == co_stock_ledger.claims_summary_for_case(CLIENT, cid)


# --- real SQL parity (DB-mode; skips in file-mode) --------------------------

def _require_db():
    from app.database import database_url

    if not database_url():
        pytest.skip("needs BARRY_DATABASE_URL (DB-backed SQL parity test)")


def test_batched_matches_single_against_real_sql():
    _require_db()
    from app.database import connect

    cases = ["caseA", "caseB", "caseC"]
    lots = ["LOT-BATCH-1", "LOT-BATCH-2"]

    def _cleanup():
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from co_stock_claims where client_id = %s", (CLIENT,))
            cur.execute("delete from co_stock_rows where client_id = %s", (CLIENT,))
            cur.execute("delete from co_cases where client_id = %s", (CLIENT,))

    _cleanup()
    try:
        with connect() as conn, conn.cursor() as cur:
            for cid in cases:
                cur.execute(
                    "insert into co_cases (client_id, case_id, payload) values (%s, %s, %s)",
                    (CLIENT, cid, "{}"),
                )
            for lot in lots:
                cur.execute(
                    "insert into co_stock_rows (client_id, source_row, remaining_qty, payload) "
                    "values (%s, %s, %s, %s)",
                    (CLIENT, lot, "1000", "{}"),
                )
        # caseA: two lots; caseB: one lot; caseC: no claims.
        co_stock_ledger.record_sheet_lock(
            CLIENT, "caseA", "P1",
            [
                {"source_row": lots[0], "claimed_qty": "5", "declaration_no": "D1", "line_no": "1", "customs_code": "C1"},
                {"source_row": lots[1], "claimed_qty": "3", "declaration_no": "D1", "line_no": "2", "customs_code": "C2"},
            ],
        )
        co_stock_ledger.record_sheet_lock(
            CLIENT, "caseB", "P1",
            [
                {"source_row": lots[0], "claimed_qty": "2", "declaration_no": "D2", "line_no": "1", "customs_code": "C1"},
            ],
        )

        ids = cases + ["caseD-absent"]
        batched = co_stock_ledger.claims_summary_for_cases(CLIENT, ids)
        for cid in ids:
            assert batched[cid] == co_stock_ledger.claims_summary_for_case(CLIENT, cid)
    finally:
        _cleanup()
