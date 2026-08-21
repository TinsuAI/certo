"""Self-service retraction of wrongly-stored BOM versions + failed-upload
cleanup. Covers the gap that forced manual SQL tombstones (MPL0100-39)."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.auth.session import create_session, hash_password, SESSION_COOKIE
from app.database import connect
from app.main import app
from app.stores.bom import create_raw_artifact, create_artifact


CLIENT = "tombstone_test"
USER_ID = "u_tombstone"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s,%s) "
            "on conflict (client_id) do nothing", (CLIENT, "tombstone test"))
        cur.execute(
            "insert into hub.users (user_id,email,display_name,password_hash,role,status) "
            "values (%s,'tomb@test.local','T',%s,'admin','active') "
            "on conflict (user_id) do update set role='admin',status='active'",
            (USER_ID, hash_password("x")))
    sid = create_session(USER_ID)
    yield sid
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.bom_audit_events where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.bom_edges where artifact_id in "
                    "(select artifact_id from hub.bom_artifacts where client_id=%s)", (CLIENT,))
        cur.execute("delete from hub.bom_artifact_rows where artifact_id in "
                    "(select artifact_id from hub.bom_artifacts where client_id=%s)", (CLIENT,))
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.file_uploads where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.sessions where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.users where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


@pytest.fixture
def http(setup):
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, setup)
    return c


def _raw_with_derived(product="TP-T1"):
    raw_id = create_raw_artifact(
        client_id=CLIENT, product_code=product,
        edges=[{"root_code": product, "parent_code": product,
                "child_code": "NVL-1", "qty_per_parent": 2.0,
                "node_path": f"{product} > NVL-1"}],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None, context={}, source_upload_id=None)
    # a derived shape pointing at the raw
    shape_id = create_artifact(
        client_id=CLIENT, product_code=product,
        rows=[{"material_code": "NVL-1", "qty_per_unit": 2.0, "uom": "kg"}],
        actor="system", intent="derived",
        parent_artifact_id=raw_id, context={"channel": "auto_derived"},
        source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="flattened", flatten_strategy="technical_exploded")
    return raw_id, shape_id


def _active(product):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.bom_artifacts where client_id=%s "
            "and product_code=%s and tombstoned_at is null", (CLIENT, product))
        return cur.fetchone()[0]


def test_tombstone_raw_cascades_to_derived(http):
    raw_id, shape_id = _raw_with_derived()
    assert _active("TP-T1") == 2

    r = http.post(
        f"/clients/{CLIENT}/bom/artifact/{raw_id}/tombstone",
        data={"reason": "lưu sai, file thực ra là BOM kỹ thuật"},
        follow_redirects=False)
    assert r.status_code == 303
    assert "tombstoned=2" in r.headers["location"]
    assert _active("TP-T1") == 0  # raw + derived both gone

    # audit rows written
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from hub.bom_audit_events where client_id=%s "
            "and event_type='version.tombstoned'", (CLIENT,))
        assert cur.fetchone()[0] == 2


def test_tombstone_via_derived_retracts_whole_version(http):
    """Clicking the derived shape retracts the raw + siblings too."""
    raw_id, shape_id = _raw_with_derived(product="TP-T2")
    r = http.post(
        f"/clients/{CLIENT}/bom/artifact/{shape_id}/tombstone",
        data={"reason": "sai"}, follow_redirects=False)
    assert r.status_code == 303
    assert _active("TP-T2") == 0


def test_tombstone_requires_reason(http):
    raw_id, _ = _raw_with_derived(product="TP-T3")
    r = http.post(f"/clients/{CLIENT}/bom/artifact/{raw_id}/tombstone",
                  data={"reason": "  "}, follow_redirects=False)
    assert r.status_code == 400
    assert _active("TP-T3") == 2  # nothing tombstoned


def test_delete_error_upload(http):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.file_uploads "
            "(upload_id, client_id, module, original_filename, stored_path, "
            " storage_backend, content_sha256, size_bytes, parse_status, result) "
            "values ('upl_err1',%s,'bom','bad.xlsx','x/bad.xlsx','local','abc',10,"
            "'error','{}'::jsonb)", (CLIENT,))
    r = http.post(f"/clients/{CLIENT}/uploads/upl_err1/delete",
                  follow_redirects=False)
    assert r.status_code == 303
    assert "deleted=1" in r.headers["location"]
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*) from hub.file_uploads where upload_id='upl_err1'")
        assert cur.fetchone()[0] == 0


def test_cannot_delete_done_upload(http):
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.file_uploads "
            "(upload_id, client_id, module, original_filename, stored_path, "
            " storage_backend, content_sha256, size_bytes, parse_status, result) "
            "values ('upl_done1',%s,'bom','ok.xlsx','x/ok.xlsx','local','def',10,"
            "'done','{}'::jsonb)", (CLIENT,))
    r = http.post(f"/clients/{CLIENT}/uploads/upl_done1/delete",
                  follow_redirects=False)
    assert r.status_code == 400
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*) from hub.file_uploads where upload_id='upl_done1'")
        assert cur.fetchone()[0] == 1  # still there
