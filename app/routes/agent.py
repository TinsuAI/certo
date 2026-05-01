"""Chat agent routes — nested under /clients/{client_id}/agent.

ACL gate: every route calls `auth.require_can_view_client`. Tools also
re-verify on dispatch (defense in depth). The thread is scoped to
(user, client) via `store.get_thread` which returns None for any
mismatch (no existence leak)."""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.agent import runtime, store
from app.llm import LLMUnavailable
from app.routes.clients import get_client, stats_for_client

router = APIRouter()


@router.get("/clients/{client_id}/agent", response_class=HTMLResponse)
async def thread_list(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    threads = store.list_threads(user_id=user.user_id, client_id=client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/agent_threads.html",
        {"client": client, "stats": stats_for_client(client_id),
         "threads": threads,
         "active_root": "clients", "active_tab": "agent"},
    )


@router.post("/clients/{client_id}/agent/threads")
async def create_thread(request: Request, client_id: str,
                        title: str = Form("")):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
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
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
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
    return request.app.state.templates.TemplateResponse(
        request, "clients/agent_thread.html",
        {"client": client, "stats": stats_for_client(client_id),
         "thread": thread, "messages": messages,
         "active_root": "clients", "active_tab": "agent"},
    )


@router.post("/clients/{client_id}/agent/{thread_id}/message")
async def send_message(request: Request, client_id: str, thread_id: str,
                       text: str = Form(...)):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
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
