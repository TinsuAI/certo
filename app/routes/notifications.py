"""Notification routes — bell fragment, list page, mark-read POSTs."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth, notifications

router = APIRouter()


@router.get("/notifications/_bell", response_class=HTMLResponse)
async def bell_fragment(request: Request):
    """HTMX-polled fragment in the navbar. Shows badge + 5 most-recent
    unread items. Stateless — every poll re-queries."""
    user = auth.require_user(request)
    unread = notifications.unread_count(user.user_id)
    recent = notifications.list_for_user(
        user.user_id, status="unread", limit=5,
    )
    return request.app.state.templates.TemplateResponse(
        request, "notifications/_bell.html",
        {"unread_count": unread, "recent": recent},
    )


@router.get("/notifications", response_class=HTMLResponse)
async def list_page(request: Request):
    """Full per-user feed. Unread first, then read (capped at 200 each)."""
    user = auth.require_user(request)
    unread = notifications.list_for_user(
        user.user_id, status="unread", limit=200,
    )
    read = notifications.list_for_user(
        user.user_id, status="read", limit=200,
    )
    return request.app.state.templates.TemplateResponse(
        request, "notifications/list.html",
        {"unread_items": unread, "read_items": read,
         "active_root": "notifications"},
    )


@router.post("/notifications/{notification_id}/read")
async def mark_read(request: Request, notification_id: int):
    """Mark one as read; redirect to its link_url (if internal & safe) or
    fall back to the list. Silently 303 to /notifications when the row
    doesn't belong to this user — no existence leak."""
    user = auth.require_user(request)
    target = notifications.get_for_user(
        user_id=user.user_id, notification_id=notification_id,
    )
    if not target:
        return RedirectResponse("/notifications", status_code=303)
    notifications.mark_read(
        user_id=user.user_id, notification_id=notification_id,
    )
    link = target.get("link_url") or "/notifications"
    safe = (
        link if isinstance(link, str) and link.startswith("/")
        else "/notifications"
    )
    return RedirectResponse(safe, status_code=303)


@router.post("/notifications/read-all")
async def mark_all_read(request: Request):
    user = auth.require_user(request)
    notifications.mark_all_read(user.user_id)
    return RedirectResponse("/notifications", status_code=303)
