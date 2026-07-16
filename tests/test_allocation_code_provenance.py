"""Canonical value-set for `resolve_allocation_code` provenance (#21).

- `source` distinguishes primary from fallback (strategy_customs vs fallback_customs).
- `confidence` is purely ordinal (high/low); provenance tags never leak in.
- `status` is boolean: resolved / unresolved (one spelling for the negative state).
"""
from app.client_config_store import resolve_allocation_code

ALLOWED_SOURCES = {"material_identity", "strategy_customs", "strategy_regex", "fallback_customs", "manual", ""}
ALLOWED_CONFIDENCE = {"high", "low"}
ALLOWED_STATUS = {"resolved", "unresolved"}

REGEX_CONFIG = {
    "allocation_code": {
        "strategy": "description_regex",
        "description_regex": r"\(([A-Z0-9][A-Z0-9._/-]{3,})\)",
        "fallback": "same_as_customs_code",
    }
}
CUSTOMS_CONFIG = {"allocation_code": {"strategy": "same_as_customs_code", "fallback": "same_as_customs_code"}}
REGEX_NO_FALLBACK = {
    "allocation_code": {
        "strategy": "description_regex",
        "description_regex": r"\(([A-Z0-9][A-Z0-9._/-]{3,})\)",
        "fallback": "requires_review",
    }
}
MANUAL_CONFIG = {"allocation_code": {"strategy": "manual_review", "fallback": "same_as_customs_code"}}


def test_primary_customs_strategy_source_is_strategy_customs():
    r = resolve_allocation_code({"item_code": "MAT-001", "description": ""}, CUSTOMS_CONFIG)
    assert r["allocation_code"] == "MAT-001"
    assert r["status"] == "resolved"
    assert r["source"] == "strategy_customs"
    assert r["confidence"] == "high"


def test_regex_match_source_is_strategy_regex():
    r = resolve_allocation_code({"item_code": "DIENTRO", "description": "x (001.0001400)"}, REGEX_CONFIG)
    assert r["allocation_code"] == "001.0001400"
    assert r["status"] == "resolved"
    assert r["source"] == "strategy_regex"
    assert r["confidence"] == "high"


def test_fallback_to_customs_is_distinguishable_from_primary():
    # regex misses -> falls back to the customs code. Source must NOT equal the
    # primary strategy_customs source, and confidence drops to the low ordinal.
    r = resolve_allocation_code({"item_code": "DIENTRO", "description": "no code in parens"}, REGEX_CONFIG)
    assert r["allocation_code"] == "DIENTRO"
    assert r["status"] == "resolved"
    assert r["source"] == "fallback_customs"
    assert r["source"] != "strategy_customs"
    assert r["confidence"] == "low"


def test_material_identity_source():
    r = resolve_allocation_code(
        {"item_code": "X", "description": "y (999.9999)", "material_identity": {"internal_code": "012.0002700"}},
        REGEX_CONFIG,
    )
    assert r["allocation_code"] == "012.0002700"
    assert r["source"] == "material_identity"
    assert r["confidence"] == "high"
    assert r["status"] == "resolved"


def test_manual_review_strategy_is_unresolved_with_manual_source():
    r = resolve_allocation_code({"item_code": "MAT-001", "description": ""}, MANUAL_CONFIG)
    assert r["status"] == "unresolved"
    assert r["source"] == "manual"
    assert r["reason"] == "manual_review"
    assert r["allocation_code"] == ""


def test_multiple_matches_unresolved():
    r = resolve_allocation_code({"item_code": "D", "description": "(001.0001400) (001.0001500)"}, REGEX_CONFIG)
    assert r["status"] == "unresolved"
    assert r["reason"] == "multiple_regex_matches"


def test_no_match_no_fallback_unresolved():
    r = resolve_allocation_code({"item_code": "D", "description": "no code"}, REGEX_NO_FALLBACK)
    assert r["status"] == "unresolved"
    assert r["reason"] == "no_regex_match"


def test_confidence_is_purely_ordinal_and_status_canonical():
    cases = [
        resolve_allocation_code({"item_code": "MAT", "description": ""}, CUSTOMS_CONFIG),
        resolve_allocation_code({"item_code": "D", "description": "(001.0001400)"}, REGEX_CONFIG),
        resolve_allocation_code({"item_code": "D", "description": "no code"}, REGEX_CONFIG),  # fallback
        resolve_allocation_code({"item_code": "D", "description": "no code"}, REGEX_NO_FALLBACK),  # unresolved
        resolve_allocation_code({"item_code": "D", "description": "(001.0001400) (001.0001500)"}, REGEX_CONFIG),
        resolve_allocation_code({"item_code": "M", "description": ""}, MANUAL_CONFIG),
    ]
    for r in cases:
        assert r["confidence"] in ALLOWED_CONFIDENCE, r
        assert r["status"] in ALLOWED_STATUS, r
        assert r["source"] in ALLOWED_SOURCES, r
        # provenance tags must not leak into the confidence ordinal
        assert r["confidence"] not in {"exact", "fallback"}
