"""DNCX directory routes."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect

router = APIRouter()

CODE_RESOLUTION_MODES = ["identity", "simple_mapping", "batch_aggregate_resolution"]
BOM_PROPOSAL_MODES = ["auto"]  # manual + hybrid deferred to phase 2


def list_dncxs() -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select dncx_id, name, tax_code, code_resolution_mode, bom_proposal_mode,
                       bom_proposal_qty_tolerance_pct, status, notes, created_at
                from hub.dncxs
                order by created_at desc
                """
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_dncx(dncx_id: str) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select dncx_id, name, tax_code, code_resolution_mode, bom_proposal_mode,
                       bom_proposal_qty_tolerance_pct, status, notes, created_at, updated_at
                from hub.dncxs where dncx_id = %s
                """,
                (dncx_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


def upsert_dncx(*, dncx_id: str, name: str, tax_code: str | None,
                code_resolution_mode: str, bom_proposal_mode: str,
                bom_proposal_qty_tolerance_pct: float, status: str, notes: str | None) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.dncxs
                  (dncx_id, name, tax_code, code_resolution_mode, bom_proposal_mode,
                   bom_proposal_qty_tolerance_pct, status, notes)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (dncx_id) do update set
                  name = excluded.name,
                  tax_code = excluded.tax_code,
                  code_resolution_mode = excluded.code_resolution_mode,
                  bom_proposal_mode = excluded.bom_proposal_mode,
                  bom_proposal_qty_tolerance_pct = excluded.bom_proposal_qty_tolerance_pct,
                  status = excluded.status,
                  notes = excluded.notes,
                  updated_at = now()
                """,
                (dncx_id, name, tax_code, code_resolution_mode, bom_proposal_mode,
                 bom_proposal_qty_tolerance_pct, status, notes),
            )


def _slug(name: str) -> str:
    base = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    base = "-".join(filter(None, base.split("-")))
    suffix = secrets.token_hex(2)
    return f"{base[:24]}-{suffix}" if base else f"dncx-{suffix}"


@router.get("/dncxs", response_class=HTMLResponse)
async def list_view(request: Request):
    user = auth.require_user(request)
    items = list_dncxs()
    return request.app.state.templates.TemplateResponse(
        request,
        "dncxs/list.html",
        { "items": items, "active": "dncxs"},
    )


@router.get("/dncxs/new", response_class=HTMLResponse)
async def new_view(request: Request):
    user = auth.require_user(request)
    return request.app.state.templates.TemplateResponse(
        request,
        "dncxs/edit.html",
        {
            "dncx": None,
            "modes": CODE_RESOLUTION_MODES,
            "bom_modes": BOM_PROPOSAL_MODES,
            "active": "dncxs",
        },
    )


@router.post("/dncxs/new")
async def new_submit(
    request: Request,
    name: str = Form(...),
    tax_code: str = Form(""),
    code_resolution_mode: str = Form("simple_mapping"),
    bom_proposal_mode: str = Form("auto"),
    bom_proposal_qty_tolerance_pct: float = Form(5.0),
    notes: str = Form(""),
):
    user = auth.require_user(request)
    if code_resolution_mode not in CODE_RESOLUTION_MODES:
        raise HTTPException(400, "Invalid code_resolution_mode")
    dncx_id = _slug(name)
    upsert_dncx(
        dncx_id=dncx_id, name=name.strip(), tax_code=tax_code.strip() or None,
        code_resolution_mode=code_resolution_mode, bom_proposal_mode=bom_proposal_mode,
        bom_proposal_qty_tolerance_pct=bom_proposal_qty_tolerance_pct,
        status="active", notes=notes.strip() or None,
    )
    return RedirectResponse(url=f"/dncxs/{dncx_id}", status_code=303)


@router.get("/dncxs/{dncx_id}", response_class=HTMLResponse)
async def detail_view(request: Request, dncx_id: str):
    user = auth.require_user(request)
    dncx = get_dncx(dncx_id)
    if not dncx:
        raise HTTPException(404, "DNCX not found")
    # quick stats per module
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from hub.materials where dncx_id = %s", (dncx_id,))
            (n_materials,) = cur.fetchone()
            cur.execute("select count(*) from hub.code_mappings where dncx_id = %s", (dncx_id,))
            (n_mappings,) = cur.fetchone()
            cur.execute("select count(*) from hub.bcct_rows where dncx_id = %s", (dncx_id,))
            (n_bcct,) = cur.fetchone()
            cur.execute("select count(*) from hub.bom_versions where dncx_id = %s and tombstoned_at is null", (dncx_id,))
            (n_bom,) = cur.fetchone()
    return request.app.state.templates.TemplateResponse(
        request,
        "dncxs/detail.html",
        {
            "dncx": dncx,
            "stats": {
                "materials": n_materials,
                "mappings": n_mappings,
                "bcct": n_bcct,
                "bom": n_bom,
            },
            "active": "dncxs",
        },
    )


@router.get("/dncxs/{dncx_id}/edit", response_class=HTMLResponse)
async def edit_view(request: Request, dncx_id: str):
    user = auth.require_user(request)
    dncx = get_dncx(dncx_id)
    if not dncx:
        raise HTTPException(404, "DNCX not found")
    return request.app.state.templates.TemplateResponse(
        request,
        "dncxs/edit.html",
        {
            "dncx": dncx,
            "modes": CODE_RESOLUTION_MODES,
            "bom_modes": BOM_PROPOSAL_MODES,
            "active": "dncxs",
        },
    )


@router.post("/dncxs/{dncx_id}/edit")
async def edit_submit(
    request: Request,
    dncx_id: str,
    name: str = Form(...),
    tax_code: str = Form(""),
    code_resolution_mode: str = Form("simple_mapping"),
    bom_proposal_mode: str = Form("auto"),
    bom_proposal_qty_tolerance_pct: float = Form(5.0),
    notes: str = Form(""),
    status: str = Form("active"),
):
    user = auth.require_user(request)
    existing = get_dncx(dncx_id)
    if not existing:
        raise HTTPException(404, "DNCX not found")
    # code_resolution_mode is immutable per onboarding lock — ignore changes
    upsert_dncx(
        dncx_id=dncx_id, name=name.strip(), tax_code=tax_code.strip() or None,
        code_resolution_mode=existing["code_resolution_mode"],
        bom_proposal_mode=bom_proposal_mode,
        bom_proposal_qty_tolerance_pct=bom_proposal_qty_tolerance_pct,
        status=status, notes=notes.strip() or None,
    )
    return RedirectResponse(url=f"/dncxs/{dncx_id}", status_code=303)
