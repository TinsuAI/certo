"""customs_relevance is defined in 3 places — the canonical view
hub.v_material_classification, and inline CASEs in app/routes/api.py
(_MATERIALS_SELECT_WITH_ROLES) and app/routes/catalog.py (_query_materials),
the latter two to avoid a 2nd v_material_roles aggregation on hot paths.

This locks all three together so they cannot drift (mig 078/079).
"""
from __future__ import annotations

import secrets

import pytest

from app.database import connect
from app.routes.api import _MATERIALS_SELECT_WITH_ROLES
from app.routes.catalog import _query_materials


@pytest.fixture
def cid():
    client_id = "crp-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("insert into hub.clients (client_id, name) values (%s,%s)",
                    (client_id, "customs_relevance parity"))
    yield client_id
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bcct_rows where client_id=%s", (client_id,))
        cur.execute("delete from hub.materials where client_id=%s", (client_id,))
        cur.execute("delete from hub.client_material_group_map where client_id=%s", (client_id,))
        cur.execute("delete from hub.clients where client_id=%s", (client_id,))


def _seed(cid):
    with connect() as conn, conn.cursor() as cur:
        cur.executemany(
            "insert into hub.client_material_group_map "
            "(client_id, material_group, item_category, is_declarable) values (%s,%s,%s,%s)",
            [(cid, "MG_DOC", "document", False),    # rác
             (cid, "MG_MET", "metal", True)],       # declarable-class
        )
        cur.executemany(
            "insert into hub.materials (client_id, material_code, name, category, material_group) "
            "values (%s,%s,%s,'nvl',%s)",
            [(cid, "DOC_NOIMP", "DOC_NOIMP", "MG_DOC"),   # → excluded_non_material
             (cid, "DOC_IMP", "DOC_IMP", "MG_DOC"),       # imported rác → declarable (import wins)
             (cid, "MET_IMP", "MET_IMP", "MG_MET"),       # → declarable
             (cid, "MET_NOIMP", "MET_NOIMP", "MG_MET"),   # → declarable_unmatched
             (cid, "UNMAPPED", "UNMAPPED", "MG_X"),       # → review
             (cid, "NOMG", "NOMG", None)],                # → null
        )
        for code in ("DOC_IMP", "MET_IMP"):
            cur.execute(
                "insert into hub.bcct_rows (client_id, transaction_key, line_no, "
                "customs_code, direction, registration_date, payload) "
                "values (%s,%s,1,%s,'import','2026-01-15','{}'::jsonb)",
                (cid, "tx-" + code, code))


def _view(cid):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select material_code, customs_relevance from "
                    "hub.v_material_classification where client_id=%s", (cid,))
        return {r[0]: r[1] for r in cur.fetchall()}


def _api_inline(cid):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(_MATERIALS_SELECT_WITH_ROLES + " where m.client_id = %s", (cid,))
        cols = [d[0] for d in cur.description]
        return {r[cols.index("material_code")]: r[cols.index("customs_relevance")]
                for r in cur.fetchall()}


def _catalog_inline(cid):
    rows = _query_materials(client_id=cid, category=None, q=None, limit=500, offset=0)
    return {r["material_code"]: r["customs_relevance"] for r in rows}


def test_import_guard_and_enum(cid):
    _seed(cid)
    v = _view(cid)
    assert v["DOC_NOIMP"] == "excluded_non_material"
    assert v["DOC_IMP"] == "declarable"          # import wins over rác MG (mig 079)
    assert v["MET_IMP"] == "declarable"
    assert v["MET_NOIMP"] == "declarable_unmatched"
    assert v["UNMAPPED"] == "review"
    assert v["NOMG"] is None


def test_inline_matches_view(cid):
    _seed(cid)
    view, api, cat = _view(cid), _api_inline(cid), _catalog_inline(cid)
    assert api == view, f"api inline drifted from view: {api} vs {view}"
    assert cat == view, f"catalog inline drifted from view: {cat} vs {view}"
