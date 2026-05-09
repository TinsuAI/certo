"""BOM proposal modes (auto / manual / hybrid) + reviewer actions.

Covers:
- mode=auto preserves existing approve-or-reject-synchronously behaviour.
- mode=manual lands every proposal in 'pending' (no auto-rule).
- mode=hybrid auto-approves clean proposals, drops auto-rejected ones
  into 'pending' for manual override.
- approve / reject / withdraw store-layer transitions and idempotency
  behaviour against still-pending duplicates.
- can_approve_proposal honours the per-client `bom_approver_tier`.
"""
from __future__ import annotations

import secrets
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth, jwt_issuer, settings_store
from app.auth.permissions import can_approve_proposal
from app.auth.session import User
from app.database import connect
from app.main import app
from app.stores import service_accounts as sa_store
from app.stores.bom import (
    ProposalNotPending,
    approve_proposal,
    create_artifact,
    get_proposal,
    reject_proposal,
    submit_proposal,
    withdraw_proposal,
)


# ─── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolated_keys_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DATA_HUB_KEYS_DIR", d)
        yield Path(d)


@pytest.fixture
def proposal_client():
    """Throwaway client with one published BOM version + an active material
    so auto-rule has something to evaluate against."""
    cid = "prop-test-" + secrets.token_hex(4)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.clients
                  (client_id, name, code_resolution_mode, bom_proposal_mode,
                   bom_proposal_qty_tolerance_pct, bom_approver_tier)
                values (%s, 'Proposal Test', 'identity', 'auto', 5.0, 'edit')
                """,
                (cid,),
            )
            cur.execute(
                """
                insert into hub.materials
                  (client_id, material_code, name, category, status)
                values (%s, 'M-A', 'Mat A', 'nvl', 'active'),
                       (%s, 'M-B', 'Mat B', 'nvl', 'active'),
                       (%s, 'M-NEW', 'Mat New', 'nvl', 'active')
                """,
                (cid, cid, cid),
            )
    parent = create_artifact(
        client_id=cid, product_code="P-1",
        rows=[
            {"material_code": "M-A", "qty_per_unit": 1.0, "uom": "kg"},
            {"material_code": "M-B", "qty_per_unit": 2.0, "uom": "kg"},
        ],
        actor="agency_staff", intent="asserted_technical",
        parent_artifact_id=None,
        context={"seed": True}, source_upload_id=None,
    )
    yield {"client_id": cid, "parent_artifact_id": parent}
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """delete from hub.bom_artifact_rows where artifact_id in
                   (select artifact_id from hub.bom_artifacts where client_id = %s)""",
                (cid,),
            )
            cur.execute("delete from hub.bom_audit_events where client_id = %s", (cid,))
            cur.execute("delete from hub.bom_change_requests where client_id = %s", (cid,))
            cur.execute("delete from hub.bom_artifacts where client_id = %s", (cid,))
            cur.execute("delete from hub.materials where client_id = %s", (cid,))
            cur.execute("delete from hub.clients where client_id = %s", (cid,))


def _set_mode(client_id: str, mode: str) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.clients set bom_proposal_mode=%s where client_id=%s",
                (mode, client_id),
            )


def _set_tier(client_id: str, tier: str) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.clients set bom_approver_tier=%s where client_id=%s",
                (tier, client_id),
            )


def _good_rows():
    return [
        {"material_code": "M-A", "qty_per_unit": 1.02, "uom": "kg"},
        {"material_code": "M-B", "qty_per_unit": 2.0, "uom": "kg"},
    ]


def _bad_rows():
    """qty deviation > 5% tolerance — auto-rule rejects."""
    return [
        {"material_code": "M-A", "qty_per_unit": 5.0, "uom": "kg"},  # +400 %
        {"material_code": "M-B", "qty_per_unit": 2.0, "uom": "kg"},
    ]


# ─── Mode dispatch ──────────────────────────────────────────────────────


def test_auto_mode_approves_synchronously(proposal_client):
    _set_mode(proposal_client["client_id"], "auto")
    res = submit_proposal(
        client_id=proposal_client["client_id"], product_code="P-1",
        actor="co_system", intent="modified_for_case",
        parent_artifact_id=proposal_client["parent_artifact_id"],
        context={"case_id": "C1"}, rows=_good_rows(),
    )
    assert res["status"] == "approved"
    assert res["artifact_id"] is not None


def test_auto_mode_rejects_synchronously(proposal_client):
    _set_mode(proposal_client["client_id"], "auto")
    res = submit_proposal(
        client_id=proposal_client["client_id"], product_code="P-1",
        actor="co_system", intent="modified_for_case",
        parent_artifact_id=proposal_client["parent_artifact_id"],
        context={"case_id": "C2"}, rows=_bad_rows(),
    )
    assert res["status"] == "rejected"
    assert res["artifact_id"] is None
    assert res["failed_conditions"]


def test_manual_mode_lands_pending_even_for_clean_rows(proposal_client):
    _set_mode(proposal_client["client_id"], "manual")
    res = submit_proposal(
        client_id=proposal_client["client_id"], product_code="P-1",
        actor="co_system", intent="modified_for_case",
        parent_artifact_id=proposal_client["parent_artifact_id"],
        context={"case_id": "C3"}, rows=_good_rows(),
    )
    assert res["status"] == "pending"
    assert res["artifact_id"] is None
    proposal = get_proposal(res["proposal_id"])
    assert proposal["decided_at"] is None
    assert proposal["decided_by"] is None


def test_hybrid_auto_approves_clean(proposal_client):
    _set_mode(proposal_client["client_id"], "hybrid")
    res = submit_proposal(
        client_id=proposal_client["client_id"], product_code="P-1",
        actor="co_system", intent="modified_for_case",
        parent_artifact_id=proposal_client["parent_artifact_id"],
        context={"case_id": "C4"}, rows=_good_rows(),
    )
    assert res["status"] == "approved"
    assert res["artifact_id"] is not None


def test_hybrid_auto_reject_falls_through_to_pending(proposal_client):
    _set_mode(proposal_client["client_id"], "hybrid")
    res = submit_proposal(
        client_id=proposal_client["client_id"], product_code="P-1",
        actor="co_system", intent="modified_for_case",
        parent_artifact_id=proposal_client["parent_artifact_id"],
        context={"case_id": "C5"}, rows=_bad_rows(),
    )
    assert res["status"] == "pending"
    assert res["artifact_id"] is None
    # Reviewer needs the failed_conditions context to override knowingly.
    assert res["failed_conditions"]


# ─── Reviewer actions ───────────────────────────────────────────────────


def test_approve_pending_materializes_version(proposal_client):
    _set_mode(proposal_client["client_id"], "manual")
    res = submit_proposal(
        client_id=proposal_client["client_id"], product_code="P-1",
        actor="co_system", intent="modified_for_case",
        parent_artifact_id=proposal_client["parent_artifact_id"],
        context={"case_id": "C6"}, rows=_good_rows(),
    )
    out = approve_proposal(
        proposal_id=res["proposal_id"], decided_by="u_reviewer",
        reason="looked good",
    )
    assert out["status"] == "approved"
    assert out["artifact_id"]
    proposal = get_proposal(res["proposal_id"])
    assert proposal["decided_by"] == "u_reviewer"
    assert proposal["decision_reason"] == "looked good"
    assert proposal["materialized_artifact_id"] == out["artifact_id"]


def test_reject_pending_writes_reason(proposal_client):
    _set_mode(proposal_client["client_id"], "manual")
    res = submit_proposal(
        client_id=proposal_client["client_id"], product_code="P-1",
        actor="co_system", intent="modified_for_case",
        parent_artifact_id=proposal_client["parent_artifact_id"],
        context={"case_id": "C7"}, rows=_good_rows(),
    )
    reject_proposal(
        proposal_id=res["proposal_id"], decided_by="u_reviewer",
        reason="wrong product line",
    )
    proposal = get_proposal(res["proposal_id"])
    assert proposal["status"] == "rejected"
    assert proposal["decision_reason"] == "wrong product line"
    assert proposal["materialized_artifact_id"] is None


def test_withdraw_pending(proposal_client):
    _set_mode(proposal_client["client_id"], "manual")
    res = submit_proposal(
        client_id=proposal_client["client_id"], product_code="P-1",
        actor="co_system", intent="modified_for_case",
        parent_artifact_id=proposal_client["parent_artifact_id"],
        context={"case_id": "C8"}, rows=_good_rows(),
    )
    withdraw_proposal(proposal_id=res["proposal_id"], by="svc:co")
    proposal = get_proposal(res["proposal_id"])
    assert proposal["status"] == "withdrawn"
    assert proposal["decided_by"] == "svc:co"


def test_actions_on_already_decided_raise(proposal_client):
    """Approve / reject / withdraw require status='pending'."""
    _set_mode(proposal_client["client_id"], "auto")
    res = submit_proposal(
        client_id=proposal_client["client_id"], product_code="P-1",
        actor="co_system", intent="modified_for_case",
        parent_artifact_id=proposal_client["parent_artifact_id"],
        context={"case_id": "C9"}, rows=_good_rows(),
    )
    assert res["status"] == "approved"
    with pytest.raises(ProposalNotPending):
        approve_proposal(
            proposal_id=res["proposal_id"], decided_by="u_reviewer",
        )
    with pytest.raises(ProposalNotPending):
        reject_proposal(
            proposal_id=res["proposal_id"], decided_by="u_reviewer",
            reason="too late",
        )
    with pytest.raises(ProposalNotPending):
        withdraw_proposal(proposal_id=res["proposal_id"], by="svc:co")


def test_resubmit_while_pending_returns_existing(proposal_client):
    """Idempotency on the (client, product, actor, intent, parent, hash) key
    must not create a duplicate row while a pending proposal exists."""
    _set_mode(proposal_client["client_id"], "manual")
    rows = _good_rows()
    first = submit_proposal(
        client_id=proposal_client["client_id"], product_code="P-1",
        actor="co_system", intent="modified_for_case",
        parent_artifact_id=proposal_client["parent_artifact_id"],
        context={"case_id": "C10"}, rows=rows,
    )
    second = submit_proposal(
        client_id=proposal_client["client_id"], product_code="P-1",
        actor="co_system", intent="modified_for_case",
        parent_artifact_id=proposal_client["parent_artifact_id"],
        context={"case_id": "C10"}, rows=rows,
    )
    assert second["proposal_id"] == first["proposal_id"]
    assert second.get("idempotent") is True


def test_resubmit_after_withdraw_creates_new_proposal(proposal_client):
    """Withdrawn proposals must not block resubmission of the same key."""
    _set_mode(proposal_client["client_id"], "manual")
    rows = _good_rows()
    first = submit_proposal(
        client_id=proposal_client["client_id"], product_code="P-1",
        actor="co_system", intent="modified_for_case",
        parent_artifact_id=proposal_client["parent_artifact_id"],
        context={"case_id": "C11"}, rows=rows,
    )
    withdraw_proposal(proposal_id=first["proposal_id"], by="svc:co")
    second = submit_proposal(
        client_id=proposal_client["client_id"], product_code="P-1",
        actor="co_system", intent="modified_for_case",
        parent_artifact_id=proposal_client["parent_artifact_id"],
        context={"case_id": "C11"}, rows=rows,
    )
    assert second["proposal_id"] != first["proposal_id"]
    assert second["status"] == "pending"


# ─── Approver-tier permissions ──────────────────────────────────────────


def _user(role: str, user_id: str = "u_test") -> User:
    return User(
        user_id=user_id, email=f"{user_id}@e", display_name=user_id,
        role=role, status="active",
    )


def test_approver_tier_edit_grants_to_edit_scope_staff(proposal_client):
    cid = proposal_client["client_id"]
    _set_tier(cid, "edit")
    user_id = "u_staff_edit_" + secrets.token_hex(2)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into hub.users
                   (user_id, email, display_name, password_hash, role, status)
                   values (%s, %s, %s, %s, 'staff', 'active')
                   on conflict (user_id) do nothing""",
                (user_id, f"{user_id}@e", user_id, auth.hash_password("x")),
            )
            cur.execute(
                """insert into hub.user_client_access
                   (user_id, client_id, scope, granted_by)
                   values (%s, %s, 'edit', %s)
                   on conflict (user_id, client_id) do update
                     set scope = excluded.scope""",
                (user_id, cid, user_id),
            )
    try:
        assert can_approve_proposal(_user("staff", user_id), cid) is True
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "delete from hub.user_client_access where user_id = %s",
                    (user_id,),
                )
                cur.execute("delete from hub.users where user_id = %s", (user_id,))


def test_approver_tier_admin_blocks_staff(proposal_client):
    cid = proposal_client["client_id"]
    _set_tier(cid, "admin")
    # Even a hypothetical staff with edit access cannot approve when tier=admin.
    user_id = "u_staff_blocked_" + secrets.token_hex(2)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into hub.users
                   (user_id, email, display_name, password_hash, role, status)
                   values (%s, %s, %s, %s, 'staff', 'active')
                   on conflict (user_id) do nothing""",
                (user_id, f"{user_id}@e", user_id, auth.hash_password("x")),
            )
            cur.execute(
                """insert into hub.user_client_access
                   (user_id, client_id, scope, granted_by)
                   values (%s, %s, 'edit', %s)
                   on conflict (user_id, client_id) do update
                     set scope = excluded.scope""",
                (user_id, cid, user_id),
            )
    try:
        assert can_approve_proposal(_user("staff", user_id), cid) is False
        assert can_approve_proposal(_user("admin"), cid) is True
        assert can_approve_proposal(_user("dev"), cid) is True
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "delete from hub.user_client_access where user_id = %s",
                    (user_id,),
                )
                cur.execute("delete from hub.users where user_id = %s", (user_id,))


def test_approver_tier_manager_includes_managers(proposal_client):
    cid = proposal_client["client_id"]
    _set_tier(cid, "manager")
    user_id = "u_mgr_" + secrets.token_hex(2)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into hub.users
                   (user_id, email, display_name, password_hash, role, status)
                   values (%s, %s, %s, %s, 'manager', 'active')
                   on conflict (user_id) do nothing""",
                (user_id, f"{user_id}@e", user_id, auth.hash_password("x")),
            )
            cur.execute(
                """insert into hub.user_managed_clients
                   (user_id, client_id, granted_by)
                   values (%s, %s, %s)
                   on conflict (user_id, client_id) do nothing""",
                (user_id, cid, user_id),
            )
    try:
        assert can_approve_proposal(_user("manager", user_id), cid) is True
    finally:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "delete from hub.user_managed_clients where user_id = %s",
                    (user_id,),
                )
                cur.execute("delete from hub.users where user_id = %s", (user_id,))


# ─── Service-token withdraw API ─────────────────────────────────────────


@pytest.fixture
def cleanup_sa():
    yield
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from hub.service_accounts where name like 'sa_test_%'",
            )


def test_api_service_token_can_withdraw_own_pending(
    proposal_client, cleanup_sa,
):
    """CO service token withdraws its own co_system pending proposal."""
    settings_store.set_many({"api_auth_strict": "true"})
    try:
        _set_mode(proposal_client["client_id"], "manual")
        res = submit_proposal(
            client_id=proposal_client["client_id"], product_code="P-1",
            actor="co_system", intent="modified_for_case",
            parent_artifact_id=proposal_client["parent_artifact_id"],
            context={"case_id": "C-API-1"}, rows=_good_rows(),
        )
        sa_store.create_account(
            name="sa_test_co", description="", scopes=["bom:propose"],
            client_ids=[proposal_client["client_id"]],
            created_by="sa_test_runner",
        )
        token_out = jwt_issuer.make_service_token(
            name="sa_test_co", scopes=["bom:propose"],
            client_ids=[proposal_client["client_id"]],
        )
        client = TestClient(app)
        r = client.post(
            f"/v1/hub/proposals/{res['proposal_id']}/withdraw",
            headers={"authorization": f"Bearer {token_out['access_token']}"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "withdrawn"
    finally:
        settings_store.set_many({"api_auth_strict": "false"})


def test_api_withdraw_already_decided_returns_409(
    proposal_client, cleanup_sa,
):
    """Withdrawing an approved/rejected proposal must surface 409."""
    settings_store.set_many({"api_auth_strict": "true"})
    try:
        _set_mode(proposal_client["client_id"], "auto")
        res = submit_proposal(
            client_id=proposal_client["client_id"], product_code="P-1",
            actor="co_system", intent="modified_for_case",
            parent_artifact_id=proposal_client["parent_artifact_id"],
            context={"case_id": "C-API-2"}, rows=_good_rows(),
        )
        assert res["status"] == "approved"
        sa_store.create_account(
            name="sa_test_co", description="", scopes=["bom:propose"],
            client_ids=[proposal_client["client_id"]],
            created_by="sa_test_runner",
        )
        token_out = jwt_issuer.make_service_token(
            name="sa_test_co", scopes=["bom:propose"],
            client_ids=[proposal_client["client_id"]],
        )
        client = TestClient(app)
        r = client.post(
            f"/v1/hub/proposals/{res['proposal_id']}/withdraw",
            headers={"authorization": f"Bearer {token_out['access_token']}"},
        )
        assert r.status_code == 409
    finally:
        settings_store.set_many({"api_auth_strict": "false"})
