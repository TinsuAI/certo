"""#18 (T0) — a saved allocation line must rebind to its lot after the client's
`allocation_code.strategy` changes.

`allocation_code` is derived and mutable (per client config) yet persisted on the
saved line. When the strategy flips (`same_as_customs_code` -> `description_regex`),
the re-derived lot `allocation_code` no longer equals the saved line's old value, so
the persisted-line match must NOT key on `allocation_code` — it identifies the lot by
`source_row` (the co_stock_rows PK component, strategy-invariant) and, for older
snapshots without it, `import_declaration_no` + `import_line_no`.
"""
from __future__ import annotations

from decimal import Decimal

from app.web.co_case_context import (
    allocation_line_matches_stock,
    apply_existing_origin_product_consumption,
    stock_for_existing_allocation_line,
)


def _lot(**over) -> dict:
    lot = {
        "material_code": "M1",
        "allocation_code": "008.0006100",  # re-derived under description_regex
        "available_qty": "10",
        "remaining_qty": "10",
        "source_row": "S1",
        "import_declaration_no": "IMP1",
        "line_no": "1",
        "unit_value": "5",
        "currency": "USD",
        "_eligibility_ok": True,
    }
    lot.update(over)
    return lot


# --------------------------------------------------------------------------- #
# Unit — allocation_line_matches_stock                                          #
# --------------------------------------------------------------------------- #
def test_rebinds_when_allocation_code_rederived_but_source_row_matches():
    """THE bug: old saved allocation_code differs from the re-derived lot value,
    but source_row identifies the same lot → must still match."""
    line = {
        "source_row": "S1",
        "import_declaration_no": "IMP1",
        "import_line_no": "1",
        "allocation_code": "DIOT",  # old same_as_customs_code value
    }
    assert allocation_line_matches_stock(line, _lot()) is True


def test_rebinds_by_declaration_and_line_when_no_source_row():
    """Older snapshot without source_row: declaration_no + line_no identify the lot;
    a differing allocation_code must not veto the rebind."""
    line = {
        "import_declaration_no": "IMP1",
        "import_line_no": "1",
        "allocation_code": "DIOT",
    }
    assert allocation_line_matches_stock(line, _lot()) is True


def test_no_match_when_source_row_differs():
    """No false positive: a genuinely different lot (source_row differs) must not
    match even if some other field happens to align."""
    line = {"source_row": "S2", "import_declaration_no": "IMP1", "import_line_no": "1"}
    assert allocation_line_matches_stock(line, _lot()) is False


def test_no_match_without_any_identity_overlap():
    """A line carrying no lot-identity field (only the dropped allocation_code) must
    not spuriously bind to a lot."""
    line = {"allocation_code": "DIOT"}
    assert allocation_line_matches_stock(line, _lot()) is False


def test_still_matches_unchanged_config():
    """Regression: when nothing changed (allocation_code equal too), it still binds."""
    line = {
        "source_row": "S1",
        "import_declaration_no": "IMP1",
        "import_line_no": "1",
        "allocation_code": "008.0006100",
    }
    assert allocation_line_matches_stock(line, _lot()) is True


# --------------------------------------------------------------------------- #
# Integration — the replay path decrements the rebound lot                      #
# --------------------------------------------------------------------------- #
def test_saved_line_rebinds_and_consumes_lot_after_strategy_change():
    """`apply_existing_origin_product_consumption` must reconnect the saved line to
    its lot and decrement it, even though the strategy change re-derived the lot's
    allocation_code."""
    product = {
        "materials": [{
            "material_code": "M1",
            "allocation_lines": [{
                "source_row": "S1",
                "import_declaration_no": "IMP1",
                "import_line_no": "1",
                "allocation_code": "DIOT",  # pre-change value on the saved line
                "allocated_qty": "4",
            }],
        }],
    }
    stock_pool = {"M1": [_lot()]}

    assert stock_for_existing_allocation_line(stock_pool, "M1", product["materials"][0]["allocation_lines"][0])

    apply_existing_origin_product_consumption(product, stock_pool)
    # 10 available − 4 consumed by the rebound saved line.
    assert stock_pool["M1"][0]["_allocation_remaining_qty"] == Decimal("6")
