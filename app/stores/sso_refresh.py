"""SSO refresh-token store — opaque, rotating, server-side, revocable.

The access token stays short (600s). This is the long-lived secret, so
it never rests in usable form: rows are keyed by `sha256(token)` and the
plaintext exists only in the HTTP response that mints it.

Lifetime is two-dimensional:

- `expires_at` — sliding idle deadline, pushed forward on every rotation
  (`sso_refresh_idle_ttl_seconds`, default 12h).
- `absolute_expires_at` — hard ceiling fixed when the family is born
  (`sso_refresh_absolute_ttl_seconds`, default 7d). Rotation never
  extends it.

Both are additionally capped by the DH SSO session the token is bound to,
so a refresh can never outlive the login that authorized it.

Rotation is single-use. `rotate()` runs consume-old and mint-new inside
one transaction, which is what makes the concurrent case safe: the loser
of a race blocks on the winner's row lock, re-evaluates `used_at is null`
under READ COMMITTED once the winner commits, matches zero rows, and
401s. Exactly one refresh wins.

Reuse of an already-spent token is the classic stolen-token signal, but
it is also what a client retry looks like. The two are split by age: a
reuse within `sso_refresh_reuse_grace_seconds` of the rotation is treated
as a benign race (401, family survives), while anything older revokes the
whole family and forces a full SSO login.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app import settings_store
from app.database import connect

logger = logging.getLogger(__name__)

TOKEN_BYTES = 48

# Ordered least- to most-privileged. Used only to decide whether a live
# role is narrower than the one frozen into the grant.
ROLE_RANK: dict[str, int] = {"staff": 0, "manager": 1, "admin": 2, "dev": 3}


class RefreshTokenInvalid(Exception):
    """Unknown, expired, revoked, or already-spent token. Maps to 401 —
    the consumer must fall back to interactive SSO."""


class UserNotPermitted(Exception):
    """Token is valid but its subject may no longer authenticate. Maps to
    403 — retrying the refresh will not help."""


class _ReplayDetected(Exception):
    """Internal: a spent token was presented past the grace window. Carries
    the family to revoke, which must happen in its own transaction — the
    one that detected it gets rolled back by the RefreshTokenInvalid raise."""

    def __init__(self, family_id: str) -> None:
        super().__init__(family_id)
        self.family_id = family_id


def idle_ttl_seconds() -> int:
    """Sliding window. Long enough that an operator working a full shift
    never re-logs; short enough that an idle workstation stops renewing."""
    return settings_store.get_int("sso_refresh_idle_ttl_seconds", 43_200)  # 12h


def absolute_ttl_seconds() -> int:
    """Hard ceiling from first issue. Bounds the blast radius of a stolen
    refresh token that is rotated continuously."""
    return settings_store.get_int("sso_refresh_absolute_ttl_seconds", 604_800)  # 7d


def reuse_grace_seconds() -> int:
    return settings_store.get_int("sso_refresh_reuse_grace_seconds", 30)


def narrow_client_scope(
    granted: list[str] | None,
    live: list[str] | None,
) -> list[str] | None:
    """Intersect the frozen grant with the live ACL. `None` means "all
    clients" on either side.

    A refresh reflects revoked access immediately, but a grant that has
    since widened stays narrow until the operator logs in again — RFC 6749
    §6 forbids a refresh from returning broader scope than was issued.
    """
    if granted is None:
        return live  # grant was unrestricted; the live ACL is the only bound
    if live is None:
        return list(granted)  # user gained all-clients; do not broaden here
    allowed = set(granted)
    return [client_id for client_id in live if client_id in allowed]


def narrow_role(granted: str, live: str) -> str:
    """Freeze the role at grant time, except when the live role is strictly
    less privileged — a demotion must take effect without waiting out the
    refresh window, while a promotion needs a fresh SSO login."""
    if ROLE_RANK.get(live, -1) < ROLE_RANK.get(granted, -1):
        return live
    return granted


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def looks_like_jwt(value: str) -> bool:
    """Refresh tokens are `token_urlsafe` (no dots); JWTs are three
    dot-separated segments. Lets the route reject an access token handed
    to /refresh by mistake without ever hashing or logging it."""
    return value.count(".") == 2


def _new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def _session_deadline(cur, session_id: str) -> datetime | None:
    cur.execute(
        "select expires_at from hub.sessions where session_id = %s and expires_at > now()",
        (session_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _load_active_user(cur, user_id: str) -> dict[str, Any]:
    cur.execute(
        "select user_id, email, display_name, role, status from hub.users where user_id = %s",
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        # FK cascade should have removed the token with the user; treat a
        # surviving orphan as unknown rather than forbidden.
        raise RefreshTokenInvalid("user no longer exists")
    user = dict(zip(("user_id", "email", "display_name", "role", "status"), row))
    if user["status"] != "active":
        raise UserNotPermitted(f"user status = {user['status']}")
    return user


def _insert(
    cur,
    *,
    family_id: str,
    user_id: str,
    session_id: str,
    granted_role: str,
    granted_client_ids: list[str] | None,
    redirect_origin: str | None,
    absolute_deadline: datetime,
    session_deadline: datetime,
) -> tuple[str, datetime]:
    token = _new_token()
    now = datetime.now(timezone.utc)
    expires_at = min(
        now + timedelta(seconds=idle_ttl_seconds()),
        absolute_deadline,
        session_deadline,
    )
    cur.execute(
        """
        insert into hub.sso_refresh_tokens
          (token_hash, family_id, user_id, session_id, granted_role,
           granted_client_ids, redirect_origin, expires_at, absolute_expires_at)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (_hash(token), family_id, user_id, session_id, granted_role,
         granted_client_ids, redirect_origin, expires_at, absolute_deadline),
    )
    return token, expires_at


def _revoke_family(cur, family_id: str, reason: str) -> None:
    cur.execute(
        """
        update hub.sso_refresh_tokens
           set revoked_at = now(), revoked_reason = %s
         where family_id = %s and revoked_at is null
        """,
        (reason, family_id),
    )


def purge_expired(cur) -> None:
    """Drop rows whose absolute ceiling passed a week ago. Keeps the
    recently-spent ones so reuse detection still has something to see."""
    cur.execute(
        "delete from hub.sso_refresh_tokens where absolute_expires_at < now() - interval '7 days'"
    )


def issue(
    *,
    user_id: str,
    session_id: str,
    granted_role: str,
    granted_client_ids: list[str] | None,
    redirect_origin: str | None = None,
) -> dict[str, Any]:
    """Mint the first refresh token of a new family, at code-exchange time.

    `granted_role` / `granted_client_ids` freeze the consented scope; every
    later rotation narrows against them and never widens.

    Raises RefreshTokenInvalid if the SSO session is already gone — there
    would be nothing to bind to.
    """
    with connect() as conn:
        with conn.cursor() as cur:
            purge_expired(cur)
            session_deadline = _session_deadline(cur, session_id)
            if session_deadline is None:
                raise RefreshTokenInvalid("sso session expired or unknown")
            absolute_deadline = min(
                datetime.now(timezone.utc) + timedelta(seconds=absolute_ttl_seconds()),
                session_deadline,
            )
            token, expires_at = _insert(
                cur,
                family_id="rf_" + uuid.uuid4().hex,
                user_id=user_id,
                session_id=session_id,
                granted_role=granted_role,
                granted_client_ids=granted_client_ids,
                redirect_origin=redirect_origin,
                absolute_deadline=absolute_deadline,
                session_deadline=session_deadline,
            )
    return {"refresh_token": token, "expires_at": expires_at}


def rotate(presented: str) -> dict[str, Any]:
    """Consume `presented` and mint its successor, atomically.

    Returns the successor token plus the freshly-read user row, so the
    caller rebuilds access-token claims from live DB state rather than
    from anything the old token carried. That is what keeps a refresh
    from ever broadening the visible-client set.

    Raises RefreshTokenInvalid (401) or UserNotPermitted (403). Both roll
    the transaction back, so a rejected refresh never burns the token.
    """
    token_hash = _hash(presented)
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                # Single-use consume. Re-checking the predicate under the
                # row lock is what makes concurrent refreshes resolve to
                # exactly one winner.
                cur.execute(
                    """
                    update hub.sso_refresh_tokens
                       set used_at = now()
                     where token_hash = %s
                       and used_at is null
                       and revoked_at is null
                       and expires_at > now()
                       and absolute_expires_at > now()
                 returning family_id, user_id, session_id, granted_role,
                           granted_client_ids, redirect_origin, absolute_expires_at
                    """,
                    (token_hash,),
                )
                row = cur.fetchone()
                if row is None:
                    family_id = _replayed_family(cur, token_hash)
                    if family_id:
                        raise _ReplayDetected(family_id)
                    raise RefreshTokenInvalid("refresh token rejected")

                (family_id, user_id, session_id, granted_role,
                 granted_client_ids, redirect_origin, absolute_deadline) = row

                session_deadline = _session_deadline(cur, session_id)
                if session_deadline is None:
                    raise RefreshTokenInvalid("sso session expired or revoked")

                user = _load_active_user(cur, user_id)

                token, expires_at = _insert(
                    cur,
                    family_id=family_id,
                    user_id=user_id,
                    session_id=session_id,
                    granted_role=granted_role,
                    granted_client_ids=granted_client_ids,
                    redirect_origin=redirect_origin,
                    absolute_deadline=absolute_deadline,
                    session_deadline=session_deadline,
                )
                cur.execute(
                    "update hub.sso_refresh_tokens set replaced_by = %s where token_hash = %s",
                    (_hash(token), token_hash),
                )
    except _ReplayDetected as exc:
        # The detecting transaction rolled back with this raise, so the
        # revocation needs a transaction of its own.
        _revoke_family_tx(exc.family_id, "reuse_detected")
        raise RefreshTokenInvalid("refresh token replayed") from None

    return {
        "refresh_token": token,
        "expires_at": expires_at,
        "user": user,
        "granted_role": granted_role,
        "granted_client_ids": (
            list(granted_client_ids) if granted_client_ids is not None else None
        ),
    }


def _replayed_family(cur, token_hash: str) -> str | None:
    """The consume matched nothing. Read-only: report the family to revoke
    when this is a genuine replay, or None when it is a benign race, an
    unknown token, or a merely-expired one.

    A spent token re-presented within the grace window is what a client
    retry and a lost rotation race both look like, so the winner keeps the
    family. Past that window, an attacker is replaying a token the
    legitimate client already exchanged.
    """
    cur.execute(
        "select family_id, used_at, revoked_at from hub.sso_refresh_tokens where token_hash = %s",
        (token_hash,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    family_id, used_at, revoked_at = row
    if revoked_at is not None or used_at is None:
        return None
    age = (datetime.now(timezone.utc) - used_at).total_seconds()
    if age <= reuse_grace_seconds():
        return None
    logger.warning(
        "sso_refresh: replay detected on family %s (token spent %.0fs ago) — revoking family",
        family_id, age,
    )
    return family_id


def _revoke_family_tx(family_id: str, reason: str) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            _revoke_family(cur, family_id, reason)


def revoke_for_session(session_id: str, *, reason: str = "session_revoked") -> None:
    """Explicit revoke path for logout. The FK cascade already removes
    rows when the session row is deleted; this exists for callers that
    end a session without deleting it."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.sso_refresh_tokens
                   set revoked_at = now(), revoked_reason = %s
                 where session_id = %s and revoked_at is null
                """,
                (reason, session_id),
            )
