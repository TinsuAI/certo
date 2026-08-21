"""CRUD endpoints for hub.client_parser_rules.

Brief: .ai/features/2026-05-08-configurable-bcct-parsing/brief.md (D6)

Endpoints under /v1/hub/clients/{client_id}/parser-rules:
  GET    list (?output_field=, ?include_disabled=)
  POST   create
  PATCH  /{rule_id}  update
  DELETE /{rule_id}  soft-disable (enabled=false; never hard delete)
  POST   /test       preview output for a sample input

Auth: writes gated by can_edit_client_technical (dev role only).
Reads gated by can_view_client.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from app import jwt_issuer
from app.database import connect
from app.main import app


@pytest.fixture
def cid():
    """Insert a clean test client + parser rule + cleanup."""
    from app.parsers.client_parser_rules import clear_rules_cache
    clear_rules_cache()
    cid = f"rules-api-{secrets.token_hex(4)}"
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name, code_resolution_mode) "
            "values (%s, %s, 'batch_aggregate_resolution')",
            (cid, f"rules api test {cid}"),
        )
    yield cid
    clear_rules_cache()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.client_parser_rules where client_id = %s", (cid,))
        cur.execute("delete from hub.clients where client_id = %s", (cid,))


def _dev_token():
    return jwt_issuer.make_token(
        user_id="u_dev",
        email="dev@test.local",
        role="dev",
        display_name="Dev",
    )["access_token"]


def _admin_token():
    """Admin role is NOT enough — parser-rule writes require dev."""
    return jwt_issuer.make_token(
        user_id="u_admin",
        email="admin@test.local",
        role="admin",
        display_name="Admin",
    )["access_token"]


def _client():
    return TestClient(app)


def _headers(token):
    return {"authorization": f"Bearer {token}"}


# ── GET list ────────────────────────────────────────────────────────


def test_list_rules_empty_for_new_client(cid):
    r = _client().get(
        f"/v1/hub/clients/{cid}/parser-rules",
        headers=_headers(_dev_token()),
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"items": []}


def test_list_rules_after_create(cid):
    c = _client()
    body = {
        "output_field": "internal_code",
        "priority": 10,
        "pattern": r"\((\w+)\)",
        "notes": "test rule",
    }
    r = c.post(
        f"/v1/hub/clients/{cid}/parser-rules",
        json=body, headers=_headers(_dev_token()),
    )
    assert r.status_code == 201, r.text
    rule_id = r.json()["rule_id"]
    assert isinstance(rule_id, int)

    r = c.get(
        f"/v1/hub/clients/{cid}/parser-rules",
        headers=_headers(_dev_token()),
    )
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["rule_id"] == rule_id
    assert items[0]["priority"] == 10
    assert items[0]["pattern"] == r"\((\w+)\)"
    assert items[0]["enabled"] is True


# ── POST create ─────────────────────────────────────────────────────


def test_create_rejects_invalid_pattern(cid):
    """Backreference pattern → 400 (re2 limitation, surface at save time)."""
    body = {
        "output_field": "internal_code",
        "priority": 10,
        "pattern": r"(\w+)\s+\1",  # backreference
    }
    r = _client().post(
        f"/v1/hub/clients/{cid}/parser-rules",
        json=body, headers=_headers(_dev_token()),
    )
    assert r.status_code == 400


def test_create_rejects_overlong_pattern(cid):
    body = {
        "output_field": "internal_code",
        "priority": 10,
        "pattern": "a" * 501,
    }
    r = _client().post(
        f"/v1/hub/clients/{cid}/parser-rules",
        json=body, headers=_headers(_dev_token()),
    )
    assert r.status_code == 400


def test_create_requires_dev_role(cid):
    """admin role is not enough — parser-rules writes need dev."""
    body = {
        "output_field": "internal_code",
        "priority": 10,
        "pattern": r"\((\w+)\)",
    }
    r = _client().post(
        f"/v1/hub/clients/{cid}/parser-rules",
        json=body, headers=_headers(_admin_token()),
    )
    assert r.status_code == 403


# ── PATCH update ────────────────────────────────────────────────────


def test_patch_updates_priority_and_notes(cid):
    c = _client()
    r = c.post(
        f"/v1/hub/clients/{cid}/parser-rules",
        json={"output_field": "internal_code", "priority": 10,
              "pattern": r"\((\w+)\)", "notes": "v1"},
        headers=_headers(_dev_token()),
    )
    rule_id = r.json()["rule_id"]

    r = c.patch(
        f"/v1/hub/clients/{cid}/parser-rules/{rule_id}",
        json={"priority": 99, "notes": "v2"},
        headers=_headers(_dev_token()),
    )
    assert r.status_code == 200, r.text
    assert r.json()["priority"] == 99
    assert r.json()["notes"] == "v2"


# ── DELETE = soft-disable ───────────────────────────────────────────


def test_delete_soft_disables(cid):
    c = _client()
    r = c.post(
        f"/v1/hub/clients/{cid}/parser-rules",
        json={"output_field": "internal_code", "priority": 10,
              "pattern": r"\((\w+)\)"},
        headers=_headers(_dev_token()),
    )
    rule_id = r.json()["rule_id"]

    r = c.delete(
        f"/v1/hub/clients/{cid}/parser-rules/{rule_id}",
        headers=_headers(_dev_token()),
    )
    assert r.status_code == 200, r.text

    # Default list excludes disabled.
    r = c.get(
        f"/v1/hub/clients/{cid}/parser-rules",
        headers=_headers(_dev_token()),
    )
    assert r.json()["items"] == []

    # ?include_disabled=true returns the row.
    r = c.get(
        f"/v1/hub/clients/{cid}/parser-rules?include_disabled=true",
        headers=_headers(_dev_token()),
    )
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["enabled"] is False


# ── POST /test  (single-sample preview) ─────────────────────────────


def test_test_endpoint_returns_per_rule_trace(cid):
    c = _client()
    c.post(
        f"/v1/hub/clients/{cid}/parser-rules",
        json={"output_field": "internal_code", "priority": 10,
              "pattern": r"\(([\w.]+)\)", "notes": "paren extract"},
        headers=_headers(_dev_token()),
    )
    r = c.post(
        f"/v1/hub/clients/{cid}/parser-rules/test",
        json={
            "output_field": "internal_code",
            "sample_input": "BIENTAN.17#&(PV01.0117500)#&VN",
        },
        headers=_headers(_dev_token()),
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["final_output"] == "PV01.0117500"
    assert len(out["trace"]) == 1
    assert out["trace"][0]["matched"] is True
    assert out["trace"][0]["captured"] == "PV01.0117500"


def test_test_endpoint_no_match_returns_null_output(cid):
    c = _client()
    c.post(
        f"/v1/hub/clients/{cid}/parser-rules",
        json={"output_field": "internal_code", "priority": 10,
              "pattern": r"\(([\w.]+)\)"},
        headers=_headers(_dev_token()),
    )
    r = _client().post(
        f"/v1/hub/clients/{cid}/parser-rules/test",
        json={
            "output_field": "internal_code",
            "sample_input": "no parens here",
        },
        headers=_headers(_dev_token()),
    )
    out = r.json()
    assert out["final_output"] is None
    assert out["trace"][0]["matched"] is False


# ── Cache invalidation ──────────────────────────────────────────────


# ── UI page smoke (session-authed) ──────────────────────────────────


def test_ui_edit_page_renders(cid):
    """The edit page pre-fills with current rule values."""
    c = _client()
    c.post(
        "/login",
        data={"email": "admin@data-hub.local", "password": "admin123"},
        follow_redirects=False,
    )
    r = c.post(
        f"/v1/hub/clients/{cid}/parser-rules",
        json={"output_field": "internal_code", "priority": 42,
              "pattern": r"\((\w+)\)", "notes": "edit test"},
        headers=_headers(_dev_token()),
    )
    rule_id = r.json()["rule_id"]
    r = c.get(
        f"/clients/{cid}/parser-rules/{rule_id}/edit",
        follow_redirects=False,
    )
    assert r.status_code == 200, r.text
    assert "Edit rule" in r.text
    assert 'value="42"' in r.text  # priority pre-filled
    assert "edit test" in r.text   # notes pre-filled


def test_ui_test_panel_recent_mode_renders(cid):
    """Recent-rows mode runs against last N BCCT rows for the client.
    With no rows for this fresh client, returns empty list — page still
    renders cleanly."""
    c = _client()
    c.post(
        "/login",
        data={"email": "admin@data-hub.local", "password": "admin123"},
        follow_redirects=False,
    )
    c.post(
        f"/v1/hub/clients/{cid}/parser-rules",
        json={"output_field": "internal_code", "priority": 10,
              "pattern": r"\((\w+)\)"},
        headers=_headers(_dev_token()),
    )
    r = c.post(
        f"/clients/{cid}/parser-rules/test",
        data={"output_field": "internal_code", "mode": "recent"},
        follow_redirects=False,
    )
    assert r.status_code == 200, r.text
    assert "Recent 50 rows" in r.text


def test_ui_test_panel_coverage_mode_renders(cid):
    c = _client()
    c.post(
        "/login",
        data={"email": "admin@data-hub.local", "password": "admin123"},
        follow_redirects=False,
    )
    c.post(
        f"/v1/hub/clients/{cid}/parser-rules",
        json={"output_field": "internal_code", "priority": 10,
              "pattern": r"\((\w+)\)"},
        headers=_headers(_dev_token()),
    )
    r = c.post(
        f"/clients/{cid}/parser-rules/test",
        data={"output_field": "internal_code", "mode": "coverage"},
        follow_redirects=False,
    )
    assert r.status_code == 200, r.text
    assert "Coverage over last 1k rows" in r.text


def test_ui_page_renders_for_dev(cid):
    """The /clients/<id>/parser-rules page lists rules and shows the
    add/test forms. Session-authed; uses the dev admin seed."""
    from app import auth as _auth

    c = _client()
    # Login as the seeded dev admin (conftest seeds admin@data-hub.local).
    login = c.post(
        "/login",
        data={"email": "admin@data-hub.local", "password": "admin123"},
        follow_redirects=False,
    )
    assert login.status_code in (200, 303), login.text

    r = c.get(f"/clients/{cid}/parser-rules", follow_redirects=False)
    assert r.status_code == 200, r.text
    assert "Parser rules" in r.text
    assert "Add rule" in r.text
    assert "Test panel" in r.text


# ── GET history endpoint ────────────────────────────────────────────


def test_history_returns_audit_trail_for_rule(cid):
    """Audit trigger logs every INSERT/UPDATE/DELETE on
    client_parser_rules. The history endpoint exposes that timeline."""
    c = _client()
    r = c.post(
        f"/v1/hub/clients/{cid}/parser-rules",
        json={"output_field": "internal_code", "priority": 10,
              "pattern": r"\((\w+)\)", "notes": "v1"},
        headers=_headers(_dev_token()),
    )
    rule_id = r.json()["rule_id"]

    c.patch(
        f"/v1/hub/clients/{cid}/parser-rules/{rule_id}",
        json={"priority": 99, "notes": "v2"},
        headers=_headers(_dev_token()),
    )
    c.delete(
        f"/v1/hub/clients/{cid}/parser-rules/{rule_id}",
        headers=_headers(_dev_token()),
    )

    r = c.get(
        f"/v1/hub/clients/{cid}/parser-rules/{rule_id}/history",
        headers=_headers(_dev_token()),
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    # Three audit events recorded: insert (creation), update (patch),
    # update (soft-disable). Newest first.
    kinds = [it["change_kind"] for it in items]
    assert kinds == ["update", "update", "insert"]
    # The patch event: notes went v1 → v2, priority 10 → 99.
    patch_event = next(
        it for it in items
        if it["change_kind"] == "update"
        and it["new_state"].get("priority") == 99
        and it["new_state"].get("enabled") is True
    )
    assert patch_event["prev_state"]["notes"] == "v1"
    assert patch_event["new_state"]["notes"] == "v2"
    # The soft-disable event flips enabled.
    disable_event = next(
        it for it in items
        if it["change_kind"] == "update" and it["new_state"]["enabled"] is False
    )
    assert disable_event["prev_state"]["enabled"] is True


def test_history_404_for_unknown_rule_id(cid):
    r = _client().get(
        f"/v1/hub/clients/{cid}/parser-rules/999999/history",
        headers=_headers(_dev_token()),
    )
    assert r.status_code == 404


def test_create_invalidates_rule_cache(cid):
    """After POST, compute_internal_code should immediately see the new
    rule (cache cleared by the endpoint)."""
    from app.parsers.derivations import compute_internal_code

    client_dict = {"client_id": cid, "code_resolution_mode": "batch_aggregate_resolution"}

    # Pre-create: no rule, helper returns None.
    out = compute_internal_code(
        {"goods_name": "BIENTAN.17#&(PV01.0117500)", "customs_code": "BIENTAN.17"},
        client=client_dict,
    )
    assert out is None

    # Create rule via API.
    _client().post(
        f"/v1/hub/clients/{cid}/parser-rules",
        json={"output_field": "internal_code", "priority": 10,
              "pattern": r"\(([\w.]+)\)"},
        headers=_headers(_dev_token()),
    )

    # Without cache clear, the helper would still see the empty list.
    out = compute_internal_code(
        {"goods_name": "BIENTAN.17#&(PV01.0117500)", "customs_code": "BIENTAN.17"},
        client=client_dict,
    )
    assert out == "PV01.0117500"
