"""Auth helpers — password hashing, session issuance, current-user lookup."""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash
from fastapi import HTTPException, Request, Response, status

from hub.app.database import connect

SESSION_COOKIE = "data_hub_session"
SESSION_TTL_HOURS = 24 * 14  # 2 weeks
PASSWORD_HASHER = PasswordHasher()


@dataclass(frozen=True)
class User:
    user_id: str
    email: str
    display_name: str
    role: str
    status: str


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        PASSWORD_HASHER.verify(password_hash, password)
        return True
    except (VerifyMismatchError, InvalidHash):
        return False


def _new_session_id() -> str:
    return secrets.token_urlsafe(32)


def create_session(user_id: str, *, user_agent: str | None = None, ip: str | None = None) -> str:
    session_id = _new_session_id()
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.sessions (session_id, user_id, expires_at, user_agent, ip_address)
                values (%s, %s, %s, %s, %s)
                """,
                (session_id, user_id, expires, user_agent, ip),
            )
    return session_id


def revoke_session(session_id: str) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from hub.sessions where session_id = %s", (session_id,))


def lookup_session(session_id: str) -> Optional[User]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select u.user_id, u.email, u.display_name, u.role, u.status
                from hub.sessions s
                join hub.users u on u.user_id = s.user_id
                where s.session_id = %s
                  and s.expires_at > now()
                  and u.status = 'active'
                """,
                (session_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cur.execute(
                "update hub.sessions set last_seen_at = now() where session_id = %s",
                (session_id,),
            )
            return User(*row)


def current_user(request: Request) -> Optional[User]:
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return None
    return lookup_session(session_id)


def require_user(request: Request) -> User:
    user = current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="login required",
            headers={"Location": "/login"},
        )
    return user


def set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=SESSION_TTL_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("DATA_HUB_FORCE_HTTPS_COOKIE") == "1",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def authenticate(email: str, password: str) -> Optional[User]:
    email = email.strip().lower()
    if not email or not password:
        return None
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select user_id, email, display_name, role, status, password_hash
                from hub.users where email = %s
                """,
                (email,),
            )
            row = cur.fetchone()
    if not row:
        return None
    user_id, email_db, display, role, status_v, pwd_hash = row
    if status_v != "active":
        return None
    if not verify_password(password, pwd_hash):
        return None
    return User(user_id, email_db, display, role, status_v)


def seed_admin_if_empty(*, email: str, password: str, display_name: str = "Admin") -> bool:
    """Create initial admin user if no users exist. Returns True if seeded."""
    user_id = "u_" + hashlib.sha256(email.encode()).hexdigest()[:16]
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from hub.users")
            (count,) = cur.fetchone()
            if count > 0:
                return False
            cur.execute(
                """
                insert into hub.users (user_id, email, display_name, password_hash, role)
                values (%s, %s, %s, %s, 'admin')
                """,
                (user_id, email.strip().lower(), display_name, hash_password(password)),
            )
    return True
