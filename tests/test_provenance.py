"""Sprint A4: catalog multi-source provenance.

Tests the auto-derive helper called from BCCT apply path + the catalog
upload path that sets registered_with_hq. Uses a synthetic test client
to avoid polluting real seed data.
"""
from __future__ import annotations

import secrets

import pytest

from app.database import connect
from app.stores.provenance import derive_from_bcct, unregistered_seen_count


@pytest.fixture
def test_client():
    """Create a throwaway client with a clean materials/bcct slate."""
    cid = "prov-test-" + secrets.token_hex(4)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.clients
                  (client_id, name, code_resolution_mode, bom_proposal_mode)
                values (%s, 'Provenance Test Co', 'identity', 'auto')
                """,
                (cid,),
            )
    yield cid
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.bcct_rows where client_id = %s", (cid,))
            cur.execute("delete from hub.materials where client_id = %s", (cid,))
            cur.execute("delete from hub.clients where client_id = %s", (cid,))


def _seed_bcct(client_id: str, decl_no: str, line_no: str, customs_code: str,
               registration_date: str = "2025-01-15", goods_name: str = "Test"):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no,
                   declaration_type, direction, registration_date, customs_code,
                   goods_name, payload)
                values (%s, %s, %s, %s, 'E11', 'import', %s, %s, %s, '{}'::jsonb)
                on conflict (client_id, year, transaction_key, line_no) do nothing
                """,
                (client_id, f"PROV_{decl_no}", line_no, decl_no,
                 registration_date, customs_code, goods_name),
            )


def _seed_material(client_id: str, customs_code: str, *, registered: bool = True):
    """Seed an existing material — used to test the merge path."""
    provenance = (
        '{"registered_with_hq": {"first_seen": "2025-01-01"}}'
        if registered else '{}'
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.materials
                  (client_id, customs_code, name, category, status, provenance)
                values (%s, %s, 'Existing', 'nvl', 'active', %s::jsonb)
                """,
                (client_id, customs_code, provenance),
            )


def _read_provenance(client_id: str, customs_code: str) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select provenance from hub.materials "
                "where client_id = %s and customs_code = %s",
                (client_id, customs_code),
            )
            row = cur.fetchone()
            return row[0] if row else None


# ─── auto-derive from BCCT ─────────────────────────────────────────────

def test_derive_creates_new_material_with_seen_in_bcct(test_client):
    """New customs_code appears on BCCT → catalog gets a row with
    seen_in_bcct provenance and default category 'nvl'."""
    _seed_bcct(test_client, "D001", "1", "AUTO-NEW")
    with connect() as conn:
        with conn.cursor() as cur:
            n = derive_from_bcct(cur, client_id=test_client,
                                 customs_codes=["AUTO-NEW"])
    assert n == 1
    prov = _read_provenance(test_client, "AUTO-NEW")
    assert prov is not None
    assert "seen_in_bcct" in prov
    assert "registered_with_hq" not in prov
    assert prov["seen_in_bcct"]["decl_count"] == 1


def test_derive_merges_onto_existing_registered_material(test_client):
    """Existing registered_with_hq + new BCCT activity → both keys present."""
    _seed_material(test_client, "MERGE-CODE", registered=True)
    _seed_bcct(test_client, "D002", "1", "MERGE-CODE")
    with connect() as conn:
        with conn.cursor() as cur:
            derive_from_bcct(cur, client_id=test_client,
                             customs_codes=["MERGE-CODE"])
    prov = _read_provenance(test_client, "MERGE-CODE")
    assert "registered_with_hq" in prov, "registered_with_hq was clobbered!"
    assert "seen_in_bcct" in prov


def test_derive_aggregates_decl_count_correctly(test_client):
    """Multiple declarations of same code → decl_count should be distinct count."""
    _seed_bcct(test_client, "D101", "1", "AGG-CODE")
    _seed_bcct(test_client, "D102", "1", "AGG-CODE")
    _seed_bcct(test_client, "D103", "1", "AGG-CODE")
    _seed_bcct(test_client, "D101", "2", "AGG-CODE")  # same decl, different line
    with connect() as conn:
        with conn.cursor() as cur:
            derive_from_bcct(cur, client_id=test_client,
                             customs_codes=["AGG-CODE"])
    prov = _read_provenance(test_client, "AGG-CODE")
    assert prov["seen_in_bcct"]["decl_count"] == 3, "expected 3 distinct declarations"


def test_derive_skips_when_no_codes(test_client):
    """Empty input → no SQL fired, returns 0."""
    with connect() as conn:
        with conn.cursor() as cur:
            n = derive_from_bcct(cur, client_id=test_client, customs_codes=[])
    assert n == 0


def test_derive_skips_empty_strings(test_client):
    """Empty / None codes filtered out."""
    with connect() as conn:
        with conn.cursor() as cur:
            n = derive_from_bcct(cur, client_id=test_client,
                                 customs_codes=["", None, "  "])
    assert n == 0


def test_derive_idempotent_refreshes_last_seen(test_client):
    """Re-running with newer BCCT data updates last_seen + decl_count."""
    _seed_bcct(test_client, "D201", "1", "IDEM-CODE",
               registration_date="2025-01-01")
    with connect() as conn:
        with conn.cursor() as cur:
            derive_from_bcct(cur, client_id=test_client,
                             customs_codes=["IDEM-CODE"])
    prov_first = _read_provenance(test_client, "IDEM-CODE")
    assert prov_first["seen_in_bcct"]["last_seen"] == "2025-01-01"

    _seed_bcct(test_client, "D202", "1", "IDEM-CODE",
               registration_date="2025-06-15")
    with connect() as conn:
        with conn.cursor() as cur:
            derive_from_bcct(cur, client_id=test_client,
                             customs_codes=["IDEM-CODE"])
    prov_second = _read_provenance(test_client, "IDEM-CODE")
    assert prov_second["seen_in_bcct"]["last_seen"] == "2025-06-15"
    assert prov_second["seen_in_bcct"]["decl_count"] == 2


# ─── audit alarm count ─────────────────────────────────────────────────

def test_unregistered_seen_count_excludes_registered(test_client):
    """Code with both flags → not counted as unregistered."""
    _seed_material(test_client, "BOTH-CODE", registered=True)
    _seed_bcct(test_client, "D301", "1", "BOTH-CODE")
    with connect() as conn:
        with conn.cursor() as cur:
            derive_from_bcct(cur, client_id=test_client,
                             customs_codes=["BOTH-CODE"])
            # Now code has both keys
            n = unregistered_seen_count(cur, client_id=test_client)
    assert n == 0


def test_unregistered_seen_count_includes_unregistered(test_client):
    """Code seen on BCCT but never registered → counted as unregistered."""
    _seed_bcct(test_client, "D401", "1", "UNREG-CODE")
    with connect() as conn:
        with conn.cursor() as cur:
            derive_from_bcct(cur, client_id=test_client,
                             customs_codes=["UNREG-CODE"])
            n = unregistered_seen_count(cur, client_id=test_client)
    assert n == 1


def test_unregistered_seen_count_zero_when_no_data(test_client):
    with connect() as conn:
        with conn.cursor() as cur:
            n = unregistered_seen_count(cur, client_id=test_client)
    assert n == 0


# ─── catalog upload preserves seen_in_bcct ─────────────────────────────

def test_catalog_upload_preserves_seen_in_bcct_on_existing_row(test_client):
    """Code seen on BCCT first → catalog upload registers it → both keys present."""
    _seed_bcct(test_client, "D501", "1", "PRESERVE-CODE")
    with connect() as conn:
        with conn.cursor() as cur:
            derive_from_bcct(cur, client_id=test_client,
                             customs_codes=["PRESERVE-CODE"])

    # Now simulate catalog upload via _insert_materials_with_cursor
    from app.routes.catalog import _insert_materials_with_cursor
    with connect() as conn:
        with conn.cursor() as cur:
            _insert_materials_with_cursor(
                cur, client_id=test_client,
                rows=[{
                    "customs_code": "PRESERVE-CODE",
                    "product_code": "P1",
                    "name": "Preserve Test",
                    "category": "tp",
                    "status": "active",
                }],
                upload_id="test-upload-001",
            )

    prov = _read_provenance(test_client, "PRESERVE-CODE")
    assert "seen_in_bcct" in prov, "seen_in_bcct was clobbered by catalog upload!"
    assert "registered_with_hq" in prov
    assert prov["registered_with_hq"]["source_upload_id"] == "test-upload-001"
