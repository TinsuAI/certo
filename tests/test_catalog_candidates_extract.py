"""Per-row classification for BCCT rows + BOM edges + code_mappings.

The 4 BCCT cases from brief D2:
1. dual (NB != HQ) — emit (hq,'hq') + (nb,'nb') for each NB
2. unified (NB == HQ overlap) — emit (hq,'unified') only
3. HQ only (no paren match) — emit (hq, 'hq' if dual_system else 'unified')
4. NB only (customs_code='.' or empty) — emit (nb,'nb') for each NB

Plus BOM and code_mappings sources.
"""
from __future__ import annotations

import re2

from app.parsers.client_parser_rules import CompiledRule
from app.parsers.catalog_candidates import (
    candidates_from_bcct_row,
    candidates_from_bom_codes,
    candidates_from_code_mapping_pairs,
)


def _paren_rule() -> CompiledRule:
    """Growatt-style paren capture rule."""
    return CompiledRule(
        rule_id=1, output_field="internal_code", priority=10,
        source_field="goods_name", match_group=1,
        match_action="capture", no_match_action="next_rule",
        compiled=re2.compile(r"\(([\d\.\w\-]+)\)"),
        notes="paren-extract",
    )


# ── BCCT per-row 4 cases ──────────────────────────────────────────────────


def test_bcct_dual_nb_neq_hq():
    """Growatt typical: customs_code='DAUNOI', goods_name has '(019.0023800)'."""
    row = {"customs_code": "DAUNOI",
           "goods_name": "DAUNOI#&Đầu nối...(019.0023800)"}
    out = candidates_from_bcct_row(row, rules=[_paren_rule()],
                                    has_dual_system=True)
    assert sorted(out) == sorted([("DAUNOI", "hq"), ("019.0023800", "nb")])


def test_bcct_unified_nb_eq_hq_overlap():
    """Same string in customs_code AND parens → emit single 'unified' (D2 case 2)."""
    row = {"customs_code": "PV01.0117500",
           "goods_name": "BIENTAN#&Bộ biến tần (PV01.0117500)"}
    out = candidates_from_bcct_row(row, rules=[_paren_rule()],
                                    has_dual_system=True)
    assert out == [("PV01.0117500", "unified")]


def test_bcct_hq_only_no_paren_match_dual_system():
    """customs_code present, no paren in goods_name. dual_system → kind='hq'."""
    row = {"customs_code": "DOV", "goods_name": "DOV#&Hàng no parens"}
    out = candidates_from_bcct_row(row, rules=[_paren_rule()],
                                    has_dual_system=True)
    assert out == [("DOV", "hq")]


def test_bcct_hq_only_no_paren_single_system():
    """No rules, no mappings → unified."""
    row = {"customs_code": "1000527370",
           "goods_name": "1000527370#&Tấm đỡ"}
    out = candidates_from_bcct_row(row, rules=[], has_dual_system=False)
    assert out == [("1000527370", "unified")]


def test_bcct_nb_only_dot_customs_code():
    """customs_code='.' (Growatt placeholder) — skip HQ, emit only NB."""
    row = {"customs_code": ".", "goods_name": "anything (019.0079001)"}
    out = candidates_from_bcct_row(row, rules=[_paren_rule()],
                                    has_dual_system=True)
    assert out == [("019.0079001", "nb")]


def test_bcct_empty_customs_code_with_paren():
    """customs_code='' or None — skip HQ, emit NB."""
    row = {"customs_code": "", "goods_name": "x (019.X)"}
    out = candidates_from_bcct_row(row, rules=[_paren_rule()],
                                    has_dual_system=True)
    assert out == [("019.X", "nb")]


def test_bcct_no_codes_returns_empty():
    """Row with neither customs_code nor paren-match — noise, skip."""
    row = {"customs_code": ".", "goods_name": "bare text no parens"}
    out = candidates_from_bcct_row(row, rules=[_paren_rule()],
                                    has_dual_system=True)
    assert out == []


def test_bcct_multi_paren_emits_all_nbs():
    """Multiple parens in goods_name (rare) — emit all distinct NB codes."""
    row = {"customs_code": "GROUP",
           "goods_name": "GROUP#&combo (019.X) and (019.Y)"}
    out = candidates_from_bcct_row(row, rules=[_paren_rule()],
                                    has_dual_system=True)
    assert sorted(out) == sorted([
        ("GROUP", "hq"), ("019.X", "nb"), ("019.Y", "nb"),
    ])


def test_bcct_dot_strips_to_skip():
    """Whitespace + '.' both treated as missing customs_code."""
    row1 = {"customs_code": " . ", "goods_name": "x (A)"}
    row2 = {"customs_code": ".", "goods_name": "x (A)"}
    out1 = candidates_from_bcct_row(row1, rules=[_paren_rule()],
                                     has_dual_system=True)
    out2 = candidates_from_bcct_row(row2, rules=[_paren_rule()],
                                     has_dual_system=True)
    assert out1 == out2 == [("A", "nb")]


# ── BOM stream ────────────────────────────────────────────────────────────


def test_bom_codes_dual_system_kind_nb():
    out = candidates_from_bom_codes(["P", "Q", "R"], has_dual_system=True)
    assert sorted(out) == sorted([("P", "nb"), ("Q", "nb"), ("R", "nb")])


def test_bom_codes_single_system_kind_unified():
    out = candidates_from_bom_codes(["1000527370", "1000527380"],
                                     has_dual_system=False)
    assert sorted(out) == sorted([
        ("1000527370", "unified"), ("1000527380", "unified"),
    ])


def test_bom_codes_dedup():
    """Distinct codes only — caller may pass duplicates."""
    out = candidates_from_bom_codes(["P", "P", "Q"], has_dual_system=True)
    assert sorted(out) == sorted([("P", "nb"), ("Q", "nb")])


def test_bom_codes_skip_empty():
    """Skip None/empty/whitespace."""
    out = candidates_from_bom_codes(["P", "", None, " ", "Q"],
                                     has_dual_system=True)
    assert sorted(out) == sorted([("P", "nb"), ("Q", "nb")])


# ── code_mappings (BQD) stream ────────────────────────────────────────────


def test_code_mappings_pair_distinct_strings():
    """Different HQ/NB strings → 2 candidates (hq + nb)."""
    out = candidates_from_code_mapping_pairs([("DAUNOI", "019.X")])
    assert sorted(out) == sorted([("DAUNOI", "hq"), ("019.X", "nb")])


def test_code_mappings_pair_same_string_unified():
    """HQ == NB string → single 'unified' candidate."""
    out = candidates_from_code_mapping_pairs([("X", "X")])
    assert out == [("X", "unified")]


def test_code_mappings_n_n_relationship():
    """Many HQ to many NB (Growatt-style): 3 HQ × 2 NB → 6 raw → 5 distinct candidates."""
    pairs = [
        ("DAUNOI", "019.X"), ("DAUNOI", "019.Y"),
        ("DOV",    "019.X"), ("DOV",    "019.Z"),
        ("LK",     "019.Y"),
    ]
    out = candidates_from_code_mapping_pairs(pairs)
    assert sorted(out) == sorted([
        ("DAUNOI", "hq"), ("DOV", "hq"), ("LK", "hq"),
        ("019.X", "nb"), ("019.Y", "nb"), ("019.Z", "nb"),
    ])


def test_code_mappings_skip_empty_pairs():
    """Skip rows where either side is None/empty."""
    out = candidates_from_code_mapping_pairs([
        ("DAUNOI", "019.X"), (None, "019.Y"), ("DOV", None), ("", ""),
    ])
    assert sorted(out) == sorted([("DAUNOI", "hq"), ("019.X", "nb")])
