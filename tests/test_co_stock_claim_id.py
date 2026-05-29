"""Claim ID stability — claim_id must not depend on BOM ordering.

DB-free unit coverage for the identity + aggregation logic in
app/co_stock_ledger.py. The end-to-end lock/release tests in test_co_demo.py
are Postgres-gated and skip without BARRY_DATABASE_URL; these run anywhere.
"""
from decimal import Decimal

from app.co_stock_ledger import _build_claim_rows, claim_id_for


def test_claim_id_stable_across_material_reorder():
    # Same physical claim (case, product, lot, material) → same id regardless
    # of where the material sits in the (re-orderable) BOM list.
    a = claim_id_for("case1", "TP1", "ROW-A1", material_code="M-A", material_index=0)
    b = claim_id_for("case1", "TP1", "ROW-A1", material_code="M-A", material_index=5)
    assert a == b


def test_claim_id_distinguishes_materials_on_same_lot():
    a = claim_id_for("case1", "TP1", "ROW-A1", material_code="M-A", material_index=0)
    b = claim_id_for("case1", "TP1", "ROW-A1", material_code="M-B", material_index=1)
    assert a != b


def test_claim_id_falls_back_to_index_when_code_empty():
    # Unnamed materials keep positional distinctness so two of them on the same
    # lot don't collapse into one claim.
    a = claim_id_for("case1", "TP1", "ROW-A1", material_code="", material_index=0)
    b = claim_id_for("case1", "TP1", "ROW-A1", material_code="", material_index=1)
    assert a != b


def test_build_claim_rows_sums_qty_on_collision():
    # Same material against the same lot via two allocation lines → one claim
    # whose qty is the SUM, not the last-write-wins overwrite the old SQL did.
    allocations = [
        {"source_row": "ROW-A1", "material_code": "M-A", "material_index": 0,
         "claimed_qty": "5", "declaration_no": "D1", "line_no": "1", "customs_code": "C1"},
        {"source_row": "ROW-A1", "material_code": "M-A", "material_index": 0,
         "claimed_qty": "3", "declaration_no": "D1", "line_no": "1", "customs_code": "C1"},
    ]
    rows, new_allocs_by_claim, new_by_lot = _build_claim_rows("growatt", "case1", "TP1", allocations)
    assert len(rows) == 1
    # row tuple: (..., claimed_qty at index 7, ...)
    assert rows[0][7] == Decimal("8")
    assert list(new_allocs_by_claim.values())[0]["qty"] == Decimal("8")
    assert new_by_lot["ROW-A1"] == Decimal("8")


def test_build_claim_rows_keeps_distinct_lots_separate():
    allocations = [
        {"source_row": "ROW-A1", "material_code": "M-A", "claimed_qty": "5"},
        {"source_row": "ROW-A2", "material_code": "M-A", "claimed_qty": "3"},
    ]
    rows, _, new_by_lot = _build_claim_rows("growatt", "case1", "TP1", allocations)
    assert len(rows) == 2
    assert new_by_lot["ROW-A1"] == Decimal("5")
    assert new_by_lot["ROW-A2"] == Decimal("3")


def test_build_claim_rows_skips_blank_lot_and_nonpositive_qty():
    allocations = [
        {"source_row": "", "material_code": "M-A", "claimed_qty": "5"},
        {"source_row": "ROW-A1", "material_code": "M-A", "claimed_qty": "0"},
        {"source_row": "ROW-A1", "material_code": "M-A", "claimed_qty": "4"},
    ]
    rows, _, _ = _build_claim_rows("growatt", "case1", "TP1", allocations)
    assert len(rows) == 1
    assert rows[0][7] == Decimal("4")
