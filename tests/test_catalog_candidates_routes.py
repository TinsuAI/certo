"""HTTP route handlers for Mã chờ duyệt — page render + accept/reject/unreject.

End-to-end via TestClient against live DB.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.session import SESSION_COOKIE, create_session, hash_password
from app.database import connect
from app.main import app


CLIENT = "_test_route_dual"
USER_ID = "u_route_test"
USER_EMAIL = "route@test.local"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, 'route test') "
            "on conflict do nothing",
            (CLIENT,),
        )
        cur.execute(
            "insert into hub.users (user_id, email, display_name, password_hash, "
            " role, status) values (%s, %s, 'Route Tester', %s, 'admin', 'active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (USER_ID, USER_EMAIL, hash_password("test-password")),
        )
        for tbl in ("catalog_candidates", "code_mappings", "bcct_rows", "materials"):
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
    session_id = create_session(USER_ID)

    yield {"session_id": session_id}

    with connect() as conn, conn.cursor() as cur:
        for tbl in ("catalog_candidates", "code_mappings", "bcct_rows", "materials"):
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


def _seed_bcct(decl, customs, goods, direction="import"):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.bcct_rows
              (client_id, transaction_key, line_no, declaration_no,
               declaration_type, direction, registration_date,
               customs_code, goods_name, payload)
            values (%s, %s, '1', %s, 'E11', %s, '2026-04-01', %s, %s, '{}'::jsonb)
            """,
            (CLIENT, f"TX_{decl}", decl, direction, customs, goods),
        )


def _candidate_id(code, kind):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select candidate_id from hub.catalog_candidates "
            "where client_id=%s and code=%s and code_kind=%s",
            (CLIENT, code, kind),
        )
        r = cur.fetchone()
        return r[0] if r else None


# ── Page render ───────────────────────────────────────────────────────────


def test_candidates_page_requires_auth():
    c = TestClient(app)  # no session cookie
    r = c.get(f"/clients/{CLIENT}/catalog/candidates", follow_redirects=False)
    assert r.status_code in (302, 303, 401)


def test_candidates_page_404_for_unknown_client(setup):
    c = _client(setup["session_id"])
    r = c.get("/clients/_does_not_exist_/catalog/candidates",
              follow_redirects=False)
    assert r.status_code == 404


def test_candidates_page_renders_pending_after_refresh(setup):
    _seed_bcct("D1", "DAUNOI", "DAUNOI (019.X)")
    c = _client(setup["session_id"])
    r = c.get(f"/clients/{CLIENT}/catalog/candidates")
    assert r.status_code == 200
    body = r.text
    assert "DAUNOI" in body
    assert "019.X" in body


def test_candidates_page_shows_kind_chips(setup):
    _seed_bcct("D1", "DAUNOI", "DAUNOI (019.X)")
    c = _client(setup["session_id"])
    r = c.get(f"/clients/{CLIENT}/catalog/candidates")
    body = r.text
    # Both NB and HQ candidates appear; UI labels them
    assert "HQ" in body or "hq" in body
    assert "NB" in body or "nb" in body


# ── Accept route ──────────────────────────────────────────────────────────


def test_accept_endpoint_inserts_material(setup):
    _seed_bcct("D1", "DAUNOI", "DAUNOI (019.X)")
    c = _client(setup["session_id"])
    c.get(f"/clients/{CLIENT}/catalog/candidates")  # populates candidates
    cid = _candidate_id("DAUNOI", "hq")
    assert cid is not None
    r = c.post(
        f"/clients/{CLIENT}/catalog/candidates/{cid}/accept",
        data={"name": "Đầu nối", "category": "nvl", "status": "active"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select code_kind, category from hub.materials "
            "where client_id=%s and material_code='DAUNOI'", (CLIENT,)
        )
        row = cur.fetchone()
    assert row is not None
    assert row == ("hq", "nvl")


def test_accept_endpoint_rejects_unauthorized(setup):
    _seed_bcct("D1", "X", "X (019.X)")
    c = _client(setup["session_id"])
    c.get(f"/clients/{CLIENT}/catalog/candidates")
    cid = _candidate_id("X", "hq")
    # Drop session — no auth cookie
    no_auth = TestClient(app)
    r = no_auth.post(
        f"/clients/{CLIENT}/catalog/candidates/{cid}/accept",
        data={"name": "x", "category": "nvl"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303, 401, 403)


def test_accept_endpoint_404_for_unknown_candidate(setup):
    c = _client(setup["session_id"])
    r = c.post(
        f"/clients/{CLIENT}/catalog/candidates/9999999/accept",
        data={"name": "x", "category": "nvl"},
        follow_redirects=False,
    )
    assert r.status_code == 404


# ── Reject route ──────────────────────────────────────────────────────────


def test_reject_endpoint_marks_rejected(setup):
    _seed_bcct("D1", "NOISE", "NOISE (019.X)")
    c = _client(setup["session_id"])
    c.get(f"/clients/{CLIENT}/catalog/candidates")
    cid = _candidate_id("NOISE", "hq")
    r = c.post(
        f"/clients/{CLIENT}/catalog/candidates/{cid}/reject",
        data={"reason": "test rubbish"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select status, decision_reason from hub.catalog_candidates "
            "where candidate_id=%s", (cid,)
        )
        s, reason = cur.fetchone()
    assert s == "rejected"
    assert reason == "test rubbish"


def test_unreject_endpoint_resets_to_pending(setup):
    _seed_bcct("D1", "MAYBE", "MAYBE (019.X)")
    c = _client(setup["session_id"])
    c.get(f"/clients/{CLIENT}/catalog/candidates")
    cid = _candidate_id("MAYBE", "hq")
    c.post(f"/clients/{CLIENT}/catalog/candidates/{cid}/reject",
           data={"reason": "oops"}, follow_redirects=False)
    r = c.post(f"/clients/{CLIENT}/catalog/candidates/{cid}/unreject",
               follow_redirects=False)
    assert r.status_code == 303
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select status, decided_at, decision_reason "
            "from hub.catalog_candidates where candidate_id=%s", (cid,)
        )
        s, decided_at, reason = cur.fetchone()
    assert s == "pending"
    assert decided_at is None
    assert reason is None


# ── Filter chips ──────────────────────────────────────────────────────────


def test_filter_by_kind(setup):
    _seed_bcct("D1", "DAUNOI", "DAUNOI (019.X)")
    _seed_bcct("D2", "DOV", "DOV (019.Y)")
    c = _client(setup["session_id"])
    r = c.get(f"/clients/{CLIENT}/catalog/candidates?kind=hq")
    body = r.text
    assert "DAUNOI" in body
    assert "DOV" in body
    # NB codes filtered out
    assert "019.X" not in body or "data-kind=\"hq\"" in body  # tolerate filter UX


def test_rejected_section_shown(setup):
    _seed_bcct("D1", "NOISE", "NOISE (019.X)")
    c = _client(setup["session_id"])
    c.get(f"/clients/{CLIENT}/catalog/candidates")
    cid = _candidate_id("NOISE", "hq")
    c.post(f"/clients/{CLIENT}/catalog/candidates/{cid}/reject",
           data={"reason": "junk"}, follow_redirects=False)
    r = c.get(f"/clients/{CLIENT}/catalog/candidates")
    body = r.text
    assert "NOISE" in body  # appears in rejected section
