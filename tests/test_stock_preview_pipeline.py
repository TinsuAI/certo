"""case_stock_preview_summary — run stock for the WHOLE case once (preview,
non-committing) and aggregate 'mã thiếu tồn' (#13a, Slice B).

Verifies the allocate-all → aggregate pipeline: insufficient CO stock surfaces
as a shortage in the summary; sufficient stock does not.
"""
from __future__ import annotations


def _workspace():
    rows = [{"product_code": "P1", "product_version_id": "bv-1", "material_code": "NVL-1", "qty_per": "2", "uom": "kg"}]
    return {
        "latest_version": {"version_id": "agg-1", "product_versions": [{"product_code": "P1", "product_version_id": "bv-1"}]},
        "versions": [{
            "version_id": "agg-1",
            "rows": rows,
            "product_versions": [{"product_code": "P1", "product_version_id": "bv-1"}],
        }],
        "latest_rows": [],
        "product_versions": [{"product_code": "P1", "product_version_id": "bv-1", "rows": rows}],
        "product_version_options_by_code": {"P1": [{"product_code": "P1", "product_version_id": "bv-1", "rows": rows}]},
    }


def _match():
    return {
        "item_code": "P1",
        "description": "Sản phẩm 1",
        "quantity": "3",  # needs 3 × qty_per 2 = 6 of NVL-1
        "customs_value": "100",
        "currency": "USD",
        "material_identity": {"resolution_status": "resolved", "product_kind": "tp", "bom_product_code": "P1"},
    }


def _stock(remaining):
    return [{
        "material_code": "NVL-1",
        "allocation_code": "NVL-1",
        "available_qty": str(remaining),
        "remaining_qty": str(remaining),
        "eligibility_status": "active",
        "allocation_code_status": "resolved",
        "unit_value": "5",
        "currency": "USD",
    }]


def test_insufficient_stock_surfaces_shortage():
    from app.main import case_stock_preview_summary
    summary = case_stock_preview_summary({}, [_match()], _workspace(), {}, [], _stock(2))
    assert summary["missing_codes"] == ["NVL-1"]
    assert summary["products"][0]["product_code"] == "P1"
    assert summary["products"][0]["materials"][0]["material_code"] == "NVL-1"


def test_empty_stock_is_shortage():
    from app.main import case_stock_preview_summary
    summary = case_stock_preview_summary({}, [_match()], _workspace(), {}, [], [])
    assert summary["missing_codes"] == ["NVL-1"]


def test_sufficient_stock_no_shortage():
    from app.main import case_stock_preview_summary
    summary = case_stock_preview_summary({}, [_match()], _workspace(), {}, [], _stock(10))
    assert summary["missing_codes"] == []
    assert summary["products"] == []
