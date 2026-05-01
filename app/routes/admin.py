"""Admin routes — user management + manager client assignment.

Gated to admin/dev. Manager-of-client + staff cannot access /admin/* at all.
"""
from __future__ import annotations

import hashlib
import secrets

import psycopg
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect
from app.routes.clients import get_client, stats_for_client

router = APIRouter()

ROLES = ("dev", "admin", "manager", "staff")
ASSIGNABLE_ROLES = ("admin", "manager", "staff")


def _new_user_id(email: str) -> str:
    digest = hashlib.sha256((email + secrets.token_hex(4)).encode()).hexdigest()[:16]
    return "u_" + digest


def _list_users() -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select user_id, email, display_name, role, status, created_at
                from hub.users order by
                  case role when 'dev' then 0 when 'admin' then 1
                           when 'manager' then 2 else 3 end,
                  email
                """
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _get_user(user_id: str) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select user_id, email, display_name, role, status, created_at
                from hub.users where user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


def _list_clients_minimal() -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select client_id, name, status from hub.clients order by name"
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _list_managed(user_id: str) -> set[str]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select client_id from hub.user_managed_clients where user_id = %s",
                (user_id,),
            )
            return {r[0] for r in cur.fetchall()}


@router.get("/admin", response_class=HTMLResponse)
async def admin_root(request: Request):
    user = auth.require_user(request)
    if not auth.can_manage_users(user):
        raise HTTPException(403, "forbidden")
    return RedirectResponse(url="/admin/users", status_code=302)


# ── Technical settings (LLM) — dev-only ────────────────────────────────

@router.get("/admin/settings/technical", response_class=HTMLResponse)
async def settings_technical_view(request: Request, saved: bool = False,
                                  fetch_models: bool = False):
    from app import llm, settings_store
    user = auth.require_user(request)
    if user.role != "dev":
        raise HTTPException(403, "dev only")
    values = settings_store.get_many(settings_store.LLM_KEYS)
    api_key_set = bool(values.get("llm_api_key"))

    # Optionally probe the endpoint for available models.
    models: list[str] = []
    fetch_error: str | None = None
    if fetch_models:
        try:
            cfg = llm.LLMConfig.load()
            models = llm.list_models(cfg)
            # Auto-default model: if we have a list and no model saved
            # yet, persist the first one so subsequent uploads work.
            if models and not values.get("llm_model"):
                settings_store.set_many({"llm_model": models[0]},
                                        updated_by=user.user_id)
                values = settings_store.get_many(settings_store.LLM_KEYS)
        except (llm.LLMUnavailable, llm.LLMProposalError) as e:
            fetch_error = f"{type(e).__name__}: {e}"

    return request.app.state.templates.TemplateResponse(
        request, "admin/settings_technical.html",
        {
            "values": {k: ("" if k == "llm_api_key" else values.get(k, ""))
                       for k in settings_store.LLM_KEYS},
            "api_key_set": api_key_set,
            "saved": saved,
            "models": models,
            "fetch_error": fetch_error,
            "active_root": "admin",
        },
    )


@router.post("/admin/settings/technical")
async def settings_technical_submit(
    request: Request,
    llm_base_url: str = Form(""),
    llm_model: str = Form(""),
    llm_api_key: str = Form(""),
    llm_temperature: str = Form("0.0"),
    llm_timeout_s: str = Form("30"),
    llm_max_retries: str = Form("2"),
    llm_max_calls_per_day_per_client: str = Form("50"),
):
    from app import settings_store
    user = auth.require_user(request)
    if user.role != "dev":
        raise HTTPException(403, "dev only")
    values: dict[str, str] = {
        "llm_base_url": llm_base_url.strip(),
        "llm_model": llm_model.strip(),
        "llm_temperature": llm_temperature.strip() or "0.0",
        "llm_timeout_s": llm_timeout_s.strip() or "30",
        "llm_max_retries": llm_max_retries.strip() or "2",
        "llm_max_calls_per_day_per_client":
            llm_max_calls_per_day_per_client.strip() or "50",
    }
    # Only update the API key when a non-empty value was submitted; an
    # empty submit means "leave existing". Avoids accidental wipe.
    if llm_api_key.strip():
        values["llm_api_key"] = llm_api_key.strip()
    settings_store.set_many(values, updated_by=user.user_id)
    # After saving base_url + api_key, fetching models is the natural
    # next step. The GET handler with fetch_models=1 also auto-sets the
    # first model when llm_model is empty — so a user can paste URL+key,
    # click Save, and have a working config without typing model names.
    return RedirectResponse(
        url="/admin/settings/technical?saved=1&fetch_models=1",
        status_code=303,
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def users_view(request: Request, error: str | None = None):
    user = auth.require_user(request)
    if not auth.can_manage_users(user):
        raise HTTPException(403, "forbidden")
    users = _list_users()
    return request.app.state.templates.TemplateResponse(
        request, "admin/users.html",
        {"users": users, "roles": ROLES, "assignable_roles": ASSIGNABLE_ROLES,
         "active_root": "admin", "error": error},
    )


@router.post("/admin/users/new")
async def users_create(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
):
    actor = auth.require_user(request)
    if not auth.can_manage_users(actor):
        raise HTTPException(403, "forbidden")
    email = email.strip().lower()
    if role not in ASSIGNABLE_ROLES:
        raise HTTPException(400, "invalid role")
    if len(password) < 6:
        raise HTTPException(400, "password too short")
    user_id = _new_user_id(email)
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into hub.users (user_id, email, display_name, password_hash, role)
                    values (%s, %s, %s, %s, %s)
                    """,
                    (user_id, email, display_name.strip(), auth.hash_password(password), role),
                )
    except psycopg.errors.UniqueViolation:
        return RedirectResponse(url="/admin/users?error=duplicate_email", status_code=303)
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/role")
async def users_set_role(
    request: Request, user_id: str,
    role: str = Form(...),
):
    actor = auth.require_user(request)
    if not auth.can_manage_users(actor):
        raise HTTPException(403, "forbidden")
    if role not in ASSIGNABLE_ROLES:
        raise HTTPException(400, "invalid role")
    target = _get_user(user_id)
    if not target:
        raise HTTPException(404, "user not found")
    if target["role"] == "dev":
        raise HTTPException(400, "cannot change role of dev user")
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update hub.users set role = %s, updated_at = now() where user_id = %s",
                    (role, user_id),
                )
                if role != "manager":
                    cur.execute(
                        "delete from hub.user_managed_clients where user_id = %s",
                        (user_id,),
                    )
                if role != "staff":
                    cur.execute(
                        "delete from hub.user_client_access where user_id = %s",
                        (user_id,),
                    )
    except psycopg.errors.UniqueViolation:
        return RedirectResponse(url="/admin/users?error=single_dev", status_code=303)
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/status")
async def users_set_status(
    request: Request, user_id: str,
    new_status: str = Form(...),
):
    actor = auth.require_user(request)
    if not auth.can_manage_users(actor):
        raise HTTPException(403, "forbidden")
    if new_status not in ("active", "locked"):
        raise HTTPException(400, "invalid status")
    target = _get_user(user_id)
    if not target:
        raise HTTPException(404, "user not found")
    if target["role"] == "dev" and new_status == "locked":
        raise HTTPException(400, "cannot lock the dev account")
    if target["user_id"] == actor.user_id:
        raise HTTPException(400, "cannot change your own status")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.users set status = %s, updated_at = now() where user_id = %s",
                (new_status, user_id),
            )
            if new_status == "locked":
                cur.execute(
                    "delete from hub.sessions where user_id = %s",
                    (user_id,),
                )
    return RedirectResponse(url="/admin/users", status_code=303)


@router.get("/admin/users/{user_id}/clients", response_class=HTMLResponse)
async def manager_clients_view(request: Request, user_id: str):
    actor = auth.require_user(request)
    if not auth.can_manage_managers(actor):
        raise HTTPException(403, "forbidden")
    target = _get_user(user_id)
    if not target:
        raise HTTPException(404, "user not found")
    if target["role"] != "manager":
        raise HTTPException(400, "user is not a manager")
    all_clients = _list_clients_minimal()
    managed_ids = _list_managed(user_id)
    assigned = [c for c in all_clients if c["client_id"] in managed_ids]
    available = [c for c in all_clients if c["client_id"] not in managed_ids]
    return request.app.state.templates.TemplateResponse(
        request, "admin/manager_clients.html",
        {"target": target, "assigned": assigned, "available": available,
         "active_root": "admin"},
    )


@router.post("/admin/users/{user_id}/clients/add")
async def manager_clients_add(
    request: Request, user_id: str,
    client_id: str = Form(...),
):
    actor = auth.require_user(request)
    if not auth.can_manage_managers(actor):
        raise HTTPException(403, "forbidden")
    target = _get_user(user_id)
    if not target or target["role"] != "manager":
        raise HTTPException(400, "user is not a manager")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.user_managed_clients (user_id, client_id, granted_by)
                values (%s, %s, %s)
                on conflict do nothing
                """,
                (user_id, client_id, actor.user_id),
            )
    return RedirectResponse(url=f"/admin/users/{user_id}/clients", status_code=303)


@router.post("/admin/users/{user_id}/clients/remove")
async def manager_clients_remove(
    request: Request, user_id: str,
    client_id: str = Form(...),
):
    actor = auth.require_user(request)
    if not auth.can_manage_managers(actor):
        raise HTTPException(403, "forbidden")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from hub.user_managed_clients where user_id = %s and client_id = %s",
                (user_id, client_id),
            )
    return RedirectResponse(url=f"/admin/users/{user_id}/clients", status_code=303)


# === Staff assignment to a client (per-client tab) ===

def _list_staff_for_client(client_id: str) -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select u.user_id, u.email, u.display_name, a.scope, a.granted_at, a.granted_by,
                       g.email as granted_by_email
                from hub.user_client_access a
                join hub.users u on u.user_id = a.user_id
                left join hub.users g on g.user_id = a.granted_by
                where a.client_id = %s
                order by u.email
                """,
                (client_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _list_staff_candidates(client_id: str) -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select user_id, email, display_name from hub.users
                where role = 'staff' and status = 'active'
                  and user_id not in (select user_id from hub.user_client_access where client_id = %s)
                order by email
                """,
                (client_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/clients/{client_id}/staff", response_class=HTMLResponse)
async def staff_view(request: Request, client_id: str):
    actor = auth.require_user(request)
    if not auth.can_assign_staff_to_client(actor, client_id):
        raise HTTPException(403, "forbidden")
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    assigned = _list_staff_for_client(client_id)
    candidates = _list_staff_candidates(client_id)
    return request.app.state.templates.TemplateResponse(
        request, "admin/client_staff.html",
        {"client": client, "stats": stats_for_client(client_id),
         "assigned": assigned, "candidates": candidates,
         "active_root": "clients", "active_tab": "staff"},
    )


@router.post("/clients/{client_id}/staff/add")
async def staff_add(
    request: Request, client_id: str,
    user_id: str = Form(...),
    scope: str = Form("read"),
):
    actor = auth.require_user(request)
    if not auth.can_assign_staff_to_client(actor, client_id):
        raise HTTPException(403, "forbidden")
    if scope not in ("read", "edit"):
        raise HTTPException(400, "invalid scope")
    target = _get_user(user_id)
    if not target or target["role"] != "staff":
        raise HTTPException(400, "target must be a staff user")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.user_client_access (user_id, client_id, scope, granted_by)
                values (%s, %s, %s, %s)
                on conflict (user_id, client_id) do update set scope = excluded.scope, granted_at = now(), granted_by = excluded.granted_by
                """,
                (user_id, client_id, scope, actor.user_id),
            )
    return RedirectResponse(url=f"/clients/{client_id}/staff", status_code=303)


@router.post("/clients/{client_id}/staff/remove")
async def staff_remove(
    request: Request, client_id: str,
    user_id: str = Form(...),
):
    actor = auth.require_user(request)
    if not auth.can_assign_staff_to_client(actor, client_id):
        raise HTTPException(403, "forbidden")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from hub.user_client_access where user_id = %s and client_id = %s",
                (user_id, client_id),
            )
    return RedirectResponse(url=f"/clients/{client_id}/staff", status_code=303)


@router.post("/clients/{client_id}/staff/scope")
async def staff_scope(
    request: Request, client_id: str,
    user_id: str = Form(...),
    scope: str = Form(...),
):
    actor = auth.require_user(request)
    if not auth.can_assign_staff_to_client(actor, client_id):
        raise HTTPException(403, "forbidden")
    if scope not in ("read", "edit"):
        raise HTTPException(400, "invalid scope")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.user_client_access set scope = %s, granted_at = now(), granted_by = %s where user_id = %s and client_id = %s",
                (scope, actor.user_id, user_id, client_id),
            )
    return RedirectResponse(url=f"/clients/{client_id}/staff", status_code=303)
