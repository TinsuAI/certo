"""Whole-case shared-pool allocation for substituted materials (concern verification).

The concern: when material A is substituted to A1 in some sheets, A1's available
stock for a substituted sheet MUST account for A1 ALSO being consumed elsewhere in
the same lô — by other sheets that use A1 natively, or by other substitutions to
A1. Formally:

    A1 available for a substituted sheet
        = A1 total stock − A1 consumed by EARLIER sheets (native or substituted)

These tests prove the SERVER allocation enforces this via one shared per-material
pool consumed sequentially in product order. They are pure/preview: no ledger
writes, no persistence.

Two seams are exercised:
  * `case_stock_preview_summary` — canonical (no overrides): two sheets using A1
    natively draw from ONE decrementing pool (needs no stubbing).
  * `allocate_whole_case_preview` — override-aware: the real `material_overrides`
    substitution path (`recalculate_origin_sheet_edits` in product order), which is
    what /preview-stock-all, /calculate-all and /bulk-substitute's re-preview all run.
    Its per-sheet recompute rebuilds a fresh pool and REPLAYS earlier sheets'
    consumption (`apply_existing_origin_product_consumption`), so a substituted A1
    still sees only the leftover.
"""
from __future__ import annotations

from decimal import Decimal


# --------------------------------------------------------------------------- #
# Shared fixtures / builders                                                   #
# --------------------------------------------------------------------------- #
def _match(code: str, qty: str = "3") -> dict:
    return {
        "item_code": code,
        "description": f"SP {code}",
        "quantity": qty,
        "customs_value": "100",
        "currency": "USD",
        "material_identity": {
            "resolution_status": "resolved",
            "product_kind": "tp",
            "bom_product_code": code,
        },
    }


def _a1_stock(remaining) -> list[dict]:
    """One eligible CO-stock lot of material A1 with `remaining` qty."""
    return [{
        "material_code": "A1",
        "allocation_code": "A1",
        "available_qty": str(remaining),
        "remaining_qty": str(remaining),
        "eligibility_status": "active",
        "allocation_code_status": "resolved",
        "unit_value": "5",
        "currency": "USD",
        # identity fields the replay path (allocation_line_matches_stock) keys on
        "source_row": "S1",
        "import_declaration_no": "IMP1",
        "line_no": "1",
    }]


def _bom_row(product_code: str, version_id: str, material_code: str) -> dict:
    return {
        "product_code": product_code,
        "product_version_id": version_id,
        "material_code": material_code,
        "qty_per": "2",
        "uom": "kg",
    }


def _workspace(p1_material: str, p2_material: str) -> dict:
    """Two-product BOM workspace: P1 uses `p1_material`, P2 uses `p2_material`."""
    rows = [
        _bom_row("P1", "bv-1", p1_material),
        _bom_row("P2", "bv-2", p2_material),
    ]
    product_versions = [
        {"product_code": "P1", "product_version_id": "bv-1", "rows": [rows[0]]},
        {"product_code": "P2", "product_version_id": "bv-2", "rows": [rows[1]]},
    ]
    version_pvs = [
        {"product_code": "P1", "product_version_id": "bv-1"},
        {"product_code": "P2", "product_version_id": "bv-2"},
    ]
    aggregate = {"version_id": "agg-1", "rows": rows, "product_versions": version_pvs}
    return {
        "latest_version": aggregate,
        "versions": [aggregate],
        "latest_rows": rows,
        "product_versions": product_versions,
        "product_version_options_by_code": {
            "P1": [product_versions[0]],
            "P2": [product_versions[1]],
        },
    }


# --------------------------------------------------------------------------- #
# Arm 1 — native shared pool (canonical path, no stubbing).                    #
# Two sheets use A1 natively; A1 lot covers P1 alone. The SECOND sheet must be #
# short because the pool decrements sequentially.                             #
# --------------------------------------------------------------------------- #
def test_native_shared_pool_second_sheet_sees_leftover():
    from app.web.co_case_context import (
        case_stock_preview_summary,
        case_shortfall_rollup,
        prepare_case_origin_products,
        decimal_value,
    )
    case = {"origin_product_order": ["P1", "P2"]}
    matches = [_match("P1"), _match("P2")]  # each needs 3 * 2 = 6 of A1 (12 total)
    ws = _workspace("A1", "A1")

    # A1 lot = 8: enough for P1 (6) but leaves only 2 for P2 (needs 6).
    summary = case_stock_preview_summary(case, matches, ws, {}, [], _a1_stock(8))
    assert summary["missing_codes"] == ["A1"]
    # ONLY P2 is short — P1 consumed A1 first from the shared pool.
    assert [p["product_code"] for p in summary["products"]] == ["P2"]
    p2_a1 = summary["products"][0]["materials"][0]
    assert p2_a1["material_code"] == "A1"
    # Available reflects the leftover (8 total − 6 consumed by P1), NOT raw 8.
    assert decimal_value(p2_a1["available_qty"]) == Decimal("2")
    assert decimal_value(p2_a1["shortage_qty"]) == Decimal("4")

    # Material-centric rollup: A1 needed 12 across the lô, available 8, short 4.
    allocated = prepare_case_origin_products(
        {"origin_product_order": ["P1", "P2"]}, matches, ws, {}, [], _a1_stock(8),
        preserve_existing=False,
    )
    roll = case_shortfall_rollup(allocated)
    assert [m["material_code"] for m in roll["materials"]] == ["A1"]
    a1 = roll["materials"][0]
    assert decimal_value(a1["needed"]) == Decimal("12")
    assert decimal_value(a1["available"]) == Decimal("8")
    assert decimal_value(a1["short_qty"]) == Decimal("4")


def test_native_shared_pool_no_shortage_when_ample():
    """Positive control: ample A1 covers both native sheets, none short."""
    from app.web.co_case_context import case_stock_preview_summary
    case = {"origin_product_order": ["P1", "P2"]}
    matches = [_match("P1"), _match("P2")]  # 12 total
    summary = case_stock_preview_summary(case, matches, _workspace("A1", "A1"), {}, [], _a1_stock(100))
    assert summary["missing_codes"] == []
    assert summary["products"] == []


# --------------------------------------------------------------------------- #
# Arm 2 — REAL material_overrides substitution (override-aware whole-case path)#
# P1 uses A1 natively; P2 uses A but is substituted A->A1. The substituted     #
# sheet must account for A1 already consumed by the earlier native sheet.      #
# --------------------------------------------------------------------------- #
def _substitution_case() -> dict:
    """Case where P1 uses A1 natively and P2 carries a saved A->A1 override.

    P2 keeps its native material A in `materials` (index 0); the override at that
    index swaps the code to A1 — exactly the shape `bulk_substitute_route` persists.
    """
    return {
        "origin_product_order": ["P1", "P2"],
        "products": [
            {"code": "P1", "name": "SP P1", "quantity": "3", "fob": "100", "currency": "USD",
             "materials": [{"material_code": "A1", "uom": "kg", "bom_qty_per": "2"}]},
            {"code": "P2", "name": "SP P2", "quantity": "3", "fob": "100", "currency": "USD",
             "materials": [{"material_code": "A", "uom": "kg", "bom_qty_per": "2",
                            "material_description": "Mat A"}]},
        ],
        "origin_sheet_states": {
            "P2": {"material_overrides": {"0": {"material_code": "A1", "norm_per_unit": "2", "uom": "kg"}}},
        },
    }


def _run_whole_case(monkeypatch, a1_qty):
    """Drive allocate_whole_case_preview with a controlled A1 lot.

    The override sheet's recompute (recalculate_origin_sheet_edits) pulls stock from
    the materialized snapshot; stub it to return the SAME lot the non-override sheet
    allocates against so the two per-sheet pools are consistent (source parity).
    """
    from app.routers import co_case as R
    from app.web.co_case_context import case_missing_stock_summary, case_shortfall_rollup

    stock = _a1_stock(a1_qty)
    monkeypatch.setattr(R, "_calculate_stock_rows_from_snapshot", lambda client: [dict(r) for r in stock])
    monkeypatch.setattr(R, "_ensure_origin_material_rows", lambda client, rows: list(rows or []))

    context = {
        "origin_source_context": {"invoice_matches": [_match("P1"), _match("P2")], "material_rows": []},
        "bom_workspace": _workspace("A1", "A"),
        "recommended_form_lane": {},
    }
    allocated = R.allocate_whole_case_preview({"id": "growatt"}, _substitution_case(), context, stock, None)
    by_code = {p["code"]: p for p in allocated["products"]}
    return allocated, by_code, case_missing_stock_summary(allocated), case_shortfall_rollup(allocated)


def test_substituted_sheet_accounts_for_material_consumed_by_earlier_native_sheet(monkeypatch):
    """THE concern. A1 lot = 8 covers P1's native 6; P2's SUBSTITUTED A1 must be
    short because only 2 remain in the shared lô pool — not fully covered off raw 8."""
    from app.web.co_case_context import decimal_value
    allocated, by_code, miss, roll = _run_whole_case(monkeypatch, 8)

    # The override took effect: P2's row is now A1, not A.
    p2_mat = by_code["P2"]["materials"][0]
    assert p2_mat["material_code"] == "A1"

    # P1 (native, earlier) is covered; P2 (substituted, later) is SHORT.
    assert by_code["P1"]["materials"][0]["allocation_status"] == "covered"
    assert p2_mat["allocation_status"] == "shortage"

    # Load-bearing: P2's A1 availability = 8 − 6 (P1's consumption), NOT 8.
    assert decimal_value(p2_mat["available_qty"]) == Decimal("2")
    assert decimal_value(p2_mat["allocation_shortage_qty"]) == Decimal("4")

    # Whole-lô rollup reflects A1's TOTAL consumption across both sheets.
    assert miss["missing_codes"] == ["A1"]
    a1 = next(m for m in roll["materials"] if m["material_code"] == "A1")
    assert decimal_value(a1["needed"]) == Decimal("12")
    assert decimal_value(a1["available"]) == Decimal("8")
    assert decimal_value(a1["short_qty"]) == Decimal("4")
    assert "P2" in a1["short_products"]
    assert "P1" not in a1["short_products"]


def test_substituted_sheet_covered_when_stock_ample(monkeypatch):
    """Positive control: ample A1 → P2's substituted A1 is covered, and its
    available reflects sequential consumption (100 − 6 from P1 = 94)."""
    from app.web.co_case_context import decimal_value
    allocated, by_code, miss, roll = _run_whole_case(monkeypatch, 100)
    p2_mat = by_code["P2"]["materials"][0]
    assert p2_mat["material_code"] == "A1"
    assert p2_mat["allocation_status"] == "covered"
    assert decimal_value(p2_mat["available_qty"]) == Decimal("94")
    assert miss["missing_codes"] == []
    assert roll["materials"] == []


def test_substitute_itself_short_still_listed_in_rollup(monkeypatch):
    """The 'substitute is itself short' case: A1 lot = 3 cannot even cover one
    sheet. Both sheets are short and the rollup STILL lists A1 (not silently
    resolved); short units sum across the lô."""
    from app.web.co_case_context import decimal_value
    allocated, by_code, miss, roll = _run_whole_case(monkeypatch, 3)

    assert by_code["P1"]["materials"][0]["allocation_status"] == "shortage"
    assert by_code["P2"]["materials"][0]["allocation_status"] == "shortage"
    assert miss["missing_codes"] == ["A1"]

    a1 = next(m for m in roll["materials"] if m["material_code"] == "A1")
    assert decimal_value(a1["needed"]) == Decimal("12")
    assert decimal_value(a1["available"]) == Decimal("3")   # only the single lot
    assert decimal_value(a1["short_qty"]) == Decimal("9")   # 12 needed − 3 available
    assert set(a1["short_products"]) == {"P1", "P2"}
