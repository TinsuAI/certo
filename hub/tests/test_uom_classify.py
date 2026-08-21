"""A.4.4 — `classify_uom_relation`: convertibility-aware UoM classifier.

Spec: `.ai/features/2026-06-07-convertibility-aware-uom/brief.md`.

The classifier maps the 6-tier `make_uom_lookup` cascade onto a relation
taxonomy used by the catalog panel, bcct_analysis, and the ingest gate:

  relation ∈ {equivalent, convertible, incompatible}
  + confirmed: bool (False only for tier-A unconfirmed_default 1:1)
  + factor / to_canonical / via / remediation

Acceptance is symmetric (a~b ⟺ b~a); the displayed factor is directional.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.database import connect


@pytest.fixture
def test_client():
    cid = "_uom_classify_test"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (cid, "uom-classify test client"),
        )
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.client_uom_overrides where client_id=%s", (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


# ── equivalent ───────────────────────────────────────────────────────────


def test_identity_same_string_is_equivalent(test_client):
    from app.stores.uom import classify_uom_relation
    rel = classify_uom_relation("EA", "EA", client_id=test_client)
    assert rel.relation == "equivalent"
    assert rel.factor == Decimal(1)
    assert rel.via == "identity"
    assert rel.confirmed is True


def test_alias_synonym_is_equivalent(test_client):
    """PIECES and pcs share a canonical → equivalent, not 'lệch'."""
    from app.stores.uom import classify_uom_relation
    rel = classify_uom_relation("PIECES", "pcs", client_id=test_client)
    assert rel.relation == "equivalent"
    assert rel.factor == Decimal(1)
    assert rel.via == "alias"
    assert rel.confirmed is True


# ── convertible ──────────────────────────────────────────────────────────


def test_same_family_base_factor_is_convertible(test_client):
    """g↔kg differ in canonical but convert cleanly → convertible."""
    from app.stores.uom import classify_uom_relation
    rel = classify_uom_relation("g", "kg", client_id=test_client)
    assert rel.relation == "convertible"
    assert rel.via == "same_family_base_factor"
    assert rel.factor == Decimal("0.001")
    assert rel.confirmed is True


def test_tier_a_default_is_convertible_but_unconfirmed(test_client):
    """EA→SETS (count↔assembly) has no real factor — tier-A guesses 1:1.
    Must classify convertible but confirmed=False (visually distinct)."""
    from app.stores.uom import classify_uom_relation
    rel = classify_uom_relation("EA", "SETS", client_id=test_client)
    assert rel.relation == "convertible"
    assert rel.via == "tier_a_default"
    assert rel.factor == Decimal(1)
    assert rel.confirmed is False


def test_client_override_makes_crossfamily_convertible(test_client):
    """Cross-family EA↔KG with a staff override row → convertible."""
    from app.stores.uom import classify_uom_relation
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'M1', 'EA', 'KG', 0.5, 'staff_form')",
            (test_client,),
        )
    rel = classify_uom_relation("EA", "KG", client_id=test_client, material_code="M1")
    assert rel.relation == "convertible"
    assert rel.via == "client_override"
    assert rel.factor == Decimal("0.5")
    assert rel.confirmed is True


# ── incompatible ─────────────────────────────────────────────────────────


def test_crossfamily_no_factor_is_incompatible_add_factor(test_client):
    """EA↔KG, both known canonical, no override → incompatible; the fix
    is to add a factor."""
    from app.stores.uom import classify_uom_relation
    rel = classify_uom_relation("EA", "KG", client_id=test_client)
    assert rel.relation == "incompatible"
    assert rel.confirmed is False
    assert rel.remediation == "add_factor"


def test_unknown_alias_is_incompatible_add_alias(test_client):
    """An unrecognized token can't be proven convertible → incompatible;
    the fix is to add the alias, not a factor."""
    from app.stores.uom import classify_uom_relation
    rel = classify_uom_relation("BLAHBLAH", "KG", client_id=test_client)
    assert rel.relation == "incompatible"
    assert rel.remediation == "add_alias"


# ── symmetry ─────────────────────────────────────────────────────────────


def test_acceptance_is_symmetric_with_directional_factor(test_client):
    """Override stored EA→KG=0.5. Asking KG→EA still classifies
    convertible (symmetric acceptance); factor inverts to 2."""
    from app.stores.uom import classify_uom_relation
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'M2', 'EA', 'KG', 0.5, 'staff_form')",
            (test_client,),
        )
    rel = classify_uom_relation("KG", "EA", client_id=test_client, material_code="M2")
    assert rel.relation == "convertible"
    assert rel.via == "client_override"
    assert rel.factor == Decimal("2")


# ── edges ────────────────────────────────────────────────────────────────


def test_empty_uom_is_incompatible_no_remediation(test_client):
    from app.stores.uom import classify_uom_relation
    rel = classify_uom_relation("", "KG", client_id=test_client)
    assert rel.relation == "incompatible"
    assert rel.factor is None
