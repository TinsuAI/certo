"""D1 — delta-vs-full parity harness for the CO-stock materializer.

Backlog worry (`.ai/BACKLOG.md` D1, "Parity delta vs full"): the refresh has two
write paths — a FULL re-derivation that returns the complete snapshot, and an
incremental DELTA that returns only changed/added rows plus explicit tombstones.
The standing fear is that delta silently under/over-applies and drifts away from
full over many refreshes (SAI TỒN downstream).

This harness proves the invariant: starting from the same source data, a FULL
refresh of the FINAL state produces byte-identical materialized `co_stock_rows`
as bootstrapping the snapshot then applying the SEQUENCE of deltas that mutate
S0 into that final state.

It exercises the REAL production body of
`co_stock_materializer.refresh_co_stock_for_client` — real `_load_existing_snapshot`,
`_classify_changes`, `_plan_removed_keys`, `_upsert_records`, `_claims_blocking_removal`
and the targeted DELETE — against an in-memory stand-in for the `co_stock_rows` /
`co_stock_claims` tables. Only the psycopg driver is faked, so parity is proven for
the actual materializer, not a reimplementation of it.

A separate DB-mode test (skipped in FILE-MODE) runs the identical scenario against a
real Postgres when `BARRY_DATABASE_URL` is set.
"""
from __future__ import annotations

import os

import pytest

from app import co_stock_materializer
from app.co_stock_derivation import import_row_id
from app.co_stock_materializer import refresh_co_stock_for_client


# --------------------------------------------------------------------------
# In-memory stand-in for co_stock_rows + co_stock_claims
# --------------------------------------------------------------------------


class _FakeCoStockStore:
    """Just enough SQL surface for the materializer's read/upsert/delete/claims
    path. Keyed by (client_id, source_row) — mirrors the table's unique key."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}
        self.locked_claims: dict[str, set[str]] = {}

    def add_locked_claim(self, client_id: str, source_row: str) -> None:
        self.locked_claims.setdefault(client_id, set()).add(source_row)

    def materialized(self, client_id: str) -> dict[str, dict]:
        return {
            sr: dict(col["payload"])
            for (cid, sr), col in self.rows.items()
            if cid == client_id
        }


def _unwrap(value):
    # psycopg wraps JSONB params in Jsonb(obj); the real value is on .obj.
    return getattr(value, "obj", value)


class _FakeCursor:
    def __init__(self, store: _FakeCoStockStore) -> None:
        self.store = store
        self._result: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params=None) -> None:
        text = " ".join(sql.split()).lower()
        params = params or ()
        if text.startswith("select source_row, payload, import_declaration_no"):
            client_id = params[0]
            self._result = [
                (
                    sr,
                    dict(col["payload"]),
                    col["import_declaration_no"],
                    col["line_no"],
                    col["customs_item_code"],
                )
                for (cid, sr), col in self.store.rows.items()
                if cid == client_id
            ]
        elif text.startswith("select payload from co_stock_rows where client_id"):
            client_id = params[0]
            selected = [
                col
                for (cid, _sr), col in self.store.rows.items()
                if cid == client_id
            ]
            selected.sort(
                key=lambda c: (
                    c["import_declaration_no"],
                    c["line_no"],
                    c["customs_item_code"],
                    c["source_row"],
                )
            )
            self._result = [(dict(col["payload"]),) for col in selected]
        elif text.startswith("select count(*) from co_stock_rows"):
            client_id = params[0]
            n = sum(1 for (cid, _sr) in self.store.rows if cid == client_id)
            self._result = [(n,)]
        elif "from co_stock_claims" in text:
            client_id = params[0]
            requested = set(params[1] or [])
            locked = self.store.locked_claims.get(client_id, set())
            self._result = [(sr,) for sr in sorted(requested & locked)]
        elif text.startswith("delete from co_stock_rows"):
            client_id = params[0]
            keys = params[1] or []
            for sr in keys:
                self.store.rows.pop((client_id, sr), None)
            self._result = []
        elif text.startswith("insert into co_stock_rows"):
            self._apply_upsert(params)
            self._result = []
        else:  # pragma: no cover - the materializer issues no other query
            raise AssertionError(f"unexpected SQL in parity fake: {text[:80]}")

    def executemany(self, sql: str, seq_params) -> None:
        text = " ".join(sql.split()).lower()
        if text.startswith("insert into co_stock_rows"):
            for params in seq_params:
                self._apply_upsert(params)
            self._result = []
            return
        for params in seq_params:  # pragma: no cover - not exercised
            self.execute(sql, params)

    def _apply_upsert(self, params) -> None:
        (
            client_id,
            source_row,
            transaction_key,
            import_declaration_no,
            line_no,
            declaration_type,
            customs_item_code,
            allocation_code,
            eligibility_status,
            remaining_qty,
            payload,
        ) = params
        # dict assignment IS the ON CONFLICT DO UPDATE (overwrite) semantics.
        self.store.rows[(client_id, source_row)] = {
            "client_id": client_id,
            "source_row": source_row,
            "transaction_key": transaction_key,
            "import_declaration_no": import_declaration_no,
            "line_no": line_no,
            "declaration_type": declaration_type,
            "customs_item_code": customs_item_code,
            "allocation_code": allocation_code,
            "eligibility_status": eligibility_status,
            "remaining_qty": remaining_qty,
            "payload": _unwrap(payload),
        }

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


class _FakeConn:
    def __init__(self, store: _FakeCoStockStore) -> None:
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _FakeCursor(self.store)

    def commit(self):
        pass


@pytest.fixture()
def fake_store(monkeypatch):
    """Run the real materializer against an in-memory co_stock table."""
    store = _FakeCoStockStore()
    monkeypatch.setattr(co_stock_materializer, "_store_available", lambda: True)
    monkeypatch.setattr(co_stock_materializer, "connect", lambda *a, **k: _FakeConn(store))
    # Audit-event emission is best-effort and hits its own table; it never
    # touches the materialized rows, so stub it out to keep the fake DB minimal.
    monkeypatch.setattr(co_stock_materializer, "_emit_diff_events", lambda *a, **k: None)
    return store


# --------------------------------------------------------------------------
# Synthetic source rows (shape = output of co_stock_rows_from_bcct, line_level)
# --------------------------------------------------------------------------


def _stock_row(tk: str, *, decl_no: str, line_no: str, item_code: str, alloc: str,
               qty, status: str = "active", desc: str = "Cell") -> dict:
    """One derived CO-stock lot. `source_row` uses the SAME derivation as
    production (`import_row_id(transaction_key)`) so a tombstone built the way
    `_try_delta_refresh` builds it lands on the exact key the materializer stored."""
    sr = import_row_id(tk)
    return {
        "source_row": sr,
        "source_transaction_key": tk,
        "source_line_ids": [sr],
        "import_declaration_no": decl_no,
        "registration_date": "2026-01-15",
        "line_no": line_no,
        "declaration_type": "A11",
        "customs_item_code": item_code,
        "allocation_code": alloc,
        "allocation_code_status": "resolved",
        "eligibility_status": status,
        "remaining_qty": str(qty),
        "material_description": desc,
        "unit": "cái",
        "unit_value": "1.5",
        "exchange_rate_to_vnd": "1",
    }


def _tombstone_for(tk: str) -> str:
    """Exactly how _try_delta_refresh derives a tombstone source_row from a
    Data Hub tombstone's transaction_key."""
    import hashlib

    return f"import-row-{hashlib.sha1(str(tk).encode('utf-8')).hexdigest()[:16]}"


def _full(store, client_id: str, rows: list[dict]) -> dict:
    return refresh_co_stock_for_client({"id": client_id}, lambda: rows, mode="full")


def _delta(store, client_id: str, rows: list[dict], tombstones: list[str]) -> dict:
    return refresh_co_stock_for_client(
        {"id": client_id}, lambda: rows, mode="delta", tombstone_source_rows=tombstones
    )


def _materialized(client_id: str) -> dict[str, dict]:
    return {p["source_row"]: p for p in co_stock_materializer.read_co_stock_rows(client_id)}


# --------------------------------------------------------------------------
# Parity: full(final) == bootstrap(S0) + sequence of deltas
# --------------------------------------------------------------------------


def test_delta_sequence_matches_full_refresh(fake_store):
    """The headline invariant. S0 has 5 lots; a sequence of deltas adds two lots,
    changes three quantities, removes one via tombstone. FULL of the final state
    and BOOTSTRAP+DELTAs must materialize identical co_stock_rows."""
    a = _stock_row("TK-A", decl_no="D100", line_no="1", item_code="C1", alloc="AL-A", qty=100)
    b = _stock_row("TK-B", decl_no="D100", line_no="2", item_code="C2", alloc="AL-B", qty=10)
    c = _stock_row("TK-C", decl_no="D101", line_no="1", item_code="C3", alloc="AL-C", qty=30)
    d = _stock_row("TK-D", decl_no="D101", line_no="2", item_code="C4", alloc="AL-D", qty=40)
    e = _stock_row("TK-E", decl_no="D102", line_no="1", item_code="C5", alloc="AL-E", qty=50)
    s0 = [a, b, c, d, e]

    # Mutations expressed as deltas over S0.
    f = _stock_row("TK-F", decl_no="D103", line_no="1", item_code="C6", alloc="AL-F", qty=60)
    b2 = _stock_row("TK-B", decl_no="D100", line_no="2", item_code="C2", alloc="AL-B", qty=3)
    g = _stock_row("TK-G", decl_no="D103", line_no="2", item_code="C7", alloc="AL-G", qty=70)
    a2 = _stock_row("TK-A", decl_no="D100", line_no="1", item_code="C1", alloc="AL-A", qty=95)
    e2 = _stock_row("TK-E", decl_no="D102", line_no="1", item_code="C5", alloc="AL-E", qty=48)

    final = [a2, b2, d, e2, f, g]  # C removed

    # FULL path: derive the complete final set, refresh in full mode from empty.
    _full(fake_store, "full-client", final)

    # DELTA path: bootstrap S0 (full), then apply each delta.
    _full(fake_store, "delta-client", s0)
    _delta(fake_store, "delta-client", [f], tombstones=[])              # add F
    _delta(fake_store, "delta-client", [b2], tombstones=[])             # change B qty
    _delta(fake_store, "delta-client", [], tombstones=[_tombstone_for("TK-C")])  # remove C
    _delta(fake_store, "delta-client", [g, a2], tombstones=[])          # add G + change A
    _delta(fake_store, "delta-client", [e2], tombstones=[])             # change E qty

    full_mat = _materialized("full-client")
    delta_mat = _materialized("delta-client")

    assert set(full_mat) == set(delta_mat), "lot keys diverge between full and delta"
    assert full_mat == delta_mat, "materialized payloads diverge between full and delta"
    # Spot-check the domain-critical field explicitly.
    assert {k: v["remaining_qty"] for k, v in delta_mat.items()} == {
        import_row_id("TK-A"): "95",
        import_row_id("TK-B"): "3",
        import_row_id("TK-D"): "40",
        import_row_id("TK-E"): "48",
        import_row_id("TK-F"): "60",
        import_row_id("TK-G"): "70",
    }
    assert import_row_id("TK-C") not in delta_mat  # tombstoned lot is gone


def test_single_qty_change_delta_equals_full(fake_store):
    """A changed quantity must carry the NEW remaining_qty through delta, not a
    stale value — the classic under/over-apply drift vector."""
    row = _stock_row("TK-Q", decl_no="D200", line_no="1", item_code="Q1", alloc="AL-Q", qty=100)
    changed = _stock_row("TK-Q", decl_no="D200", line_no="1", item_code="Q1", alloc="AL-Q", qty=42)

    _full(fake_store, "full-client", [changed])

    _full(fake_store, "delta-client", [row])
    summary = _delta(fake_store, "delta-client", [changed], tombstones=[])

    assert summary["rows_updated"] == 1
    assert _materialized("full-client") == _materialized("delta-client")
    assert _materialized("delta-client")[import_row_id("TK-Q")]["remaining_qty"] == "42"


def test_tombstone_key_matches_materialized_source_row(fake_store):
    """Backlog risk: `tombstone_source_rows` hashes transaction_key — does it hit
    the `source_row` the materializer stored? If not, the DELETE misses and a
    removed lot lingers (tồn ảo). Prove the keys align by deleting through it."""
    row = _stock_row("TK-Z", decl_no="D300", line_no="1", item_code="Z1", alloc="AL-Z", qty=5)
    _full(fake_store, "c", [row])
    assert import_row_id("TK-Z") in _materialized("c")

    summary = _delta(fake_store, "c", [], tombstones=[_tombstone_for("TK-Z")])

    assert summary["rows_removed"] == 1
    assert _materialized("c") == {}, "tombstone did not match the stored source_row"


def test_remove_then_readd_churn_matches_full(fake_store):
    """The `snapshot_row_added` newer-than `snapshot_row_removed` churn pattern
    the backlog flags: a lot removed via tombstone, then re-added in a later delta
    with a new qty. Full of the final state must equal the delta churn."""
    row = _stock_row("TK-R", decl_no="D400", line_no="1", item_code="R1", alloc="AL-R", qty=20)
    readd = _stock_row("TK-R", decl_no="D400", line_no="1", item_code="R1", alloc="AL-R", qty=8)

    _full(fake_store, "full-client", [readd])  # final state: present with qty 8

    _full(fake_store, "delta-client", [row])
    _delta(fake_store, "delta-client", [], tombstones=[_tombstone_for("TK-R")])  # remove
    _delta(fake_store, "delta-client", [readd], tombstones=[])                    # re-add

    assert _materialized("full-client") == _materialized("delta-client")
    assert _materialized("delta-client")[import_row_id("TK-R")]["remaining_qty"] == "8"


def test_empty_delta_is_noop_and_preserves_snapshot(fake_store):
    """An empty delta (nothing changed upstream) must leave the snapshot intact —
    it must NOT behave like an empty full pull and wipe rows."""
    s0 = [
        _stock_row("TK-1", decl_no="D1", line_no="1", item_code="I1", alloc="AL-1", qty=1),
        _stock_row("TK-2", decl_no="D1", line_no="2", item_code="I2", alloc="AL-2", qty=2),
    ]
    _full(fake_store, "c", s0)
    before = _materialized("c")

    summary = _delta(fake_store, "c", [], tombstones=[])

    assert summary["rows_removed"] == 0
    assert _materialized("c") == before


def test_added_lot_delta_equals_full(fake_store):
    """A pure add: delta that introduces a new lot equals full re-derive that
    includes it. Classification must bucket it as added, not updated."""
    a = _stock_row("TK-A", decl_no="D1", line_no="1", item_code="I1", alloc="AL-A", qty=10)
    b = _stock_row("TK-B", decl_no="D1", line_no="2", item_code="I2", alloc="AL-B", qty=20)

    _full(fake_store, "full-client", [a, b])

    _full(fake_store, "delta-client", [a])
    summary = _delta(fake_store, "delta-client", [b], tombstones=[])

    assert summary["rows_added"] == 1
    assert _materialized("full-client") == _materialized("delta-client")


# --------------------------------------------------------------------------
# Boundary: parity is CONDITIONAL on a tombstone for every removal
# --------------------------------------------------------------------------


def test_removal_without_tombstone_diverges_by_design(fake_store):
    """Documents the drift boundary the D1 worry points at ("dòng xoá không qua
    tombstone"). If a lot is deleted upstream but Data Hub emits NO tombstone and
    NO changed row, a delta cannot know the lot is gone — it lingers. A full pull
    drops it. So delta != full HERE, and that is BY DESIGN, not a materializer bug:
    delta removal requires an explicit tombstone (the DH contract must emit one).

    This is an assertion of the CONDITION under which the parity guarantee holds,
    not a bug reproducer. The materializer's delta mode never sweeps untracked
    rows on purpose (that is what protects the incremental snapshot)."""
    a = _stock_row("TK-A", decl_no="D1", line_no="1", item_code="I1", alloc="AL-A", qty=10)
    b = _stock_row("TK-B", decl_no="D1", line_no="2", item_code="I2", alloc="AL-B", qty=20)

    # Final state after B is deleted upstream.
    _full(fake_store, "full-client", [a])

    # Delta learns nothing about B's removal (no tombstone, no changed row).
    _full(fake_store, "delta-client", [a, b])
    _delta(fake_store, "delta-client", [], tombstones=[])  # empty delta

    full_mat = _materialized("full-client")
    delta_mat = _materialized("delta-client")

    assert import_row_id("TK-B") not in full_mat
    assert import_row_id("TK-B") in delta_mat  # lingers without a tombstone
    assert full_mat != delta_mat
    # With the tombstone supplied, parity is restored:
    _delta(fake_store, "delta-client", [], tombstones=[_tombstone_for("TK-B")])
    assert _materialized("delta-client") == full_mat


# --------------------------------------------------------------------------
# DB-mode end-to-end (skipped in FILE-MODE)
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("BARRY_DATABASE_URL", "").strip(),
    reason="DB-mode parity requires BARRY_DATABASE_URL (real Postgres)",
)
def test_delta_sequence_matches_full_refresh_db_mode():
    """Identical scenario as the pure harness, but through a real Postgres so the
    ON CONFLICT upsert, ANY(%s) delete and claims join are exercised for real.
    Uses unique client ids and cleans up after itself."""
    from app.database import apply_migrations, connect

    apply_migrations()
    full_client = "parity-full-e2e"
    delta_client = "parity-delta-e2e"

    def _cleanup():
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "delete from co_stock_rows where client_id = any(%s)",
                ([full_client, delta_client],),
            )

    _cleanup()
    try:
        a = _stock_row("TK-A", decl_no="D100", line_no="1", item_code="C1", alloc="AL-A", qty=100)
        b = _stock_row("TK-B", decl_no="D100", line_no="2", item_code="C2", alloc="AL-B", qty=10)
        c = _stock_row("TK-C", decl_no="D101", line_no="1", item_code="C3", alloc="AL-C", qty=30)
        s0 = [a, b, c]
        f = _stock_row("TK-F", decl_no="D103", line_no="1", item_code="C6", alloc="AL-F", qty=60)
        b2 = _stock_row("TK-B", decl_no="D100", line_no="2", item_code="C2", alloc="AL-B", qty=3)
        final = [a, b2, f]  # C removed, B changed, F added

        refresh_co_stock_for_client({"id": full_client}, lambda: final, mode="full")

        refresh_co_stock_for_client({"id": delta_client}, lambda: s0, mode="full")
        refresh_co_stock_for_client(
            {"id": delta_client}, lambda: [f], mode="delta", tombstone_source_rows=[]
        )
        refresh_co_stock_for_client(
            {"id": delta_client}, lambda: [b2], mode="delta", tombstone_source_rows=[]
        )
        refresh_co_stock_for_client(
            {"id": delta_client}, lambda: [], mode="delta",
            tombstone_source_rows=[_tombstone_for("TK-C")],
        )

        full_mat = {p["source_row"]: p for p in co_stock_materializer.read_co_stock_rows(full_client)}
        delta_mat = {p["source_row"]: p for p in co_stock_materializer.read_co_stock_rows(delta_client)}
        assert set(full_mat) == set(delta_mat)
        assert {k: v["remaining_qty"] for k, v in full_mat.items()} == {
            k: v["remaining_qty"] for k, v in delta_mat.items()
        }
    finally:
        _cleanup()
