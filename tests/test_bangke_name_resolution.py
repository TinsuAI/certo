"""Bảng kê NVL name resolution — regression for the "xuất bảng kê bị trống" bug.

Root cause: the fast origin paths (/calculate, load-bom, edited-sheet recalc,
whole-case preview) built materials from the CO-stock snapshot, which carries
material_rows=[]. With an empty catalog, NVL names resolved ONLY from a matched
CO-stock lot, so every NVL that did not match a lot exported with a BLANK name.

Fix has two parts:
  A. _ensure_origin_material_rows() falls back to a catalog-only pull when the
     fast source context omitted material_rows.
  B. origin_material_from_bom_row() falls back to ANY matched CO-stock/BCCT
     candidate's description/hs when the catalog has no entry for the code.
"""
from __future__ import annotations

from decimal import Decimal

import app.routers.co_case as co_case
from app.web.co_case_context import origin_material_from_bom_row


class _FakeDataHub:
    def __init__(self, rows):
        self._rows = rows
        self.calls = 0

    def list_materials(self, client_id, **_query):
        self.calls += 1
        return list(self._rows)


def test_ensure_origin_material_rows_passthrough():
    existing = [{"material_code": "A", "name": "Có sẵn"}]
    assert co_case._ensure_origin_material_rows({"id": "c1"}, existing) == existing


def test_ensure_origin_material_rows_falls_back_to_catalog(monkeypatch):
    co_case._MATERIAL_CATALOG_CACHE.clear()
    fake = _FakeDataHub([
        {"material_code": "X1", "name": "Tên X1", "category": "nvl"},
        {"material_code": "TP1", "name": "Thành phẩm", "category": "tp"},
    ])
    monkeypatch.setattr(co_case.portfolio_service, "data_hub", fake, raising=False)

    rows = co_case._ensure_origin_material_rows({"id": "client-fallback"}, [])
    codes = {r["material_code"]: r["name"] for r in rows}
    assert codes == {"X1": "Tên X1"}  # category 'tp' excluded
    assert fake.calls == 1


def test_ensure_origin_material_rows_caches_per_client(monkeypatch):
    co_case._MATERIAL_CATALOG_CACHE.clear()
    fake = _FakeDataHub([{"material_code": "X1", "name": "Tên X1"}])
    monkeypatch.setattr(co_case.portfolio_service, "data_hub", fake, raising=False)
    co_case._ensure_origin_material_rows({"id": "client-cache"}, [])
    co_case._ensure_origin_material_rows({"id": "client-cache"}, [])
    assert fake.calls == 1  # second call served from the TTL cache


def _stock(**extra):
    base = {
        "source_row": "ROW-1",
        "material_code": "NVL-1",
        "allocation_code": "NVL-1",
        "customs_item_code": "NVL-1",
        "import_declaration_no": "D100",
        "registration_date": "2026-04-21",
        "line_no": "1",
        "value_currency": "VND",
        "currency": "VND",
        "unit_value": "1000",
        "remaining_qty": "100",
        "available_qty": "100",
        "exchange_rate_to_vnd": "1",
        "exchange_rate_source": "vnd_native",
    }
    base.update(extra)
    return base


def test_name_and_hs_fall_back_to_stock_when_catalog_empty():
    # Catalog has NO entry for NVL-1 (material_index empty) and the BOM row has
    # no name — exactly the bug condition. The matched CO-stock lot carries the
    # real name + HS, so the bảng kê row must NOT be blank.
    row = {"material_code": "NVL-1", "qty_per": "2"}
    stock_pool = {"NVL-1": [_stock(material_description="NVL-1#&Vòng đệm thép", hs_code="73182200")]}
    material = origin_material_from_bom_row(
        row, Decimal("1"), {}, stock_pool, product_code="TP1", product_name="SP",
    )
    assert material["material_description"] == "NVL-1#&Vòng đệm thép"
    assert material["hs_code"] == "73182200"
    assert material["material_name_missing"] is False


def test_name_still_blank_when_no_catalog_and_no_stock():
    # No catalog, no stock match → genuinely nameless (flag stays True). The fix
    # must not fabricate a name out of nothing.
    row = {"material_code": "GHOST", "qty_per": "1"}
    material = origin_material_from_bom_row(
        row, Decimal("1"), {}, {}, product_code="TP1", product_name="SP",
    )
    assert material["material_description"] == ""
    assert material["material_name_missing"] is True
