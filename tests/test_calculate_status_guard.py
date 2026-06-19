"""Root-cause guard (#13c): /calculate must not advance an empty/no-BOM sheet to
"calculated". calculated_sheet_status keeps a missing_bom result at "bom_loaded"
(non-lockable / non-exportable); any real result becomes "calculated".
"""
from __future__ import annotations


def test_missing_bom_stays_bom_loaded():
    from app.routers.co_case import calculated_sheet_status
    assert calculated_sheet_status({"lvc_status": "missing_bom"}) == "bom_loaded"


def test_real_results_become_calculated():
    from app.routers.co_case import calculated_sheet_status
    for lvc in ("pass", "fail", "review", "missing_value", ""):
        assert calculated_sheet_status({"lvc_status": lvc}) == "calculated", lvc
