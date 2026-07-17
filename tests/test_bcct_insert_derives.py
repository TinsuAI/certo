"""_insert_bcct derives catalog rows (#52).

`_apply_bcct_rows` has always inserted declaration rows AND derived the
materials those codes name. The lower `_insert_bcct` wrapper did not, so
every caller that used it — `app/seed.py` and the ad-hoc script behind
Growatt's 2026-05-27 bulk ingest — left declared HQ codes with no material
row. Those codes then surfaced in the discovery queue as if a human had to
approve a fact the client already declared to customs.
"""
from __future__ import annotations

import secrets

import pytest

from app.database import connect
from app.routes.bcct import _insert_bcct


# `<prefix>-<8 hex>` so conftest's sweep reclaims it if this run is killed —
# _insert_bcct opens its own connection, so no rollback fixture can isolate it.
CLIENT = "insert-derives-" + secrets.token_hex(4)


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, customs_code_placeholders) "
            "values (%s, 'insert derives test', '{\".\"}')",
            (CLIENT,),
        )
        conn.commit()
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))
        conn.commit()


def _row(customs_code, *, line_no="1", goods_name=None, unit="PCE"):
    return {
        "transaction_key": "TK-DERIVE-1",
        "line_no": line_no,
        "declaration_no": "1234567890",
        "direction": "import",
        "registration_date": "2026-01-15",
        "customs_code": customs_code,
        "goods_name": goods_name or f"{customs_code}#&Hàng thử#&VN",
        "unit": unit,
        "payload": {},
    }


def _insert(rows):
    return _insert_bcct(client_id=CLIENT, rows=rows, upload_id=None,
                        client={"client_id": CLIENT})


def _materials():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select material_code, status, source, category, uom "
            "from hub.materials where client_id=%s order by material_code",
            (CLIENT,),
        )
        return cur.fetchall()


def test_insert_bcct_creates_material_for_new_customs_code():
    # uom lands as the raw mode token from bcct_rows.unit — derive does not
    # normalise; alias resolution happens at read time in app/stores/uom.py.
    _insert([_row("NEW-CODE-1")])
    assert _materials() == [
        ("NEW-CODE-1", "active", "bcct_observed", "nvl", "PCE"),
    ]


def test_insert_bcct_skips_placeholder_code():
    _insert([_row(".")])
    assert _materials() == []


def test_insert_bcct_derives_every_distinct_code_in_one_batch():
    _insert([_row("CODE-A", line_no="1"),
             _row("CODE-B", line_no="2"),
             _row(".", line_no="3"),
             _row("CODE-A", line_no="4")])
    assert [m[0] for m in _materials()] == ["CODE-A", "CODE-B"]


def test_insert_bcct_does_not_clobber_an_existing_material():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.materials "
            "(client_id, material_code, name, category, status, source) "
            "values (%s, 'CODE-EDITED', 'Tên do nhân viên sửa', 'tp', "
            "        'active', 'client_declared')",
            (CLIENT,),
        )
        conn.commit()
    _insert([_row("CODE-EDITED")])
    assert _materials() == [
        ("CODE-EDITED", "active", "client_declared", "tp", "PCE"),
    ]
