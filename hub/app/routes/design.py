"""Design gallery — read-only reference page for the 2026-08 UI redesign.

Renders every component of the new design system on one screen with
sample content, so the system can be judged without clicking through the
app. No client context, no writes: a logged-in session is the only
requirement.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from hub.app import auth

router = APIRouter()


@router.get("/design", response_class=HTMLResponse)
async def design_gallery(request: Request):
    auth.require_user(request)
    return request.app.state.templates.TemplateResponse(
        request, "design_gallery.html", {"active_root": "design"},
    )
