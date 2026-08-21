"""One-time browser-SSO code store.

Backs `GET /v1/auth/authorize` -> `POST /v1/auth/exchange`. Lives in Postgres
rather than process memory so the two halves of the round-trip can land on
different uvicorn workers.

Only `sha256(code)` is stored, as with `hub.sso_refresh_tokens`. Consumption is
a single atomic `UPDATE ... WHERE used_at IS NULL`, so two concurrent exchanges
of the same code yield exactly one winner: the loser blocks on the row lock,
re-checks the predicate under READ COMMITTED once the winner commits, matches
zero rows, and is rejected.

A `redirect_uri` mismatch raises, which rolls the consume back and leaves the
code spendable — same as the in-memory version, where the dict entry was popped
only after the check passed.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from hub.app.database import connect

CODE_TTL_SECONDS = 120
CODE_BYTES = 32


class SsoCodeInvalid(Exception):
    """Unknown, expired, or already-spent code."""


class SsoCodeRedirectMismatch(Exception):
    """Code is live, but presented with a different redirect_uri than the one
    it was minted for. Does not spend the code."""


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _purge_expired(cur) -> None:
    """Codes live 120s. Keep spent/expired rows an hour so a replayed code is
    still recognisable as spent rather than silently unknown."""
    cur.execute("delete from hub.sso_codes where expires_at < now() - interval '1 hour'")


def issue(
    *,
    user_id: str,
    email: str,
    role: str,
    display_name: str,
    redirect_uri: str,
    session_id: str | None,
) -> str:
    """Mint a one-time code and return its plaintext. Only the hash is stored."""
    code = secrets.token_urlsafe(CODE_BYTES)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=CODE_TTL_SECONDS)
    with connect() as conn:
        with conn.cursor() as cur:
            _purge_expired(cur)
            cur.execute(
                """
                insert into hub.sso_codes
                  (code_hash, user_id, session_id, email, role, display_name,
                   redirect_uri, expires_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (_hash(code), user_id, session_id, email, role, display_name,
                 redirect_uri, expires_at),
            )
    return code


def consume(code: str, *, redirect_uri: str) -> dict[str, Any]:
    """Spend `code` and return the identity it carries.

    Raises SsoCodeInvalid when the code is unknown, expired, or already spent,
    and SsoCodeRedirectMismatch when it was minted for a different callback.
    Both roll back, so a mismatch leaves the code usable by its rightful owner.
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.sso_codes
                   set used_at = now()
                 where code_hash = %s
                   and used_at is null
                   and expires_at > now()
             returning user_id, session_id, email, role, display_name, redirect_uri
                """,
                (_hash(code),),
            )
            row = cur.fetchone()
            if row is None:
                raise SsoCodeInvalid("invalid or expired code")
            claims = dict(zip(
                ("user_id", "session_id", "email", "role", "display_name", "redirect_uri"),
                row,
            ))
            if claims["redirect_uri"] != redirect_uri:
                raise SsoCodeRedirectMismatch("redirect_uri does not match the code")
    return claims
