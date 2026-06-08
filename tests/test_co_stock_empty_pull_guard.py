"""D1 fix D — a successful-but-EMPTY full pull must NOT wipe a populated snapshot.

`_full_refresh` derives `co_stock_rows` from a full BCCT pull. When that pull
returns 0 rows for a transient reason (empty page, pagination/auth glitch,
upstream hiccup) — NOT an exception — full mode computed `removed = all old
keys` and DELETEd every lot, then recorded snapshot_row_count=0. The `039baeb`
fix only guarded the READ side (empty snapshot ⇒ force full); nothing guarded
the WRITE side. This stranded the client's Tồn CO empty (same johnson-vn
symptom, different root cause).

Guard: in full mode, if the derived set is empty but the existing snapshot is
non-empty, refuse the wipe — preserve the snapshot, flag the abort, and don't
advance refresh_state / server_time.
"""
from __future__ import annotations

import httpx

from app.co_stock_materializer import _plan_removed_keys
from app.web import co_case_context as ctx


# --- pure removal planner -------------------------------------------------

def test_full_empty_pull_over_populated_snapshot_aborts():
    removed, abort = _plan_removed_keys("full", new_keys=set(), old_keys={"a", "b"}, tombstone_source_rows=[])
    assert abort is True
    assert removed == set()  # nothing deleted — snapshot preserved


def test_full_empty_pull_over_empty_snapshot_does_not_abort():
    # Legit "client genuinely has no BCCT" — empty over empty is a no-op, not a wipe.
    removed, abort = _plan_removed_keys("full", new_keys=set(), old_keys=set(), tombstone_source_rows=[])
    assert abort is False
    assert removed == set()


def test_full_normal_deletion_still_computed():
    # A real full pull that dropped some rows still deletes them (no over-guarding).
    removed, abort = _plan_removed_keys(
        "full", new_keys={"a"}, old_keys={"a", "b", "c"}, tombstone_source_rows=[]
    )
    assert abort is False
    assert removed == {"b", "c"}


def test_delta_uses_tombstones_and_never_aborts():
    removed, abort = _plan_removed_keys(
        "delta", new_keys=set(), old_keys={"a", "b"}, tombstone_source_rows=["a", "zzz"]
    )
    assert abort is False
    assert removed == {"a"}  # only tombstoned keys that exist in the snapshot


def test_delta_empty_with_no_tombstones_removes_nothing():
    removed, abort = _plan_removed_keys("delta", new_keys=set(), old_keys={"a", "b"}, tombstone_source_rows=[])
    assert abort is False
    assert removed == set()


# --- _full_refresh must not poison refresh_state on abort ------------------

def test_full_refresh_skips_state_advance_when_pull_aborted(monkeypatch):
    """When the materializer reports an aborted empty full pull, _full_refresh
    must NOT record refresh_state — advancing the high-water mark over rows we
    never pulled would strand them out of the next delta. (A read-only
    server_time probe is harmless; what matters is that state is not written.)"""
    recorded = []

    monkeypatch.setattr(
        ctx.portfolio_service, "source_workspace",
        lambda c: ({"co_stock_rows": []}, "data-hub"), raising=False,
    )
    monkeypatch.setattr(
        ctx.portfolio_service, "source_summary",
        lambda c: ({"bcct": {"published_row_count": 0}}, "data-hub"), raising=False,
    )
    monkeypatch.setattr(
        ctx.co_stock_materializer, "refresh_co_stock_for_client",
        lambda *a, **k: {"mode": "full", "aborted_empty_full_pull": True, "rows_persisted": 42},
    )
    monkeypatch.setattr(
        ctx.co_stock_materializer, "record_refresh_state",
        lambda *a, **k: recorded.append((a, k)),
    )
    monkeypatch.setattr(ctx, "_probe_server_time", lambda c: "PROBED")

    summary = ctx._full_refresh({"id": "johnson-vn"})

    assert summary.get("aborted_empty_full_pull") is True
    assert recorded == [], "must not advance refresh_state on an aborted empty pull"


def test_full_refresh_probes_server_time_before_pulling(monkeypatch):
    """B fix — the high-water mark must be captured BEFORE the data pull, never
    after. Probing after means any row created during the pull window lands
    after the snapshot yet before the recorded server_time, so the next
    delta (since=that-later-mark) skips it forever. Probing before is
    conservative: the next delta re-pulls the window (idempotent UPSERT)."""
    order = []

    monkeypatch.setattr(ctx, "_probe_server_time", lambda c: order.append("probe") or "T1")
    monkeypatch.setattr(
        ctx.portfolio_service, "source_workspace",
        lambda c: (order.append("pull"), ({"co_stock_rows": [{"source_row": "a"}]}, "data-hub"))[1],
        raising=False,
    )
    monkeypatch.setattr(
        ctx.portfolio_service, "source_summary",
        lambda c: ({"bcct": {"published_row_count": 1}}, "data-hub"), raising=False,
    )
    monkeypatch.setattr(
        ctx.co_stock_materializer, "refresh_co_stock_for_client",
        lambda *a, **k: {"mode": "full", "rows_persisted": 1},
    )
    recorded = {}
    monkeypatch.setattr(
        ctx.co_stock_materializer, "record_refresh_state",
        lambda cid, **k: recorded.update(k),
    )

    ctx._full_refresh({"id": "johnson-vn"})

    assert order == ["probe", "pull"], f"server_time must be probed before the pull, got: {order}"
    assert recorded.get("last_bcct_server_time") == "T1"


# --- A: delta is unsafe under aggregate lot_policy → force full -------------

class _DeltaCapableHub:
    def list_bcct_with_envelope(self, *a, **k):
        return {"server_time": "2026-06-07T00:00:00+00:00", "items": [], "tombstones": []}


def _patch_delta_preconditions(monkeypatch, lot_policy: str):
    """Snapshot non-empty + stored server_time + delta-capable hub — all the
    conditions that would normally take the delta path."""
    monkeypatch.setattr(
        "app.co_stock_materializer.read_refresh_state",
        lambda cid: {"last_bcct_server_time": "2026-01-01T00:00:00+00:00"},
    )
    monkeypatch.setattr("app.co_stock_materializer.row_count", lambda cid: 5)
    monkeypatch.setattr(ctx.portfolio_service, "data_hub", _DeltaCapableHub(), raising=False)
    monkeypatch.setattr(
        ctx.portfolio_service, "get_client_config",
        lambda c: {"co_stock": {"lot_policy": lot_policy}}, raising=False,
    )


def test_aggregate_policy_forces_full_even_when_delta_preconditions_met(monkeypatch):
    """Under aggregate_by_declaration_and_allocation_code, co_stock `source_row`
    is a comma-joined aggregate, so per-import-row tombstones never match and
    new rows insert a duplicate aggregate. Delta is unsound — force full."""
    calls = []
    _patch_delta_preconditions(monkeypatch, "aggregate_by_declaration_and_allocation_code")
    monkeypatch.setattr(ctx, "_try_delta_refresh", lambda *a, **k: calls.append("delta") or {"mode": "delta"})
    monkeypatch.setattr(ctx, "_full_refresh", lambda c: calls.append("full") or {"mode": "full"})

    ctx._refresh_co_stock_delta_or_full({"id": "agg-client"})

    assert calls == ["full"], f"aggregate policy must force full, got: {calls}"


def test_line_level_policy_still_uses_delta(monkeypatch):
    calls = []
    _patch_delta_preconditions(monkeypatch, "line_level")
    monkeypatch.setattr(ctx, "_try_delta_refresh", lambda *a, **k: calls.append("delta") or {"mode": "delta"})
    monkeypatch.setattr(ctx, "_full_refresh", lambda c: calls.append("full") or {"mode": "full"})

    ctx._refresh_co_stock_delta_or_full({"id": "johnson-vn"})

    assert calls == ["delta"], f"line_level must still use delta, got: {calls}"


# --- cheap server_time probe (page 1 only, no full re-pagination) ----------

def test_bcct_server_time_fetches_only_first_page():
    """The high-water-mark probe must NOT re-paginate the whole BCCT corpus just
    to read server_time. A single page-1 request (limit=1), even when the
    response carries a next_cursor, is enough."""
    from app.data_hub_client import DataHubClient

    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        # next_cursor present → a paginating call would fire a 2nd request.
        return httpx.Response(200, json={"items": [{"x": 1}], "server_time": "T-HWM", "next_cursor": "more"})

    client = DataHubClient(base_url="https://hub.test", token="t", transport=httpx.MockTransport(handler))

    assert client.bcct_server_time("growatt-vn") == "T-HWM"
    assert len(requests) == 1, f"must hit exactly one page, got {len(requests)}: {requests}"
    assert "limit=1" in requests[0]
    assert "/v1/hub/bcct" in requests[0]


def test_bcct_server_time_blank_on_old_contract():
    from app.data_hub_client import DataHubClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []})  # no server_time

    client = DataHubClient(base_url="https://hub.test", token="t", transport=httpx.MockTransport(handler))
    assert client.bcct_server_time("growatt-vn") == ""


def test_probe_server_time_prefers_cheap_method(monkeypatch):
    """_probe_server_time uses the cheap page-1 probe when the backend exposes it,
    and does NOT fall back to the full-pagination list_bcct_with_envelope."""
    used = []

    class _CheapHub:
        def bcct_server_time(self, cid):
            used.append(("cheap", cid))
            return "T-CHEAP"

        def list_bcct_with_envelope(self, *a, **k):
            used.append(("full", a, k))
            return {"server_time": "T-FULL"}

    monkeypatch.setattr(ctx.portfolio_service, "data_hub", _CheapHub(), raising=False)
    assert ctx._probe_server_time({"id": "growatt-vn"}) == "T-CHEAP"
    assert used == [("cheap", "growatt-vn")], f"must use cheap probe only, got: {used}"


def test_probe_server_time_falls_back_when_no_cheap_method(monkeypatch):
    """Backends/fakes without bcct_server_time still work via the envelope path."""
    class _LegacyHub:
        def list_bcct_with_envelope(self, *a, **k):
            return {"server_time": "T-FULL", "items": [], "tombstones": []}

    monkeypatch.setattr(ctx.portfolio_service, "data_hub", _LegacyHub(), raising=False)
    assert ctx._probe_server_time({"id": "growatt-vn"}) == "T-FULL"
