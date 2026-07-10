"""supplier_key — the single shared whitespace-only normalization of consignee_name.

Introduced by VN-origin ticket #6 (plumb lot origin fields); reused verbatim by the
supplier-evidence store (ticket #11): the curation write path and the Tính read path
MUST produce identical keys or flags silently stop matching rows.

Whitespace-only by design (ADR 2026-07-11): collapse runs, strip, and insert a space
before "(" — the two moves proven on real BCCT data (136 raw names → 132 suppliers).
No case folding, no diacritics stripping, no branch/parent merging: the same real
supplier under two spellings is flagged twice, explicitly.
"""
from __future__ import annotations

from app.supplier_identity import supplier_key


def test_collapses_whitespace_runs_and_strips():
    assert supplier_key(" CONG TY  TNHH\tMINGJIE   VIET NAM ") == "CONG TY TNHH MINGJIE VIET NAM"


def test_inserts_space_before_open_paren():
    # Real Johnson pair: MYS GROUP(VIET NAM) vs MYS GROUP (VIET NAM) is ONE company.
    assert supplier_key("MYS GROUP(VIET NAM)") == "MYS GROUP (VIET NAM)"
    assert supplier_key("MYS GROUP(VIET NAM)") == supplier_key("MYS GROUP (VIET NAM)")


def test_distinct_legal_entities_stay_distinct():
    # The HK namesake is a different legal entity and must never collapse into the
    # VN company (no-auto-merge decision).
    assert supplier_key("CONG TY TNHH MINGJIE VIET NAM") != supplier_key("MINGJIE INDUSTRIAL (HK) LIMITED")


def test_no_case_folding():
    assert supplier_key("Cong Ty Tnhh Abc") == "Cong Ty Tnhh Abc"


def test_empty_and_none_yield_empty_key():
    assert supplier_key("") == ""
    assert supplier_key(None) == ""
    assert supplier_key("   ") == ""


def test_idempotent():
    key = supplier_key("MYS  GROUP(VIET NAM)")
    assert supplier_key(key) == key
