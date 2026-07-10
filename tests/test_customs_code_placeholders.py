"""Per-client customs_code placeholder config (mig 090, issue #30).

A placeholder is a string a client writes in the BCCT customs_code field
to mean "no HQ code on this line" (Growatt/Johnson use '.'). Placeholder
lines mark fixed-asset rows (E13 forklifts, racks) — they must never
become materials.
"""
from __future__ import annotations

import pytest

from app.database import connect


@pytest.fixture()
def cur():
    with connect() as conn, conn.cursor() as cur:
        yield cur
        conn.rollback()


def test_seeded_clients_have_dot_placeholder(cur):
    cur.execute(
        "select client_id, customs_code_placeholders from hub.clients "
        "where client_id in ('growatt-vn', 'johnson-vn') order by client_id",
    )
    rows = dict(cur.fetchall())
    assert rows == {"growatt-vn": ["."], "johnson-vn": ["."]}


def test_new_client_defaults_to_no_placeholders(cur):
    cur.execute(
        "insert into hub.clients (client_id, name) "
        "values ('tmp-placeholder-default', 'tmp') "
        "returning customs_code_placeholders",
    )
    (placeholders,) = cur.fetchone()
    assert placeholders == []


# ── derive_from_bcct skips placeholder lines ──────────────────────────────


def _insert_bcct_row(cur, client_id, line_no, customs_code, goods_name):
    cur.execute(
        "insert into hub.bcct_rows "
        "(client_id, transaction_key, line_no, customs_code, goods_name, "
        " unit, payload, registration_date) "
        "values (%s, 'TK-PH-TEST', %s, %s, %s, 'PCE', '{}'::jsonb, "
        "        '2026-01-15')",
        (client_id, line_no, customs_code, goods_name),
    )


def _derive(cur, client_id, codes):
    from app.stores.provenance import derive_from_bcct
    return derive_from_bcct(cur, client_id=client_id, customs_codes=codes)


def test_derive_skips_placeholder_never_creates_material(cur):
    """The oracle from #30: placeholder lines never become materials."""
    cur.execute(
        "insert into hub.clients (client_id, name, customs_code_placeholders) "
        "values ('tmp-ph-dash', 'tmp', '{\"-\"}')",
    )
    _insert_bcct_row(cur, "tmp-ph-dash", "1", "-", "forklift, no HQ code")
    _insert_bcct_row(cur, "tmp-ph-dash", "2", "REALCODE", "real material")
    _derive(cur, "tmp-ph-dash", ["-", "REALCODE"])
    cur.execute(
        "select material_code from hub.materials where client_id='tmp-ph-dash'",
    )
    assert [r[0] for r in cur.fetchall()] == ["REALCODE"]


def test_derive_skips_dot_for_seeded_client(cur):
    """Re-running a Growatt-shaped ingest does not recreate the '.' junk row."""
    _insert_bcct_row(cur, "growatt-vn", "ph-1", ".", "BYD forklift (E13)")
    _derive(cur, "growatt-vn", ["."])
    cur.execute(
        "select count(*) from hub.materials "
        "where client_id='growatt-vn' and material_code='.'",
    )
    (n,) = cur.fetchone()
    assert n == 0


def test_derive_placeholder_of_other_client_is_not_global(cur):
    """'-' is tmp-ph-dash's placeholder, not growatt-vn's — for Growatt it
    stays an ordinary customs_code."""
    _insert_bcct_row(cur, "growatt-vn", "ph-2", "-", "dash is a real code here")
    _derive(cur, "growatt-vn", ["-"])
    cur.execute(
        "select count(*) from hub.materials "
        "where client_id='growatt-vn' and material_code='-'",
    )
    (n,) = cur.fetchone()
    assert n == 1
