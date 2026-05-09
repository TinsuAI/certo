"""Candidate enrichment — HS code, UoM, origin, production_source inference.

Each candidate must carry near-catalog-equivalent fields so Accept doesn't
add sparse rows.
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.database import connect


CLIENT = "_test_richness"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, 'rich test') "
            "on conflict do nothing",
            (CLIENT,),
        )
        for tbl in ("catalog_candidates", "bcct_rows", "materials"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute(
            "delete from hub.client_parser_rules where client_id=%s", (CLIENT,)
        )
    yield
    with connect() as conn, conn.cursor() as cur:
        for tbl in ("catalog_candidates", "bcct_rows", "materials"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute(
            "delete from hub.client_parser_rules where client_id=%s", (CLIENT,)
        )
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _seed_bcct(rows):
    """rows: (decl, customs_code, hs_code, unit, origin, direction, goods_name)."""
    with connect() as conn, conn.cursor() as cur:
        for i, (decl, cc, hs, unit, origin, dirn, gn) in enumerate(rows):
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no,
                   declaration_type, direction, registration_date,
                   customs_code, hs_code, unit, origin, goods_name, payload)
                values (%s, %s, '1', %s, 'E11', %s, '2026-04-01',
                        %s, %s, %s, %s, %s, '{}'::jsonb)
                """,
                (CLIENT, f"TX_{decl}_{i}", decl, dirn, cc, hs, unit, origin, gn),
            )


def _candidate(code, kind="unified"):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select hs_code, hs_alternates_count, uom, origin, "
            "inferred_production_source "
            "from hub.catalog_candidates "
            "where client_id=%s and code=%s and code_kind=%s",
            (CLIENT, code, kind),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def test_richness_hs_code_most_common():
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct([
        ("D1", "X", "85369012", "PIECES", "VN", "import", "X#&item"),
        ("D2", "X", "85369012", "PIECES", "VN", "import", "X#&item"),
        ("D3", "X", "85369019", "PIECES", "VN", "import", "X#&item"),
    ])
    refresh_candidates(CLIENT)
    c = _candidate("X")
    assert c is not None
    assert c["hs_code"] == "85369012"  # 2/3 occurrences
    assert c["hs_alternates_count"] == 2  # 2 distinct HS codes


def test_richness_single_hs_no_warning():
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct([
        ("D1", "Y", "85332100", "PIECES", "VN", "import", "Y#&res"),
    ])
    refresh_candidates(CLIENT)
    c = _candidate("Y")
    assert c["hs_code"] == "85332100"
    assert c["hs_alternates_count"] == 1  # only 1 distinct, no warning


def test_richness_uom_most_common_normalized():
    """UoM aliases collapse to canonical before picking most-common."""
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct([
        ("D1", "Z", "85332100", "PIECES", "VN", "import", "Z"),
        ("D2", "Z", "85332100", "PIECES", "VN", "import", "Z"),
        ("D3", "Z", "85332100", "KG", "VN", "import", "Z"),
    ])
    refresh_candidates(CLIENT)
    c = _candidate("Z")
    assert c["uom"] == "pcs"  # canonical of PIECES; 2/3 occurrences


def test_richness_uom_synonyms_collapse():
    """PIECES + PCS + ST should collapse to single 'pcs' bucket and
    outvote a single KG."""
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct([
        ("D1", "Z2", "85332100", "PIECES", "VN", "import", "Z2"),
        ("D2", "Z2", "85332100", "PCS", "VN", "import", "Z2"),
        ("D3", "Z2", "85332100", "KG", "VN", "import", "Z2"),
    ])
    refresh_candidates(CLIENT)
    c = _candidate("Z2")
    assert c["uom"] == "pcs"  # 2 alias-collapsed votes vs 1 kg


def test_richness_origin_most_common():
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct([
        ("D1", "W", "85332100", "PIECES", "CN", "import", "W"),
        ("D2", "W", "85332100", "PIECES", "CN", "import", "W"),
        ("D3", "W", "85332100", "PIECES", "VN", "import", "W"),
    ])
    refresh_candidates(CLIENT)
    c = _candidate("W")
    assert c["origin"] == "CN"


def test_inferred_production_source_import_only_is_nk():
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct([
        ("D1", "A", "85332100", "PIECES", "CN", "import", "A"),
        ("D2", "A", "85332100", "PIECES", "CN", "import", "A"),
    ])
    refresh_candidates(CLIENT)
    c = _candidate("A")
    assert c["inferred_production_source"] == "nk"


def test_inferred_production_source_export_only_is_sx():
    """Export-only is a hint that this is a TP produced internally → 'sx'."""
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct([
        ("D1", "B", "85332100", "PIECES", "VN", "export", "B"),
    ])
    refresh_candidates(CLIENT)
    c = _candidate("B")
    assert c["inferred_production_source"] == "sx"


def test_inferred_production_source_both_directions_is_mixed():
    from app.stores.catalog_candidates import refresh_candidates
    _seed_bcct([
        ("D1", "C", "85332100", "PIECES", "CN", "import", "C"),
        ("D2", "C", "85332100", "PIECES", "VN", "export", "C"),
    ])
    refresh_candidates(CLIENT)
    c = _candidate("C")
    assert c["inferred_production_source"] == "mixed"
