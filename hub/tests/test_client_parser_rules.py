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


# ── DB load layer (Phase 3) ──────────────────────────────────────────


def test_load_rules_returns_empty_for_client_without_rules():
    """A client with no rows in client_parser_rules → empty list, not error."""
    from app.parsers.client_parser_rules import load_rules

    rules = load_rules(
        client_id="zzz-no-such-client-ever", output_field="internal_code",
    )
    assert rules == []


@pytest.fixture
def _rules_test_client():
    """Insert a temp client + cleanup. Uses random suffix to avoid clashes
    with parallel tests / leftover rows from prior runs. Clears the
    rules cache before + after to prevent cross-test leak."""
    import secrets
    from app.database import connect
    from app.parsers.client_parser_rules import clear_rules_cache

    clear_rules_cache()
    cid = f"rules-test-{secrets.token_hex(4)}"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (cid, f"rules test {cid}"),
        )
    yield cid
    clear_rules_cache()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id = %s", (cid,))


def test_load_rules_returns_compiled_rules_in_priority_order(_rules_test_client):
    from app.database import connect
    from app.parsers.client_parser_rules import load_rules

    cid = _rules_test_client
    with connect() as conn, conn.cursor() as cur:
        # Insert two rules out-of-order to verify priority sort.
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, created_by) "
            "values (%s, 'internal_code', 20, %s, 'test')",
            (cid, r"^([A-Z]+)"),
        )
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, created_by) "
            "values (%s, 'internal_code', 10, %s, 'test')",
            (cid, r"\((\w+)\)"),
        )

    rules = load_rules(client_id=cid, output_field="internal_code")

    assert len(rules) == 2
    assert rules[0].priority == 10
    assert rules[1].priority == 20
    # Compiled patterns are usable by the engine.
    match = rules[0].compiled.search("foo (BAR)")
    assert match is not None and match.group(1) == "BAR"


def test_compute_internal_code_evaluates_db_rules_for_non_identity_client(
    _rules_test_client,
):
    """End-to-end: client with rules in DB → compute_internal_code returns
    the captured group. Identity short-circuit is bypassed when mode is
    non-identity."""
    from app.database import connect
    from app.parsers.derivations import compute_internal_code

    cid = _rules_test_client
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, created_by) "
            "values (%s, 'internal_code', 10, %s, 'test')",
            (cid, r"\(([\w.]+)\)"),
        )

    out = compute_internal_code(
        {"goods_name": "BIENTAN.17#&Hàng (PV01.0117500)#&VN",
         "customs_code": "BIENTAN.17"},
        client={"client_id": cid, "code_resolution_mode": "batch_aggregate_resolution"},
    )
    assert out == "PV01.0117500"


def test_compute_internal_code_identity_mode_short_circuits_no_db_query(
    _rules_test_client,
):
    """Identity-mode clients return customs_code without consulting rules.
    Adding a rule that would match must be ignored."""
    from app.database import connect
    from app.parsers.derivations import compute_internal_code

    cid = _rules_test_client
    with connect() as conn, conn.cursor() as cur:
        # This rule would match if engine ran — but identity must skip it.
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, created_by) "
            "values (%s, 'internal_code', 10, %s, 'test')",
            (cid, r"(.+)"),
        )

    out = compute_internal_code(
        {"goods_name": "anything",
         "customs_code": "CUSTOMS-X"},
        client={"client_id": cid, "code_resolution_mode": "identity"},
    )
    assert out == "CUSTOMS-X"


def test_load_rules_caches_across_calls(_rules_test_client):
    """Second call returns cached object identity-equal to first call.
    No DB query on the second call — verified via object identity."""
    from app.database import connect
    from app.parsers.client_parser_rules import load_rules

    cid = _rules_test_client
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, created_by) "
            "values (%s, 'internal_code', 10, %s, 'test')",
            (cid, r"\((\w+)\)"),
        )

    first = load_rules(client_id=cid, output_field="internal_code")
    second = load_rules(client_id=cid, output_field="internal_code")
    # Cache returns the same list object — proves no DB requery.
    assert first is second


def test_clear_rules_cache_forces_reload(_rules_test_client):
    """clear_rules_cache() drops cached entries; next load hits DB."""
    from app.database import connect
    from app.parsers.client_parser_rules import clear_rules_cache, load_rules

    cid = _rules_test_client
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, created_by) "
            "values (%s, 'internal_code', 10, %s, 'test')",
            (cid, r"\((\w+)\)"),
        )

    first = load_rules(client_id=cid, output_field="internal_code")
    clear_rules_cache()
    second = load_rules(client_id=cid, output_field="internal_code")
    # Different list objects — cache was invalidated, DB re-queried.
    assert first is not second
    # But same content (same rule still in DB).
    assert len(first) == len(second) == 1


# ── Multi-match extraction (for resolver Stage 2 candidates) ────────


def test_extract_all_matches_collects_every_match_in_priority_order():
    """For multi-candidate use cases (e.g. material_identity Stage 2),
    iterate every capture rule and collect ALL matches (finditer), not
    just first-match-wins. Reject rules are honored (skip the source).
    Returns dicts with product_code + source_field + matched_text +
    match_rule (= rule notes or fallback id)."""
    import re
    from app.parsers.client_parser_rules import (
        CompiledRule,
        extract_all_matches_from_compiled,
    )

    rule_paren = CompiledRule(
        rule_id=42, output_field="material_identity_candidates", priority=10,
        source_field="goods_name", match_group=1,
        match_action="capture", no_match_action="next_rule",
        compiled=re.compile(r"\(([A-Z]{2,}\d{2}\.[\w.\-]+)\)"),
    )
    rule_paren_with_notes = CompiledRule(
        rule_id=43, output_field="material_identity_candidates", priority=20,
        source_field="goods_name", match_group=1,
        match_action="capture", no_match_action="next_rule",
        compiled=re.compile(r"\((\d{3}\.[\w.\-]+)\)"),
    )
    row = {"goods_name": "BIENTAN.17#&Hàng (Pro.E), (PV01.0117500), (940.0622900)#&VN"}

    out = extract_all_matches_from_compiled(
        [rule_paren, rule_paren_with_notes], row=row,
    )

    assert len(out) == 2
    by_code = {m["product_code"]: m for m in out}
    assert "PV01.0117500" in by_code
    assert "940.0622900" in by_code
    assert by_code["PV01.0117500"]["source_field"] == "goods_name"
    assert by_code["PV01.0117500"]["matched_text"] == "(PV01.0117500)"
    assert by_code["PV01.0117500"]["match_rule"] == "rule_42"
    assert by_code["940.0622900"]["match_rule"] == "rule_43"


def test_extract_all_matches_dedups_within_rule():
    """Same code captured twice by the same rule → emitted once.
    Different rules each emitting the same code → also dedup'd
    (a code is what it is regardless of which rule found it)."""
    import re
    from app.parsers.client_parser_rules import (
        CompiledRule,
        extract_all_matches_from_compiled,
    )

    rule = CompiledRule(
        rule_id=1, output_field="material_identity_candidates", priority=10,
        source_field="goods_name", match_group=1,
        match_action="capture", no_match_action="next_rule",
        compiled=re.compile(r"\(([A-Z]{2,}\d{2}\.[\w.\-]+)\)"),
    )
    row = {"goods_name": "(PV01.0117500) ... (PV01.0117500) again"}
    out = extract_all_matches_from_compiled([rule], row=row)
    assert len(out) == 1
    assert out[0]["product_code"] == "PV01.0117500"
