"""Phase 2: preview confirm gate for a clear price-column inversion.

A blocking anomaly (unit_price ↔ unit_price_nt swapped on all foreign rows)
must require an explicit `confirm_anomalies` ack before commit; the gate is
enforced server-side, not just in the UI.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from hub.app.auth.session import create_session, hash_password, SESSION_COOKIE
from hub.app.database import connect
from hub.app.main import app

CLIENT = "anomgate-test"
USER_ID = "u_anomgate_test"
USER_EMAIL = "anomgate@test.local"
PENDING = "test_anomgate_pending"


def _inverted_rows() -> list[dict]:
    return [
        {
            "transaction_key": f"ANOMGATE_{i}", "line_no": "1",
            "declaration_no": f"ANOMGATE_{i}",
            "declaration_type": "E42", "direction": "export",
            "registration_date": "2026-05-18", "customs_code": f"MAT-{i}",
            "goods_name": "X", "currency_nt": "EUR", "exchange_rate": 30377.72,
            # swapped: VND field tiny, nguyên-tệ field huge.
            "unit_price": 380.7, "unit_price_nt": 10136289.92,
        }
        for i in range(4)
    ]


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s,%s) "
            "on conflict (client_id) do nothing", (CLIENT, "anom gate test"))
        cur.execute(
            "insert into hub.users (user_id,email,display_name,password_hash,role,status) "
            "values (%s,%s,'Anom',%s,'admin','active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (USER_ID, USER_EMAIL, hash_password("pw")))
    sid = create_session(USER_ID)
    yield {"session_id": sid}
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bcct_rows where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.upload_pending where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.file_uploads where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.sessions where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.users where user_id=%s", (USER_ID,))


def _stash(rows):
    summary = {"new": len(rows), "noop": 0, "diff": [], "orphan": [],
               "total": len(rows)}
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.file_uploads "
            "(upload_id, client_id, module, original_filename, stored_path, "
            " content_sha256, size_bytes, uploader_user_id) "
            "values ('upl_anomgate',%s,'bcct','a.xlsx','/tmp/a.xlsx','sha',1,%s) "
            "on conflict (upload_id) do nothing", (CLIENT, USER_ID))
        cur.execute(
            "insert into hub.upload_pending "
            "(pending_id, client_id, module, upload_id, parsed_rows, "
            " diff_summary, created_by, expires_at) "
            "values (%s,%s,'bcct',%s,%s::jsonb,%s::jsonb,%s, now()+interval '1 day') "
            "on conflict (pending_id) do update set parsed_rows=excluded.parsed_rows",
            (PENDING, CLIENT, "upl_anomgate", json.dumps(rows),
             json.dumps(summary), USER_ID))


def _http(setup) -> TestClient:
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, setup["session_id"])
    return c


def _pending_exists() -> bool:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select 1 from hub.upload_pending where pending_id=%s", (PENDING,))
        return cur.fetchone() is not None


def test_preview_shows_advisory_warning_no_gate(setup):
    # Anomaly is ADVISORY: the warning shows, but there is no ack checkbox
    # and the copy says it does not block saving.
    _stash(_inverted_rows())
    r = _http(setup).get(f"/clients/{CLIENT}/bcct/upload/preview/{PENDING}")
    assert r.status_code == 200, r.text
    assert "Lưu ý" in r.text and "unit_price" in r.text
    assert "không chặn lưu" in r.text
    assert 'name="confirm_anomalies"' not in r.text


def test_confirm_not_blocked_by_anomaly(setup):
    # Confirm succeeds WITHOUT any anomaly ack — advisory, not a gate.
    _stash(_inverted_rows())
    r = _http(setup).post(
        f"/clients/{CLIENT}/bcct/upload/preview/{PENDING}/confirm",
        data={"confirm_diffs": "on", "confirm_orphans": "on"},
        follow_redirects=False)
    assert r.status_code == 303, r.text
    assert not _pending_exists()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*) from hub.bcct_rows where client_id=%s", (CLIENT,))
        assert cur.fetchone()[0] == 4
