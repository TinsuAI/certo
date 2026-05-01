"""Drive every fixture through its parser; assert known outcomes.

Two fixture roots:

- `tests/fixtures/manual_test/` — 18 curated `.xlsx` from `barry-CO-bom-data`
  designed for the CO app's manual upload flow (catalog full/partial, BCCT
  overlap, BOM duplicate, etc.). Most map cleanly onto Data Hub parsers; a
  few don't (different app concept) — flagged below.

- `tests/fixtures/edge_cases/` — synthetic, hub-specific bug traps and
  boundary cases (`tests/fixtures/edge_cases/_generate.py`).

When a parser bug is fixed, flip the corresponding entry from
`xfail`/`error_contains` to a numeric `expected_rows` and re-run. That keeps
the corpus honest without skipping it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.parsers.bcct import parse_bcct_workbook, BcctParseError
from app.parsers.bom import parse_bom_workbook, BomParseError
from app.parsers.code_mappings import parse_code_mappings_workbook  # noqa: F401
from app.parsers.materials import parse_materials_workbook, MaterialsParseError

ROOT = Path(__file__).parent / "fixtures"
MANUAL = ROOT / "manual_test"
EDGE = ROOT / "edge_cases"


# (label, file, parser_name, kwargs, expected): expected is one of
#   {"rows": int}                   parser succeeds with exactly this row count
#   {"rows_at_least": int}          parser succeeds with >= rows
#   {"products": int, "rows": int}  bom result: product count + total rows
#   {"raises": ExceptionType, "match": str_or_None}  parser must raise
#   {"xfail": str}                  known bug — explain the gap
CASES: list[tuple] = [
    # ---- manual_test: Growatt catalog ----
    ("growatt_dsnvl_full_missing", MANUAL / "01-growatt-ds-nvl-full-missing-demo-npl-003.xlsx",
     "materials", {}, {"rows": 2}),
    ("growatt_dsnvl_partial_edit", MANUAL / "02-growatt-ds-nvl-partial-edit-demo-npl-001.xlsx",
     "materials", {}, {"rows": 1}),
    ("growatt_dssp_full_no_hq", MANUAL / "03-growatt-ds-sp-full-products.xlsx",
     "materials", {}, {"rows": 2}),  # P1 fixed 2026-05-03: product_code-only catalog accepted

    # ---- manual_test: Do Thanh BCCT ----
    ("dothanh_bcct_import_pcs", MANUAL / "10-do-thanh-bcct-import-tk001-pcs.xlsx",
     "bcct", {}, {"rows": 1}),
    ("dothanh_bcct_overlap_add_tk002", MANUAL / "11-do-thanh-bcct-overlap-add-tk002.xlsx",
     "bcct", {}, {"rows": 1}),
    ("dothanh_bcct_pce_alias", MANUAL / "12-do-thanh-bcct-reupload-tk001-pce-alias.xlsx",
     "bcct", {}, {"rows": 1}),
    ("dothanh_bcct_kg_conflict", MANUAL / "13-do-thanh-bcct-reupload-tk001-kg-conflict.xlsx",
     "bcct", {}, {"rows": 1}),
    ("dothanh_bcct_qty_conflict", MANUAL / "14-do-thanh-bcct-reupload-tk001-qty-conflict.xlsx",
     "bcct", {}, {"rows": 1}),
    ("dothanh_bcct_mixed_directions", MANUAL / "15-do-thanh-bcct-mixed-import-export.xlsx",
     "bcct", {}, {"rows": 2}),

    # ---- manual_test: Growatt BOM (manual_flat profile) ----
    ("growatt_bom_no_change", MANUAL / "20-growatt-bom-direct-no-change.xlsx",
     "bom", {"profile": "manual_flat"}, {"products": 2, "rows": 4}),
    ("growatt_bom_changed_qty", MANUAL / "21-growatt-bom-direct-changed-qty.xlsx",
     "bom", {"profile": "manual_flat"}, {"products": 2, "rows": 4}),
    ("growatt_bom_full_retire_pv01", MANUAL / "22-growatt-bom-direct-full-retire-pv01.xlsx",
     "bom", {"profile": "manual_flat"}, {"products": 1, "rows": 2}),
    ("growatt_bom_partial_pv00", MANUAL / "23-growatt-bom-direct-partial-pv00-only.xlsx",
     "bom", {"profile": "manual_flat"}, {"products": 1, "rows": 2}),
    ("growatt_bom_duplicate_row", MANUAL / "24-growatt-bom-duplicate-row.xlsx",
     "bom", {"profile": "manual_flat"}, {"products": 2, "rows": 5}),

    # ---- manual_test: Growatt technical BOM (Chinese template) ----
    ("growatt_technical_chinese_review", MANUAL / "25-growatt-technical-needs-flatten-review.xlsx",
     "bom", {"profile": "manual_flat"}, {"products": 1, "rows": 1}),
    ("growatt_technical_chinese_accept", MANUAL / "26-growatt-technical-accept-as-flat.xlsx",
     "bom", {"profile": "manual_flat"}, {"products": 1, "rows": 1}),

    # ---- manual_test: Johnson SAP ----
    ("johnson_sap_leaf_only", MANUAL / "30-johnson-technical-sap-leaf-only.xlsx",
     "bom", {"profile": "johnson_sap_exploded"}, {"products": 1, "rows": 2}),

    # ---- manual_test: not applicable (CO-app concept, not hub) ----
    # 00-growatt-demo-input.xlsx is a CO case workbook (Case/Documents/Products/Materials
    # sheets). Hub has no concept of cases. Excluded from corpus.

    # ---- edge_cases: hub-specific bug traps ----
    ("edge_growatt_bom_chinese", EDGE / "growatt_bom_chinese_headers.xlsx",
     "bom", {"profile": "manual_flat"}, {"products": 2, "rows": 3}),
    ("edge_growatt_sp_no_hq", EDGE / "growatt_sp_catalog_no_hq.xlsx",
     "materials", {}, {"rows": 2}),
    ("edge_johnson_sap_english", EDGE / "johnson_sap_english_headers.xlsx",
     "bom", {"profile": "johnson_sap_exploded"}, {"products": 1, "rows": 2}),
    ("edge_empty_workbook_bcct", EDGE / "empty_workbook.xlsx",
     "bcct", {}, {"raises": BcctParseError, "match": None}),
    ("edge_empty_workbook_materials", EDGE / "empty_workbook.xlsx",
     "materials", {}, {"raises": MaterialsParseError, "match": None}),
    ("edge_empty_workbook_bom", EDGE / "empty_workbook.xlsx",
     "bom", {"profile": "manual_flat"}, {"raises": BomParseError, "match": None}),
    ("edge_headers_in_row_5", EDGE / "headers_in_row_5.xlsx",
     "bcct", {}, {"rows": 1}),
    ("edge_bom_uploaded_as_bcct", EDGE / "bom_workbook_uploaded_as_bcct.xlsx",
     "bcct", {}, {"raises": BcctParseError, "match": None}),
    ("edge_dke_synthetic_bcct", EDGE / "dke_bcct_synthetic.xlsx",
     "bcct", {}, {"rows": 3}),

    # ---- edge_cases: legacy .xls (OLE format) — exercises xlrd adapter ----
    ("edge_legacy_xls_bcct", EDGE / "legacy_xls_bcct.xls",
     "bcct", {}, {"rows": 2}),
    ("edge_legacy_xls_materials", EDGE / "legacy_xls_materials.xls",
     "materials", {}, {"rows": 2}),
]


PARSERS = {
    "materials": parse_materials_workbook,
    "bcct": parse_bcct_workbook,
    "bom": parse_bom_workbook,
}


def _ids(cases):
    return [c[0] for c in cases]


@pytest.mark.parametrize("label,path,parser,kwargs,expected", CASES, ids=_ids(CASES))
def test_fixture(label, path, parser, kwargs, expected):
    assert path.exists(), f"Missing fixture: {path}"
    blob = path.read_bytes()
    fn = PARSERS[parser]

    if "xfail" in expected:
        # Track as xfail so the corpus runs green while bugs are open.
        # When fixed, flip the entry to {"rows": N} (or similar).
        try:
            result = fn(blob, **kwargs)
        except Exception:
            pytest.xfail(expected["xfail"])
        else:
            # If the parser starts succeeding (after a fix), force a hard fail
            # so the test author updates the expectation.
            pytest.fail(
                f"{label}: parser unexpectedly succeeded ({_describe(result)}). "
                f"Update CASES entry to assert exact row count."
            )

    if "raises" in expected:
        exc_type = expected["raises"]
        match = expected.get("match")
        with pytest.raises(exc_type, match=match):
            fn(blob, **kwargs)
        return

    result = fn(blob, **kwargs)
    if "rows" in expected and parser != "bom":
        assert len(result) == expected["rows"], f"{label}: got {len(result)} rows"
    elif "rows_at_least" in expected:
        assert len(result) >= expected["rows_at_least"]
    elif "products" in expected:
        assert len(result) == expected["products"], f"{label}: got {len(result)} products"
        total = sum(len(v) for v in result.values())
        assert total == expected["rows"], f"{label}: got {total} bom rows"
    else:
        pytest.fail(f"{label}: malformed expected: {expected}")


def _describe(result) -> str:
    if isinstance(result, list):
        return f"list[{len(result)}]"
    if isinstance(result, dict):
        return f"dict[{len(result)} products, {sum(len(v) for v in result.values())} rows]"
    return str(type(result))
