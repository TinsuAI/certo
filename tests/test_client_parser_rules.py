"""Configurable per-client BCCT parsing rules — engine core.

Brief: .ai/features/2026-05-08-configurable-bcct-parsing/brief.md

Engine semantics (D2):
  - Rules ordered by priority asc, evaluated in order.
  - Match: match_action='capture' → return capture group;
           match_action='reject'  → return None and stop.
  - No match: no_match_action='next_rule' → continue;
              no_match_action='return_null' → return None and stop.
  - All rules exhausted with no resolution → return None.

ReDoS protection (D3): pure engine accepts already-compiled patterns;
compilation goes through re2 with backreference + length validation
at the rule-save layer.
"""
from __future__ import annotations

import pytest


def test_empty_rule_list_returns_none():
    from app.parsers.client_parser_rules import evaluate_compiled_rules

    result = evaluate_compiled_rules([], row={"goods_name": "anything"})
    assert result is None


def test_single_capture_rule_match_returns_group():
    import re
    from app.parsers.client_parser_rules import (
        CompiledRule,
        evaluate_compiled_rules,
    )

    rule = CompiledRule(
        rule_id=1, output_field="internal_code", priority=10,
        source_field="goods_name", match_group=1,
        match_action="capture", no_match_action="next_rule",
        compiled=re.compile(r"\((\w+)\)"),
    )
    result = evaluate_compiled_rules([rule], row={"goods_name": "foo (BAR)"})
    assert result == "BAR"


def test_single_capture_rule_no_match_returns_none():
    import re
    from app.parsers.client_parser_rules import (
        CompiledRule,
        evaluate_compiled_rules,
    )

    rule = CompiledRule(
        rule_id=1, output_field="internal_code", priority=10,
        source_field="goods_name", match_group=1,
        match_action="capture", no_match_action="next_rule",
        compiled=re.compile(r"\((\w+)\)"),
    )
    result = evaluate_compiled_rules([rule], row={"goods_name": "no parens here"})
    assert result is None


def test_reject_rule_matches_returns_none_and_stops():
    import re
    from app.parsers.client_parser_rules import (
        CompiledRule,
        evaluate_compiled_rules,
    )

    reject_rule = CompiledRule(
        rule_id=1, output_field="internal_code", priority=10,
        source_field="goods_name", match_group=1,
        match_action="reject", no_match_action="next_rule",
        compiled=re.compile(r"^\.\s*#&"),
    )
    capture_rule = CompiledRule(
        rule_id=2, output_field="internal_code", priority=20,
        source_field="goods_name", match_group=1,
        match_action="capture", no_match_action="next_rule",
        compiled=re.compile(r"^([A-Z]+)"),
    )
    # Reject rule matches `.#&...` shape → return None, never reach capture.
    result = evaluate_compiled_rules(
        [reject_rule, capture_rule], row={"goods_name": ".#&Equipment description"}
    )
    assert result is None


def test_no_match_action_return_null_stops_chain():
    import re
    from app.parsers.client_parser_rules import (
        CompiledRule,
        evaluate_compiled_rules,
    )

    # First rule doesn't match; no_match_action='return_null' → stop, never run rule 2.
    gate_rule = CompiledRule(
        rule_id=1, output_field="internal_code", priority=10,
        source_field="goods_name", match_group=1,
        match_action="capture", no_match_action="return_null",
        compiled=re.compile(r"^MUST_START_WITH_THIS"),
    )
    fallback_rule = CompiledRule(
        rule_id=2, output_field="internal_code", priority=20,
        source_field="goods_name", match_group=1,
        match_action="capture", no_match_action="next_rule",
        compiled=re.compile(r"(.+)"),  # would capture anything
    )
    result = evaluate_compiled_rules(
        [gate_rule, fallback_rule], row={"goods_name": "would have matched fallback"}
    )
    assert result is None


def test_first_match_wins_rules_evaluated_in_order():
    """Engine consumes a pre-ordered list. Loader is responsible for
    `order by priority asc`. Engine just iterates."""
    import re
    from app.parsers.client_parser_rules import (
        CompiledRule,
        evaluate_compiled_rules,
    )

    high_priority = CompiledRule(
        rule_id=1, output_field="internal_code", priority=10,
        source_field="goods_name", match_group=1,
        match_action="capture", no_match_action="next_rule",
        compiled=re.compile(r"\((\w+)\)"),
    )
    low_priority = CompiledRule(
        rule_id=2, output_field="internal_code", priority=20,
        source_field="goods_name", match_group=1,
        match_action="capture", no_match_action="next_rule",
        compiled=re.compile(r"^(\w+)"),
    )
    # Both rules would match; high_priority listed first wins.
    result = evaluate_compiled_rules(
        [high_priority, low_priority], row={"goods_name": "PREFIX (CAPTURED)"}
    )
    assert result == "CAPTURED"


# ── Save-time pattern validator (D3 ReDoS protection) ────────────────


def test_compile_pattern_returns_searchable_object_for_valid_input():
    from app.parsers.client_parser_rules import compile_pattern

    compiled = compile_pattern(r"\((\w+)\)")
    match = compiled.search("foo (BAR)")
    assert match is not None
    assert match.group(1) == "BAR"


def test_compile_pattern_rejects_overlong_pattern():
    from app.parsers.client_parser_rules import (
        InvalidPatternError,
        compile_pattern,
    )

    too_long = "a" * 501
    with pytest.raises(InvalidPatternError, match="too long"):
        compile_pattern(too_long)


def test_compile_pattern_rejects_backreference():
    """re2 does not support backreferences; staff-authored patterns
    using them must fail at save time, not silently break runtime."""
    from app.parsers.client_parser_rules import (
        InvalidPatternError,
        compile_pattern,
    )

    with pytest.raises(InvalidPatternError):
        compile_pattern(r"(\w+)\s+\1")  # \1 = backreference
