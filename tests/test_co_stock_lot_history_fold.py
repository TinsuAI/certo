"""Unit tests for the display-only fold of a lot's history events.

`fold_lot_events` collapses the chốt→mở-chốt→chốt churn into one net row per
(case, sheet) claim stream so the per-lot "Lịch sử" modal reads cleanly. The
raw `co_stock_events` rows are untouched — this is presentation only.

Sign convention (matches emission + the modal's effectOf):
  claim_lock   qty_delta > 0  → effect = −qty (consumes the lot)
  claim_release qty_delta < 0 → effect = +qty (returns it to the pool)
Events arrive newest-first (as `events_for_lot` returns them).
"""
from app.co_stock_events_store import fold_lot_events


def _ev(event_type, qty_delta, *, case_id="", sheet="", recorded_at="",
        event_id="", actor="", **kw):
    row = {
        "event_id": event_id or f"evt-{recorded_at or qty_delta}",
        "event_type": event_type,
        "qty_delta": str(qty_delta),
        "case_id": case_id,
        "sheet_product_code": sheet,
        "recorded_at": recorded_at,
        "actor": actor,
    }
    row.update(kw)
    return row


def test_empty_input():
    assert fold_lot_events([]) == []


def test_single_lock_is_holding():
    groups = fold_lot_events([
        _ev("claim_lock", "10", case_id="C1", sheet="P1", recorded_at="2026-06-01T10:00:00"),
    ])
    assert len(groups) == 1
    g = groups[0]
    assert g["kind"] == "claim"
    assert g["case_id"] == "C1"
    assert g["status"] == "holding"
    assert g["held_qty"] == "10"
    assert g["net_delta"] == "-10"
    assert g["event_count"] == 1
    assert g["lock_count"] == 1
    assert g["release_count"] == 0


def test_lock_then_unlock_nets_to_released():
    # Newest-first: release (mở chốt) on top, lock below.
    groups = fold_lot_events([
        _ev("claim_release", "-10", case_id="C1", sheet="P1", recorded_at="2026-06-02T09:00:00"),
        _ev("claim_lock", "10", case_id="C1", sheet="P1", recorded_at="2026-06-01T10:00:00"),
    ])
    assert len(groups) == 1
    g = groups[0]
    assert g["status"] == "released"
    assert g["held_qty"] == "0"
    assert g["net_delta"] == "0"
    assert g["event_count"] == 2
    assert g["lock_count"] == 1
    assert g["release_count"] == 1


def test_lock_unlock_relock_collapses_to_one_holding_row():
    # The exact churn Phase 3 targets: 3 events → 1 net "đang giữ" row.
    groups = fold_lot_events([
        _ev("claim_lock", "10", case_id="C1", sheet="P1", recorded_at="2026-06-03T11:00:00"),
        _ev("claim_release", "-10", case_id="C1", sheet="P1", recorded_at="2026-06-02T09:00:00"),
        _ev("claim_lock", "10", case_id="C1", sheet="P1", recorded_at="2026-06-01T10:00:00"),
    ])
    assert len(groups) == 1
    g = groups[0]
    assert g["status"] == "holding"
    assert g["held_qty"] == "10"
    assert g["net_delta"] == "-10"
    assert g["event_count"] == 3
    assert g["latest_at"] == "2026-06-03T11:00:00"
    assert g["earliest_at"] == "2026-06-01T10:00:00"


def test_two_cases_stay_separate():
    groups = fold_lot_events([
        _ev("claim_lock", "5", case_id="C2", sheet="P1", recorded_at="2026-06-04T08:00:00"),
        _ev("claim_lock", "10", case_id="C1", sheet="P1", recorded_at="2026-06-01T10:00:00"),
    ])
    assert len(groups) == 2
    by_case = {g["case_id"]: g for g in groups}
    assert by_case["C1"]["held_qty"] == "10"
    assert by_case["C2"]["held_qty"] == "5"


def test_same_case_different_sheets_stay_separate():
    groups = fold_lot_events([
        _ev("claim_lock", "5", case_id="C1", sheet="P2", recorded_at="2026-06-04T08:00:00"),
        _ev("claim_lock", "10", case_id="C1", sheet="P1", recorded_at="2026-06-01T10:00:00"),
    ])
    assert len(groups) == 2
    assert {g["sheet_product_code"] for g in groups} == {"P1", "P2"}


def test_adjustment_events_pass_through_individually():
    groups = fold_lot_events([
        _ev("adjustment_import_insert", "0", event_id="a2",
            recorded_at="2026-06-05T08:00:00",
            opening_qty_before="0", opening_qty_after="100"),
        _ev("adjustment_import_update", "20", event_id="a1",
            recorded_at="2026-06-04T08:00:00",
            opening_qty_before="100", opening_qty_after="100"),
    ])
    assert len(groups) == 2
    insert = next(g for g in groups if g["kind"] == "adjustment_import_insert")
    # Δopening 100 − Δused 0 = +100
    assert insert["net_delta"] == "100"
    assert insert["status"] == ""
    update = next(g for g in groups if g["kind"] == "adjustment_import_update")
    # Δopening 0 − Δused 20 = −20
    assert update["net_delta"] == "-20"


def test_order_follows_newest_activity_first():
    groups = fold_lot_events([
        _ev("claim_lock", "5", case_id="C2", sheet="P1", recorded_at="2026-06-04T08:00:00"),
        _ev("claim_lock", "10", case_id="C1", sheet="P1", recorded_at="2026-06-01T10:00:00"),
    ])
    assert [g["case_id"] for g in groups] == ["C2", "C1"]


def test_over_release_flags_anomaly():
    # More released than locked (shouldn't normally happen) → net positive.
    groups = fold_lot_events([
        _ev("claim_release", "-10", case_id="C1", sheet="P1", recorded_at="2026-06-02T09:00:00"),
    ])
    assert groups[0]["status"] == "anomaly"
    assert groups[0]["net_delta"] == "10"


def test_claim_without_case_id_falls_back_to_singletons():
    groups = fold_lot_events([
        _ev("claim_lock", "10", case_id="", sheet="P1", event_id="x1", recorded_at="2026-06-01T10:00:00"),
    ])
    assert len(groups) == 1
    # No case identity → not folded as a claim stream.
    assert groups[0]["kind"] == "claim_lock"


def test_system_events_fold_into_one_row_with_counts():
    groups = fold_lot_events([
        _ev("snapshot_row_added", "0", event_id="s2", recorded_at="2026-06-07T08:00:00",
            notes="materializer:import-row-abc"),
        _ev("snapshot_row_updated", "0", event_id="s1", recorded_at="2026-05-29T08:00:00",
            notes="materializer:import-row-abc"),
    ])
    assert len(groups) == 1
    g = groups[0]
    assert g["kind"] == "system"
    assert g["event_count"] == 2
    assert (g["added_count"], g["updated_count"], g["removed_count"]) == (1, 1, 0)
    assert g["net_delta"] == "0"  # system events never move tồn
    assert g["latest_at"] == "2026-06-07T08:00:00"


def test_added_with_updated_flags_readded_not_duplicate():
    # CS1 symptom: one lot shows added (later) + updated (earlier) ⇒ dropped from
    # a pull and re-derived in a later one, NOT a duplicate row.
    groups = fold_lot_events([
        _ev("snapshot_row_added", "0", recorded_at="2026-06-07T08:00:00"),
        _ev("snapshot_row_updated", "0", recorded_at="2026-05-29T08:00:00"),
    ])
    assert groups[0]["readded"] is True


def test_plain_updated_only_is_not_readded():
    groups = fold_lot_events([
        _ev("snapshot_row_updated", "0", recorded_at="2026-05-29T08:00:00"),
    ])
    assert groups[0]["kind"] == "system"
    assert groups[0]["readded"] is False


def test_system_row_pinned_after_business_events():
    groups = fold_lot_events([
        _ev("snapshot_row_added", "0", recorded_at="2026-06-07T08:00:00"),
        _ev("claim_lock", "10", case_id="C1", sheet="P1", recorded_at="2026-06-05T10:00:00"),
    ])
    assert [g["kind"] for g in groups] == ["claim", "system"]
