"""Authorization helpers — role + per-client ACL.

Roles (locked 2026-05-02):
- dev: single user. Vendor-side technical settings (deployment_config, code_resolution_mode).
- admin: agency-wide. User management, role assignment, all client edits.
- manager: scoped to clients in hub.user_managed_clients. Manages staff + non-technical config within group.
- staff: per-client access via hub.user_client_access (scope ∈ {read, edit}).
"""
from __future__ import annotations

from fastapi import HTTPException, status

from app.auth.session import User
from app.database import connect


def _is_dev(user: User | None) -> bool:
    return bool(user and user.role == "dev")


def _is_admin_or_dev(user: User | None) -> bool:
    return bool(user and user.role in ("dev", "admin"))


def _manages_client(user_id: str, client_id: str) -> bool:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select 1 from hub.user_managed_clients where user_id = %s and client_id = %s",
                (user_id, client_id),
            )
            return cur.fetchone() is not None


def _staff_scope(user_id: str, client_id: str) -> str | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select scope from hub.user_client_access where user_id = %s and client_id = %s",
                (user_id, client_id),
            )
            row = cur.fetchone()
            return row[0] if row else None


def can_view_client(user: User | None, client_id: str) -> bool:
    if not user:
        return False
    if user.role in ("dev", "admin"):
        return True
    if user.role == "manager":
        return _manages_client(user.user_id, client_id)
    if user.role == "staff":
        return _staff_scope(user.user_id, client_id) is not None
    return False


def can_edit_client(user: User | None, client_id: str) -> bool:
    """Row edits, uploads, tombstones — non-config writes."""
    if not user:
        return False
    if user.role in ("dev", "admin"):
        return True
    if user.role == "manager":
        return _manages_client(user.user_id, client_id)
    if user.role == "staff":
        return _staff_scope(user.user_id, client_id) == "edit"
    return False


def can_edit_client_config(user: User | None, client_id: str) -> bool:
    """Non-technical config: tax_code, notes, status, bom_proposal_qty_tolerance_pct, bom_proposal_mode."""
    if not user:
        return False
    if user.role in ("dev", "admin"):
        return True
    if user.role == "manager":
        return _manages_client(user.user_id, client_id)
    return False


def _client_approver_tier(client_id: str) -> str:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select bom_approver_tier from hub.clients where client_id = %s",
                (client_id,),
            )
            row = cur.fetchone()
    return (row[0] if row else "edit") or "edit"


def can_approve_proposal(user: User | None, client_id: str) -> bool:
    """Per-client `bom_approver_tier` decides who can approve / reject a
    pending BOM proposal:

      edit    — anyone with edit access on the client (default).
      manager — managers + admin/dev only.
      admin   — admin / dev only.
    """
    if not user:
        return False
    tier = _client_approver_tier(client_id)
    if tier == "admin":
        return user.role in ("dev", "admin")
    if tier == "manager":
        if user.role in ("dev", "admin"):
            return True
        if user.role == "manager":
            return _manages_client(user.user_id, client_id)
        return False
    # tier == 'edit' (default)
    return can_edit_client(user, client_id)


def require_can_approve_proposal(user: User | None, client_id: str) -> None:
    if not can_approve_proposal(user, client_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="forbidden",
        )


def can_edit_client_technical(user: User | None, client_id: str) -> bool:
    """Technical config: code_resolution_mode. Dev only."""
    return _is_dev(user)


def can_edit_deployment_config(user: User | None) -> bool:
    return _is_dev(user)


def can_manage_users(user: User | None) -> bool:
    """Create/lock users, set role. Admin and dev."""
    return _is_admin_or_dev(user)


def can_create_client(user: User | None) -> bool:
    """Create a new client (DNCX). Admin and dev only — managers are scoped to assigned clients."""
    return _is_admin_or_dev(user)


def can_manage_managers(user: User | None) -> bool:
    """Assign managers → client groups. Admin and dev."""
    return _is_admin_or_dev(user)


def can_assign_staff_to_client(user: User | None, client_id: str) -> bool:
    """Add/remove staff access on a client. Dev/admin anywhere; manager within their group."""
    if not user:
        return False
    if user.role in ("dev", "admin"):
        return True
    if user.role == "manager":
        return _manages_client(user.user_id, client_id)
    return False


def visible_clients(user: User | None) -> list[str] | None:
    """Return list of client_ids user may see, or None for 'all clients'.

    None means no filter — caller should not apply a where-clause.
    [] means user sees nothing.
    """
    if not user:
        return []
    if user.role in ("dev", "admin"):
        return None
    with connect() as conn:
        with conn.cursor() as cur:
            if user.role == "manager":
                cur.execute(
                    "select client_id from hub.user_managed_clients where user_id = %s",
                    (user.user_id,),
                )
            elif user.role == "staff":
                cur.execute(
                    "select client_id from hub.user_client_access where user_id = %s",
                    (user.user_id,),
                )
            else:
                return []
            return [row[0] for row in cur.fetchall()]


def require_can_view_client(user: User | None, client_id: str) -> None:
    if not can_view_client(user, client_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


def require_can_edit_client(user: User | None, client_id: str) -> None:
    if not can_edit_client(user, client_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
