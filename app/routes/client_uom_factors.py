"""Per-client admin UI for hub.client_uom_overrides (mig 055).

Phase 2 step 7: list / create / update / delete factor rows + CSV
import. Mounted at /clients/{client_id}/uom-factors. Edit gated by
can_edit_client_config (same as other client-scoped admin pages).
"""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import auth
from app.routes.clients import get_client, stats_for_client
from app.stores import client_uom_overrides as factors

router = APIRouter()


@router.get("/clients/{client_id}/uom-factors", response_class=HTMLResponse)
async def list_view(request: Request, client_id: str,
                     error: str | None = None,
                     saved: str | None = None):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "client not found")
    rows = factors.list_factors(client_id)
    summary = factors.stats(client_id)
    can_edit = auth.can_edit_client(user, client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/uom_factors.html",
        {"client": client, "stats": stats_for_client(client_id),
         "factors": rows, "summary": summary,
         "valid_sources": factors.VALID_SOURCES,
         "error": error, "saved": saved,
         "can_edit": can_edit,
         "active_root": "clients", "active_tab": "uom-factors"},
    )


@router.post("/clients/{client_id}/uom-factors/new")
async def create_view(
    request: Request, client_id: str,
    material_code: str = Form(""),
    from_uom: str = Form(...),
    to_uom: str = Form(...),
    factor: str = Form(...),
    source: str = Form("staff_form"),
    notes: str = Form(""),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "client not found")
    try:
        factors.create_factor(
            client_id=client_id,
            material_code=material_code or None,
            from_uom=from_uom, to_uom=to_uom,
            factor=factor, source=source,
            notes=notes or None,
        )
    except factors.FactorError as exc:
        return RedirectResponse(
            url=f"/clients/{client_id}/uom-factors?error={exc}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/clients/{client_id}/uom-factors?saved=created",
        status_code=303,
    )


@router.post("/clients/{client_id}/uom-factors/update")
async def update_view(
    request: Request, client_id: str,
    material_code: str = Form(""),
    from_uom: str = Form(...),
    to_uom: str = Form(...),
    factor: str = Form(...),
    source: str = Form("staff_form"),
    notes: str = Form(""),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "client not found")
    try:
        factors.update_factor(
            client_id=client_id,
            material_code=material_code or None,
            from_uom=from_uom, to_uom=to_uom,
            factor=factor, source=source,
            notes=notes or None,
        )
    except factors.FactorError as exc:
        return RedirectResponse(
            url=f"/clients/{client_id}/uom-factors?error={exc}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/clients/{client_id}/uom-factors?saved=updated",
        status_code=303,
    )


@router.post("/clients/{client_id}/uom-factors/delete")
async def delete_view(
    request: Request, client_id: str,
    material_code: str = Form(""),
    from_uom: str = Form(...),
    to_uom: str = Form(...),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "client not found")
    try:
        factors.delete_factor(
            client_id=client_id,
            material_code=material_code or None,
            from_uom=from_uom, to_uom=to_uom,
        )
    except factors.FactorError as exc:
        return RedirectResponse(
            url=f"/clients/{client_id}/uom-factors?error={exc}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/clients/{client_id}/uom-factors?saved=deleted",
        status_code=303,
    )


@router.post("/clients/{client_id}/uom-factors/import")
async def import_view(
    request: Request, client_id: str,
    upload: UploadFile = File(...),
    source: str = Form("imported"),
):
    """Import factors from CSV or XLSX (auto-detect by filename suffix)."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "client not found")
    raw = await upload.read()
    fname = (upload.filename or "").lower()
    try:
        if fname.endswith(".xlsx") or fname.endswith(".xlsm"):
            result = factors.import_xlsx(
                client_id=client_id, xlsx_bytes=raw, source=source,
            )
        elif fname.endswith(".csv") or upload.content_type == "text/csv":
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                return RedirectResponse(
                    url=f"/clients/{client_id}/uom-factors?error=CSV must be UTF-8",
                    status_code=303,
                )
            result = factors.import_csv(
                client_id=client_id, csv_text=text, source=source,
            )
        else:
            return RedirectResponse(
                url=(f"/clients/{client_id}/uom-factors?error="
                     f"Unsupported file type {fname!r}. Use .csv or .xlsx"),
                status_code=303,
            )
    except factors.FactorError as exc:
        return RedirectResponse(
            url=f"/clients/{client_id}/uom-factors?error={exc}",
            status_code=303,
        )
    msg = (f"import ok: {result['inserted']} inserted, "
           f"{result['failed']} failed")
    if result["errors"]:
        msg += " — " + " | ".join(result["errors"])
    return RedirectResponse(
        url=f"/clients/{client_id}/uom-factors?saved={msg}",
        status_code=303,
    )


# Backward-compat alias for the old endpoint URL.
@router.post("/clients/{client_id}/uom-factors/import-csv")
async def import_csv_alias(
    request: Request, client_id: str,
    upload: UploadFile = File(..., alias="csv_file"),
    source: str = Form("imported"),
):
    return await import_view(
        request=request, client_id=client_id,
        upload=upload, source=source,
    )


@router.get("/clients/{client_id}/uom-factors/template.xlsx")
async def download_template(request: Request, client_id: str):
    """Download the import template (XLSX) — pre-filled with header +
    sample rows + instructions sheet. Generated on-the-fly so always
    reflects current schema."""
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    payload = factors.render_template_xlsx()
    return Response(
        content=payload,
        media_type=("application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"),
        headers={
            "Content-Disposition":
                'attachment; filename="uom-factors-template.xlsx"',
        },
    )
