"""#14 S3 — a CO-owned config change forces one FULL co_stock re-derivation.

A change to a CO-owned config section (allocation_code strategy/regex/fallback,
or co_stock lot_policy) re-derives codes but touches no DH source row, so the
delta refresh re-derives nothing and the existing snapshot keeps stale codes.
The dispatch fingerprints both CO-owned sections in co_stock_refresh_state and
forces full on mismatch. Without S3 the #14 fix silently no-ops on the 60k
snapshot.
"""
from __future__ import annotations

from app import co_stock_materializer
from app.web import co_case_context as ctx


class _FakeDataHub:
    def list_bcct_with_envelope(self, *args, **kwargs):
        return {"server_time": "2026-07-12T00:00:00+00:00", "items": [], "tombstones": []}


def _config(strategy="same_as_customs_code", lot_policy="line_level"):
    return {
        "allocation_code": {"strategy": strategy, "description_regex": r"\((.+)\)",
                            "fallback": "same_as_customs_code"},
        "co_stock": {"lot_policy": lot_policy},
    }


def _run(monkeypatch, *, stamped_config, current_config):
    """Snapshot was stamped under `stamped_config`; the client now runs
    `current_config`. Returns the refresh path taken."""
    state = {
        "last_bcct_server_time": "2026-06-07T15:34:18+00:00",
        "derivation_schema_version": co_stock_materializer.DERIVATION_SCHEMA_VERSION,
        "co_config_fingerprint": co_stock_materializer.co_config_fingerprint(stamped_config),
    }
    monkeypatch.setattr("app.co_stock_materializer.read_refresh_state", lambda cid: state)
    monkeypatch.setattr("app.co_stock_materializer.row_count", lambda cid: 38287)
    monkeypatch.setattr(ctx.portfolio_service, "data_hub", _FakeDataHub(), raising=False)
    monkeypatch.setattr(ctx.portfolio_service, "get_client_config", lambda c: current_config, raising=False)

    calls = []
    monkeypatch.setattr(ctx, "_try_delta_refresh", lambda *a, **k: calls.append("delta") or {"mode": "delta"})
    monkeypatch.setattr(ctx, "_full_refresh", lambda c: calls.append("full") or {"mode": "full"})
    ctx._refresh_co_stock_delta_or_full({"id": "growatt-vn"})
    return calls


def test_allocation_strategy_change_forces_full(monkeypatch):
    calls = _run(
        monkeypatch,
        stamped_config=_config(strategy="same_as_customs_code"),
        current_config=_config(strategy="description_regex"),
    )
    assert calls == ["full"]


def test_lot_policy_line_level_to_manual_review_forces_full(monkeypatch):
    # manual_review is delta_safe (only aggregate_* is not), so ONLY the config
    # fingerprint catches this — an allocation_code-only fingerprint would miss it.
    calls = _run(
        monkeypatch,
        stamped_config=_config(lot_policy="line_level"),
        current_config=_config(lot_policy="manual_review"),
    )
    assert calls == ["full"]


def test_unchanged_config_keeps_delta(monkeypatch):
    cfg = _config(strategy="description_regex")
    calls = _run(monkeypatch, stamped_config=cfg, current_config=cfg)
    assert calls == ["delta"]


def test_missing_fingerprint_forces_full(monkeypatch):
    # Pre-021 snapshot: co_config_fingerprint defaults to '' -> never matches a
    # real fingerprint -> one forced full refresh (self-healing).
    state = {
        "last_bcct_server_time": "2026-06-07T15:34:18+00:00",
        "derivation_schema_version": co_stock_materializer.DERIVATION_SCHEMA_VERSION,
        "co_config_fingerprint": "",
    }
    monkeypatch.setattr("app.co_stock_materializer.read_refresh_state", lambda cid: state)
    monkeypatch.setattr("app.co_stock_materializer.row_count", lambda cid: 38287)
    monkeypatch.setattr(ctx.portfolio_service, "data_hub", _FakeDataHub(), raising=False)
    monkeypatch.setattr(ctx.portfolio_service, "get_client_config", lambda c: _config(), raising=False)

    calls = []
    monkeypatch.setattr(ctx, "_try_delta_refresh", lambda *a, **k: calls.append("delta") or {"mode": "delta"})
    monkeypatch.setattr(ctx, "_full_refresh", lambda c: calls.append("full") or {"mode": "full"})
    ctx._refresh_co_stock_delta_or_full({"id": "growatt-vn"})
    assert calls == ["full"]
