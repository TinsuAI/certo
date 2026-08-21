"""UoM factor-direction fixes (review 2026-06-14):

- P2: make_uom_lookup (the flatten lookup) accepts a reverse-only client
  override by inverting it, matching classify_uom_relation's symmetric
  acceptance — so a pair the catalog panel calls "convertible" no longer
  fails flatten with uom_conversion_missing.
- P3: the multi-canonical-leaf guard flags a child whose source edges span
  more than one canonical (alias-equivalent units do NOT trip it).
"""
from __future__ import annotations

from decimal import Decimal

from hub.app.stores import client_uom_overrides as factors
from hub.app.stores.uom import make_uom_lookup
from hub.scripts.materialize_shallow_and_full_flat import _group_offenders

CLIENT = "growatt-vn"


# ── P2: reverse-override symmetry in the flatten lookup ────────────────

def test_reverse_only_override_inverts_in_flatten_lookup():
    # Store ONLY the kg → ztestbox direction (a staff-entered, otherwise
    # non-convertible pair — ztestbox is not a known canonical/alias).
    factors.create_factor(
        client_id=CLIENT, material_code=None,
        from_uom="kg", to_uom="ztestbox", factor="2",
        source="staff_form", notes=None,
    )
    try:
        lookup = make_uom_lookup(CLIENT)
        # Forward direction (ztestbox → kg) was never stored; the lookup
        # must rescue it by inverting the reverse override.
        m = lookup("ANYMAT", "ztestbox", "kg")
        assert m is not None, "reverse override not picked up by flatten lookup"
        assert m.factor == Decimal("0.5")
        assert m.source == "client_wide"
        # The stored forward direction still resolves directly.
        fwd = lookup("ANYMAT", "kg", "ztestbox")
        assert fwd is not None and fwd.factor == Decimal("2")
    finally:
        factors.delete_factor(
            client_id=CLIENT, material_code=None,
            from_uom="kg", to_uom="ztestbox",
        )


def test_same_family_still_resolves_without_override():
    lookup = make_uom_lookup(CLIENT)
    m = lookup("ANYMAT", "g", "kg")
    assert m is not None and m.source == "global"
    assert m.factor == Decimal("0.001")


def test_incompatible_pair_still_none():
    lookup = make_uom_lookup(CLIENT)
    # No override either direction, genuinely cross-family unknown → None.
    assert lookup("ANYMAT", "ztestbox", "ztestother") is None


# ── P3: multi-canonical-leaf guard core ───────────────────────────────

def _resolver(mapping):
    return lambda u: mapping.get((u or "").strip().lower())


def test_group_offenders_flags_only_cross_canonical():
    resolve = _resolver({"pcs": "pcs", "st": "pcs", "ea": "pcs",
                         "g": "g", "kg": "kg"})
    edges = [
        ("A", "PCS"), ("A", "ST"), ("A", "EA"),  # all → pcs (alias) → OK
        ("B", "g"), ("B", "kg"),                 # g vs kg → flagged
        ("C", "PCS"),                            # single → OK
    ]
    assert _group_offenders(edges, resolve) == [("B", ["g", "kg"])]


def test_group_offenders_unknown_token_falls_back_to_itself():
    # Unknown tokens (resolver returns None) compare by their own lowered
    # string, so two genuinely different unknowns on one child are flagged.
    resolve = _resolver({})
    edges = [("X", "foo"), ("X", "bar"), ("Y", "foo"), ("Y", "FOO")]
    out = _group_offenders(edges, resolve)
    assert out == [("X", ["bar", "foo"])]  # Y: foo/FOO collapse, not flagged


def test_group_offenders_ignores_blank_uom():
    resolve = _resolver({"kg": "kg"})
    edges = [("Z", "kg"), ("Z", ""), ("Z", None)]
    assert _group_offenders(edges, resolve) == []
