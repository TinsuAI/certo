"""Per-client material-group map: store CRUD + validation + admin UI (B.0).

The (client_id, material_group) -> (item_category, is_declarable) map drives
hub.v_material_classification. Staff edit it here; declarability updates in the
view live (re-tagging row exclusions needs the backfill job — covered elsewhere).
"""
from __future__ import annotations

import pytest

from app.database import connect
from app.stores import material_group_map as mgm

CLIENT = "mgmap-test"


@pytest.fixture(autouse=True)
def setup():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s,%s) "
            "on conflict (client_id) do nothing", (CLIENT, "mgmap"))
    yield
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.client_material_group_map where client_id=%s",
                    (CLIENT,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


def test_upsert_and_list():
    mgm.upsert(client_id=CLIENT, material_group="RD99", item_category="metal",
               is_declarable=True, notes="custom steel")
    rows = mgm.list_map(CLIENT)
    row = next(r for r in rows if r["material_group"] == "RD99")
    assert row["item_category"] == "metal"
    assert row["is_declarable"] is True
    assert row["source"] == "staff_form"
    assert row["notes"] == "custom steel"


def test_material_group_uppercased_and_trimmed():
    mgm.upsert(client_id=CLIENT, material_group="  rd88 ", item_category="label",
               is_declarable=False)
    assert any(r["material_group"] == "RD88" for r in mgm.list_map(CLIENT))


def test_invalid_item_category_rejected():
    with pytest.raises(ValueError):
        mgm.upsert(client_id=CLIENT, material_group="RD77",
                   item_category="not_a_category", is_declarable=True)


def test_empty_material_group_rejected():
    with pytest.raises(ValueError):
        mgm.upsert(client_id=CLIENT, material_group="   ",
                   item_category="metal", is_declarable=True)


def test_upsert_conflict_updates_in_place():
    mgm.upsert(client_id=CLIENT, material_group="RD55", item_category="metal",
               is_declarable=True)
    mgm.upsert(client_id=CLIENT, material_group="RD55", item_category="drawing",
               is_declarable=False, notes="reclassified")
    rows = [r for r in mgm.list_map(CLIENT) if r["material_group"] == "RD55"]
    assert len(rows) == 1
    assert rows[0]["item_category"] == "drawing"
    assert rows[0]["is_declarable"] is False
    assert rows[0]["notes"] == "reclassified"


def test_delete():
    mgm.upsert(client_id=CLIENT, material_group="RD33", item_category="other",
               is_declarable=True)
    mgm.delete(client_id=CLIENT, material_group="RD33")
    assert not any(r["material_group"] == "RD33" for r in mgm.list_map(CLIENT))


# ── admin UI ──────────────────────────────────────────────────────────────

def _admin_client():
    from fastapi.testclient import TestClient
    from app.auth.session import create_session, hash_password, SESSION_COOKIE
    from app.main import app
    uid = "u_mgmap_admin"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.users (user_id,email,display_name,password_hash,role,status) "
            "values (%s,'mgmap-admin@t.local','A',%s,'admin','active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (uid, hash_password("pw")))
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, create_session(uid))
    return c, uid


def _cleanup_admin(uid):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from hub.sessions where user_id=%s", (uid,))
        cur.execute("delete from hub.users where user_id=%s", (uid,))


def test_admin_ui_add_list_delete(setup):
    c, uid = _admin_client()
    try:
        g = c.get(f"/clients/{CLIENT}/material-group-map")
        assert g.status_code == 200
        assert "assembly_set" in g.text  # item_category enum option present

        p = c.post(f"/clients/{CLIENT}/material-group-map/add",
                   data={"material_group": "RD42", "item_category": "hardware",
                         "is_declarable": "on", "notes": "bolts"},
                   follow_redirects=False)
        assert p.status_code == 303
        g2 = c.get(f"/clients/{CLIENT}/material-group-map")
        assert "RD42" in g2.text

        # invalid item_category rejected
        bad = c.post(f"/clients/{CLIENT}/material-group-map/add",
                     data={"material_group": "RD43", "item_category": "bogus",
                           "is_declarable": "on"}, follow_redirects=False)
        assert bad.status_code == 400

        d = c.post(f"/clients/{CLIENT}/material-group-map/delete",
                   data={"material_group": "RD42"}, follow_redirects=False)
        assert d.status_code == 303
        g3 = c.get(f"/clients/{CLIENT}/material-group-map")
        assert "RD42" not in g3.text
    finally:
        _cleanup_admin(uid)
