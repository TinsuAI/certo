"""Client (DNCX) management + workspace overview."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect

router = APIRouter()

CODE_RESOLUTION_MODES = ["identity", "simple_mapping", "batch_aggregate_resolution"]
BOM_PROPOSAL_MODES = ["auto"]


def list_clients() -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select c.client_id, c.name, c.tax_code, c.code_resolution_mode,
                       c.bom_proposal_mode, c.bom_proposal_qty_tolerance_pct,
                       c.status, c.notes, c.created_at,
                       (select count(*) from hub.materials m where m.client_id = c.client_id) as n_materials,
                       (select count(*) from hub.code_mappings cm where cm.client_id = c.client_id) as n_mappings,
                       (select count(*) from hub.bcct_rows b where b.client_id = c.client_id) as n_bcct,
                       (select count(*) from hub.bom_versions bv where bv.client_id = c.client_id and bv.tombstoned_at is null) as n_bom
                from hub.clients c
                order by c.created_at desc
                """
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_client(client_id: str) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select client_id, name, tax_code, code_resolution_mode, bom_proposal_mode,
                       bom_proposal_qty_tolerance_pct, status, notes, created_at, updated_at
                from hub.clients where client_id = %s
                """,
                (client_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


def stats_for_client(client_id: str) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from hub.materials where client_id = %s", (client_id,))
            (n_materials,) = cur.fetchone()
            cur.execute("select count(*) from hub.code_mappings where client_id = %s", (client_id,))
            (n_mappings,) = cur.fetchone()
            cur.execute("select count(*) from hub.bcct_rows where client_id = %s", (client_id,))
            (n_bcct,) = cur.fetchone()
            cur.execute(
                "select count(*) from hub.bom_versions where client_id = %s and tombstoned_at is null",
                (client_id,),
            )
            (n_bom,) = cur.fetchone()
            cur.execute(
                "select count(*) from hub.bom_change_requests where client_id = %s",
                (client_id,),
            )
            (n_proposals,) = cur.fetchone()
    return {"materials": n_materials, "mappings": n_mappings,
            "bcct": n_bcct, "bom": n_bom, "proposals": n_proposals}


def upsert_client(*, client_id: str, name: str, tax_code: str | None,
                  code_resolution_mode: str, bom_proposal_mode: str,
                  bom_proposal_qty_tolerance_pct: float, status: str,
                  notes: str | None) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.clients
                  (client_id, name, tax_code, code_resolution_mode, bom_proposal_mode,
                   bom_proposal_qty_tolerance_pct, status, notes)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (client_id) do update set
                  name = excluded.name,
                  tax_code = excluded.tax_code,
                  code_resolution_mode = excluded.code_resolution_mode,
                  bom_proposal_mode = excluded.bom_proposal_mode,
                  bom_proposal_qty_tolerance_pct = excluded.bom_proposal_qty_tolerance_pct,
                  status = excluded.status,
                  notes = excluded.notes,
                  updated_at = now()
                """,
                (client_id, name, tax_code, code_resolution_mode, bom_proposal_mode,
                 bom_proposal_qty_tolerance_pct, status, notes),
            )


def slug(name: str) -> str:
    base = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    base = "-".join(filter(None, base.split("-")))
    suffix = secrets.token_hex(2)
    return f"{base[:24]}-{suffix}" if base else f"client-{suffix}"


@router.get("/clients", response_class=HTMLResponse)
async def list_view(request: Request):
    auth.require_user(request)
    items = list_clients()
    return request.app.state.templates.TemplateResponse(
        request, "clients/list.html",
        {"items": items, "active_root": "clients"},
    )


@router.get("/clients/new", response_class=HTMLResponse)
async def new_view(request: Request):
    auth.require_user(request)
    return request.app.state.templates.TemplateResponse(
        request, "clients/edit.html",
        {"client": None, "modes": CODE_RESOLUTION_MODES, "bom_modes": BOM_PROPOSAL_MODES,
         "active_root": "clients"},
    )


@router.post("/clients/new")
async def new_submit(
    request: Request,
    name: str = Form(...), tax_code: str = Form(""),
    code_resolution_mode: str = Form("simple_mapping"),
    bom_proposal_mode: str = Form("auto"),
    bom_proposal_qty_tolerance_pct: float = Form(5.0),
    notes: str = Form(""),
):
    auth.require_user(request)
    if code_resolution_mode not in CODE_RESOLUTION_MODES:
        raise HTTPException(400, "Invalid code_resolution_mode")
    client_id = slug(name)
    upsert_client(
        client_id=client_id, name=name.strip(), tax_code=tax_code.strip() or None,
        code_resolution_mode=code_resolution_mode, bom_proposal_mode=bom_proposal_mode,
        bom_proposal_qty_tolerance_pct=bom_proposal_qty_tolerance_pct,
        status="active", notes=notes.strip() or None,
    )
    return RedirectResponse(url=f"/clients/{client_id}", status_code=303)


@router.get("/clients/{client_id}", response_class=HTMLResponse)
async def workspace_view(request: Request, client_id: str):
    auth.require_user(request)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    stats = stats_for_client(client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/workspace.html",
        {"client": client, "stats": stats,
         "active_root": "clients", "active_tab": "overview"},
    )


@router.get("/clients/{client_id}/edit", response_class=HTMLResponse)
async def edit_view(request: Request, client_id: str):
    auth.require_user(request)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    stats = stats_for_client(client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/edit.html",
        {"client": client, "stats": stats,
         "modes": CODE_RESOLUTION_MODES, "bom_modes": BOM_PROPOSAL_MODES,
         "active_root": "clients", "active_tab": "config"},
    )


@router.post("/clients/{client_id}/edit")
async def edit_submit(
    request: Request, client_id: str,
    name: str = Form(...), tax_code: str = Form(""),
    bom_proposal_mode: str = Form("auto"),
    bom_proposal_qty_tolerance_pct: float = Form(5.0),
    notes: str = Form(""), status: str = Form("active"),
):
    auth.require_user(request)
    existing = get_client(client_id)
    if not existing:
        raise HTTPException(404, "Client not found")
    upsert_client(
        client_id=client_id, name=name.strip(), tax_code=tax_code.strip() or None,
        code_resolution_mode=existing["code_resolution_mode"],
        bom_proposal_mode=bom_proposal_mode,
        bom_proposal_qty_tolerance_pct=bom_proposal_qty_tolerance_pct,
        status=status, notes=notes.strip() or None,
    )
    return RedirectResponse(url=f"/clients/{client_id}", status_code=303)
