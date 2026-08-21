"""In-app notifications: persistent per-user feed for async-task events
+ multi-step waiting work.

Routes call ``notify(...)`` whenever something important lands for a
specific user. The bell fragment + ``/notifications`` list page consume
the rows. Each helper opens its own short-lived connection so the
module is safe to call from background tasks (no request scope).

Design refs: BCQT-System/app/notifications.py (pattern source) +
.ai/features/2026-05-02-bcqt-borrow-survey.md.
"""
from __future__ import annotations

from typing import Any

from app.database import connect


def notify(
    *,
    user_id: str,
    kind: str,
    title: str,
    body: str | None = None,
    link_url: str | None = None,
    client_id: str | None = None,
    related_kind: str | None = None,
    related_id: str | None = None,
) -> int:
    """Insert a single notification row. Returns the new row id.

    `kind` is a stable string for routing/filtering: 'preview_pending',
    'llm_mapping_proposed', 'provenance_alarm', 'bom_proposal_queued',
    etc. Title + body are user-facing; link_url should be an internal
    path the route helpers know how to gate (must start with `/`).
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.notifications
                  (user_id, kind, title, body, link_url, client_id,
                   related_kind, related_id)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                returning id
                """,
                (user_id, kind, title, body, link_url, client_id,
                 related_kind, related_id),
            )
            (nid,) = cur.fetchone()
            return nid


def notify_many(
    *,
    user_ids: list[str],
    kind: str,
    title: str,
    body: str | None = None,
    link_url: str | None = None,
    client_id: str | None = None,
    related_kind: str | None = None,
    related_id: str | None = None,
) -> int:
    """Send the same notification to N users. Returns count inserted.

    Use for fan-out events (e.g. catalog alarm crossed threshold →
    notify every active staff with edit access to the client)."""
    if not user_ids:
        return 0
    with connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                insert into hub.notifications
                  (user_id, kind, title, body, link_url, client_id,
                   related_kind, related_id)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (uid, kind, title, body, link_url, client_id,
                     related_kind, related_id)
                    for uid in user_ids
                ],
            )
            return cur.rowcount or 0


def notify_api_contract_changed(
    *, summary: str, changelog_url: str | None = None,
) -> int:
    """Fan a `Breaking:` API contract change to all dev + admin users.

    Used by scripts/announce_breaking_change.py after API_CHANGELOG.md
    gets a new `## YYYY-MM-DD — Breaking: ...` entry. Sister-app
    operators (CO + BCQT dev/admin) read the bell and adjust consumer
    code.
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select user_id from hub.users
                where role in ('dev', 'admin') and status = 'active'
                """
            )
            user_ids = [row[0] for row in cur.fetchall()]
    if not user_ids:
        return 0
    return notify_many(
        user_ids=user_ids,
        kind="api_contract_changed",
        title="Breaking API contract change",
        body=summary,
        link_url=changelog_url or "/docs/API_CHANGELOG.md",
    )


def list_for_user(
    user_id: str,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Newest-first list. `status` filter optional ('unread'/'read')."""
    with connect() as conn:
        with conn.cursor() as cur:
            if status:
                cur.execute(
                    """
                    select id, kind, title, body, link_url, status,
                           client_id, related_kind, related_id,
                           created_at, read_at
                    from hub.notifications
                    where user_id = %s and status = %s
                    order by created_at desc, id desc
                    limit %s
                    """,
                    (user_id, status, limit),
                )
            else:
                cur.execute(
                    """
                    select id, kind, title, body, link_url, status,
                           client_id, related_kind, related_id,
                           created_at, read_at
                    from hub.notifications
                    where user_id = %s
                    order by created_at desc, id desc
                    limit %s
                    """,
                    (user_id, limit),
                )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def unread_count(user_id: str) -> int:
    """Drives the bell badge."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) from hub.notifications "
                "where user_id = %s and status = 'unread'",
                (user_id,),
            )
            (n,) = cur.fetchone()
            return n


def mark_read(*, user_id: str, notification_id: int) -> bool:
    """Mark one notification as read, scoped to the owner. Returns True
    when a row changed (i.e. notif belonged to user AND was unread)."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.notifications
                  set status = 'read', read_at = now()
                where id = %s and user_id = %s and status = 'unread'
                """,
                (notification_id, user_id),
            )
            return (cur.rowcount or 0) > 0


def mark_all_read(user_id: str) -> int:
    """Bulk-clear every unread for a user. Returns count."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.notifications
                  set status = 'read', read_at = now()
                where user_id = %s and status = 'unread'
                """,
                (user_id,),
            )
            return cur.rowcount or 0


def get_for_user(*, user_id: str, notification_id: int) -> dict[str, Any] | None:
    """Single-row read scoped to owner. Returns None if not found OR
    if it belongs to another user (no existence leak)."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, kind, title, body, link_url, status,
                       client_id, related_kind, related_id,
                       created_at, read_at
                from hub.notifications
                where id = %s and user_id = %s
                """,
                (notification_id, user_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


def staff_with_edit_access_to_client(client_id: str) -> list[str]:
    """List of user_ids that have edit access to the given client.

    Includes: dev/admin (global edit), managers of this client (via
    user_managed_clients), and staff with explicit `edit` scope (via
    user_client_access). Used for fan-out notifications so every
    responsible party hears about (e.g.) a new provenance alarm."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select distinct u.user_id
                from hub.users u
                left join hub.user_managed_clients m
                  on m.user_id = u.user_id and m.client_id = %s
                left join hub.user_client_access a
                  on a.user_id = u.user_id and a.client_id = %s
                where u.status = 'active'
                  and (
                    u.role in ('dev','admin')
                    or m.client_id is not null
                    or a.scope = 'edit'
                  )
                """,
                (client_id, client_id),
            )
            return [r[0] for r in cur.fetchall()]
