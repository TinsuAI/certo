"""Identity + latest-safety tests. Spec items: 22 (structured identity
fields), 23 (generic latest-by-product is safe), 24 (English machine
codes, no Vietnamese in stored values).
"""
from __future__ import annotations

import pytest

from hub.app.flatten.identity import build_display_label
from hub.app.flatten.types import (
    DecisionType, FlattenStatus, FlattenStrategy, SourceBomKind,
    SourceChannel, UnresolvedReason, ConversionMatchSource,
)


# ── Item 22 — display_label derivation ────────────────────────────────

def test_display_label_includes_all_structured_fields():
    label = build_display_label(
        product_code="TP-A", bom_variant_id="default",
        artifact_no=3, source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy="self_produced_btp_exploded",
    )
    assert label == "TP-A · default · v3 · technical_flattened · flattened · self_produced_btp_exploded"


def test_display_label_uses_default_when_variant_none():
    label = build_display_label(
        product_code="TP-A", bom_variant_id=None,
        artifact_no=1, source_bom_kind="manual_flat",
        flatten_status="not_applicable",
        flatten_strategy="manual_flat_as_provided",
    )
    assert "default" in label


def test_display_label_dual_source_variants_distinguishable():
    """The two dual-source variants must have visibly different labels."""
    purchased = build_display_label(
        product_code="TP-A", bom_variant_id="default", artifact_no=4,
        source_bom_kind="technical_flattened", flatten_status="flattened",
        flatten_strategy="purchased_btp_as_leaf",
    )
    exploded = build_display_label(
        product_code="TP-A", bom_variant_id="default", artifact_no=5,
        source_bom_kind="technical_flattened", flatten_status="flattened",
        flatten_strategy="self_produced_btp_exploded",
    )
    assert purchased != exploded
    assert "purchased_btp_as_leaf" in purchased
    assert "self_produced_btp_exploded" in exploded


# ── Item 24 — All enum codes are English machine codes (typing audit) ──

def test_all_enum_types_are_english_machine_codes():
    """Every Literal type used by the flatten layer expands to lowercase
    English snake_case codes — no Vietnamese, no display labels."""
    from typing import get_args
    for L in (FlattenStatus, FlattenStrategy, SourceBomKind, SourceChannel,
              UnresolvedReason, DecisionType, ConversionMatchSource):
        for code in get_args(L):
            assert isinstance(code, str)
            # snake_case: lowercase + underscores + ASCII only
            assert code == code.lower(), f"{code} not lowercase"
            assert all(c.isascii() for c in code), f"{code} contains non-ASCII"
            assert " " not in code, f"{code} contains whitespace"
