"""HTTP route handlers for Mã chờ duyệt — live feed + decisions (#34).

End-to-end via TestClient against live DB. The feed is computed
(hub.catalog_discovery), so pages render current data with no refresh
step; decisions are keyed by (code, code_kind) form fields.
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
        for tbl in ("catalog_rejections", "bcct_nb_codes", "code_mappings",
                    "bcct_rows", "materials"):
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
        for tbl in ("catalog_rejections", "bcct_nb_codes", "code_mappings",
                    "bcct_rows", "materials"):
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
    from app.stores.bcct_nb_codes import rebuild_for_client
    rebuild_for_client(CLIENT)


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


def test_candidates_page_renders_live(setup):
    """The feed is computed — seeded data shows with no refresh step."""
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
    assert "HQ" in body or "hq" in body
    assert "NB" in body or "nb" in body


def test_get_page_writes_nothing(setup):
    """#32 oracle still holds: loading the page writes zero rows —
    there is no candidates table at all now, so assert on rejections
    (the only queue-side table) and materials."""
    _seed_bcct("D1", "DAUNOI", "DAUNOI (019.X)")
    c = _client(setup["session_id"])
    r = c.get(f"/clients/{CLIENT}/catalog/candidates")
    assert r.status_code == 200
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.catalog_rejections where client_id=%s",
            (CLIENT,),
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            "select count(*) from hub.materials where client_id=%s", (CLIENT,),
        )
        assert cur.fetchone()[0] == 0


def test_refresh_button_rebuilds_links(setup):
    """«Làm mới» re-extracts bcct_nb_codes (catch-up for script loads)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into hub.bcct_rows
              (client_id, transaction_key, line_no, declaration_no,
               declaration_type, direction, registration_date,
               customs_code, goods_name, payload)
            values (%s, 'TX_S', '1', 'DS', 'E11', 'import', '2026-04-01',
                    'DAUNOI', 'script load (019.S)', '{}'::jsonb)
            """,
            (CLIENT,),
        )
    # No rebuild ran — the paren link is missing.
    c = _client(setup["session_id"])
    r = c.post(f"/clients/{CLIENT}/catalog/candidates/refresh",
               follow_redirects=False)
    assert r.status_code == 303
    assert "refreshed=" in r.headers["location"]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.bcct_nb_codes "
            "where client_id=%s and nb_code='019.S'", (CLIENT,),
        )
        assert cur.fetchone()[0] == 1


# ── Accept route ──────────────────────────────────────────────────────────


def test_accept_endpoint_inserts_material(setup):
    _seed_bcct("D1", "DAUNOI", "DAUNOI (019.X)")
    c = _client(setup["session_id"])
    r = c.post(
        f"/clients/{CLIENT}/catalog/candidates/accept",
        data={"code": "DAUNOI", "code_kind": "hq",
              "name": "Đầu nối", "category": "nvl", "status": "active"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select code_kind, category, source from hub.materials "
            "where client_id=%s and material_code='DAUNOI'", (CLIENT,)
        )
        row = cur.fetchone()
    assert row == ("hq", "nvl", "bcct_observed")


def test_accept_endpoint_rejects_unauthorized(setup):
    _seed_bcct("D1", "X", "X (019.X)")
    no_auth = TestClient(app)
    r = no_auth.post(
        f"/clients/{CLIENT}/catalog/candidates/accept",
        data={"code": "X", "code_kind": "hq", "name": "x", "category": "nvl"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303, 401, 403)


def test_accept_endpoint_404_for_unknown_code(setup):
    c = _client(setup["session_id"])
    r = c.post(
        f"/clients/{CLIENT}/catalog/candidates/accept",
        data={"code": "NOPE", "code_kind": "hq", "name": "x",
              "category": "nvl"},
        follow_redirects=False,
    )
    assert r.status_code == 404


# ── Reject / unreject ─────────────────────────────────────────────────────


def test_reject_endpoint_suppresses(setup):
    _seed_bcct("D1", "NOISE", "NOISE (019.X)")
    c = _client(setup["session_id"])
    r = c.post(
        f"/clients/{CLIENT}/catalog/candidates/reject",
        data={"code": "NOISE", "code_kind": "hq", "reason": "test rubbish"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select reason, rejected_by from hub.catalog_rejections "
            "where client_id=%s and code='NOISE'", (CLIENT,)
        )
        reason, by = cur.fetchone()
    assert reason == "test rubbish"
    assert by == USER_EMAIL
    # Gone from pending, shown in the rejected section.
    body = c.get(f"/clients/{CLIENT}/catalog/candidates").text
    assert "test rubbish" in body


def test_unreject_endpoint_lifts_suppression(setup):
    _seed_bcct("D1", "MAYBE", "MAYBE (019.X)")
    c = _client(setup["session_id"])
    c.post(f"/clients/{CLIENT}/catalog/candidates/reject",
           data={"code": "MAYBE", "code_kind": "hq", "reason": "oops"},
           follow_redirects=False)
    r = c.post(f"/clients/{CLIENT}/catalog/candidates/unreject",
               data={"code": "MAYBE"}, follow_redirects=False)
    assert r.status_code == 303
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.catalog_rejections "
            "where client_id=%s and code='MAYBE'", (CLIENT,)
        )
        assert cur.fetchone()[0] == 0


def test_unreject_404_when_not_rejected(setup):
    c = _client(setup["session_id"])
    r = c.post(f"/clients/{CLIENT}/catalog/candidates/unreject",
               data={"code": "NEVER"}, follow_redirects=False)
    assert r.status_code == 404


# ── Filter chips ──────────────────────────────────────────────────────────


def test_filter_by_kind(setup):
    _seed_bcct("D1", "DAUNOI", "DAUNOI (019.X)")
    _seed_bcct("D2", "DOV", "DOV (019.Y)")
    c = _client(setup["session_id"])
    r = c.get(f"/clients/{CLIENT}/catalog/candidates?kind=hq")
    body = r.text
    assert "DAUNOI" in body
    assert "DOV" in body
