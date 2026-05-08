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
    notes: str | None = None  # used as match_rule label in multi-match output


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


def extract_all_matches_from_compiled(
    rules: list[CompiledRule], *, row: dict,
) -> list[dict]:
    """Run every capture rule against the row, collect ALL matches
    (finditer, not just first). For multi-candidate consumers like the
    material_identity resolver Stage 2 (paren-code extraction).

    Reject rules are skipped (their semantic is single-output gating).
    Within a single iteration, duplicates by product_code are dropped.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for rule in rules:
        if rule.match_action != "capture":
            continue
        source_value = row.get(rule.source_field, "") or ""
        for match in rule.compiled.finditer(source_value):
            code = match.group(rule.match_group)
            if code in seen:
                continue
            seen.add(code)
            out.append({
                "product_code": code,
                "source_field": rule.source_field,
                "matched_text": match.group(0),
                "match_rule": rule.notes or f"rule_{rule.rule_id}",
            })
    return out


# Module-level cache for loaded rules. Keyed by (client_id, output_field).
# Invalidated wholesale via clear_rules_cache() — called from CRUD edit
# endpoints + tests that mutate hub.client_parser_rules. Cache is server-
# wide (single process); multi-worker deployments invalidate per-worker.
_RULES_CACHE: dict[tuple[str, str], list[CompiledRule]] = {}


def clear_rules_cache() -> None:
    """Drop the entire rules cache. Call after rule INSERT/UPDATE/DELETE."""
    _RULES_CACHE.clear()


def _load_rules_uncached(*, client_id: str, output_field: str) -> list[CompiledRule]:
    from app.database import connect

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select rule_id, priority, pattern, source_field,
                   match_group, match_action, no_match_action, notes
            from hub.client_parser_rules
            where client_id = %s and output_field = %s and enabled
            order by priority asc
            """,
            (client_id, output_field),
        )
        rows = cur.fetchall()
    return [
        CompiledRule(
            rule_id=rule_id,
            output_field=output_field,
            priority=priority,
            source_field=source_field,
            match_group=match_group,
            match_action=match_action,
            no_match_action=no_match_action,
            compiled=compile_pattern(pattern),
            notes=notes,
        )
        for (rule_id, priority, pattern, source_field, match_group,
             match_action, no_match_action, notes) in rows
    ]


def load_rules(*, client_id: str, output_field: str) -> list[CompiledRule]:
    """Load enabled rules for (client_id, output_field), priority asc,
    compiled and ready for evaluate_compiled_rules. Cached server-wide."""
    key = (client_id, output_field)
    cached = _RULES_CACHE.get(key)
    if cached is not None:
        return cached
    rules = _load_rules_uncached(client_id=client_id, output_field=output_field)
    _RULES_CACHE[key] = rules
    return rules
