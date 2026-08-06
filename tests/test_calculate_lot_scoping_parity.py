"""P1 perf: the single-sheet /calculate snapshot read is scoped to the lots the
sheet's product/materials can reach (`case_stock_scope_codes` ->
`_calculate_stock_rows_from_snapshot(scope_codes=...)`), instead of copying +
overlaying the whole ~60k-row client snapshot each calc.

Acceptance bar is CORRECTNESS PARITY, not speed: the scoped read must produce a
byte-identical allocation/tồn result to the unscoped read for the same product.
A lot whose `co_stock_key_candidates` miss every scoped code lands only in
allocation-pool buckets the calc never queries, so dropping it cannot change any
allocation. Filtering preserves the cached rows' relative order, so the retained
lots keep the same `_allocation_sequence` ordering the pool sort relies on even
though their absolute indices shift once the noise lots are gone.
"""
from __future__ import annotations

from decimal import Decimal

import app.web.co_case_context as ctx
from app.web.co_case_context import (
    case_stock_scope_codes,
    decimal_value,
    prepare_case_origin_sheet,
    _calculate_stock_rows_from_snapshot,
)

CLIENT = {"id": "scope-parity"}


# --------------------------------------------------------------------------- #
# Builders                                                                     #
# --------------------------------------------------------------------------- #
def _lot(source_row: str, material_code: str, remaining: str, line_no: str = "1", decl: str = "IMP1") -> dict:
    return {
        "material_code": material_code,
        "allocation_code": material_code,
        "available_qty": remaining,
        "remaining_qty": remaining,
        "eligibility_status": "active",
        "allocation_code_status": "resolved",
        "unit_value": "5",
        "currency": "USD",
        "source_row": source_row,
        "import_declaration_no": decl,
        "line_no": line_no,
    }


def _snapshot() -> list[dict]:
    """Two A1 lots the sheet needs, interleaved with six unrelated NOISE lots.

    The interleave is deliberate: A1 lots sit at absolute indices 2 and 5 in the
    full snapshot but 0 and 1 once scoped — so a scoping bug that leaned on the
    absolute `_allocation_sequence` would diverge here."""
    return [
        _lot("N0", "NOISE-0", "9"),
        _lot("N1", "NOISE-1", "9"),
        _lot("S1", "A1", "4"),
        _lot("N2", "NOISE-2", "9"),
        _lot("N3", "NOISE-3", "9"),
        _lot("S2", "A1", "4"),
        _lot("N4", "NOISE-4", "9"),
        _lot("N5", "NOISE-5", "9"),
    ]


def _bom_row(material_code: str) -> dict:
    return {
        "product_code": "P1",
        "product_version_id": "bv-1",
        "material_code": material_code,
        "qty_per": "2",
        "uom": "kg",
    }


def _workspace(material_code: str) -> dict:
    rows = [_bom_row(material_code)]
    product_versions = [{"product_code": "P1", "product_version_id": "bv-1", "rows": [rows[0]]}]
    aggregate = {
        "version_id": "agg-1",
        "rows": rows,
        "product_versions": [{"product_code": "P1", "product_version_id": "bv-1"}],
    }
    return {
        "latest_version": aggregate,
        "versions": [aggregate],
        "latest_rows": rows,
        "product_versions": product_versions,
        "product_version_options_by_code": {"P1": [product_versions[0]]},
    }


def _match(code: str = "P1", qty: str = "3") -> dict:
    return {
        "item_code": code,
        "description": f"SP {code}",
        "quantity": qty,
        "customs_value": "100",
        "currency": "USD",
        "material_identity": {"resolution_status": "resolved", "product_kind": "tp", "bom_product_code": code},
    }


def _case() -> dict:
    return {
        "origin_product_order": ["P1"],
        "products": [{
            "code": "P1",
            "bom_product_code": "P1",
            "name": "SP P1",
            "quantity": "3",
            "fob": "100",
            "currency": "USD",
            "materials": [],
        }],
    }


def _install_snapshot(monkeypatch, snapshot: list[dict]) -> None:
    monkeypatch.setattr(ctx.co_stock_materializer, "read_co_stock_rows_cached", lambda client_id: snapshot)
    monkeypatch.setattr(ctx, "_co_stock_snapshot_is_fresh", lambda client_id: True)
    monkeypatch.setattr(ctx.co_stock_ledger, "used_qty_by_lot", lambda client_id: {})


# --------------------------------------------------------------------------- #
# scope computation                                                            #
# --------------------------------------------------------------------------- #
def test_case_stock_scope_codes_gathers_bom_and_product_material_codes():
    case = {
        "products": [
            {"code": "P0", "materials": [{"internal_material_code": "IM0"}, {"material_code": "M0"}]},
            {"code": "P1", "materials": [{"material_code": "A1"}]},
        ],
    }
    # Without a workspace: only the product materials (both key spellings).
    assert case_stock_scope_codes(case) == {"IM0", "M0", "A1"}
    # With a workspace: also the selected BOM rows' material codes.
    scope = case_stock_scope_codes(_case(), _workspace("A1"))
    assert scope == {"A1"}


# --------------------------------------------------------------------------- #
# scoped read                                                                  #
# --------------------------------------------------------------------------- #
def test_scoped_read_drops_unrelated_lots_keeps_relevant_in_order(monkeypatch):
    _install_snapshot(monkeypatch, _snapshot())
    scoped = _calculate_stock_rows_from_snapshot(CLIENT, scope_codes={"A1"})
    assert [r["source_row"] for r in scoped] == ["S1", "S2"]  # noise gone, order preserved


def test_scope_none_or_empty_returns_full_snapshot_unchanged(monkeypatch):
    _install_snapshot(monkeypatch, _snapshot())
    full_default = _calculate_stock_rows_from_snapshot(CLIENT)
    full_none = _calculate_stock_rows_from_snapshot(CLIENT, scope_codes=None)
    full_empty = _calculate_stock_rows_from_snapshot(CLIENT, scope_codes=set())
    expected = ["N0", "N1", "S1", "N2", "N3", "S2", "N4", "N5"]
    assert [r["source_row"] for r in full_default] == expected
    assert [r["source_row"] for r in full_none] == expected
    assert [r["source_row"] for r in full_empty] == expected


# --------------------------------------------------------------------------- #
# allocation parity — the acceptance bar                                       #
# --------------------------------------------------------------------------- #
def test_scoped_read_allocation_is_byte_identical_to_full_read(monkeypatch):
    _install_snapshot(monkeypatch, _snapshot())
    ws = _workspace("A1")
    matches = [_match("P1")]

    scope_codes = case_stock_scope_codes(_case(), ws)
    assert scope_codes == {"A1"}

    full_rows = _calculate_stock_rows_from_snapshot(CLIENT)  # unscoped: whole snapshot
    scoped_rows = _calculate_stock_rows_from_snapshot(CLIENT, scope_codes=scope_codes)
    assert len(full_rows) == 8 and len(scoped_rows) == 2  # scoping really narrowed the read

    full_result = prepare_case_origin_sheet(_case(), "P1", matches, ws, {}, [], full_rows)
    scoped_result = prepare_case_origin_sheet(_case(), "P1", matches, ws, {}, [], scoped_rows)

    # Sanity: the sheet actually allocated (6 needed = 4 from S1 + 2 from S2).
    p1 = next(p for p in full_result["products"] if p["code"] == "P1")
    lines = p1["materials"][0]["allocation_lines"]
    assert [l["source_row"] for l in lines] == ["S1", "S2"]
    assert [l["allocated_qty"] for l in lines] == ["4", "2"]
    assert decimal_value(p1["materials"][0].get("shortage_qty") or "0") == Decimal("0")

    # Parity: scoped allocation == full allocation, byte for byte.
    assert scoped_result == full_result
