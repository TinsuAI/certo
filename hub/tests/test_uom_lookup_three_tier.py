"""Mig-055 + Phase-2 step 2a — `make_uom_lookup` 3-tier policy.

Spec: `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md`
decision 6.

Existing precedence (mig 021 + spec §9):
  1. client_uom_overrides (client_id, material_code) exact
  2. client_uom_overrides (client_id, NULL material) client-wide
  3. uom_canonical family-based factor (same-family auto-convert)
  4. alias-equivalent canonical (factor 1.0, source='alias')
  5. None (caller emits uom_conversion_missing)

Phase 2 inserts a NEW tier between (4) and (5):

  5. Cross-family default — both UoMs resolve to canonical AND
     families differ AND both families ∈ {count, count_packaging,
     assembly} → factor=1.0 with source='unconfirmed_default'.
     Caller (flatten engine + bom_staleness refresh) is expected
     to mark the produced derived artifact `has_uom_drift=true`
     reason `unconfirmed_default_1to1`.

  6. None (caller emits uom_conversion_missing for the hard-block
     tier — count↔mass, mass↔length, etc.)
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from hub.app.database import connect


@pytest.fixture
def test_client():
    cid = "_uom_lookup_test"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (cid, "uom-lookup test client"),
        )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.client_uom_overrides where client_id=%s", (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


# ── Existing precedence (regression coverage) ────────────────────────────


def test_precedence_1_client_material_exact_match(test_client):
    from hub.app.stores.uom import make_uom_lookup
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'M1', 'EA', 'KG', 0.5, 'staff_form')",
            (test_client,),
        )
    lookup = make_uom_lookup(test_client)
    match = lookup("M1", "EA", "KG")
    assert match is not None
    assert match.factor == Decimal("0.5")
    assert match.source == "client_specific"


def test_precedence_2_client_wide_when_no_material(test_client):
    from hub.app.stores.uom import make_uom_lookup
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, NULL, 'EA', 'KG', 0.7, 'staff_form')",
            (test_client,),
        )
    lookup = make_uom_lookup(test_client)
    match = lookup("M_unknown", "EA", "KG")
    assert match is not None
    assert match.factor == Decimal("0.7")
    assert match.source == "client_wide"


def test_precedence_3_canonical_family_same(test_client):
    """Same family different canonical (g→kg) auto-converts via mig 021 base_factor."""
    from hub.app.stores.uom import make_uom_lookup
    lookup = make_uom_lookup(test_client)
    match = lookup("ANY", "g", "kg")
    assert match is not None
    assert match.source == "global"
    assert match.factor == Decimal("0.001")


def test_precedence_4_alias_equivalent(test_client):
    """PIECES and pcs resolve to same canonical → factor 1, source='alias'."""
    from hub.app.stores.uom import make_uom_lookup
    lookup = make_uom_lookup(test_client)
    match = lookup("ANY", "PIECES", "pcs")
    assert match is not None
    assert match.factor == Decimal(1)
    assert match.source == "alias"


# ── Tier A: cross-family count↔{count_packaging, assembly} → 1:1 default ──


def test_tier_a_count_to_assembly_returns_default_one(test_client):
    """EA (count) → SETS (assembly): no override, no canonical bridge,
    but tier-A applies → factor=1, source='unconfirmed_default'."""
    from hub.app.stores.uom import make_uom_lookup
    lookup = make_uom_lookup(test_client)
    match = lookup("ANY", "EA", "SETS")
    assert match is not None, "tier-A should default factor=1, not return None"
    assert match.factor == Decimal(1)
    assert match.source == "unconfirmed_default"


def test_tier_a_count_to_count_packaging(test_client):
    """EA (count) → CAY (count_packaging) → tier-A default."""
    from hub.app.stores.uom import make_uom_lookup
    lookup = make_uom_lookup(test_client)
    match = lookup("ANY", "EA", "CAY")
    assert match is not None
    assert match.factor == Decimal(1)
    assert match.source == "unconfirmed_default"


def test_tier_a_assembly_to_count_packaging(test_client):
    """SETS (assembly) → CAY (count_packaging) — both inside tier-A set."""
    from hub.app.stores.uom import make_uom_lookup
    lookup = make_uom_lookup(test_client)
    match = lookup("ANY", "SETS", "CAY")
    assert match is not None
    assert match.factor == Decimal(1)
    assert match.source == "unconfirmed_default"


def test_tier_a_uses_aliases(test_client):
    """PIECES → SETS still goes through tier-A (PIECES → pcs (count))."""
    from hub.app.stores.uom import make_uom_lookup
    lookup = make_uom_lookup(test_client)
    match = lookup("ANY", "PIECES", "SETS")
    assert match is not None
    assert match.source == "unconfirmed_default"


# ── Tier B: cross-family count↔mass/length/volume → None (hard-block) ────


def test_tier_b_count_to_mass_returns_none(test_client):
    """EA (count) → KG (mass): no default. Caller emits factor_missing."""
    from hub.app.stores.uom import make_uom_lookup
    lookup = make_uom_lookup(test_client)
    match = lookup("ANY", "EA", "KG")
    assert match is None, "tier-B mass cross — must NOT default 1:1"


def test_tier_b_count_to_volume_returns_none(test_client):
    from hub.app.stores.uom import make_uom_lookup
    lookup = make_uom_lookup(test_client)
    match = lookup("ANY", "EA", "L")
    assert match is None


def test_tier_b_mass_to_length_returns_none(test_client):
    from hub.app.stores.uom import make_uom_lookup
    lookup = make_uom_lookup(test_client)
    match = lookup("ANY", "KG", "m")
    assert match is None


def test_tier_b_assembly_to_mass_returns_none(test_client):
    """SETS (assembly) → KG (mass) — even within count-ish family it's
    not in the safe set when mass is involved."""
    from hub.app.stores.uom import make_uom_lookup
    lookup = make_uom_lookup(test_client)
    match = lookup("ANY", "SETS", "KG")
    assert match is None


# ── Override beats tier-A default ────────────────────────────────────────


def test_explicit_override_beats_tier_a_default(test_client):
    """If client provides explicit factor, use it instead of 1:1 default."""
    from hub.app.stores.uom import make_uom_lookup
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'M_real', 'EA', 'SETS', 4, 'staff_form')",
            (test_client,),
        )
    lookup = make_uom_lookup(test_client)
    match = lookup("M_real", "EA", "SETS")
    assert match is not None
    assert match.factor == Decimal("4")
    assert match.source == "client_specific"


def test_explicit_override_unblocks_tier_b(test_client):
    """Cross-family mass case: with override row, conversion works."""
    from hub.app.stores.uom import make_uom_lookup
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'M_heavy', 'EA', 'KG', 0.5, 'supplier_data')",
            (test_client,),
        )
    lookup = make_uom_lookup(test_client)
    match = lookup("M_heavy", "EA", "KG")
    assert match is not None
    assert match.factor == Decimal("0.5")
    assert match.source == "client_specific"


# ── Edge: unknown alias on either side returns None ──────────────────────


def test_unknown_alias_returns_none(test_client):
    """No canonical resolution → can't determine tier → None."""
    from hub.app.stores.uom import make_uom_lookup
    lookup = make_uom_lookup(test_client)
    assert lookup("ANY", "BLAHBLAH", "KG") is None
    assert lookup("ANY", "EA", "BLAHBLAH") is None


# ── Empty UoM args ──────────────────────────────────────────────────────


def test_empty_from_or_to_returns_none(test_client):
    from hub.app.stores.uom import make_uom_lookup
    lookup = make_uom_lookup(test_client)
    assert lookup("ANY", "", "KG") is None
    assert lookup("ANY", "EA", "") is None
    assert lookup("ANY", None, "KG") is None
