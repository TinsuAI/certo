"""Adapter registry: registry_info() helper + read-only admin view (B.0)."""
from __future__ import annotations

import secrets

import pytest

from app.database import connect
from app.parsers import bom_adapters


def test_registry_info_describes_all_adapters():
    info = bom_adapters.registry_info()
    names = [a["name"] for a in info]
    # The 5 registered Protocol adapters, in registration order.
    assert names == [
        "sap_indented_walk", "multi_sheet_per_root", "manual_flat",
        "sheet_per_product", "sap_exploded_levels",
    ]
    by = {a["name"]: a for a in info}
    # detect() coverage: implemented on the deep-tree SAP adapters, abstained
    # (explicitly) on the generic ones.
    assert by["sap_indented_walk"]["has_detect"] is True
    assert by["sap_exploded_levels"]["has_detect"] is True
    assert by["manual_flat"]["has_detect"] is True  # explicit None-return
    # legacy aliases resolve to their canonical adapter.
    assert "growatt_multi_workbook" in by["sheet_per_product"]["legacy_aliases"]
    assert "johnson_sap_exploded" in by["sap_exploded_levels"]["legacy_aliases"]
    # capability flags + hooks surfaced.
    assert by["sap_indented_walk"]["post_ingest_hooks"] == [
        "derive_btp_shallows", "materialize_shapes"]
    assert by["sap_indented_walk"]["emits_intermediate_btp_versions"] is False


def _admin_client():
    from fastapi.testclient import TestClient
    from app.auth.session import create_session, hash_password, SESSION_COOKIE
    from app.main import app
    uid = "u_registry_admin"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.users (user_id,email,display_name,password_hash,role,status) "
            "values (%s,'registry-admin@t.local','A',%s,'admin','active') "
            "on conflict (user_id) do update set role='admin', status='active'",
            (uid, hash_password("pw")))
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, create_session(uid))
    return c, uid


def test_admin_registry_view_lists_adapters():
    c, uid = _admin_client()
    try:
        r = c.get("/admin/bom-adapters")
        assert r.status_code == 200
        assert "sap_indented_walk" in r.text
        assert "manual_flat" in r.text
        # raw-edge legacy aliases footnoted.
        assert "sap_indented_raw" in r.text
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from hub.sessions where user_id=%s", (uid,))
            cur.execute("delete from hub.users where user_id=%s", (uid,))


def test_admin_registry_view_shows_binding_matrix():
    from app.stores import adapter_binding as ab
    c, uid = _admin_client()
    cid = "regbind-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("insert into hub.clients (client_id, name) values (%s,%s)",
                    (cid, "registry binding"))
    try:
        ab.set_default_adapter(cid, "sap_indented_walk")
        r = c.get("/admin/bom-adapters")
        assert r.status_code == 200
        assert cid in r.text
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("delete from hub.clients where client_id=%s", (cid,))
            cur.execute("delete from hub.sessions where user_id=%s", (uid,))
            cur.execute("delete from hub.users where user_id=%s", (uid,))
