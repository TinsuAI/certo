"""Stock-first substitute discovery (#2, ADR 2026-07-08).

Candidates are built FROM the CO-stock snapshot (grouped at the logical-material
grain) LEFT-JOINed to the catalog — so an NVL in stock but absent from the DH
catalog is findable. A stock-sourced candidate is fully declarable (it has a BCCT
import match by construction): metadata comes from the stock lot, the catalog join
only enriches. `stock_only` is a display flag, NOT a blocker.
"""
from __future__ import annotations


def _lot(**kw):
    base = {
        "customs_item_code": "",
        "allocation_code": "",
        "allocation_code_status": "resolved",
        "material_code": "",
        "material_description": "",
        "hs_code": "",
        "remaining_qty": "0",
    }
    base.update(kw)
    # mirror the materializer: material_code == allocation_code when usable
    if not base["material_code"] and base["allocation_code"] and base["allocation_code_status"] == "resolved":
        base["material_code"] = base["allocation_code"]
    return base


def _codes(cands):
    return [c["material_code"] for c in cands]


def test_stock_only_code_is_discoverable_with_lot_metadata():
    from app.substitute_discovery import build_stock_first_candidates

    lot = _lot(
        allocation_code="AL-100",
        customs_item_code="AL-100",
        material_description="Nhôm tấm 1mm",
        hs_code="7606.11.00",
        remaining_qty="500",
    )
    cands = build_stock_first_candidates([lot], catalog_index={})

    assert _codes(cands) == ["AL-100"]
    c = cands[0]
    assert c["stock_only"] is True           # not in catalog...
    assert c["catalog_matched"] is False
    assert c["name"] == "Nhôm tấm 1mm"       # ...but name/HS come from the lot
    assert c["hs_code"] == "7606.11.00"
    assert c["total_remaining_qty"] == "500"


def test_catalog_match_enriches_and_clears_stock_only():
    from app.substitute_discovery import build_stock_first_candidates

    lot = _lot(allocation_code="AL-100", customs_item_code="AL-100", material_description="from lot", remaining_qty="10")
    catalog = {"AL-100": {"name": "Aluminium sheet (canonical)", "hs_code": "7606.11.00", "customs_relevance": ""}}

    c = build_stock_first_candidates([lot], catalog_index=catalog)[0]
    assert c["catalog_matched"] is True
    assert c["stock_only"] is False
    assert c["name"] == "Aluminium sheet (canonical)"


def test_lots_with_same_allocation_code_group_into_one_candidate():
    from app.substitute_discovery import build_stock_first_candidates

    lots = [
        _lot(allocation_code="AL-100", customs_item_code="C1", remaining_qty="300"),
        _lot(allocation_code="AL-100", customs_item_code="C2", remaining_qty="200"),
    ]
    cands = build_stock_first_candidates(lots, catalog_index={})
    assert _codes(cands) == ["AL-100"]
    assert cands[0]["total_remaining_qty"] == "500"
    assert cands[0]["lot_count"] == 2


def test_unresolved_allocation_falls_back_to_customs_item_code():
    from app.substitute_discovery import build_stock_first_candidates

    lot = _lot(
        allocation_code="",
        allocation_code_status="requires_review",
        customs_item_code="DECL-777",
        material_description="chưa chuẩn hoá",
        remaining_qty="42",
    )
    c = build_stock_first_candidates([lot], catalog_index={})[0]
    assert c["material_code"] == "DECL-777"
    assert c["stock_only"] is True


def test_excludes_the_material_being_replaced():
    from app.substitute_discovery import build_stock_first_candidates

    lots = [
        _lot(allocation_code="AL-100", customs_item_code="AL-100", remaining_qty="10"),
        _lot(allocation_code="CU-200", customs_item_code="CU-200", remaining_qty="10"),
    ]
    cands = build_stock_first_candidates(lots, catalog_index={}, exclude_codes={"AL-100"})
    assert _codes(cands) == ["CU-200"]


def test_query_filters_by_code_or_name():
    from app.substitute_discovery import build_stock_first_candidates

    lots = [
        _lot(allocation_code="AL-100", customs_item_code="AL-100", material_description="Nhôm", remaining_qty="10"),
        _lot(allocation_code="CU-200", customs_item_code="CU-200", material_description="Đồng", remaining_qty="10"),
    ]
    assert _codes(build_stock_first_candidates(lots, catalog_index={}, query="cu-2")) == ["CU-200"]
    assert _codes(build_stock_first_candidates(lots, catalog_index={}, query="nhôm")) == ["AL-100"]


def test_stock_first_ordering_by_remaining_desc():
    from app.substitute_discovery import build_stock_first_candidates

    lots = [
        _lot(allocation_code="SMALL", customs_item_code="SMALL", remaining_qty="5"),
        _lot(allocation_code="BIG", customs_item_code="BIG", remaining_qty="900"),
    ]
    assert _codes(build_stock_first_candidates(lots, catalog_index={})) == ["BIG", "SMALL"]
