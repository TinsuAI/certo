"""BOM routes — list, detail, upload (technical), proposal queue."""
from __future__ import annotations

import json
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app import auth
from app.database import connect
from app.routes.dncxs import get_dncx, list_dncxs
from app.parsers.bom import parse_bom_workbook, BomParseError
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


@router.get("/bom", response_class=HTMLResponse)
async def list_view(request: Request, dncx_id: str | None = None):
    user = auth.require_user(request)
    dncxs = list_dncxs()
    if not dncxs:
        return request.app.state.templates.TemplateResponse(
        request,
        "bom/empty.html",
        { "active": "bom"},
        )
    dncx_id = dncx_id or dncxs[0]["dncx_id"]
    dncx = get_dncx(dncx_id)
    if not dncx:
        raise HTTPException(404, "DNCX not found")
    products = list_products_with_bom(dncx_id)
    return request.app.state.templates.TemplateResponse(
        request,
        "bom/list.html",
        {
            "dncxs": dncxs,
            "dncx": dncx,
            "products": products,
            "active": "bom",
        },
    )


@router.get("/bom/upload", response_class=HTMLResponse)
async def upload_view(request: Request, dncx_id: str | None = None):
    user = auth.require_user(request)
    dncxs = list_dncxs()
    if not dncxs:
        return request.app.state.templates.TemplateResponse(
        request,
        "bom/empty.html",
        { "active": "bom"},
        )
    dncx_id = dncx_id or dncxs[0]["dncx_id"]
    return request.app.state.templates.TemplateResponse(
        request,
        "bom/upload.html",
        {
            "dncxs": dncxs,
            "dncx_id": dncx_id,
            "profiles": BOM_PROFILES,
            "active": "bom",
        },
    )


@router.post("/bom/upload")
async def upload_submit(
    request: Request,
    dncx_id: str = Form(...),
    profile: str = Form("manual_flat"),
    file: UploadFile = File(...),
):
    user = auth.require_user(request)
    dncx = get_dncx(dncx_id)
    if not dncx:
        raise HTTPException(404, "DNCX not found")
    if profile not in BOM_PROFILES:
        raise HTTPException(400, "Invalid profile")
    blob = await file.read()
    sha = sha256_bytes(blob)
    stored = save_upload(blob, filename=file.filename or "bom.xlsx", module="bom", dncx_id=dncx_id)
    upload_id = record_upload(
        dncx_id=dncx_id, module="bom",
        original_filename=file.filename or "bom.xlsx",
        stored_path=stored.path, content_sha256=sha, size_bytes=len(blob),
        mime_type=file.content_type, uploader_user_id=user.user_id,
    )
    try:
        products = parse_bom_workbook(blob, profile=profile)
    except BomParseError as e:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s", (str(e), upload_id))
        raise HTTPException(400, f"Parse error: {e}")
    n_created = 0
    for product_code, rows in products.items():
        version_id = create_version(
            dncx_id=dncx_id, product_code=product_code, rows=rows,
            actor="agency_staff", intent="asserted_technical",
            parent_version_id=None,
            context={"channel": "agency_upload", "profile": profile},
            source_upload_id=upload_id,
        )
        if version_id:
            n_created += 1
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.file_uploads set parse_status='done', row_count=%s, parsed_at=now() where upload_id=%s",
                (n_created, upload_id),
            )
    return RedirectResponse(url=f"/bom?dncx_id={dncx_id}", status_code=303)


@router.get("/bom/{product_code:path}/versions", response_class=HTMLResponse)
async def versions_view(request: Request, product_code: str, dncx_id: str):
    user = auth.require_user(request)
    dncx = get_dncx(dncx_id)
    if not dncx:
        raise HTTPException(404, "DNCX not found")
    versions = list_versions_for_product(dncx_id=dncx_id, product_code=product_code)
    return request.app.state.templates.TemplateResponse(
        request,
        "bom/versions.html",
        {
            "dncx": dncx,
            "product_code": product_code,
            "versions": versions,
            "active": "bom",
        },
    )


@router.get("/bom/version/{version_id}", response_class=HTMLResponse)
async def version_detail(request: Request, version_id: str):
    user = auth.require_user(request)
    data = get_version_with_rows(version_id)
    if not data:
        raise HTTPException(404, "Version not found")
    return request.app.state.templates.TemplateResponse(
        request,
        "bom/version_detail.html",
        { "version": data["version"], "rows": data["rows"], "active": "bom"},
    )


# ---- Proposal queue API ----

@router.post("/api/v1/hub/products/{product_code:path}/bom/proposals")
async def submit_bom_proposal(
    request: Request,
    product_code: str,
):
    user = auth.require_user(request)
    body = await request.json()
    dncx_id = body.get("dncx_id")
    if not dncx_id or not get_dncx(dncx_id):
        raise HTTPException(404, "DNCX not found")
    actor = body.get("actor", "co_system")
    intent = body.get("intent", "modified_for_case")
    parent_version_id = body.get("parent_version_id")
    context = body.get("context", {})
    rows = body.get("rows", [])
    if not isinstance(rows, list) or not rows:
        raise HTTPException(400, "rows required")
    result = submit_proposal(
        dncx_id=dncx_id, product_code=product_code, actor=actor, intent=intent,
        parent_version_id=parent_version_id, context=context, rows=rows,
    )
    return JSONResponse(result)
