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


@pytest.mark.parametrize("rel", [
    "growatt/bcct_nk_2026_t3-t4.xls",
    "growatt/bcct_xk_2026_t3-t4.xls",
    "dke/bcct_2025_official.xls",
    "dothanh/bcct_e31.xls",
    "dothanh/bcct_e62.xls",
    "danh_muc_co/danh_muc_npl.xls",
    "danh_muc_co/danh_muc_sp.xls",
    "dke/danh_muc_nvl_sp.xls",
])
def test_legacy_xls_currently_fails(rel):
    """openpyxl can't read legacy .xls. Documents P0: the hub today rejects
    every real BCCT/Danh Mục we have. Fix needs xlrd or in-flight conversion."""
    p = _opt(rel)
    if p is None:
        pytest.skip(f"missing real fixture: {rel}")
    blob = p.read_bytes()
    # Try BCCT first (it's the most permissive matcher); expect ParseError
    # with the openpyxl-zip-format message.
    with pytest.raises((BcctParseError, MaterialsParseError, BomParseError)) as exc:
        parse_bcct_workbook(blob)
    msg = str(exc.value)
    assert "Cannot open workbook" in msg or "not a zip file" in msg.lower() \
        or "no valid workbook part" in msg.lower(), \
        f"unexpected error: {msg}"


def test_growatt_real_bom_xlsm_does_not_fit_any_profile():
    """Real Growatt 51MB BOM .xlsm opens but doesn't match any of our 3 profiles.

    When the Chinese-headers fix or a 4th profile lands, flip this assertion.
    """
    p = _opt("growatt/bom_2025_full.xlsm")
    if p is None:
        pytest.skip("missing growatt/bom_2025_full.xlsm")
    blob = p.read_bytes()
    failed = []
    succeeded = []
    for prof in ("manual_flat", "growatt_multi_workbook", "johnson_sap_exploded"):
        try:
            products = parse_bom_workbook(blob, profile=prof)
            succeeded.append((prof, len(products), sum(len(v) for v in products.values())))
        except BomParseError as e:
            failed.append((prof, str(e)[:80]))
    assert not succeeded, (
        f"Real Growatt BOM unexpectedly parsed under: {succeeded}. "
        f"Update test if a profile fix landed."
    )
    assert len(failed) == 3


@pytest.mark.xfail(reason="P0: BCCT parser accepts BOM-shaped workbook (real Growatt 51MB → 197K junk rows)")
def test_growatt_real_bom_should_not_match_as_bcct():
    """Trap: BCCT parser matches a BOM workbook (Mã NVL aliases to customs_code).
    Today produces ~197K rows; should raise BcctParseError instead.
    """
    p = _opt("growatt/bom_2025_full.xlsm")
    if p is None:
        pytest.skip("missing growatt/bom_2025_full.xlsm")
    blob = p.read_bytes()
    with pytest.raises(BcctParseError):
        parse_bcct_workbook(blob)
