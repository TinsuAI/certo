"""Bug: refresh tồn CO từ Data Hub no-op khi snapshot rỗng nhưng refresh_state
còn `last_bcct_server_time` (vd DB reset / full-pull đầu chưa persist mà đã ghi
server_time). Delta-since-then trả 0 dòng → bảng co_stock kẹt rỗng mãi vì full
pull không bao giờ chạy lại.

Fix: chỉ đi đường delta khi snapshot KHÔNG rỗng; rỗng ⇒ ép full pull.
"""
from __future__ import annotations

from app.web import co_case_context as ctx


class _FakeDataHub:
    def list_bcct_with_envelope(self, *args, **kwargs):
        return {"server_time": "2026-06-07T00:00:00+00:00", "items": [], "tombstones": []}


def _patch_common(monkeypatch, row_count: int):
    monkeypatch.setattr(
        "app.co_stock_materializer.read_refresh_state",
        lambda cid: {"last_bcct_server_time": "2026-01-01T00:00:00+00:00"},
    )
    monkeypatch.setattr("app.co_stock_materializer.row_count", lambda cid: row_count)
    monkeypatch.setattr(ctx.portfolio_service, "data_hub", _FakeDataHub(), raising=False)


def test_empty_snapshot_forces_full_refresh_even_with_stored_server_time(monkeypatch):
    calls = []
    _patch_common(monkeypatch, row_count=0)  # snapshot RỖNG
    monkeypatch.setattr(ctx, "_try_delta_refresh", lambda *a, **k: calls.append("delta") or {"mode": "delta"})
    monkeypatch.setattr(ctx, "_full_refresh", lambda c: calls.append("full") or {"mode": "full"})

    summary = ctx._refresh_co_stock_delta_or_full({"id": "johnson-vn"})

    assert calls == ["full"], f"snapshot rỗng phải ép full pull, nhưng gọi: {calls}"
    assert summary["mode"] == "full"


def test_nonempty_snapshot_still_uses_delta(monkeypatch):
    calls = []
    _patch_common(monkeypatch, row_count=5)  # snapshot có dữ liệu
    monkeypatch.setattr(ctx, "_try_delta_refresh", lambda *a, **k: calls.append("delta") or {"mode": "delta"})
    monkeypatch.setattr(ctx, "_full_refresh", lambda c: calls.append("full") or {"mode": "full"})

    ctx._refresh_co_stock_delta_or_full({"id": "johnson-vn"})

    assert calls == ["delta"], f"snapshot có dữ liệu vẫn dùng delta, nhưng gọi: {calls}"
