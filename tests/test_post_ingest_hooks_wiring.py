"""Track D Phase B — wire post_ingest_hooks into BOM upload confirm flow.

The hooks scaffold (`app/parsers/bom_adapters/__init__.py`) has been
in place since Phase 3c but never invoked from production code. This
wires it into the confirm route so that adapters declaring
`post_ingest_hooks=['derive_btp_shallows']` (sap_indented_walk,
multi_sheet_per_root) auto-mint per-BTP raw_graph artifacts, closing
the staleness window for dimension D2.

Spec: `.ai/features/2026-05-11-bom-staleness-track-d/brief.md`,
"Wire post_ingest_hooks" section.
"""
from __future__ import annotations

import json
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth.session import create_session, hash_password, SESSION_COOKIE
from app.database import connect
from app.main import app
from app.parsers import bom_adapters


CLIENT = "track_d_hooks_test"
USER_ID = "test_track_d_hooks_user"
USER_EMAIL = "track_d_hooks@test.local"


@pytest.fixture
def setup_client_and_user():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.clients (client_id, name) values (%s, %s) "
            "on conflict (client_id) do nothing",
            (CLIENT, "Track D hooks test"),
        )
        cur.execute(
            "insert into hub.users (user_id, email, display_name, "
            "password_hash, role, status) values (%s, %s, 'tester', %s, "
            "'admin', 'active') on conflict (user_id) do update set "
            "role='admin', status='active'",
            (USER_ID, USER_EMAIL, hash_password("test-password")),
        )
    session_id = create_session(USER_ID)
    yield {"session_id": session_id}
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.bom_artifact_rows where artifact_id in "
            "(select artifact_id from hub.bom_artifacts where client_id=%s)",
            (CLIENT,),
        )
        cur.execute("delete from hub.bom_artifacts where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.upload_pending where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.file_uploads where client_id=%s", (CLIENT,))
        cur.execute("delete from hub.sessions where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.users where user_id=%s", (USER_ID,))
        cur.execute("delete from hub.clients where client_id=%s", (CLIENT,))


@pytest.fixture
def http(setup_client_and_user):
    c = TestClient(app, follow_redirects=False)
    c.cookies.set(SESSION_COOKIE, setup_client_and_user["session_id"])
    return c


def _stash_pending(profile: str, products: dict) -> tuple[str, str]:
    pending_id = secrets.token_urlsafe(16)
    upload_id = secrets.token_urlsafe(16)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.file_uploads (upload_id, client_id, module, "
            "original_filename, stored_path, content_sha256, size_bytes, "
            "uploader_user_id, parse_status, parsed_at) values "
            "(%s, %s, 'bom', 'test.xlsx', '/tmp/x', %s, 0, %s, "
            "'pending_preview', now())",
            (upload_id, CLIENT, secrets.token_hex(32), USER_ID),
        )
        cur.execute(
            "insert into hub.upload_pending (pending_id, client_id, "
            "module, upload_id, parsed_rows, diff_summary, created_by, "
            "expires_at) values (%s, %s, 'bom', %s, %s::jsonb, %s::jsonb, "
            "%s, now() + interval '1 hour')",
            (
                pending_id, CLIENT, upload_id,
                json.dumps({"products": products}),
                json.dumps({"profile": profile}),
                USER_ID,
            ),
        )
    return pending_id, upload_id


def test_confirm_flow_invokes_post_ingest_hooks_for_deep_tree_adapter(
    http, monkeypatch
):
    """Profile sap_indented_walk declares ['derive_btp_shallows'] hook.
    Confirm flow must invoke run_post_ingest_hooks per artifact created."""
    calls: list[dict] = []

    def _recorder(*, artifact_id: str, client_id: str, **kwargs):
        calls.append({"artifact_id": artifact_id, "client_id": client_id})
        return []

    monkeypatch.setitem(bom_adapters.HOOKS, "derive_btp_shallows", _recorder)

    products = {
        "P_HOOKS_1": [
            {"material_code": "M-A", "qty_per_unit": 1, "uom": "pcs"},
        ],
    }
    pending_id, _ = _stash_pending("sap_indented_walk", products)

    r = http.post(f"/clients/{CLIENT}/bom/preview/{pending_id}/confirm")
    assert r.status_code == 303, r.text

    assert len(calls) == 1, (
        f"Expected hook called once per ingested artifact; got {calls}"
    )
    assert calls[0]["client_id"] == CLIENT
    # artifact_id is server-generated; assert it points to a real artifact.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select 1 from hub.bom_artifacts where artifact_id=%s",
            (calls[0]["artifact_id"],),
        )
        assert cur.fetchone() is not None


def test_confirm_flow_does_not_invoke_hooks_for_no_hook_adapter(
    http, monkeypatch
):
    """Profile manual_flat declares no hooks; runner must be a no-op."""
    calls: list[dict] = []

    def _recorder(*, artifact_id: str, client_id: str, **kwargs):
        calls.append({"artifact_id": artifact_id})
        return []

    monkeypatch.setitem(bom_adapters.HOOKS, "derive_btp_shallows", _recorder)

    products = {
        "P_HOOKS_NOOP": [
            {"material_code": "M-A", "qty_per_unit": 1, "uom": "pcs"},
        ],
    }
    pending_id, _ = _stash_pending("manual_flat", products)

    r = http.post(f"/clients/{CLIENT}/bom/preview/{pending_id}/confirm")
    assert r.status_code == 303, r.text

    assert calls == [], (
        f"manual_flat declares no post_ingest_hooks; runner must skip. "
        f"Got: {calls}"
    )


def test_confirm_flow_continues_when_hook_raises(http, monkeypatch, caplog):
    """Hook failure must NOT crash confirm flow. Per brief decision:
    'log + continue. Hook failure marks new artifact stale with
    dim=derive_hook_failed.'"""
    def _boom(*, artifact_id: str, client_id: str, **kwargs):
        raise RuntimeError("hook intentionally failed")

    monkeypatch.setitem(bom_adapters.HOOKS, "derive_btp_shallows", _boom)

    products = {
        "P_HOOKS_FAIL": [
            {"material_code": "M-A", "qty_per_unit": 1, "uom": "pcs"},
        ],
    }
    pending_id, _ = _stash_pending("sap_indented_walk", products)

    r = http.post(f"/clients/{CLIENT}/bom/preview/{pending_id}/confirm")
    assert r.status_code == 303, (
        f"Hook failure must not bubble up; confirm must redirect. "
        f"Got status={r.status_code}, body={r.text[:300]}"
    )

    # Failed-hook artifact gets marked stale with dim=derive_hook_failed.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select is_stale, stale_reasons from hub.bom_artifacts "
            "where client_id=%s and product_code=%s",
            (CLIENT, "P_HOOKS_FAIL"),
        )
        row = cur.fetchone()
    assert row is not None
    is_stale, reasons = row
    assert is_stale is True
    dims = [r["dim"] for r in reasons]
    assert "derive_hook_failed" in dims, (
        f"Failed hook must mark artifact stale with dim=derive_hook_failed. "
        f"Got reasons: {reasons}"
    )
