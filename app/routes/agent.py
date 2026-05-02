"""Chat agent routes — nested under /clients/{client_id}/agent.

ACL gate: every route calls `auth.require_can_view_client`. Tools also
re-verify on dispatch (defense in depth). The thread is scoped to
(user, client) via `store.get_thread` which returns None for any
mismatch (no existence leak)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app import auth, settings_store
from app.agent import runtime, store
from app.llm import LLMUnavailable
from app.routes.clients import get_client, stats_for_client

router = APIRouter()


# ── Floating widget JSON endpoints ──────────────────────────────────────
# Declared FIRST so they win over the more permissive
# /agent/{thread_id} pattern below. Same ACL rules as page routes:
# every call goes through require_can_view_client + owner-scoped
# get_thread.

def _require_agent_user(request: Request, client_id: str):
    user = auth.require_user(request)
    if not settings_store.chat_agent_enabled():
        raise HTTPException(404, "Chat Agent disabled")
    auth.require_can_view_client(user, client_id)
    return user


def _serialize_msg(m: dict) -> dict:
    content = m.get("content") or ""
    payload = {
        "id": m["id"],
        "role": m["role"],
        "content": content,
        "created_at": m["created_at"].isoformat() if m.get("created_at") else None,
    }
    if m["role"] == "assistant" and m.get("tool_calls"):
        tcs = m["tool_calls"]
        # If this turn has no sibling content but DOES carry a final
        # answer inside submit_final_answer's args (legacy threads from
        # before the E2 fix), surface it so the widget renders cleanly.
        if not content:
            for tc in tcs:
                if tc.get("function", {}).get("name") == "submit_final_answer":
                    raw = tc.get("function", {}).get("arguments") or "{}"
                    try:
                        args = json.loads(raw)
                        legacy = (args.get("answer") or "").strip()
                        if legacy:
                            payload["content"] = legacy
                    except Exception:
                        pass
                    break
        # Hide submit_final_answer from the user-visible "→ tool" summary
        # — it's the terminator, not real work.
        non_terminator = [
            tc.get("function", {}).get("name", "?")
            for tc in tcs
            if tc.get("function", {}).get("name") != "submit_final_answer"
        ]
        if non_terminator:
            payload["tool_call_summary"] = non_terminator
    elif m["role"] == "tool":
        payload["tool_name"] = m.get("tool_name")
    return payload


@router.get("/clients/{client_id}/agent/_widget")
async def widget_init(request: Request, client_id: str):
    user = _require_agent_user(request, client_id)
    threads = store.list_threads(
        user_id=user.user_id, client_id=client_id, limit=1,
    )
    if threads:
        thread_id = threads[0]["thread_id"]
    else:
        thread_id = store.create_thread(
            user_id=user.user_id, client_id=client_id, title="",
        )
    msgs = store.list_messages(thread_id=thread_id)
    return JSONResponse({
        "thread_id": thread_id,
        "messages": [_serialize_msg(m) for m in msgs],
    })


@router.post("/clients/{client_id}/agent/_widget/send")
async def widget_send(request: Request, client_id: str):
    """Run a turn synchronously and return the updated message list.
    Body: {thread_id: str, text: str}. The frontend shows
    'Trợ lý đang suy nghĩ…' while this is in flight."""
    user = _require_agent_user(request, client_id)
    body = await request.json()
    thread_id = body.get("thread_id") or ""
    text = (body.get("text") or "").strip()
    thread = store.get_thread(
        thread_id=thread_id, user_id=user.user_id, client_id=client_id,
    )
    if not thread:
        raise HTTPException(404, "Thread not found")
    if not text:
        raise HTTPException(400, "text is empty")
    try:
        runtime.run_turn(
            thread_id=thread_id, user=user, client_id=client_id,
            user_text=text,
        )
    except LLMUnavailable as e:
        store.append_message(
            thread_id=thread_id, role="assistant",
            content=f"LLM chưa cấu hình: {e}. Liên hệ admin.",
        )
    except Exception as e:  # noqa: BLE001
        store.append_message(
            thread_id=thread_id, role="assistant",
            content=f"Lỗi khi gọi LLM ({type(e).__name__}). Vui lòng thử lại.",
        )
    msgs = store.list_messages(thread_id=thread_id)
    return JSONResponse({
        "thread_id": thread_id,
        "messages": [_serialize_msg(m) for m in msgs],
    })


@router.post("/clients/{client_id}/agent/_widget/new")
async def widget_new_thread(request: Request, client_id: str):
    user = _require_agent_user(request, client_id)
    thread_id = store.create_thread(
        user_id=user.user_id, client_id=client_id, title="",
    )
    return JSONResponse({"thread_id": thread_id, "messages": []})


@router.get("/clients/{client_id}/agent/_widget/threads")
async def widget_list_threads(request: Request, client_id: str):
    """Return all threads for the (user, client). Used by the
    in-widget threads list view."""
    user = _require_agent_user(request, client_id)
    threads = store.list_threads(
        user_id=user.user_id, client_id=client_id, limit=100,
    )
    return JSONResponse({
        "threads": [
            {
                "thread_id": t["thread_id"],
                "title": t.get("title") or "",
                "message_count": t.get("message_count", 0),
                "updated_at": t["updated_at"].isoformat()
                if t.get("updated_at") else None,
            }
            for t in threads
        ],
    })


@router.get("/clients/{client_id}/agent/_widget/threads/{thread_id}")
async def widget_select_thread(request: Request, client_id: str,
                               thread_id: str):
    """Switch the widget to an existing thread. Returns its messages.
    Owner-scoped — foreign threads return 404 (no existence leak)."""
    user = _require_agent_user(request, client_id)
    thread = store.get_thread(
        thread_id=thread_id, user_id=user.user_id, client_id=client_id,
    )
    if not thread:
        raise HTTPException(404, "Thread not found")
    msgs = store.list_messages(thread_id=thread_id)
    return JSONResponse({
        "thread_id": thread_id,
        "title": thread.get("title") or "",
        "messages": [_serialize_msg(m) for m in msgs],
    })


@router.post("/clients/{client_id}/agent/_widget/threads/{thread_id}/rename")
async def widget_rename_thread(request: Request, client_id: str,
                               thread_id: str):
    """Body: {title: str}. Owner-scoped."""
    user = _require_agent_user(request, client_id)
    body = await request.json()
    title = (body.get("title") or "").strip()[:120]
    ok = store.update_thread_title(
        thread_id=thread_id, user_id=user.user_id,
        client_id=client_id, title=title,
    )
    if not ok:
        raise HTTPException(404, "Thread not found")
    return JSONResponse({"ok": True, "title": title})


@router.post("/clients/{client_id}/agent/_widget/threads/{thread_id}/delete")
async def widget_delete_thread(request: Request, client_id: str,
                               thread_id: str):
    """Owner-scoped delete. Messages cascade via FK."""
    user = _require_agent_user(request, client_id)
    ok = store.delete_thread(
        thread_id=thread_id, user_id=user.user_id, client_id=client_id,
    )
    if not ok:
        raise HTTPException(404, "Thread not found")
    return JSONResponse({"ok": True})


@router.get("/clients/{client_id}/agent", response_class=HTMLResponse)
async def thread_list(request: Request, client_id: str):
    user = _require_agent_user(request, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    threads = store.list_threads(user_id=user.user_id, client_id=client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/agent_thread.html",
        {"client": client, "stats": stats_for_client(client_id),
         "threads": threads, "thread": None, "messages": [],
         "active_root": "clients", "active_tab": "agent"},
    )


@router.post("/clients/{client_id}/agent/threads")
async def create_thread(request: Request, client_id: str,
                        title: str = Form("")):
    user = _require_agent_user(request, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    thread_id = store.create_thread(
        user_id=user.user_id, client_id=client_id, title=(title or "").strip(),
    )
    return RedirectResponse(
        url=f"/clients/{client_id}/agent/{thread_id}", status_code=303,
    )


@router.get("/clients/{client_id}/agent/{thread_id}", response_class=HTMLResponse)
async def thread_view(request: Request, client_id: str, thread_id: str):
    user = _require_agent_user(request, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    thread = store.get_thread(
        thread_id=thread_id, user_id=user.user_id, client_id=client_id,
    )
    if not thread:
        # No existence leak — same 404 whether thread doesn't exist or
        # belongs to another user.
        raise HTTPException(404, "Thread not found")
    messages = store.list_messages(thread_id=thread_id)
    threads = store.list_threads(user_id=user.user_id, client_id=client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/agent_thread.html",
        {"client": client, "stats": stats_for_client(client_id),
         "threads": threads, "thread": thread, "messages": messages,
         "active_root": "clients", "active_tab": "agent"},
    )


@router.post("/clients/{client_id}/agent/{thread_id}/message")
async def send_message(request: Request, client_id: str, thread_id: str,
                       text: str = Form(...)):
    user = _require_agent_user(request, client_id)
    thread = store.get_thread(
        thread_id=thread_id, user_id=user.user_id, client_id=client_id,
    )
    if not thread:
        raise HTTPException(404, "Thread not found")

    text = (text or "").strip()
    if not text:
        return RedirectResponse(
            url=f"/clients/{client_id}/agent/{thread_id}", status_code=303,
        )

    try:
        runtime.run_turn(
            thread_id=thread_id, user=user, client_id=client_id,
            user_text=text,
        )
    except LLMUnavailable as e:
        # Persist the error as an assistant message so the UI shows it.
        store.append_message(
            thread_id=thread_id, role="assistant",
            content=f"LLM chưa cấu hình: {e}. Liên hệ admin.",
        )
    except Exception as e:  # noqa: BLE001
        store.append_message(
            thread_id=thread_id, role="assistant",
            content=f"Lỗi khi gọi LLM ({type(e).__name__}). Vui lòng thử lại.",
        )

    return RedirectResponse(
        url=f"/clients/{client_id}/agent/{thread_id}", status_code=303,
    )
