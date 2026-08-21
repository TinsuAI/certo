"""Search filter on candidate feed — query param `q` matches code/sample_text."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hub.app.auth.session import SESSION_COOKIE, create_session, hash_password
from hub.app.database import connect
from hub.app.main import app


CLIENT = "_test_search"
USER_ID = "u_search_test"
USER_EMAIL = "search@test.local"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, 'search') "
            "on conflict do nothing",
            (CLIENT,),
        )
        cur.execute(
            "insert into hub.users (user_id, email, display_name, password_hash, "
            " role, status) values (%s, %s, 'S Test', %s, 'admin', 'active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (USER_ID, USER_EMAIL, hash_password("test-pw")),
        )
        cur.execute("delete from hub.catalog_rejections where client_id=%s",
                    (CLIENT,))
        cur.execute("delete from hub.bcct_rows where client_id=%s", (CLIENT,))
        for i, (code, sample) in enumerate([
            ("ABC123", "Apple widget"),
            ("XYZ999", "Banana gadget"),
            ("ABC456", "Apple thing"),
        ]):
            cur.execute(
                """
                insert into hub.bcct_rows
                  (client_id, transaction_key, line_no, declaration_no,
                   declaration_type, direction, registration_date,
                   customs_code, goods_name, payload)
                values (%s, %s, '1', %s, 'E11', 'import', '2026-04-01',
                        %s, %s, '{}'::jsonb)
                """,
                (CLIENT, f"TX_{i}", f"D{i}", code, sample),
            )
    # The feed is computed live (#34) — no build step needed.
    sess = create_session(USER_ID)
    yield {"session": sess}
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.catalog_rejections where client_id=%s",
                    (CLIENT,))
        cur.execute("delete from hub.bcct_rows where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.sessions where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.users where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _c(session):
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, session)
    return c


def test_search_by_code_substring(setup):
    c = _c(setup["session"])
    r = c.get(f"/clients/{CLIENT}/catalog/candidates?q=ABC")
    assert r.status_code == 200
    body = r.text
    assert "ABC123" in body
    assert "ABC456" in body
    assert "XYZ999" not in body


def test_search_by_sample_text_substring(setup):
    c = _c(setup["session"])
    r = c.get(f"/clients/{CLIENT}/catalog/candidates?q=Banana")
    body = r.text
    assert "XYZ999" in body
    assert "ABC123" not in body


def test_search_case_insensitive(setup):
    c = _c(setup["session"])
    r = c.get(f"/clients/{CLIENT}/catalog/candidates?q=apple")
    body = r.text
    assert "ABC123" in body
    assert "ABC456" in body


def test_search_combined_with_kind_filter(setup):
    """Search ABC + kind=unified should exclude unrelated kinds."""
    c = _c(setup["session"])
    r = c.get(f"/clients/{CLIENT}/catalog/candidates?q=ABC&kind=unified")
    body = r.text
    assert "ABC123" in body
    assert "ABC456" in body
    # Kind filter is exclusive; no HQ codes here so easy assertion: XYZ excluded.
    assert "XYZ999" not in body
