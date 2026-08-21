"""Unit tests for scripts/preprocess_mau16_to_xlsx.transform_rows().

Covers the row-level transform of Mẫu 16 raw data:
- forward-fill product code across continuation rows
- skip rows where NVL is blank (between product blocks)
- stop at signature footer
- coerce qty to float, default 0 on parse error
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from preprocess_mau16_to_xlsx import transform_rows  # noqa: E402


def _row(stt, tp_code, nvl_code, nvl_uom, qty):
    """9-col raw row helper (mirrors Mẫu 16 layout)."""
    return [stt, tp_code, "tp_name", "tp_uom", nvl_code, "nvl_name", nvl_uom, qty, "note"]


def test_forward_fill_within_block():
    raw = [
        _row("1.0", "P-1", "M-1", "SETS", 1.0),
        _row("",    "",    "M-2", "PIECES", 0.5),
        _row("",    "",    "M-3", "KILO-GRAMMES", 0.25),
    ]
    out, products = transform_rows(raw)
    assert products == {"P-1"}
    assert out == [
        ("P-1", "M-1", "SETS", 1.0),
        ("P-1", "M-2", "PIECES", 0.5),
        ("P-1", "M-3", "KILO-GRAMMES", 0.25),
    ]


def test_new_block_resets_product():
    raw = [
        _row("1.0", "P-1", "M-1", "SETS", 1.0),
        _row("",    "",    "M-2", "SETS", 1.0),
        _row("2.0", "P-2", "M-3", "PIECES", 2.0),
        _row("",    "",    "M-4", "PIECES", 2.5),
    ]
    out, products = transform_rows(raw)
    assert products == {"P-1", "P-2"}
    assert [(o[0], o[1]) for o in out] == [
        ("P-1", "M-1"), ("P-1", "M-2"),
        ("P-2", "M-3"), ("P-2", "M-4"),
    ]


def test_signature_footer_stops_iteration():
    raw = [
        _row("1.0", "P-1", "M-1", "SETS", 1.0),
        _row("",    "",    "M-2", "SETS", 1.0),
        _row("",    "",    "",    "",     ""),
        _row("NGƯỜI LẬP", "", "", "", ""),
        _row("(Ký, ghi rõ họ tên)", "", "", "", ""),
    ]
    out, products = transform_rows(raw)
    assert products == {"P-1"}
    assert len(out) == 2


def test_blank_nvl_skipped():
    raw = [
        _row("1.0", "P-1", "M-1", "SETS", 1.0),
        _row("",    "",    "",    "",     ""),  # blank between rows
        _row("",    "",    "M-2", "SETS", 1.0),
    ]
    out, _ = transform_rows(raw)
    assert len(out) == 2
    assert out[0][1] == "M-1"
    assert out[1][1] == "M-2"


def test_qty_non_numeric_emits_zero():
    raw = [
        _row("1.0", "P-1", "M-1", "SETS", "not-a-number"),
    ]
    out, _ = transform_rows(raw)
    assert out == [("P-1", "M-1", "SETS", 0.0)]


def test_no_preceding_tp_skipped():
    """Material row before any TP block — skip with warning, no emit."""
    raw = [
        _row("",    "",    "M-orphan", "SETS", 1.0),
        _row("1.0", "P-1", "M-1",      "SETS", 1.0),
    ]
    out, products = transform_rows(raw)
    assert products == {"P-1"}
    assert out == [("P-1", "M-1", "SETS", 1.0)]


def test_partial_continuation_after_two_blocks():
    """Real-world: most Mẫu 16 products have 5-10 NVL rows. Ensure
    forward-fill works across 3 blocks of varying sizes."""
    raw = [
        _row("1.0", "P-A", "M-A1", "SETS", 1.0),
        _row("",    "",    "M-A2", "SETS", 0.5),
        _row("2.0", "P-B", "M-B1", "PIECES", 1.0),
        _row("3.0", "P-C", "M-C1", "KILO-GRAMMES", 0.001),
        _row("",    "",    "M-C2", "KILO-GRAMMES", 0.002),
        _row("",    "",    "M-C3", "KILO-GRAMMES", 0.003),
    ]
    out, products = transform_rows(raw)
    assert products == {"P-A", "P-B", "P-C"}
    counts = {p: 0 for p in products}
    for prod, *_ in out:
        counts[prod] += 1
    assert counts == {"P-A": 2, "P-B": 1, "P-C": 3}
