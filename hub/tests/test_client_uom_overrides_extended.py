"""Mig 055 — `client_uom_overrides` extension (Phase 2 step 1).

Adds:
- `is_cross_family` boolean (auto-computed via trigger from from_uom +
  to_uom canonical family lookup; staff cannot set manually).
- `notes` text nullable (staff annotation).
- Source enum extended with `supplier_data`, `packaging_spec`,
  `derived_average`, `imported`.

Spec: `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md`
decision 1.
"""
from __future__ import annotations

import pytest

from app.database import connect


def _seed_test_client(cur, client_id: str = "_uom_test"):
    """Create or upsert a test client (CASCADE-deletes on teardown via fixture)."""
    cur.execute(
        "insert into hub.clients (client_id, name) values (%s, %s) "
        "on conflict (client_id) do nothing",
        (client_id, "uom-override test client"),
    )
    return client_id


@pytest.fixture
def test_client():
    cid = "_uom_test"
    with connect() as conn, conn.cursor() as cur:
        _seed_test_client(cur, cid)
    yield cid
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.client_uom_overrides where client_id=%s", (cid,))
        cur.execute("delete from hub.clients where client_id=%s", (cid,))


# ── Schema ────────────────────────────────────────────────────────────────


def test_is_cross_family_column_exists():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            select data_type, is_nullable, column_default
            from information_schema.columns
            where table_schema='hub' and table_name='client_uom_overrides'
              and column_name='is_cross_family'
        """)
        row = cur.fetchone()
        assert row is not None, "is_cross_family column missing"
        dtype, nullable, default = row
        assert dtype == "boolean"
        assert nullable == "NO"
        assert default and "false" in default.lower()


def test_notes_column_exists():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            select data_type, is_nullable
            from information_schema.columns
            where table_schema='hub' and table_name='client_uom_overrides'
              and column_name='notes'
        """)
        row = cur.fetchone()
        assert row is not None, "notes column missing"
        dtype, nullable = row
        assert dtype == "text"
        assert nullable == "YES"


def test_source_enum_includes_new_values(test_client):
    with connect() as conn, conn.cursor() as cur:
        for source in ("supplier_data", "packaging_spec", "derived_average",
                       "imported"):
            cur.execute(
                "insert into hub.client_uom_overrides "
                "(client_id, material_code, from_uom, to_uom, factor, source) "
                "values (%s, %s, 'kg', 'g', 1000, %s)",
                (test_client, f"src-test-{source}", source),
            )
            # Cleanup before next iteration
            cur.execute(
                "delete from hub.client_uom_overrides "
                "where client_id=%s and material_code=%s",
                (test_client, f"src-test-{source}"),
            )


def test_source_enum_rejects_unknown(test_client):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "insert into hub.client_uom_overrides "
                "(client_id, material_code, from_uom, to_uom, factor, source) "
                "values (%s, 'reject-test', 'kg', 'g', 1000, 'made_up_source')",
                (test_client,),
            )


# ── Trigger: is_cross_family auto-compute ────────────────────────────────


def test_same_family_sets_is_cross_family_false(test_client):
    """gam → kg = same family (mass) → is_cross_family=false."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'mass-same', 'g', 'kg', 0.001, 'staff_form') "
            "returning is_cross_family",
            (test_client,),
        )
        assert cur.fetchone()[0] is False


def test_cross_family_count_to_mass_sets_true(test_client):
    """EA (count) → KG (mass) = cross-family → is_cross_family=true."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'count-to-mass', 'EA', 'KG', 0.5, 'staff_form') "
            "returning is_cross_family",
            (test_client,),
        )
        assert cur.fetchone()[0] is True


def test_cross_family_count_to_assembly_sets_true(test_client):
    """EA (count) → SETS (assembly) = cross-family → is_cross_family=true."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'count-to-assembly', 'EA', 'SETS', 4, 'staff_form') "
            "returning is_cross_family",
            (test_client,),
        )
        assert cur.fetchone()[0] is True


def test_cross_family_count_to_count_packaging_sets_true(test_client):
    """EA (count) → CAY (count_packaging) = cross-family → is_cross_family=true."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'count-to-cay', 'EA', 'CAY', 5, 'staff_form') "
            "returning is_cross_family",
            (test_client,),
        )
        assert cur.fetchone()[0] is True


def test_unknown_alias_defaults_false(test_client):
    """Unknown alias on either side → can't determine → is_cross_family=false."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'unknown-alias', 'BLAHBLAH', 'KG', 1, 'staff_form') "
            "returning is_cross_family",
            (test_client,),
        )
        assert cur.fetchone()[0] is False


def test_update_from_uom_recomputes_flag(test_client):
    """Editing from_uom from same-family to cross-family flips flag."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'flip-test', 'g', 'kg', 0.001, 'staff_form')",
            (test_client,),
        )
        cur.execute(
            "select is_cross_family from hub.client_uom_overrides "
            "where client_id=%s and material_code='flip-test'",
            (test_client,),
        )
        assert cur.fetchone()[0] is False
        cur.execute(
            "update hub.client_uom_overrides set from_uom='EA' "
            "where client_id=%s and material_code='flip-test'",
            (test_client,),
        )
        cur.execute(
            "select is_cross_family from hub.client_uom_overrides "
            "where client_id=%s and material_code='flip-test'",
            (test_client,),
        )
        assert cur.fetchone()[0] is True


def test_explicit_is_cross_family_value_is_overwritten(test_client):
    """Trigger always recomputes; staff cannot lie about is_cross_family."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source, "
            " is_cross_family) "
            "values (%s, 'lie-test', 'g', 'kg', 0.001, 'staff_form', true) "
            "returning is_cross_family",
            (test_client,),
        )
        # Trigger overrode the lying value (g→kg is same-family).
        assert cur.fetchone()[0] is False


def test_alias_normalization_handles_case_and_whitespace(test_client):
    """Trigger uses normalized lookup against uom_aliases."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'norm-test', '  PIECES  ', 'kilo-grammes', 1, 'staff_form') "
            "returning is_cross_family",
            (test_client,),
        )
        # PIECES → pcs (count); KILO-GRAMMES → kg (mass) → cross-family
        assert cur.fetchone()[0] is True


def test_canonical_code_lookup_works_directly(test_client):
    """If from/to is already a canonical code (not alias), trigger still resolves."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'canonical-direct', 'pcs', 'kg', 0.5, 'staff_form') "
            "returning is_cross_family",
            (test_client,),
        )
        assert cur.fetchone()[0] is True


# ── Notes column ─────────────────────────────────────────────────────────


def test_notes_can_be_null(test_client):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source) "
            "values (%s, 'notes-null', 'kg', 'g', 1000, 'staff_form') "
            "returning notes",
            (test_client,),
        )
        assert cur.fetchone()[0] is None


def test_notes_persists_text(test_client):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.client_uom_overrides "
            "(client_id, material_code, from_uom, to_uom, factor, source, notes) "
            "values (%s, 'notes-text', 'kg', 'g', 1000, 'staff_form', "
            " 'Confirmed by Johnson on 2026-05-12, factor stable across batches') "
            "returning notes",
            (test_client,),
        )
        notes = cur.fetchone()[0]
        assert "Johnson" in notes
        assert "stable" in notes
