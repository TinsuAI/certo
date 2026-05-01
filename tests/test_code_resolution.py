"""Code resolution worker tests — Growatt-style 1:n disambiguation."""
import pytest

from app.database import connect
from app.stores.code_resolution import resolve_for_dncx, lookup_resolution


@pytest.fixture
def client_fixture():
    client_id = "test-resolver-dncx"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.code_mapping_resolutions where client_id = %s", (client_id,))
            cur.execute("delete from hub.bcct_rows where client_id = %s", (client_id,))
            cur.execute("delete from hub.code_mappings where client_id = %s", (client_id,))
            cur.execute("delete from hub.clients where client_id = %s", (client_id,))
            cur.execute(
                """
                insert into hub.clients (client_id, name, code_resolution_mode)
                values (%s, 'Test Resolver', 'batch_aggregate_resolution')
                """,
                (client_id,),
            )
    yield client_id
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.code_mapping_resolutions where client_id = %s", (client_id,))
            cur.execute("delete from hub.bcct_rows where client_id = %s", (client_id,))
            cur.execute("delete from hub.code_mappings where client_id = %s", (client_id,))
            cur.execute("delete from hub.clients where client_id = %s", (client_id,))


def _seed(client_id, mappings, bcct):
    with connect() as conn:
        with conn.cursor() as cur:
            for ic, cc in mappings:
                cur.execute(
                    "insert into hub.code_mappings (client_id, internal_code, customs_code) values (%s, %s, %s)",
                    (client_id, ic, cc),
                )
            for i, (ic, cc, qty, direction) in enumerate(bcct):
                cur.execute(
                    """
                    insert into hub.bcct_rows
                      (client_id, year, transaction_key, line_no, internal_code, customs_code, quantity, direction)
                    values (%s, 2025, %s, '0', %s, %s, %s, %s)
                    """,
                    (client_id, f"tk-{i}", ic, cc, qty, direction),
                )


def test_bqd_unique_basis(client_fixture):
    _seed(client_fixture, mappings=[("X", "X-HQ")], bcct=[])
    summary = resolve_for_dncx(client_fixture)
    res = lookup_resolution(client_id=client_fixture, internal_code="X")
    assert res["resolution_basis"] == "bqd_unique"
    assert res["resolved_customs_code"] == "X-HQ"
    assert summary["bqd_unique"] == 1


def test_one_to_n_resolved_by_bcct_qty(client_fixture):
    _seed(
        client_fixture,
        mappings=[("X", "X-A"), ("X", "X-B"), ("X", "X-C")],
        bcct=[
            ("X", "X-A", 10, "import"),
            ("X", "X-B", 50, "import"),
            ("X", "X-C", 5, "import"),
        ],
    )
    resolve_for_dncx(client_fixture)
    res = lookup_resolution(client_id=client_fixture, internal_code="X")
    assert res["resolution_basis"] == "bcct_qty_pick"
    assert res["resolved_customs_code"] == "X-B"


def test_one_to_n_falls_back_when_no_bcct_qty(client_fixture):
    _seed(
        client_fixture,
        mappings=[("Y", "Y-A"), ("Y", "Y-B")],
        bcct=[],
    )
    resolve_for_dncx(client_fixture)
    res = lookup_resolution(client_id=client_fixture, internal_code="Y")
    assert res["resolution_basis"] == "fallback"
    assert res["resolved_customs_code"] in {"Y-A", "Y-B"}


def test_identity_for_codes_only_in_bcct(client_fixture):
    _seed(
        client_fixture,
        mappings=[],
        bcct=[("Z", "Z", 100, "export")],
    )
    resolve_for_dncx(client_fixture)
    res = lookup_resolution(client_id=client_fixture, internal_code="Z")
    assert res["resolution_basis"] == "identity"
    assert res["resolved_customs_code"] == "Z"


def test_backfills_resolved_customs_code_on_bcct_rows(client_fixture):
    _seed(
        client_fixture,
        mappings=[("M", "M-PRIMARY"), ("M", "M-ALT")],
        bcct=[
            ("M", "M-PRIMARY", 100, "import"),
            ("M", "M-ALT", 5, "import"),
        ],
    )
    resolve_for_dncx(client_fixture)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select internal_code, resolved_customs_code from hub.bcct_rows where client_id = %s",
                (client_fixture,),
            )
            rows = cur.fetchall()
    assert all(r[1] == "M-PRIMARY" for r in rows)
