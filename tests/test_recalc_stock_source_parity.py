"""Regression: override-recalc (Lưu / post-substitute "Tính bảng kê") must
allocate tồn from the SAME trừ-lùi-FOLDED + live-ledger snapshot the sheet-lock
validates against (co_stock_ledger.record_sheet_lock), NOT the raw
list_bcct_by_codes pull (remaining_qty == quantity, un-folded, blind to
other-case claims).

Before the fix the edited-sheet path allocated against raw BCCT (over-stated
tồn); "Chốt" then failed with a spurious "không chốt được ... vì vượt tồn ở N
lot" on every lot carrying a trừ-lùi baseline — while an unedited sheet (which
calculates from the folded snapshot) locked fine. Repro: johnson-vn
co-case-a4e1dbbdb0f5 sheet MFW0507-39 (47 lots).
"""
from __future__ import annotations

import app.routers.co_case as co_case


def _case_with_substitute() -> dict:
    return {
        "products": [
            {
                "code": "MFW0507-39",
                "bom_product_code": "MFW0507-39",
                "finished_hs": "8501",
                "materials": [
                    {"material_code": "ORIG-NO-STOCK", "bom_qty_per": "1", "uom": "kg"},
                ],
            }
        ],
        "origin_sheet_states": {
            "MFW0507-39": {
                "material_overrides": {
                    "1": {"material_code": "SUB-WITH-STOCK", "norm_per_unit": "1"},
                },
            }
        },
    }


def test_recalc_allocates_from_folded_snapshot_not_raw_bcct(monkeypatch):
    folded_snapshot = [
        {
            "source_row": "import-row-aaaa",
            "material_code": "SUB-WITH-STOCK",
            "available_qty": "100",
            "remaining_qty": "10",  # folded down from 100 by the trừ-lùi baseline
            "import_declaration_no": "D1",
            "line_no": "1",
        }
    ]
    monkeypatch.setattr(co_case, "_calculate_stock_rows_from_snapshot", lambda client, scope_codes=None: folded_snapshot)

    def _must_not_pull(*args, **kwargs):
        raise AssertionError("recalc must not pull RAW BCCT when a folded snapshot exists")

    monkeypatch.setattr(co_case.portfolio_service, "list_bcct_by_codes", _must_not_pull)

    captured: dict = {}

    def _capture_pool(case, matches, stock_rows, **kwargs):
        captured["stock_rows"] = stock_rows
        return {}

    monkeypatch.setattr(co_case, "case_allocation_pool", _capture_pool)

    co_case.recalculate_origin_sheet_edits({"id": "johnson-vn"}, _case_with_substitute(), "MFW0507-39")

    # The folded snapshot (remaining_qty == real tồn) is what reached allocation
    # — the same numbers record_sheet_lock checks, so calculate and lock agree.
    assert captured["stock_rows"] == folded_snapshot


def test_recalc_falls_back_to_raw_pull_only_when_snapshot_empty(monkeypatch):
    # Cold start: no materialized snapshot (no fold exists yet) -> the legacy
    # narrow BCCT pull still runs so a fresh client can calculate.
    monkeypatch.setattr(co_case, "_calculate_stock_rows_from_snapshot", lambda client, scope_codes=None: None)
    monkeypatch.setattr(
        co_case, "co_case_source_context_cached", lambda client, case: {"material_rows": [], "stock_rows": []}
    )

    pulled: dict = {}

    def _narrow(client_id, codes, **kwargs):
        pulled["codes"] = list(codes)
        return []

    monkeypatch.setattr(co_case.portfolio_service, "list_bcct_by_codes", _narrow)
    monkeypatch.setattr(co_case, "case_allocation_pool", lambda *a, **k: {})

    co_case.recalculate_origin_sheet_edits({"id": "johnson-vn"}, _case_with_substitute(), "MFW0507-39")

    assert pulled.get("codes") == ["SUB-WITH-STOCK"]
