"""Unit tests for the folded CO-stock model.

The static trừ-lùi layer is folded into the snapshot (`fold_baseline`); the
live cross-case ledger is overlaid at read time (`apply_used_qty`). Together
they must yield: remaining = opening - baseline_used - ledger_used, with the
displayed remaining clamped at 0 and an overclaim flag preserving the truth.
"""
from decimal import Decimal

from app.co_stock_adjustments_store import fold_baseline
from app.co_stock_ledger import apply_used_qty


def _lot(**kw):
    row = {"source_row": "row-1", "import_declaration_no": "D1", "line_no": "2", "customs_item_code": "C1"}
    row.update(kw)
    return row


def test_fold_no_adjustment_normalizes_fields():
    rows = fold_baseline([_lot(available_qty="3000")], {})
    row = rows[0]
    assert row["bcct_qty"] == "3000"
    assert row["opening_qty"] == "3000"
    assert row["available_qty"] == "3000"
    assert row["baseline_used_qty"] == "0"
    assert row["used_qty"] == "0"
    assert row["remaining_qty"] == "3000"


def test_fold_override_and_baseline_used():
    adj = {("D1", "2", "C1"): {"opening_qty_override": Decimal("3000"), "used_qty": Decimal("3000")}}
    row = fold_baseline([_lot(available_qty="3000")], adj)[0]
    assert row["opening_qty"] == "3000"
    assert row["baseline_used_qty"] == "3000"
    assert row["remaining_qty"] == "0"  # opening - baseline


def test_fold_override_differs_from_bcct():
    adj = {("D1", "2", "C1"): {"opening_qty_override": Decimal("2500"), "used_qty": Decimal("100")}}
    row = fold_baseline([_lot(available_qty="3000")], adj)[0]
    assert row["bcct_qty"] == "3000"
    assert row["opening_qty"] == "2500"
    assert row["remaining_qty"] == "2400"


def test_fold_is_idempotent():
    adj = {("D1", "2", "C1"): {"opening_qty_override": Decimal("2500"), "used_qty": Decimal("100")}}
    row = fold_baseline([_lot(available_qty="3000")], adj)[0]
    again = fold_baseline([row], adj)[0]
    assert again["bcct_qty"] == "3000"
    assert again["opening_qty"] == "2500"
    assert again["remaining_qty"] == "2400"


def test_fold_void_reverts_to_bcct():
    adj = {("D1", "2", "C1"): {"opening_qty_override": Decimal("2500"), "used_qty": Decimal("100")}}
    folded = fold_baseline([_lot(available_qty="3000")], adj)[0]
    # Adjustment voided -> key no longer in the aggregate; re-fold reverts.
    reverted = fold_baseline([folded], {})[0]
    assert reverted["opening_qty"] == "3000"
    assert reverted["baseline_used_qty"] == "0"
    assert reverted["remaining_qty"] == "3000"


def test_apply_ledger_overclaim_on_folded_row():
    row = fold_baseline(
        [_lot(available_qty="3000")],
        {("D1", "2", "C1"): {"opening_qty_override": Decimal("3000"), "used_qty": Decimal("3000")}},
    )[0]
    apply_used_qty([row], {"row-1": Decimal("5.728")})
    assert row["used_qty"] == "3005.728"  # baseline 3000 + ledger 5.728
    assert row["remaining_signed_qty"] == "-5.728"
    assert row["remaining_qty"] == "0"  # clamped for display
    assert row["ledger_overclaim"] is True


def test_apply_ledger_backward_compatible_without_fold():
    # File-mode / demo fixtures never get folded: no opening_qty/baseline.
    row = _lot(available_qty="500")
    apply_used_qty([row], {"row-1": Decimal("120")})
    assert row["used_qty"] == "120"
    assert row["remaining_signed_qty"] == "380"
    assert row["remaining_qty"] == "380"
    assert row["ledger_overclaim"] is False


def test_apply_ledger_exact_zero_is_not_overclaim():
    row = fold_baseline([_lot(available_qty="100")], {})[0]
    apply_used_qty([row], {"row-1": Decimal("100")})
    assert row["remaining_signed_qty"] == "0"
    assert row["remaining_qty"] == "0"
    assert row["ledger_overclaim"] is False
