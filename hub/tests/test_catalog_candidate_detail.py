"""Candidate detail page — keyed by ?code=&kind= (#34, no stored id).

Locks: renders the code + HS/UoM enrichment, BCCT sample lines,
co-occurrences from the persisted paren links, 404 for unknown codes,
and client scoping (another client's code 404s).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hub.app.auth.session import SESSION_COOKIE, create_session, hash_password
from hub.app.database import connect
from hub.app.main import app


CLIENT = "_test_detail_disc"
OTHER = "_test_detail_other"
USER_ID = "u_detail_test"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        for cid, name in ((CLIENT, "detail test"), (OTHER, "other")):
            cur.execute(
                "insert into hub.clients (client_id, name) values (%s, %s) "
                "on conflict do nothing",
                (cid, name),
            )
        cur.execute(
            "insert into hub.users (user_id, email, display_name, password_hash, "
            " role, status) values (%s, 'detail@test.local', 'D', %s, 'admin', "
            " 'active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (USER_ID, hash_password("pw")),
        )
        for cid in (CLIENT, OTHER):
            for tbl in ("catalog_rejections", "bcct_nb_codes", "bcct_rows",
                        "materials", "client_parser_rules"):
                cur.execute(f"delete from hub.{tbl} where client_id=%s", (cid,))
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, source_field, "
            " match_group, match_action, no_match_action, enabled, created_by) "
            "values (%s, 'internal_code', 10, '\\(([\\d\\.\\w\\-]+)\\)', "
            " 'goods_name', 1, 'capture', 'next_rule', true, 'test')",
            (CLIENT,),
        )
        cur.execute(
            """
            insert into hub.bcct_rows
              (client_id, transaction_key, line_no, declaration_no,
               declaration_type, direction, registration_date, customs_code,
               goods_name, hs_code, unit, payload)
            values (%s, 'TXD', '1', 'DD1', 'E11', 'import', '2026-04-01',
                    'BUCKET', 'hàng test (019.D)', '85044090', 'PCS',
                    '{}'::jsonb)
            """,
            (CLIENT,),
        )
    from hub.app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()
    from hub.app.stores.bcct_nb_codes import rebuild_for_client
    rebuild_for_client(CLIENT)
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, create_session(USER_ID))
    yield c
    with connect() as conn, conn.cursor() as cur:
        for cid in (CLIENT, OTHER):
            for tbl in ("catalog_rejections", "bcct_nb_codes", "bcct_rows",
                        "materials", "client_parser_rules"):
                cur.execute(f"delete from hub.{tbl} where client_id=%s", (cid,))
            cur.execute("delete from hub.clients where client_id=%s", (cid,))
        cur.execute("delete from hub.sessions where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.users where user_id=%s", (USER_ID,))
    clear_rules_cache()


def test_detail_renders_enrichment(setup):
    r = setup.get(
        f"/clients/{CLIENT}/catalog/candidates/detail?code=BUCKET&kind=hq",
    )
    assert r.status_code == 200
    body = r.text
    assert "BUCKET" in body
    assert "85044090" in body
    assert "DD1" in body            # BCCT sample line
    assert "019.D" in body          # co-occurrence partner


def test_detail_nb_side_shows_hq_partner(setup):
    r = setup.get(
        f"/clients/{CLIENT}/catalog/candidates/detail?code=019.D&kind=nb",
    )
    assert r.status_code == 200
    assert "BUCKET" in r.text


def test_detail_404_unknown_code(setup):
    r = setup.get(
        f"/clients/{CLIENT}/catalog/candidates/detail?code=NOPE",
    )
    assert r.status_code == 404


def test_detail_is_client_scoped(setup):
    """BUCKET exists for CLIENT only — OTHER 404s on the same code."""
    r = setup.get(
        f"/clients/{OTHER}/catalog/candidates/detail?code=BUCKET",
    )
    assert r.status_code == 404
