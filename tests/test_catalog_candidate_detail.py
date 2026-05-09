"""Candidate detail page — surface full info + cross-references for one candidate."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.session import SESSION_COOKIE, create_session, hash_password
from app.database import connect
from app.main import app


CLIENT = "_test_cdetail"
USER_ID = "u_cdetail"
USER_EMAIL = "cdetail@test.local"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, 'cdetail') "
            "on conflict do nothing",
            (CLIENT,),
        )
        cur.execute(
            "insert into hub.users (user_id, email, display_name, password_hash, "
            " role, status) values (%s, %s, 'CD Test', %s, 'admin', 'active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (USER_ID, USER_EMAIL, hash_password("test-pw")),
        )
        for tbl in ("catalog_candidates", "bcct_rows", "materials"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute(
            "delete from hub.client_parser_rules where client_id=%s", (CLIENT,)
        )
        cur.execute(
            "insert into hub.client_parser_rules "
            "(client_id, output_field, priority, pattern, source_field, "
            " match_group, match_action, no_match_action, enabled, created_by) "
            "values (%s, 'internal_code', 10, '\\(([\\d\\.\\w\\-]+)\\)', "
            " 'goods_name', 1, 'capture', 'next_rule', true, 'test') "
            "on conflict do nothing",
            (CLIENT,),
        )
    from app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()
    session = create_session(USER_ID)
    yield {"session": session}
    with connect() as conn, conn.cursor() as cur:
        for tbl in ("catalog_candidates", "bcct_rows", "materials"):
            cur.execute(f"delete from hub.{tbl} where client_id=%s", (CLIENT,))
        cur.execute(
            "delete from hub.client_parser_rules where client_id=%s", (CLIENT,)
        )
        cur.execute("delete from hub.sessions where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.users where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))
    clear_rules_cache()


def _client(session_id):
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, session_id)
    return c


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


def _refresh_and_get_id(code, kind):
    from app.stores.catalog_candidates import refresh_candidates
    refresh_candidates(CLIENT)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select candidate_id from hub.catalog_candidates "
            "where client_id=%s and code=%s and code_kind=%s",
            (CLIENT, code, kind),
        )
        row = cur.fetchone()
        return row[0] if row else None


def test_candidate_detail_renders(setup):
    _seed_bcct([
        ("D1", "WIDGET", "85369012", "PIECES", "VN", "import", "WIDGET#&item"),
    ])
    # Client has parser_rules → has_dual_system=True → no-paren goods_name
    # classifies as kind='hq'.
    cid = _refresh_and_get_id("WIDGET", "hq")
    c = _client(setup["session"])
    r = c.get(f"/clients/{CLIENT}/catalog/candidates/{cid}")
    assert r.status_code == 200
    assert "WIDGET" in r.text
    assert "85369012" in r.text  # HS code shown
    assert "PIECES" in r.text  # UoM shown


def test_candidate_detail_shows_bcct_samples(setup):
    _seed_bcct([
        ("D1", "WIDGET", "85369012", "PIECES", "VN", "import",
         "WIDGET#&Sample one"),
        ("D2", "WIDGET", "85369012", "PIECES", "VN", "import",
         "WIDGET#&Sample two"),
    ])
    cid = _refresh_and_get_id("WIDGET", "hq")
    c = _client(setup["session"])
    r = c.get(f"/clients/{CLIENT}/catalog/candidates/{cid}")
    assert "D1" in r.text
    assert "D2" in r.text


def test_candidate_detail_shows_co_occurrences(setup):
    """HQ candidate with multiple paired NB → list them."""
    _seed_bcct([
        ("D1", "BUCKET", "85369012", "PIECES", "VN", "import",
         "BUCKET#&parts (019.X)"),
        ("D2", "BUCKET", "85369012", "PIECES", "VN", "import",
         "BUCKET#&parts (019.Y)"),
    ])
    cid = _refresh_and_get_id("BUCKET", "hq")
    c = _client(setup["session"])
    r = c.get(f"/clients/{CLIENT}/catalog/candidates/{cid}")
    body = r.text
    assert "019.X" in body
    assert "019.Y" in body


def test_candidate_detail_404_for_unknown(setup):
    c = _client(setup["session"])
    r = c.get(f"/clients/{CLIENT}/catalog/candidates/99999999",
              follow_redirects=False)
    assert r.status_code == 404


def test_candidate_detail_404_for_other_client_candidate(setup):
    """Candidate belongs to another client → 404 (URL-tampering protection)."""
    _seed_bcct([
        ("D1", "X", "85369012", "PIECES", "VN", "import", "X#&item"),
    ])
    cid = _refresh_and_get_id("X", "hq")
    c = _client(setup["session"])
    r = c.get(f"/clients/_other_client_/catalog/candidates/{cid}",
              follow_redirects=False)
    # Either 404 (candidate not in URL client) or 403/404 (URL client doesn't exist)
    assert r.status_code in (403, 404)
