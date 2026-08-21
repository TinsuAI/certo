"""Catalog material detail — cross-source inconsistency warnings.

For each material, query BCCT/BOM/code_mappings and compute warnings:
- HS code drift (multiple distinct hs_code values for same material)
- UoM drift (BCCT.unit vs BOM.uom vs materials.uom mismatch)
- Origin drift (BCCT.origin variation)
- Direction drift (declared as both import + export)
- Mapping drift (1 NB → multiple HQ buckets, or vice versa)
"""
from __future__ import annotations

import pytest

from app.database import connect


CLIENT = "_test_warn_dual"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, 'warn test') "
            "on conflict do nothing",
            (CLIENT,),
        )
        for tbl in ("bcct_rows", "code_mappings", "materials"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute(
            "insert into hub.materials (client_id, material_code, name, "
            " category, status, source, code_kind, uom) "
            "values (%s, 'WIDGET', 'Widget', 'nvl', 'active', "
            "'client_declared', 'unified', 'PIECES')",
            (CLIENT,),
        )
    yield
    with connect() as conn, conn.cursor() as cur:
        for tbl in ("bcct_rows", "code_mappings", "materials"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _seed_bcct(rows):
    """rows: (decl, customs_code, hs_code, unit, origin, direction)."""
    with connect() as conn, conn.cursor() as cur:
        for i, (decl, cc, hs, unit, origin, dirn) in enumerate(rows):
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no,
                   declaration_type, direction, registration_date,
                   customs_code, hs_code, unit, origin, goods_name, payload)
                values (%s, %s, '1', %s, 'E11', %s, '2026-04-01',
                        %s, %s, %s, %s, %s, '{}'::jsonb)
                """,
                (CLIENT, f"TX_{decl}_{i}", decl, dirn, cc, hs, unit, origin,
                 cc + "#&item"),
            )


# ── HS code drift ─────────────────────────────────────────────────────────


def test_no_warning_when_single_hs_code():
    from app.stores.catalog_warnings import compute_warnings
    _seed_bcct([
        ("D1", "WIDGET", "85369012", "PIECES", "VN", "import"),
        ("D2", "WIDGET", "85369012", "PIECES", "VN", "import"),
    ])
    w = compute_warnings(CLIENT, "WIDGET")
    assert all(x["kind"] != "hs_drift" for x in w), f"unexpected: {w}"


def test_warns_on_hs_code_drift():
    from app.stores.catalog_warnings import compute_warnings
    _seed_bcct([
        ("D1", "WIDGET", "85369012", "PIECES", "VN", "import"),
        ("D2", "WIDGET", "85369012", "PIECES", "VN", "import"),
        ("D3", "WIDGET", "85369019", "PIECES", "VN", "import"),
    ])
    w = compute_warnings(CLIENT, "WIDGET")
    hs = next((x for x in w if x["kind"] == "hs_drift"), None)
    assert hs is not None
    assert hs["count"] == 2  # 2 distinct HS codes
    # Evidence: each HS code with its frequency
    assert any(e["value"] == "85369012" and e["n"] == 2 for e in hs["evidence"])
    assert any(e["value"] == "85369019" and e["n"] == 1 for e in hs["evidence"])


# ── UoM drift ─────────────────────────────────────────────────────────────


def test_warns_on_uom_drift():
    """Materials says PIECES but BCCT shows KG too."""
    from app.stores.catalog_warnings import compute_warnings
    _seed_bcct([
        ("D1", "WIDGET", "85369012", "PIECES", "VN", "import"),
        ("D2", "WIDGET", "85369012", "KG", "VN", "import"),
    ])
    w = compute_warnings(CLIENT, "WIDGET")
    uom = next((x for x in w if x["kind"] == "uom_drift"), None)
    assert uom is not None


def test_uom_drift_incompatible_stays_warn():
    """A.4.4: PIECES vs KG (count↔mass) can't convert → severity warn."""
    from app.stores.catalog_warnings import compute_warnings
    _seed_bcct([
        ("D1", "WIDGET", "85369012", "PIECES", "VN", "import"),
        ("D2", "WIDGET", "85369012", "KG", "VN", "import"),
    ])
    uom = next((x for x in compute_warnings(CLIENT, "WIDGET")
                if x["kind"] == "uom_drift"), None)
    assert uom is not None
    assert uom["severity"] == "warn"


def test_uom_drift_same_family_convertible_is_info():
    """A.4.4: g vs kg convert cleanly → still surfaced but info, not warn."""
    from app.stores.catalog_warnings import compute_warnings
    with connect() as conn, conn.cursor() as cur:
        cur.execute("update hub.materials set uom='kg' where client_id=%s "
                    "and material_code='WIDGET'", (CLIENT,))
    _seed_bcct([
        ("D1", "WIDGET", "85369012", "g", "VN", "import"),
        ("D2", "WIDGET", "85369012", "kg", "VN", "import"),
    ])
    uom = next((x for x in compute_warnings(CLIENT, "WIDGET")
                if x["kind"] == "uom_drift"), None)
    assert uom is not None
    assert uom["severity"] == "info"


def test_uom_drift_tier_a_unconfirmed_stays_warn():
    """A.4.4: SETS vs PIECES is tier-A 1:1 (a guess) → needs confirmation,
    so it stays warn, consistent with the panel's amber chip."""
    from app.stores.catalog_warnings import compute_warnings
    _seed_bcct([
        ("D1", "WIDGET", "85369012", "PIECES", "VN", "import"),
        ("D2", "WIDGET", "85369012", "SETS", "VN", "import"),
    ])
    uom = next((x for x in compute_warnings(CLIENT, "WIDGET")
                if x["kind"] == "uom_drift"), None)
    assert uom is not None
    assert uom["severity"] == "warn"


def test_no_warning_for_uom_synonyms():
    """PCS / PIECE / ST all resolve to canonical 'pcs' → no drift warning."""
    from app.stores.catalog_warnings import compute_warnings
    _seed_bcct([
        ("D1", "WIDGET", "85369012", "PIECES", "VN", "import"),
        ("D2", "WIDGET", "85369012", "PCS", "VN", "import"),
        ("D3", "WIDGET", "85369012", "ST", "VN", "import"),
    ])
    w = compute_warnings(CLIENT, "WIDGET")
    assert all(x["kind"] != "uom_drift" for x in w), \
        f"unexpected uom_drift for synonyms: {w}"


def test_no_warning_when_catalog_uom_is_alias_of_bcct_uom():
    """Catalog uom='PIECES', BCCT unit='PCS' → same canonical 'pcs' → no warn."""
    from app.stores.catalog_warnings import compute_warnings
    # Seed update materials.uom (was 'PIECES' from initial setup)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.materials set uom='PIECES' where client_id=%s "
            "and material_code='WIDGET'", (CLIENT,),
        )
    _seed_bcct([
        ("D1", "WIDGET", "85369012", "PCS", "VN", "import"),
        ("D2", "WIDGET", "85369012", "PCS", "VN", "import"),
    ])
    w = compute_warnings(CLIENT, "WIDGET")
    assert all(x["kind"] != "uom_drift" for x in w), \
        f"unexpected uom_drift: {w}"


# ── Origin drift ──────────────────────────────────────────────────────────


def test_warns_on_origin_drift():
    from app.stores.catalog_warnings import compute_warnings
    _seed_bcct([
        ("D1", "WIDGET", "85369012", "PIECES", "VN", "import"),
        ("D2", "WIDGET", "85369012", "PIECES", "CN", "import"),
        ("D3", "WIDGET", "85369012", "PIECES", "JP", "import"),
    ])
    w = compute_warnings(CLIENT, "WIDGET")
    origin = next((x for x in w if x["kind"] == "origin_drift"), None)
    assert origin is not None
    assert origin["count"] == 3


# ── Direction drift ──────────────────────────────────────────────────────


def test_warns_on_both_directions():
    from app.stores.catalog_warnings import compute_warnings
    _seed_bcct([
        ("D1", "WIDGET", "85369012", "PIECES", "VN", "import"),
        ("D2", "WIDGET", "85369012", "PIECES", "VN", "export"),
    ])
    w = compute_warnings(CLIENT, "WIDGET")
    direction = next((x for x in w if x["kind"] == "direction_drift"), None)
    assert direction is not None


# ── Mapping drift (N-N code_mappings) ─────────────────────────────────────


def test_warns_on_multiple_hq_for_one_nb():
    """NB code mapped to multiple HQ buckets → potential ambiguity."""
    from app.stores.catalog_warnings import compute_warnings
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.code_mappings (client_id, internal_code, customs_code) "
            "values (%s, 'WIDGET', 'BUCKET-A'), (%s, 'WIDGET', 'BUCKET-B')",
            (CLIENT, CLIENT),
        )
    w = compute_warnings(CLIENT, "WIDGET")
    mapping = next((x for x in w if x["kind"] == "mapping_drift"), None)
    assert mapping is not None
    assert mapping["count"] == 2


def test_no_warnings_when_clean():
    from app.stores.catalog_warnings import compute_warnings
    _seed_bcct([
        ("D1", "WIDGET", "85369012", "PIECES", "VN", "import"),
    ])
    w = compute_warnings(CLIENT, "WIDGET")
    assert w == []
