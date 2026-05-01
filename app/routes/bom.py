"""BOM routes — nested under /clients/{client_id}/. Plus public proposal POST API."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app import auth
from app.database import connect
from app.parsers.bom import parse_bom_workbook, BomParseError
from app.routes.clients import get_client, stats_for_client
from app.storage import save_upload, sha256_bytes
from app.stores.bom import (
    create_version,
    list_products_with_bom,
    list_versions_for_product,
    get_version_with_rows,
    submit_proposal,
)
from app.stores.uploads import record_upload

router = APIRouter()
BOM_PROFILES = ["manual_flat", "growatt_multi_workbook", "johnson_sap_exploded"]


@router.get("/clients/{client_id}/bom", response_class=HTMLResponse)
async def list_view(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    products = list_products_with_bom(client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/bom.html",
        {"client": client, "stats": stats_for_client(client_id),
         "products": products,
         "active_root": "clients", "active_tab": "bom"},
    )


@router.get("/clients/{client_id}/bom/upload", response_class=HTMLResponse)
async def upload_view(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/bom_upload.html",
        {"client": client, "stats": stats_for_client(client_id),
         "profiles": BOM_PROFILES,
         "active_root": "clients", "active_tab": "bom"},
    )


@router.post("/clients/{client_id}/bom/upload")
async def upload_submit(request: Request, client_id: str,
                        profile: str = Form("manual_flat"),
                        file: UploadFile = File(...)):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    if profile not in BOM_PROFILES:
        raise HTTPException(400, "Invalid profile")
    blob = await file.read()
    sha = sha256_bytes(blob)
    stored = save_upload(blob, filename=file.filename or "bom.xlsx",
                         module="bom", client_id=client_id)
    upload_id = record_upload(
        client_id=client_id, module="bom",
        original_filename=file.filename or "bom.xlsx",
        stored_path=stored.path, content_sha256=sha, size_bytes=len(blob),
        mime_type=file.content_type, uploader_user_id=user.user_id,
    )
    try:
        products = parse_bom_workbook(blob, profile=profile)
    except BomParseError as e:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s",
                    (str(e), upload_id))
        raise HTTPException(400, f"Parse error: {e}")
    n = 0
    for product_code, rows in products.items():
        version_id = create_version(
            client_id=client_id, product_code=product_code, rows=rows,
            actor="agency_staff", intent="asserted_technical",
            parent_version_id=None,
            context={"channel": "agency_upload", "profile": profile},
            source_upload_id=upload_id,
        )
        if version_id:
            n += 1
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.file_uploads set parse_status='done', row_count=%s, parsed_at=now() where upload_id=%s",
                (n, upload_id))
    return RedirectResponse(url=f"/clients/{client_id}/bom", status_code=303)


@router.get("/clients/{client_id}/bom/{product_code:path}/versions", response_class=HTMLResponse)
async def versions_view(request: Request, client_id: str, product_code: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    versions = list_versions_for_product(client_id=client_id, product_code=product_code)
    return request.app.state.templates.TemplateResponse(
        request, "clients/bom_versions.html",
        {"client": client, "stats": stats_for_client(client_id),
         "product_code": product_code, "versions": versions,
         "active_root": "clients", "active_tab": "bom"},
    )


@router.get("/clients/{client_id}/bom/version/{version_id}", response_class=HTMLResponse)
async def version_detail(request: Request, client_id: str, version_id: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    data = get_version_with_rows(version_id)
    if not data or data["version"]["client_id"] != client_id:
        raise HTTPException(404, "Version not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/bom_version_detail.html",
        {"client": client, "stats": stats_for_client(client_id),
         "version": data["version"], "rows": data["rows"],
         "active_root": "clients", "active_tab": "bom"},
    )


@router.post("/api/v1/hub/products/{product_code:path}/bom/proposals")
async def submit_bom_proposal(request: Request, product_code: str):
    auth.require_user(request)
    body = await request.json()
    client_id = body.get("client_id") or body.get("dncx_id")
    if not client_id or not get_client(client_id):
        raise HTTPException(404, "Client not found")
    actor = body.get("actor", "co_system")
    intent = body.get("intent", "modified_for_case")
    parent_version_id = body.get("parent_version_id")
    context = body.get("context", {})
    rows = body.get("rows", [])
    if not isinstance(rows, list) or not rows:
        raise HTTPException(400, "rows required")
    result = submit_proposal(
        client_id=client_id, product_code=product_code, actor=actor, intent=intent,
        parent_version_id=parent_version_id, context=context, rows=rows,
    )
    return JSONResponse(result)
