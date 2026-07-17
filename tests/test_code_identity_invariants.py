"""Code-overload invariants (#20 / 2026-07-16 code-vocabulary audit).

Two identities are copied 1:1 across a spelling boundary in the CO stock
pipeline. Renaming the persisted columns was deliberately skipped (T5), so these
tests lock the overloads instead — they fail the moment a consumer treats the
two spellings as independent.

  INV-1  A claim's `customs_code` is the source lot's `customs_item_code`.
         Chain: co_stock_rows.customs_item_code
                  -> stock_allocation_line() customs_material_code   (co_case_context.py)
                  -> claim dict customs_code                         (routers/co_case.py:205)
                  -> co_stock_claims.customs_code                    (co_stock_ledger.py 1:1)
         A divergence mis-keys claims against snapshot lots.

  INV-2  On a `co_stock_rows` row, `material_code` holds the DERIVED
         `allocation_code`, not the catalog/customs code. Any consumer that
         reads stock-row `material_code` as catalog identity regresses.

Dictionary: .ai/GLOSSARY.md -> "Material & lot codes".
"""
from __future__ import annotations

from decimal import Decimal

from app.co_stock_derivation import co_stock_rows_from_bcct
from app.web.co_case_context import stock_allocation_line


REGEX_CONFIG = {
    "co_stock": {"lot_policy": "line_level"},
    "bcct": {"eligible_import_declaration_types": []},
    "allocation_code": {
        "strategy": "description_regex",
        "description_regex": r"\(([A-Z0-9][A-Z0-9._/-]{3,})\)",
        "fallback": "same_as_customs_code",
    },
}


def _bcct_row(**extra):
    base = {
        "direction": "import",
        "transaction_key": "tk-1",
        "declaration_no": "NK-1",
        "declaration_type": "E15",
        "line_no": "1",
        "item_code": "CUST-100",
        "description": "Ống đồng (001.0009900)",
        "hs_code": "74111000",
        "quantity": "100",
        "unit": "PCE",
        "customs_value": "1000",
        "currency": "VND",
        "origin_country": "CHINA",
    }
    base.update(extra)
    return base


def _stock(**extra):
    base = {
        "source_row": "ROW-1",
        "customs_item_code": "CUST-100",
        "allocation_code": "001.0009900",
        "import_declaration_no": "NK-1",
        "registration_date": "2026-04-21",
        "line_no": "1",
        "value_currency": "VND",
        "currency": "VND",
        "unit_value": "1000",
        "remaining_qty": "100",
        "available_qty": "100",
        "exchange_rate_to_vnd": "1",
    }
    base.update(extra)
    return base


# --- INV-1: claim customs_code == source lot customs_item_code ---

def test_allocation_line_customs_code_is_the_lot_customs_item_code():
    # The claim (routers/co_case.py:205) reads this line's customs_material_code
    # into co_stock_claims.customs_code, so this hop pins the whole 1:1 chain.
    line = stock_allocation_line(
        _stock(customs_item_code="CUST-100", allocation_code="001.0009900"),
        allocated_qty=Decimal("1"),
        available_qty=Decimal("10"),
        bom_row={},
        material={},
    )
    assert line["customs_material_code"] == "CUST-100"


def test_allocation_line_customs_code_is_not_the_allocation_code():
    # customs_item_code (customs identity) and allocation_code (BOM-match spelling)
    # are distinct owners — the adapter must not conflate them.
    line = stock_allocation_line(
        _stock(customs_item_code="CUST-100", allocation_code="001.0009900"),
        allocated_qty=Decimal("1"),
        available_qty=Decimal("10"),
        bom_row={},
        material={},
    )
    assert line["customs_material_code"] != line["allocation_code"]


# --- INV-2: co_stock_rows.material_code holds the derived allocation_code ---

def test_stock_row_material_code_is_the_derived_allocation_code():
    rows = co_stock_rows_from_bcct([_bcct_row()], REGEX_CONFIG)
    assert len(rows) == 1
    row = rows[0]
    # regex strategy derives allocation_code from the description paren, so it
    # diverges from the catalog customs code — proving material_code follows the
    # DERIVED code, not the catalog identity.
    assert row["allocation_code"] == "001.0009900"
    assert row["customs_item_code"] == "CUST-100"
    assert row["material_code"] == row["allocation_code"]
    assert row["material_code"] != row["customs_item_code"]


def test_unusable_stock_row_has_blank_material_code_but_keeps_customs_identity():
    # A lot that can't back a BOM line drops material_code but still carries its
    # customs identity — the two fields are independent by construction.
    row = co_stock_rows_from_bcct(
        [_bcct_row(description="no code in parens")],
        {**REGEX_CONFIG, "allocation_code": {"strategy": "description_regex",
                                             "description_regex": r"\(([A-Z0-9][A-Z0-9._/-]{3,})\)",
                                             "fallback": "requires_review"}},
    )[0]
    assert row["material_code"] == ""
    assert row["customs_item_code"] == "CUST-100"
