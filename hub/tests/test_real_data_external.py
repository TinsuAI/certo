"""Real client data smoke tests — gated behind DATA_HUB_REAL_DATA_DIR.

Real BCCT / BQD / BOM / Danh Mục files are too big and proprietary to commit.
Point at a directory of them via env var and these tests will run; otherwise
skipped.

Layout expected (organized by company; only tested files listed):
    $DATA_HUB_REAL_DATA_DIR/
        growatt/
            bcct_nk_2026_t3-t4.xls
            bcct_xk_2026_t3-t4.xls
            bom_tp.xlsx       # 963 KB — Chinese SAP shape, real
            bom_btp.xlsx      # 462 KB — same shape, semi-finished
            bqd_tp.xlsx       # 14 KB  — Vietnamese N-to-N (TP)
            bqd_nvl.xlsx      # 170 KB — Vietnamese N-to-N (NVL)
        dke/
            bcct_2025_official.xls
            bqd.xls           # 143 KB — multi-sheet legacy .xls
        dothanh/
            bcct_e31.xls
            bcct_e62.xls
        johnson/
            bom_sap.xlsx      # synthetic SAP-leaf-only fixture

Every test is a positive assertion. When parser bugs A/B/C/D are fixed,
the suite goes green. Today the Growatt BOM + DKE BQD cases fail — that
is the red TDD step.

Run:
    DATA_HUB_REAL_DATA_DIR=/path/to/real/data uv run pytest tests/test_real_data_external.py -v
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from hub.app.parsers.bcct import parse_bcct_workbook
from hub.app.parsers.bom import parse_bom_workbook
from hub.app.parsers.code_mappings import parse_code_mappings_workbook

REAL_DIR_ENV = "DATA_HUB_REAL_DATA_DIR"
real_dir = os.environ.get(REAL_DIR_ENV)
pytestmark = pytest.mark.skipif(
    not real_dir, reason=f"set {REAL_DIR_ENV} to a directory of real client files",
)
ROOT = Path(real_dir) if real_dir else None

# Growatt product/material codes look like 'DV01.D401720' / 'B700.0084201' —
# alphanumeric with at least one dot, capital prefix, digits, dot, more
# alphanumerics. The garbage-resolution path that compounding bugs A+C used
# to produce gave brand strings like 'FARATRONIC' or '菲尼克斯' which fail
# this shape — so this regex is the correctness guard.
GROWATT_CODE_SHAPE = re.compile(r"^[A-Z]{1,4}[0-9]+\.[A-Z0-9]+")


def _opt(rel: str) -> Path | None:
    """Return the path if it exists; else None (caller skips)."""
    if ROOT is None:
        return None
    p = ROOT / rel
    return p if p.exists() else None


@pytest.mark.parametrize("rel,parser,min_rows", [
    ("growatt/bcct_nk_2026_t3-t4.xls", "bcct", 100),
    ("growatt/bcct_xk_2026_t3-t4.xls", "bcct", 50),
    ("dke/bcct_2025_official.xls", "bcct", 100),
    ("dothanh/bcct_e31.xls", "bcct", 10),
    ("dothanh/bcct_e62.xls", "bcct", 10),
])
def test_legacy_xls_bcct_loads(rel, parser, min_rows):
    """Legacy .xls BCCT files load via the xlrd adapter and parse to plausible
    row counts. Documents that the .xls fix is intact for real data."""
    p = _opt(rel)
    if p is None:
        pytest.skip(f"missing real fixture: {rel}")
    blob = p.read_bytes()
    rows = parse_bcct_workbook(blob)
    assert len(rows) >= min_rows, f"{rel}: only {len(rows)} rows parsed"


# Out of scope: the Growatt 51MB .xlsm is the CO app's working workbook
# (staff processing CO requests). Hub doesn't ingest it; CO owns it. Hub's
# upload types are BCCT, DS NVL, DS SP, BOM — none of which this file is.
# If uploaded to a hub slot it would parse misleadingly; that's a misuse
# rather than a parser bug.


# ─────────────────────────────────────────────────────────────────────────
# BOM real-data smoke tests
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel,profile,min_products,min_rows", [
    # Synthetic Johnson SAP fixture — passes today.
    ("johnson/bom_sap.xlsx",  "johnson_sap_exploded", 1,  2),
    # Real Growatt BOMs — single-sheet flat with Chinese headers + leading STT
    # column. Will parse cleanly via manual_flat profile after Bug A (header_row
    # alias-aware scoring) and Bug C (drop pass-2 substring) land.
    ("growatt/bom_tp.xlsx",   "manual_flat",          10, 100),
    ("growatt/bom_btp.xlsx",  "manual_flat",          10, 100),
])
def test_bom_real_data_parses(rel, profile, min_products, min_rows):
    """Each real BOM workbook produces enough products + rows to be plausible."""
    p = _opt(rel)
    if p is None:
        pytest.skip(f"missing real fixture: {rel}")
    blob = p.read_bytes()
    products = parse_bom_workbook(blob, profile=profile)
    assert len(products) >= min_products, f"{rel}: only {len(products)} products"
    total_rows = sum(len(rows) for rows in products.values())
    assert total_rows >= min_rows, f"{rel}: only {total_rows} rows"


@pytest.mark.parametrize("rel", [
    "growatt/bom_tp.xlsx",
    "growatt/bom_btp.xlsx",
])
def test_bom_growatt_real_data_codes_look_real(rel):
    """Real-shape guard: the majority of product codes parsed from a Growatt BOM
    must match Growatt's actual code shape. Catches the Bug A + Bug C compound
    where empty-header substring match silently maps `product_code` to a brand
    column, producing values like 'FARATRONIC' that pass len/count checks but
    fail real-shape regex.
    """
    p = _opt(rel)
    if p is None:
        pytest.skip(f"missing real fixture: {rel}")
    blob = p.read_bytes()
    products = parse_bom_workbook(blob, profile="manual_flat")
    n_real = sum(1 for code in products if GROWATT_CODE_SHAPE.match(code))
    assert n_real >= max(5, len(products) // 2), (
        f"{rel}: only {n_real}/{len(products)} product codes look Growatt-shaped"
    )


def test_bom_growatt_real_data_has_qty():
    """At least some BOM rows must carry a positive qty_per_unit. The Growatt
    BTP file has 标准用量 (qty) populated for ~half its rows. Today this assertion
    happens to be satisfied via garbage column resolution — but after Bug A+C
    fix it must remain true via the correct 标准用量 column."""
    p = _opt("growatt/bom_tp.xlsx")
    if p is None:
        pytest.skip("missing real fixture: growatt/bom_tp.xlsx")
    products = parse_bom_workbook(p.read_bytes(), profile="manual_flat")
    n_with_qty = sum(
        1 for rows in products.values() for r in rows
        if r.get("qty_per_unit", 0) > 0
    )
    assert n_with_qty >= 5, f"only {n_with_qty} rows carry qty>0"


# ─────────────────────────────────────────────────────────────────────────
# BQD (code mappings) real-data smoke tests
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel,min_rows", [
    ("growatt/bqd_tp.xlsx",  50),    # 73 actual
    ("growatt/bqd_nvl.xlsx", 2000),  # 2819 actual
    # DKE multi-sheet legacy .xls — passes after Bug B (alias additions for
    # 'Mã ERP' / 'Mã NPL/TP') lands. File has ~190 NPL + ~85 SP rows.
    ("dke/bqd.xls",          150),
])
def test_bqd_real_data_parses(rel, min_rows):
    p = _opt(rel)
    if p is None:
        pytest.skip(f"missing real fixture: {rel}")
    blob = p.read_bytes()
    rows, _ = parse_code_mappings_workbook(blob)
    assert len(rows) >= min_rows, f"{rel}: only {len(rows)} mappings"
    # Sanity: every row has both codes set.
    assert all(r["internal_code"] and r["customs_code"] for r in rows)


def test_bqd_growatt_nvl_carries_n_to_n_mappings():
    """Growatt NVL file is N-to-N: a single internal_code can map to
    multiple customs_codes. The parser must NOT collapse them.
    """
    p = _opt("growatt/bqd_nvl.xlsx")
    if p is None:
        pytest.skip("missing real fixture: growatt/bqd_nvl.xlsx")
    rows, _ = parse_code_mappings_workbook(p.read_bytes())
    by_internal: dict[str, set[str]] = {}
    for r in rows:
        by_internal.setdefault(r["internal_code"], set()).add(r["customs_code"])
    n_with_multiple = sum(1 for cs in by_internal.values() if len(cs) > 1)
    assert n_with_multiple > 0, "expected at least one 1-to-N mapping"
