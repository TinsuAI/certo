"""Phase 3: per-client column-alias config + resolution wiring."""
from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from hub.app.database import connect
from hub.app.routes.bcct import BCCT_MAPPING_CFG
from hub.app.routes._mapping_flow import try_auto_map
from hub.app.stores import column_aliases as ca

CLIENT = "colalias-test"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s,%s) "
            "on conflict (client_id) do nothing", (CLIENT, "colalias"))
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.client_column_aliases where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def _xlsx(rows):
    wb = Workbook(); ws = wb.active; ws.title = "BCCT"
    for r in rows:
        ws.append(r)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_resolved_merges_client_override_onto_code_aliases():
    base = ca.resolved_aliases(CLIENT, "bcct")
    assert "số tờ khai" in [a.lower() for a in base["declaration_no"]]  # code default
    ca.add_alias(client_id=CLIENT, module="bcct", field="customs_code",
                 alias="Mã Cty")
    merged = ca.resolved_aliases(CLIENT, "bcct")
    assert "Mã Cty" in merged["customs_code"]
    # code defaults preserved
    assert "mã npl/sp" in [a.lower() for a in merged["customs_code"]]


def test_add_list_toggle_delete():
    ca.add_alias(client_id=CLIENT, module="bcct", field="goods_name",
                 alias="Diễn giải")
    rows = ca.list_aliases(CLIENT, "bcct")
    assert any(r["alias"] == "Diễn giải" and r["enabled"] for r in rows)
    aid = next(r["id"] for r in rows if r["alias"] == "Diễn giải")
    # disable → drops out of resolved
    ca.set_alias_enabled(aid, False, client_id=CLIENT)
    assert "Diễn giải" not in ca.resolved_aliases(CLIENT, "bcct").get("goods_name", [])
    ca.delete_alias(aid, client_id=CLIENT)
    assert not ca.list_aliases(CLIENT, "bcct")


def test_admin_ui_add_and_list(setup):
    from fastapi.testclient import TestClient
    from hub.app.auth.session import create_session, hash_password, SESSION_COOKIE
    from hub.app.main import app
    uid = "u_colalias_admin"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.users (user_id,email,display_name,password_hash,role,status) "
            "values (%s,'colalias-admin@t.local','A',%s,'admin','active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (uid, hash_password("pw")))
    try:
        c = TestClient(app)
        c.cookies.set(SESSION_COOKIE, create_session(uid))
        g = c.get(f"/clients/{CLIENT}/column-aliases?module=bcct")
        assert g.status_code == 200
        assert "customs_code" in g.text  # field dropdown option
        p = c.post(f"/clients/{CLIENT}/column-aliases/add",
                   data={"module": "bcct", "field": "goods_name",
                         "alias": "Diễn giải HĐ"}, follow_redirects=False)
        assert p.status_code == 303
        g2 = c.get(f"/clients/{CLIENT}/column-aliases?module=bcct")
        assert "Diễn giải HĐ" in g2.text
        # invalid field rejected
        bad = c.post(f"/clients/{CLIENT}/column-aliases/add",
                     data={"module": "bcct", "field": "not_a_field",
                           "alias": "x"}, follow_redirects=False)
        assert bad.status_code == 400
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from hub.sessions where user_id=%s", (uid,))
            cur.execute("delete from hub.users where user_id=%s", (uid,))


def test_auto_map_uses_client_alias():
    # customs_code header is non-standard → auto-map fails (required unresolved)
    blob = _xlsx([
        ("Số tờ khai", "Ngày đăng ký", "Mã Cty", "Tên hàng"),
        ("123", "2025-03-15", "PE-1", "PE"),
    ])
    assert try_auto_map(blob, BCCT_MAPPING_CFG, client_id=CLIENT) is None
    # register the client's header variant → now customs_code resolves
    ca.add_alias(client_id=CLIENT, module="bcct", field="customs_code",
                 alias="Mã Cty")
    mapping = try_auto_map(blob, BCCT_MAPPING_CFG, client_id=CLIENT)
    assert mapping is not None
    assert mapping["Mã Cty"] == "customs_code"
