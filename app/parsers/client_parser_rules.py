"""Configurable per-client parsing rules engine.

Brief: .ai/features/2026-05-08-configurable-bcct-parsing/brief.md

Patterns are compiled via google-re2 (linear-time matching) to neutralize
ReDoS attack surface from staff-authored regex.
"""
from __future__ import annotations

from dataclasses import dataclass

import re2


@dataclass(frozen=True)
class CompiledRule:
    rule_id: int
    output_field: str
    priority: int
    source_field: str
    match_group: int
    match_action: str        # 'capture' | 'reject'
    no_match_action: str     # 'next_rule' | 'return_null'
    compiled: object         # re-compatible compiled pattern (re or re2)


MAX_PATTERN_LENGTH = 500


class InvalidPatternError(ValueError):
    """Raised when a parser-rule pattern fails save-time validation."""


def compile_pattern(pattern: str):
    """Compile a regex pattern via re2 (linear-time, no ReDoS).

    Raises InvalidPatternError on length violation or re2-incompatible
    syntax (e.g. backreferences, lookahead/lookbehind).
    """
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise InvalidPatternError(
            f"pattern too long: {len(pattern)} chars (max {MAX_PATTERN_LENGTH})"
        )
    try:
        return re2.compile(pattern)
    except re2.error as e:
        raise InvalidPatternError(f"invalid regex: {e}") from e


def evaluate_compiled_rules(rules: list[CompiledRule], *, row: dict) -> str | None:
    for rule in rules:
        source_value = row.get(rule.source_field, "") or ""
        match = rule.compiled.search(source_value)
        if match:
            if rule.match_action == "reject":
                return None
            return match.group(rule.match_group)
        if rule.no_match_action == "return_null":
            return None
    return None
