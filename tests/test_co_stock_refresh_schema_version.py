"""Bug: pre-VN-origin co_stock snapshots never gain the new derived payload
fields (consignee_name/origin_country, ticket #6) through "Refresh tồn" — the
dispatch picks the DELTA path, which only rewrites rows whose source BCCT data
changed on Data Hub. The suppliers screen (ticket #11) reads consignee_name
from the snapshot, so it stayed empty and the refresh the empty-state hint
suggests was a no-op (observed live: johnson-vn refreshed post-deploy with
0/60,173 rows carrying consignee_name).

Fix: co_stock_refresh_state carries a `derivation_schema_version` stamp
(migration 020, stamped by record_refresh_state); the dispatch forces one FULL
re-derivation whenever the stored stamp differs from the code's
DERIVATION_SCHEMA_VERSION.
"""
from __future__ import annotations

from app import co_stock_materializer
from app.web import co_case_context as ctx


class _FakeDataHub:
    def list_bcct_with_envelope(self, *args, **kwargs):
        return {"server_time": "2026-07-12T00:00:00+00:00", "items": [], "tombstones": []}


_CONFIG = {
    "allocation_code": {"strategy": "same_as_customs_code", "description_regex": "", "fallback": "same_as_customs_code"},
    "co_stock": {"lot_policy": "line_level"},
}


def _patch_common(monkeypatch, state: dict):
    monkeypatch.setattr("app.co_stock_materializer.read_refresh_state", lambda cid: state)
    monkeypatch.setattr("app.co_stock_materializer.row_count", lambda cid: 38287)
    monkeypatch.setattr(ctx.portfolio_service, "data_hub", _FakeDataHub(), raising=False)
    monkeypatch.setattr(ctx.portfolio_service, "get_client_config", lambda c: _CONFIG, raising=False)
    # Keep the CO-config fingerprint matching so these tests isolate the
    # derivation-schema dimension (#14 adds a separate config-fingerprint guard).
    state.setdefault("co_config_fingerprint", co_stock_materializer.co_config_fingerprint(_CONFIG))


def _run(monkeypatch):
    calls = []
    monkeypatch.setattr(ctx, "_try_delta_refresh", lambda *a, **k: calls.append("delta") or {"mode": "delta"})
    monkeypatch.setattr(ctx, "_full_refresh", lambda c: calls.append("full") or {"mode": "full"})
    ctx._refresh_co_stock_delta_or_full({"id": "growatt-vn"})
    return calls


def test_pre_stamp_snapshot_forces_full_refresh(monkeypatch):
    # migration 020 default 0 = snapshot materialized before the stamp existed
    _patch_common(monkeypatch, {
        "last_bcct_server_time": "2026-06-07T15:34:18+00:00",
        "derivation_schema_version": 0,
    })
    assert _run(monkeypatch) == ["full"]


def test_older_derivation_stamp_forces_full_refresh(monkeypatch):
    _patch_common(monkeypatch, {
        "last_bcct_server_time": "2026-06-07T15:34:18+00:00",
        "derivation_schema_version": co_stock_materializer.DERIVATION_SCHEMA_VERSION - 1,
    })
    assert _run(monkeypatch) == ["full"]


def test_current_stamp_keeps_delta_path(monkeypatch):
    _patch_common(monkeypatch, {
        "last_bcct_server_time": "2026-06-07T15:34:18+00:00",
        "derivation_schema_version": co_stock_materializer.DERIVATION_SCHEMA_VERSION,
    })
    assert _run(monkeypatch) == ["delta"]
