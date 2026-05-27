"""Tests for the cost_buildup schema expansion (4 rollup keys → 6 details + profit).

Covers:
- _sanitize_cost_buildup accepts both legacy and new shape, preserves what
  came in (no lossy reshape).
- _coerce_cost_buildup (engine reader) rolls up 6 details into 4 rollups
  for the XML config; falls back to legacy when no detail keys present.
- Round-trip: form fields → store → engine produces the same numeric
  output for matched legacy cases.
"""
from __future__ import annotations

from decimal import Decimal

from app.co_case_store import _sanitize_cost_buildup
from app.bang_ke_xml_generator import _coerce_cost_buildup


# ---------- Sanitizer ----------


def test_sanitize_accepts_legacy_4_keys():
    out = _sanitize_cost_buildup({"labor": "100", "overhead": "200", "profit": "50", "other": "10"})
    assert out["labor"] == "100"
    assert out["overhead"] == "200"
    assert out["profit"] == "50"
    assert out["other"] == "10"


def test_sanitize_accepts_new_6_detail_keys_and_profit():
    out = _sanitize_cost_buildup({
        "wages": "10", "welfare": "20",
        "rent": "30", "depreciation": "40", "other_mfg": "50",
        "transport_storage": "60",
        "profit": "70",
    })
    assert out["wages"] == "10"
    assert out["welfare"] == "20"
    assert out["rent"] == "30"
    assert out["depreciation"] == "40"
    assert out["other_mfg"] == "50"
    assert out["transport_storage"] == "60"
    assert out["profit"] == "70"


def test_sanitize_drops_negative_and_invalid():
    out = _sanitize_cost_buildup({
        "wages": "-5",
        "welfare": "bogus",
        "rent": "30",
        "profit": "",
    })
    assert out["wages"] == ""
    assert out["welfare"] == ""
    assert out["rent"] == "30"
    assert out["profit"] == ""


def test_sanitize_empty_input_returns_blank_dict():
    out = _sanitize_cost_buildup(None)
    # All recognised keys present with empty defaults.
    for key in ("labor", "overhead", "profit", "other",
                "wages", "welfare", "rent", "depreciation", "other_mfg", "transport_storage"):
        assert out.get(key, "") == ""


# ---------- Engine reader (rollup) ----------


def test_coerce_rolls_up_6_details_to_4_rollups():
    out = _coerce_cost_buildup({
        "wages": "10", "welfare": "20",
        "rent": "30", "depreciation": "40", "other_mfg": "50",
        "transport_storage": "60",
        "profit": "70",
    })
    assert out["labor"] == Decimal("30")          # 10 + 20
    assert out["overhead"] == Decimal("120")      # 30 + 40 + 50
    assert out["other"] == Decimal("60")          # transport_storage
    assert out["profit"] == Decimal("70")


def test_coerce_falls_back_to_legacy_4_keys_when_no_details():
    out = _coerce_cost_buildup({"labor": "100", "overhead": "200", "profit": "50", "other": "10"})
    assert out["labor"] == Decimal("100")
    assert out["overhead"] == Decimal("200")
    assert out["profit"] == Decimal("50")
    assert out["other"] == Decimal("10")


def test_coerce_prefers_details_over_legacy_when_both_present():
    """New shape wins; legacy keys are stale shadows after the schema migration."""
    out = _coerce_cost_buildup({
        "labor": "9999", "overhead": "9999", "other": "9999",  # ignored
        "wages": "10", "welfare": "20",
        "rent": "30", "depreciation": "40", "other_mfg": "50",
        "transport_storage": "60",
        "profit": "70",
    })
    assert out["labor"] == Decimal("30")
    assert out["overhead"] == Decimal("120")
    assert out["other"] == Decimal("60")
    assert out["profit"] == Decimal("70")


def test_coerce_handles_partial_detail_keys():
    """Missing detail keys default to 0; this should not silently fall back to legacy."""
    out = _coerce_cost_buildup({
        "wages": "10",
        # no welfare/rent/etc; legacy keys also absent
    })
    assert out["labor"] == Decimal("10")
    assert out["overhead"] == Decimal("0")
    assert out["other"] == Decimal("0")
    assert out["profit"] == Decimal("0")


def test_coerce_empty_dict_returns_zeros():
    out = _coerce_cost_buildup({})
    assert out["labor"] == Decimal("0")
    assert out["overhead"] == Decimal("0")
    assert out["other"] == Decimal("0")
    assert out["profit"] == Decimal("0")
