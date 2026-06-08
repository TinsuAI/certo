"""hub.v_material_classification — derived item_category + customs_relevance
(migration 078). Locks the declarability enum.

  material_group NULL          → customs_relevance NULL
  MG present, no map row        → 'review'
  map.is_declarable = false     → 'excluded_non_material'
  declarable + BCCT import      → 'declarable'
  declarable + no import        → 'declarable_unmatched'
"""
from __future__ import annotations

import secrets

import pytest

from app.database import connect


@pytest.fixture
def cid():
    client_id = "vmc-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s)",
            (client_id, "v_material_classification test"),
        )
    yield client_id
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bcct_rows where client_id=%s", (client_id,))
        cur.execute("delete from hub.materials where client_id=%s", (client_id,))
        cur.execute("delete from hub.client_material_group_map where client_id=%s",
                    (client_id,))
        cur.execute("delete from hub.clients where client_id=%s", (client_id,))


def _material(cur, cid, code, mg):
    cur.execute(
        "insert into hub.materials (client_id, material_code, name, category, "
        "material_group) values (%s,%s,%s,'nvl',%s)",
        (cid, code, code, mg),
    )


def _map(cur, cid, mg, item_category, is_declarable):
    cur.execute(
        "insert into hub.client_material_group_map "
        "(client_id, material_group, item_category, is_declarable) "
        "values (%s,%s,%s,%s)",
        (cid, mg, item_category, is_declarable),
    )


def _import(cur, cid, code):
    cur.execute(
        "insert into hub.bcct_rows (client_id, transaction_key, line_no, "
        "customs_code, direction, registration_date, payload) "
        "values (%s,%s,1,%s,'import','2026-01-15','{}'::jsonb)",
        (cid, "tx-" + code, code),
    )


def _classify(cid):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select material_code, item_category, customs_relevance "
            "from hub.v_material_classification where client_id=%s "
            "order by material_code", (cid,),
        )
        return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def test_customs_relevance_enum(cid):
    with connect() as conn, conn.cursor() as cur:
        _map(cur, cid, "MG_DRAW", "drawing", False)
        _map(cur, cid, "MG_STEEL", "metal", True)
        _material(cur, cid, "DRAW1", "MG_DRAW")     # rác
        _material(cur, cid, "STEEL_IMP", "MG_STEEL")  # declarable
        _material(cur, cid, "STEEL_NOIMP", "MG_STEEL")  # declarable_unmatched
        _material(cur, cid, "UNMAPPED", "MG_XYZ")   # MG present, no map → review
        _material(cur, cid, "NOMG", None)           # no MG → NULL
        _import(cur, cid, "STEEL_IMP")

    got = _classify(cid)
    assert got["DRAW1"] == ("drawing", "excluded_non_material")
    assert got["STEEL_IMP"] == ("metal", "declarable")
    assert got["STEEL_NOIMP"] == ("metal", "declarable_unmatched")
    assert got["UNMAPPED"][1] == "review"
    assert got["NOMG"] == (None, None)
