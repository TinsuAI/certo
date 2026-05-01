"""DB I/O for chat threads + messages. Owner-scoped queries to prevent
existence leaks across users."""
from __future__ import annotations

import json
import secrets
from typing import Any

from app.database import connect


def create_thread(*, user_id: str, client_id: str, title: str = "") -> str:
    thread_id = "th_" + secrets.token_urlsafe(12)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.chat_threads
                  (thread_id, user_id, client_id, title)
                values (%s, %s, %s, %s)
                """,
                (thread_id, user_id, client_id, title),
            )
    return thread_id


def get_thread(*, thread_id: str, user_id: str, client_id: str) -> dict | None:
    """Return None if thread doesn't exist OR doesn't belong to this
    (user, client) — no existence leak. Returns the thread dict otherwise."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select thread_id, user_id, client_id, title,
                       created_at, updated_at
                from hub.chat_threads
                where thread_id = %s and user_id = %s and client_id = %s
                """,
                (thread_id, user_id, client_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


def list_threads(*, user_id: str, client_id: str, limit: int = 20) -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select thread_id, title, created_at, updated_at,
                  (select count(*) from hub.chat_messages m
                    where m.thread_id = t.thread_id) as message_count
                from hub.chat_threads t
                where user_id = %s and client_id = %s
                order by updated_at desc
                limit %s
                """,
                (user_id, client_id, limit),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def append_message(*, thread_id: str, role: str, content: str | None = None,
                   tool_calls: list | None = None,
                   tool_call_id: str | None = None,
                   tool_name: str | None = None) -> int:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.chat_messages
                  (thread_id, role, content, tool_calls,
                   tool_call_id, tool_name)
                values (%s, %s, %s, %s::jsonb, %s, %s)
                returning id
                """,
                (thread_id, role, content,
                 json.dumps(tool_calls) if tool_calls is not None else None,
                 tool_call_id, tool_name),
            )
            (mid,) = cur.fetchone()
            cur.execute(
                "update hub.chat_threads set updated_at = now() where thread_id = %s",
                (thread_id,),
            )
    return mid


def list_messages(*, thread_id: str) -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, role, content, tool_calls, tool_call_id,
                       tool_name, created_at
                from hub.chat_messages
                where thread_id = %s
                order by id asc
                """,
                (thread_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def to_openai_messages(rows: list[dict]) -> list[dict]:
    """Convert stored DB rows into OpenAI chat-completion message shape."""
    out: list[dict] = []
    for r in rows:
        if r["role"] == "user":
            out.append({"role": "user", "content": r["content"] or ""})
        elif r["role"] == "system":
            out.append({"role": "system", "content": r["content"] or ""})
        elif r["role"] == "assistant":
            msg: dict[str, Any] = {"role": "assistant",
                                   "content": r["content"] or ""}
            if r["tool_calls"]:
                msg["tool_calls"] = r["tool_calls"]
            out.append(msg)
        elif r["role"] == "tool":
            out.append({
                "role": "tool",
                "tool_call_id": r["tool_call_id"] or "",
                "name": r["tool_name"] or "",
                "content": r["content"] or "",
            })
    return out
