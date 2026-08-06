"""D1 (F) — refresh mode/reason UX + operation-scoped count field.

A "Refresh từ Data Hub" that returns ok:true, rows:0 must tell the operator WHY:
"nothing new" (delta/incremental) vs "full re-derivation forced" (config/schema
change) vs "snapshot/source was empty". The dispatch already KNOWS which path it
took and why; this surfaces `mode` (full|delta) + `reason` (machine string) on
the refresh summary (which is the route's JSON body via `{**summary}`).

Also asserts the count fields distinguish the OPERATION (`source_rows_considered`
— rows this pull actually touched) from the whole-corpus high-water mark
(`bcct_total_rows`, ~65k). Reporting only the total made a 3-row delta look like
it re-processed 65846 rows.
"""
from __future__ import annotations

import json

from app import co_stock_materializer
from app.web import co_case_context as ctx


_CONFIG = {
    "allocation_code": {"strategy": "same_as_customs_code", "description_regex": "",
                        "fallback": "same_as_customs_code"},
    "co_stock": {"lot_policy": "line_level"},
}


class _DeltaHub:
    def __init__(self, *, server_time="2026-07-12T00:00:00+00:00", items=None, tombstones=None):
        self._envelope = {
            "server_time": server_time,
            "items": items if items is not None else [],
            "tombstones": tombstones if tombstones is not None else [],
        }

    def list_bcct_with_envelope(self, *args, **kwargs):
        return dict(self._envelope)


# --- dispatch: reason for full-vs-delta -----------------------------------

def _patch_dispatch(monkeypatch, *, row_count, state, config=_CONFIG, hub=None):
    monkeypatch.setattr("app.co_stock_materializer.read_refresh_state", lambda cid: state)
    monkeypatch.setattr("app.co_stock_materializer.row_count", lambda cid: row_count)
    monkeypatch.setattr(ctx.portfolio_service, "data_hub", hub or _DeltaHub(), raising=False)
    monkeypatch.setattr(ctx.portfolio_service, "get_client_config", lambda c: config, raising=False)


def test_delta_path_reports_incremental_mode_and_reason(monkeypatch):
    _patch_dispatch(monkeypatch, row_count=5, state={
        "last_bcct_server_time": "2026-06-07T15:34:18+00:00",
        "derivation_schema_version": co_stock_materializer.DERIVATION_SCHEMA_VERSION,
        "co_config_fingerprint": co_stock_materializer.co_config_fingerprint(_CONFIG),
    })
    monkeypatch.setattr(ctx, "_try_delta_refresh", lambda *a, **k: {"mode": "delta", "reason": "incremental"})

    summary = ctx._refresh_co_stock_delta_or_full({"id": "growatt-vn"})

    assert summary["mode"] == "delta"
    assert summary["reason"] == "incremental"


def test_full_forced_by_config_fingerprint_reports_config_changed(monkeypatch):
    _patch_dispatch(monkeypatch, row_count=38287, state={
        "last_bcct_server_time": "2026-06-07T15:34:18+00:00",
        "derivation_schema_version": co_stock_materializer.DERIVATION_SCHEMA_VERSION,
        # fingerprint stamped under a DIFFERENT config -> mismatch -> full
        "co_config_fingerprint": "stale-fingerprint",
    })
    monkeypatch.setattr(ctx, "_try_delta_refresh", lambda *a, **k: {"mode": "delta"})
    monkeypatch.setattr(ctx, "_full_refresh", lambda c: {"mode": "full"})

    summary = ctx._refresh_co_stock_delta_or_full({"id": "growatt-vn"})

    assert summary["mode"] == "full"
    assert summary["reason"] == "config_changed"


def test_full_forced_by_schema_version_reports_schema_version(monkeypatch):
    _patch_dispatch(monkeypatch, row_count=38287, state={
        "last_bcct_server_time": "2026-06-07T15:34:18+00:00",
        "derivation_schema_version": co_stock_materializer.DERIVATION_SCHEMA_VERSION - 1,
        "co_config_fingerprint": co_stock_materializer.co_config_fingerprint(_CONFIG),
    })
    monkeypatch.setattr(ctx, "_full_refresh", lambda c: {"mode": "full"})

    summary = ctx._refresh_co_stock_delta_or_full({"id": "growatt-vn"})

    assert summary["reason"] == "schema_version"


def test_empty_snapshot_reports_empty_snapshot(monkeypatch):
    _patch_dispatch(monkeypatch, row_count=0, state={
        "last_bcct_server_time": "2026-06-07T15:34:18+00:00",
        "derivation_schema_version": co_stock_materializer.DERIVATION_SCHEMA_VERSION,
        "co_config_fingerprint": co_stock_materializer.co_config_fingerprint(_CONFIG),
    })
    monkeypatch.setattr(ctx, "_full_refresh", lambda c: {"mode": "full"})

    summary = ctx._refresh_co_stock_delta_or_full({"id": "johnson-vn"})

    assert summary["reason"] == "empty_snapshot"


def test_delta_preconditions_met_but_pull_unavailable_reports_delta_unavailable(monkeypatch):
    # Delta was structurally OK (snapshot, server_time, schema, config, hub) but
    # the pull returned None (old contract / raised) -> fall back to full with a
    # reason that says the delta contract was unavailable, not that the client changed.
    _patch_dispatch(monkeypatch, row_count=5, state={
        "last_bcct_server_time": "2026-06-07T15:34:18+00:00",
        "derivation_schema_version": co_stock_materializer.DERIVATION_SCHEMA_VERSION,
        "co_config_fingerprint": co_stock_materializer.co_config_fingerprint(_CONFIG),
    })
    monkeypatch.setattr(ctx, "_try_delta_refresh", lambda *a, **k: None)
    monkeypatch.setattr(ctx, "_full_refresh", lambda c: {"mode": "full"})

    summary = ctx._refresh_co_stock_delta_or_full({"id": "growatt-vn"})

    assert summary["mode"] == "full"
    assert summary["reason"] == "delta_unavailable"


# --- operation-scoped count vs total high-water mark -----------------------

def test_delta_count_reflects_operation_not_total(monkeypatch):
    """A delta that pulled 3 rows over a 65846-row corpus reports
    source_rows_considered=3, bcct_total_rows=65846 — never 65846 for both."""
    hub = _DeltaHub(items=[{"a": 1}, {"a": 2}, {"a": 3}], tombstones=[])
    monkeypatch.setattr(ctx.portfolio_service, "get_client_config", lambda c: _CONFIG, raising=False)
    monkeypatch.setattr(
        ctx.portfolio_service, "source_summary",
        lambda c: ({"bcct": {"published_row_count": 65846}}, "data-hub"), raising=False,
    )
    monkeypatch.setattr("app.source_store.co_stock_rows_from_bcct", lambda rows, cfg, customs_fx_rows=None: list(rows))
    monkeypatch.setattr("app.source_store._safe_customs_fx_rows", lambda: [])
    monkeypatch.setattr("app.data_hub_client.normalize_bcct_row", lambda r: r)
    monkeypatch.setattr(
        ctx.co_stock_materializer, "refresh_co_stock_for_client",
        lambda *a, **k: {"mode": "delta", "rows_persisted": 3, "rows_added": 1, "rows_updated": 2},
    )
    monkeypatch.setattr(ctx.co_stock_materializer, "row_count", lambda cid: 5)
    monkeypatch.setattr(ctx.co_stock_materializer, "record_refresh_state", lambda *a, **k: None)

    summary = ctx._try_delta_refresh({"id": "growatt-vn"}, hub, "2026-01-01T00:00:00+00:00")

    assert summary["mode"] == "delta"
    assert summary["reason"] == "incremental"
    assert summary["source_rows_considered"] == 3
    assert summary["bcct_total_rows"] == 65846


def test_full_refresh_count_and_mode(monkeypatch):
    monkeypatch.setattr(ctx, "_probe_server_time", lambda c: "T1")
    monkeypatch.setattr(
        ctx.portfolio_service, "source_workspace",
        lambda c: ({"co_stock_rows": [{"source_row": "a"}]}, "data-hub"), raising=False,
    )
    monkeypatch.setattr(
        ctx.portfolio_service, "source_summary",
        lambda c: ({"bcct": {"published_row_count": 65846}}, "data-hub"), raising=False,
    )
    monkeypatch.setattr(
        ctx.co_stock_materializer, "refresh_co_stock_for_client",
        lambda *a, **k: {"mode": "full", "rows_persisted": 65846},
    )
    monkeypatch.setattr(ctx.co_stock_materializer, "record_refresh_state", lambda *a, **k: None)
    monkeypatch.setattr(ctx.portfolio_service, "get_client_config", lambda c: _CONFIG, raising=False)

    summary = ctx._full_refresh({"id": "johnson-vn"})

    assert summary["mode"] == "full"
    # A full considers the whole corpus, so the two counts coincide (but both present).
    assert summary["source_rows_considered"] == 65846
    assert summary["bcct_total_rows"] == 65846


def test_empty_source_full_reports_empty_source_and_zero_considered(monkeypatch):
    """A full pull that came back empty over a populated snapshot: the abort
    guard preserves the snapshot. Report reason=empty_source, considered=0 — so
    ok:false, rows:0 reads as 'the pull was empty', not 'nothing changed'."""
    monkeypatch.setattr(ctx, "_probe_server_time", lambda c: "T1")
    monkeypatch.setattr(
        ctx.portfolio_service, "source_workspace",
        lambda c: ({"co_stock_rows": []}, "data-hub"), raising=False,
    )
    monkeypatch.setattr(
        ctx.co_stock_materializer, "refresh_co_stock_for_client",
        lambda *a, **k: {"mode": "full", "aborted_empty_full_pull": True, "rows_persisted": 42,
                         "errors": ["empty full pull over non-empty snapshot; snapshot preserved"]},
    )
    recorded = []
    monkeypatch.setattr(ctx.co_stock_materializer, "record_refresh_state", lambda *a, **k: recorded.append(k))
    monkeypatch.setattr(ctx.portfolio_service, "get_client_config", lambda c: _CONFIG, raising=False)

    # Route through the dispatch so we prove empty_source wins over the
    # dispatch-level decision (setdefault does not clobber it).
    monkeypatch.setattr("app.co_stock_materializer.read_refresh_state", lambda cid: {
        "last_bcct_server_time": "2026-06-07T15:34:18+00:00",
        "derivation_schema_version": co_stock_materializer.DERIVATION_SCHEMA_VERSION,
        "co_config_fingerprint": co_stock_materializer.co_config_fingerprint(_CONFIG),
    })
    monkeypatch.setattr("app.co_stock_materializer.row_count", lambda cid: 5)
    monkeypatch.setattr(ctx.portfolio_service, "data_hub", None, raising=False)

    summary = ctx._refresh_co_stock_delta_or_full({"id": "johnson-vn"})

    assert summary["mode"] == "full"
    assert summary["reason"] == "empty_source"
    assert summary["source_rows_considered"] == 0
    assert recorded == [], "aborted empty pull must not advance refresh_state"


# --- route surfaces mode + reason in the JSON body -------------------------

def test_refresh_route_json_carries_mode_and_reason(monkeypatch):
    from app.routers import co_stock as route_mod

    monkeypatch.setattr(route_mod, "resolve_client", lambda cid: {"id": cid})
    monkeypatch.setattr(route_mod.co_stock_materializer, "is_workbook_sourced", lambda cid: False)
    monkeypatch.setattr(route_mod, "_refresh_co_stock_delta_or_full", lambda c: {
        "mode": "delta", "reason": "incremental", "rows_persisted": 0,
        "source_rows_considered": 0, "bcct_total_rows": 65846, "errors": [],
    })

    import asyncio

    resp = asyncio.run(route_mod.refresh_co_stock_endpoint("growatt-vn"))
    body = json.loads(resp.body)

    assert body["ok"] is True
    assert body["mode"] == "delta"
    assert body["reason"] == "incremental"
    assert body["source_rows_considered"] == 0
    assert body["bcct_total_rows"] == 65846
