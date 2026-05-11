"""Sprint A4: catalog multi-source provenance.

Tests the auto-derive helper called from BCCT apply path + the catalog
upload path that sets registered_with_hq. Uses a synthetic test client
to avoid polluting real seed data.
"""
from __future__ import annotations

import secrets

import pytest

from app.database import connect
from app.stores.provenance import (
    bom_unresolved_material_count,
    derive_from_bcct,
    unregistered_seen_count,
)


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


def _seed_bcct(client_id: str, decl_no: str, line_no: str, material_code: str,
               registration_date: str = "2025-01-15", goods_name: str = "Test",
               unit: str | None = None):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no,
                   declaration_type, direction, registration_date, customs_code,
                   goods_name, unit, payload)
                values (%s, %s, %s, %s, 'E11', 'import', %s, %s, %s, %s, '{}'::jsonb)
                on conflict (client_id, year, transaction_key, line_no) do nothing
                """,
                (client_id, f"PROV_{decl_no}", line_no, decl_no,
                 registration_date, material_code, goods_name, unit),
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
                  (client_id, material_code, name, category, status, provenance)
                values (%s, %s, 'Existing', 'nvl', 'active', %s::jsonb)
                """,
                (client_id, customs_code, provenance),
            )


def _read_provenance(client_id: str, customs_code: str) -> dict:
    """Mig 042: provenance jsonb `seen_in_bcct` key dropped — replaced by
    source enum + v_material_roles view stats. This helper synthesizes the
    legacy jsonb shape from new schema so existing tests assert the same
    semantic without rewrite."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select m.provenance, m.source, m.hq_registered,
                       vmr.observed_count, vmr.observed_first_at, vmr.observed_last_at
                from hub.materials m
                left join hub.v_material_roles vmr
                       on vmr.client_id=m.client_id and vmr.material_code=m.material_code
                where m.client_id=%s and m.material_code=%s
                """,
                (client_id, customs_code),
            )
            row = cur.fetchone()
            if not row:
                return None
            prov, source, hq_reg, obs_count, obs_first, obs_last = row
            prov = dict(prov or {})
            # Re-synthesize seen_in_bcct from view stats. Any material with
            # observed_count > 0 (i.e., appears in BCCT) gets the legacy signal,
            # regardless of source enum value (which tracks initial provenance,
            # not whether the row has BCCT activity).
            if obs_count and obs_count > 0:
                prov["seen_in_bcct"] = {
                    "decl_count": obs_count,
                    "first_seen": obs_first.strftime("%Y-%m-%d") if obs_first else None,
                    "last_seen": obs_last.strftime("%Y-%m-%d") if obs_last else None,
                }
            if hq_reg and "registered_with_hq" not in prov:
                prov["registered_with_hq"] = {"first_seen": "synthetic"}
            return prov


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


# ─── bom_unresolved_material_count ────────────────────────────────────


def _seed_bom_with_materials(client_id: str, materials: list[tuple[str, str]],
                             code_mappings: list[tuple[str, str]],
                             bom_rows: list[tuple[str, str, float]]):
    """materials = [(customs_code, internal_code or None)],
    code_mappings = [(internal_code, customs_code)],
    bom_rows = [(product_code, material_code, qty)]"""
    from app.stores.bom import create_artifact
    with connect() as conn, conn.cursor() as cur:
        for cc, _ic in materials:
            # Mig 042: dropped materials.internal_code; legacy `ic` arg ignored
            # (values were redundant since 100% = customs_code).
            cur.execute(
                """insert into hub.materials
                   (client_id, material_code, name, category, status)
                   values (%s, %s, 'X', 'nvl', 'active')
                   on conflict do nothing""",
                (client_id, cc),
            )
        for ic, cc in code_mappings:
            cur.execute(
                """insert into hub.code_mappings
                   (client_id, internal_code, customs_code)
                   values (%s, %s, %s)
                   on conflict do nothing""",
                (client_id, ic, cc),
            )
    by_product: dict[str, list[dict]] = {}
    for prod, mat, qty in bom_rows:
        by_product.setdefault(prod, []).append(
            {"material_code": mat, "qty_per_unit": qty, "uom": "kg"},
        )
    for prod, rows in by_product.items():
        create_artifact(
            client_id=client_id, product_code=prod, rows=rows,
            actor="agency_staff", intent="asserted_technical",
            parent_artifact_id=None, context={}, source_upload_id=None,
        )


def test_bom_unresolved_zero_when_all_resolve(test_client):
    """All BOM material_codes resolve directly via materials.customs_code."""
    _seed_bom_with_materials(
        test_client,
        materials=[("M-A", None), ("M-B", None)],
        code_mappings=[],
        bom_rows=[("P-1", "M-A", 1.0), ("P-1", "M-B", 2.0)],
    )
    with connect() as conn, conn.cursor() as cur:
        assert bom_unresolved_material_count(cur, client_id=test_client) == 0


def test_bom_unresolved_zero_via_bqd(test_client):
    """BOM uses internal codes; BQD resolves them — 0 unresolved."""
    _seed_bom_with_materials(
        test_client,
        materials=[("HQ-001", None)],
        code_mappings=[("INT-001", "HQ-001")],
        bom_rows=[("P-1", "INT-001", 1.0)],
    )
    with connect() as conn, conn.cursor() as cur:
        assert bom_unresolved_material_count(cur, client_id=test_client) == 0


def test_bom_unresolved_counts_unmapped_codes(test_client):
    """A BOM material that has no catalog row, no internal_code match,
    no BQD entry — that's the genuine ghost-code case."""
    _seed_bom_with_materials(
        test_client,
        materials=[("HQ-001", None)],
        code_mappings=[("INT-001", "HQ-001")],
        bom_rows=[
            ("P-1", "INT-001", 1.0),       # resolves via BQD
            ("P-1", "GHOST-A", 0.5),       # neither in catalog nor BQD
            ("P-1", "GHOST-B", 0.5),
        ],
    )
    with connect() as conn, conn.cursor() as cur:
        assert bom_unresolved_material_count(cur, client_id=test_client) == 2


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


# ─── mig 063: derive_from_bcct must populate uom from BCCT.unit mode ───


def _read_material_uom(client_id: str, material_code: str) -> str | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select uom from hub.materials "
                "where client_id=%s and material_code=%s",
                (client_id, material_code),
            )
            row = cur.fetchone()
    return row[0] if row else None


def test_derive_captures_uom_from_bcct_mode(test_client):
    """Mig 063 invariant: new catalog row gets uom from the mode of
    BCCT.unit observations for that customs_code. Without this, engine
    would drift on `catalog_uom_missing` despite source data being
    available (the bug fixed by mig 063 + pipeline rework)."""
    _seed_bcct(test_client, "D-UOM-1", "1", "UOM-NEW",
               unit="KILO-GRAMMES")
    _seed_bcct(test_client, "D-UOM-2", "1", "UOM-NEW",
               unit="KILO-GRAMMES")
    _seed_bcct(test_client, "D-UOM-3", "1", "UOM-NEW",
               unit="METRIC-TONS")  # minority — should lose to mode
    with connect() as conn, conn.cursor() as cur:
        derive_from_bcct(cur, client_id=test_client,
                         customs_codes=["UOM-NEW"])
    # uom = mode = KILO-GRAMMES (raw from BCCT; alias normalization
    # happens at engine read time via uom_lookup).
    assert _read_material_uom(test_client, "UOM-NEW") == "KILO-GRAMMES"


def test_derive_backfills_uom_when_existing_row_missing_it(test_client):
    """On-conflict path: if material exists but uom IS NULL (legacy
    pre-mig-063 rows or rows seeded via other paths), re-running
    derive_from_bcct must populate uom from BCCT.unit mode."""
    # Pre-seed material without uom (simulates a legacy row).
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, category, "
            "status, source) values (%s, %s, 'nvl', 'active', 'bcct_observed')",
            (test_client, "UOM-LEGACY"),
        )
    assert _read_material_uom(test_client, "UOM-LEGACY") is None
    _seed_bcct(test_client, "D-UOM-BF", "1", "UOM-LEGACY", unit="SETS")
    with connect() as conn, conn.cursor() as cur:
        derive_from_bcct(cur, client_id=test_client,
                         customs_codes=["UOM-LEGACY"])
    assert _read_material_uom(test_client, "UOM-LEGACY") == "SETS"


def test_derive_keeps_existing_uom_when_already_set(test_client):
    """On-conflict path: if material already has a uom (staff-declared
    canonical via Mã chờ duyệt or edit form), derive_from_bcct must NOT
    clobber it. Staff override wins over BCCT mode."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials (client_id, material_code, category, "
            "status, source, uom) "
            "values (%s, %s, 'nvl', 'active', 'client_declared', 'pcs')",
            (test_client, "UOM-STAFF"),
        )
    _seed_bcct(test_client, "D-UOM-ST", "1", "UOM-STAFF", unit="KILO-GRAMMES")
    with connect() as conn, conn.cursor() as cur:
        derive_from_bcct(cur, client_id=test_client,
                         customs_codes=["UOM-STAFF"])
    # Staff-declared uom='pcs' survives; BCCT mode 'KILO-GRAMMES' is ignored.
    assert _read_material_uom(test_client, "UOM-STAFF") == "pcs"
