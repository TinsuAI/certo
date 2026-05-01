"""Real client data smoke tests — gated behind DATA_HUB_REAL_DATA_DIR.

Real BCCT/Danh Mục/BOM files are too big and proprietary to commit. Point at
a directory of them via env var and these tests will run; otherwise skipped.

Layout expected:
    $DATA_HUB_REAL_DATA_DIR/
        growatt/
            bcct_nk_2026_t3-t4.xls           # legacy .xls — known to fail today
            bcct_xk_2026_t3-t4.xls
            bom_2025_full.xlsm
        dke/
            bcct_2025_official.xls
            danh_muc_nvl_sp.xls
        dothanh/
            bcct_e31.xls
            bcct_e62.xls
            danh_muc.xlsx
        danh_muc_co/
            danh_muc_npl.xls
            danh_muc_sp.xls

Each test asserts what we *currently* observe (legacy .xls fails, real BOM
opens but doesn't fit any profile, BCCT parser falsely matches BOM as 197K
rows, etc.). When fixes land, tests flip from xfail to assertions.

Run:
    DATA_HUB_REAL_DATA_DIR=/path/to/real/data uv run pytest tests/test_real_data_external.py -v
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.parsers.bcct import parse_bcct_workbook, BcctParseError
from app.parsers.bom import parse_bom_workbook, BomParseError
from app.parsers.materials import parse_materials_workbook, MaterialsParseError

REAL_DIR_ENV = "DATA_HUB_REAL_DATA_DIR"
real_dir = os.environ.get(REAL_DIR_ENV)
pytestmark = pytest.mark.skipif(
    not real_dir, reason=f"set {REAL_DIR_ENV} to a directory of real client files",
)
ROOT = Path(real_dir) if real_dir else None


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


def test_growatt_settlement_workbook_has_bcct_sheets():
    """The Growatt 'BOM' .xlsm is actually a settlement workbook with multiple
    BCCT-shaped sheets (NK/NK2/XK/X-N/Save) — confirmed during 2026-05-03
    parser audit. The BCCT parser correctly accepts these via the tightened
    declaration_no AND registration_date gate. This test pins the row count
    so a regression to either (a) accepting too few or (b) leaking through
    LVC/RVC summary sheets becomes visible.
    """
    p = _opt("growatt/bom_2025_full.xlsm")
    if p is None:
        pytest.skip("missing growatt/bom_2025_full.xlsm")
    blob = p.read_bytes()
    rows = parse_bcct_workbook(blob)
    # Observed 2026-05-03: 197,356 rows across the 5 BCCT-shaped sheets.
    # Tolerance ±5% to allow for small datasource churn.
    assert 187_000 <= len(rows) <= 207_000, f"got {len(rows)}"
