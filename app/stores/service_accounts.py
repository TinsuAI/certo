"""Service account store — registry + jti blacklist.

Service accounts are non-human identities for sister-app integration
(CO write-back, BCQT consumer reads, cron jobs). Each row maps to a
named service token whose `sub` becomes 'svc:<name>'.

Revocation:
- Soft (entire account): `delete_account(name)` — verifier rejects
  any token referencing this name on the next call.
- Specific token: `revoke_jti(jti, ...)` — jti blacklist; verifier
  rejects matching jti even if the account is still alive.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.database import connect


def create_account(
    *,
    name: str,
    description: str,
    scopes: list[str],
    client_ids: list[str] | None,
    created_by: str,
) -> dict[str, Any]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.service_accounts
                  (name, description, scopes, client_ids, created_by)
                values (%s, %s, %s, %s, %s)
                returning name, description, scopes, client_ids, created_at,
                          created_by, last_used_at
                """,
                (name, description, scopes, client_ids, created_by),
            )
            return _row_to_dict(cur.fetchone(), cur.description)


def get_account(name: str) -> dict[str, Any] | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select name, description, scopes, client_ids, created_at,
                       created_by, last_used_at
                from hub.service_accounts where name = %s
                """,
                (name,),
            )
            row = cur.fetchone()
            return _row_to_dict(row, cur.description) if row else None


def list_accounts() -> list[dict[str, Any]]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select name, description, scopes, client_ids, created_at,
                       created_by, last_used_at
                from hub.service_accounts order by name
                """,
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def delete_account(name: str) -> bool:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from hub.service_accounts where name = %s",
                (name,),
            )
            return cur.rowcount > 0


def touch_last_used(name: str, when: datetime) -> None:
    """Bump last_used_at; best-effort, swallows missing-row case."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.service_accounts set last_used_at = %s where name = %s",
                (when, name),
            )


def revoke_jti(*, jti: str, revoked_by: str, reason: str = "") -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.revoked_service_tokens (jti, revoked_by, reason)
                values (%s, %s, %s)
                on conflict (jti) do nothing
                """,
                (jti, revoked_by, reason),
            )


def is_jti_revoked(jti: str) -> bool:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select 1 from hub.revoked_service_tokens where jti = %s",
                (jti,),
            )
            return cur.fetchone() is not None


def _row_to_dict(row, description) -> dict[str, Any]:
    cols = [d[0] for d in description]
    return dict(zip(cols, row))
