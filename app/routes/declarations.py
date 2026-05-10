"""Customs declaration file management — Feature 6 (TKX/TKN).

Web pages: declarations index per client, per-declaration detail with
file list + upload. JSON API for sister-app C/O lookup.

See `.ai/features/2026-05-10-johnson-onboarding/brief.md` Feature 6.
"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    HTMLResponse, JSONResponse, RedirectResponse, Response,
)

from app import auth
from app.parsers.declaration_files import (
    DeclarationFileError, parse_declaration_file,
)
from app.routes._paging import pagination_context, parse_page_params
from app.routes.clients import get_client, stats_for_client
from app.storage import get_backend, save_upload, sha256_bytes
from app.stores.customs_declaration_files import (
    count_declarations_with_status,
    delete_declaration_file,
    get_declaration_file,
    insert_declaration_file,
    list_declarations_with_status,
    list_files_for_declaration,
)


router = APIRouter()


# ── Web pages ───────────────────────────────────────────────────────


@router.get("/clients/{client_id}/declarations", response_class=HTMLResponse)
async def declarations_index(
    request: Request, client_id: str,
    direction: str | None = None,
    has_files: str | None = None,
    q: str | None = None,
):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    if direction and direction not in ("import", "export"):
        direction = None
    has_files_filter: bool | None = None
    if has_files == "yes":
        has_files_filter = True
    elif has_files == "no":
        has_files_filter = False

    page_params = parse_page_params(query_params=request.query_params)
    summaries = list_declarations_with_status(
        client_id, direction=direction, has_files=has_files_filter,
        search=q, limit=page_params.page_size, offset=page_params.offset,
    )
    total = count_declarations_with_status(
        client_id, direction=direction, has_files=has_files_filter,
        search=q,
    )
    paging_ctx = pagination_context(
        request=request, page_params=page_params, total=total,
    )
    return request.app.state.templates.TemplateResponse(
        request, "clients/declarations.html",
        {
            "client": client,
            "stats": stats_for_client(client_id),
            "summaries": summaries,
            "direction": direction,
            "has_files": has_files,
            "q": q or "",
            "paging": paging_ctx,
            "active_root": "clients",
            "active_tab": "declarations",
        },
    )


@router.get(
    "/clients/{client_id}/declarations/upload",
    response_class=HTMLResponse,
)
async def declarations_upload_view(
    request: Request, client_id: str,
    error: str | None = None,
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/declaration_upload.html",
        {
            "client": client,
            "stats": stats_for_client(client_id),
            "error": error,
            "active_root": "clients",
            "active_tab": "declarations",
        },
    )


@router.get(
    "/clients/{client_id}/declarations/{declaration_no}",
    response_class=HTMLResponse,
)
async def declaration_detail(
    request: Request, client_id: str, declaration_no: str,
    uploaded: int | None = None, deduped: int | None = None,
    error: str | None = None,
):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    files = list_files_for_declaration(client_id, declaration_no)
    return request.app.state.templates.TemplateResponse(
        request, "clients/declaration_detail.html",
        {
            "client": client,
            "stats": stats_for_client(client_id),
            "declaration_no": declaration_no,
            "files": files,
            "uploaded": uploaded,
            "deduped": deduped,
            "error": error,
            "active_root": "clients",
            "active_tab": "declarations",
        },
    )


@router.post("/clients/{client_id}/declarations/upload")
async def upload_declaration_file(
    request: Request, client_id: str,
    file: UploadFile = File(...),
    direction: str = Form(...),
    declaration_no: str | None = Form(None),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    if direction not in ("import", "export"):
        raise HTTPException(400, "direction must be 'import' or 'export'")

    blob = await file.read()
    filename = file.filename or "declaration.xls"

    # Determine file_kind + final_decl_no.
    # 3 cases:
    # (a) user provided declaration_no   → trust it; skip content cross-validate
    # (b) no declaration_no, filename ok → auto-detect with content validate
    # (c) no declaration_no, filename bad → reject back to upload page
    file_kind: str | None = None
    info = None
    if declaration_no:
        # Manual override path. Filename is informational at best.
        try:
            info = parse_declaration_file(
                filename, blob, validate_content=False,
            )
            file_kind = info.file_kind
        except DeclarationFileError:
            # Filename doesn't follow `<prefix>_<digits>.<ext>` — derive
            # file_kind from extension only.
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext in ("xls", "xlsx"):
                file_kind = "xls"
            elif ext == "pdf":
                file_kind = "pdf"
            else:
                file_kind = "other"
        final_decl_no = declaration_no
    else:
        try:
            info = parse_declaration_file(filename, blob)
        except DeclarationFileError as exc:
            return RedirectResponse(
                url=(f"/clients/{client_id}/declarations/upload"
                     f"?error={_q(str(exc))}"),
                status_code=303,
            )
        file_kind = info.file_kind
        final_decl_no = info.declaration_no

    sha = sha256_bytes(blob)
    stored = save_upload(
        blob, filename=filename,
        module="customs_declarations", client_id=client_id,
    )
    fid, created = insert_declaration_file(
        client_id=client_id,
        declaration_no=final_decl_no,
        direction=direction,
        file_kind=file_kind,
        backend_key=stored.path,
        original_filename=filename,
        sha256=sha, size_bytes=stored.size_bytes,
        uploaded_by=user.user_id,
    )
    suffix = "uploaded=1" if created else "deduped=1"
    return RedirectResponse(
        url=(f"/clients/{client_id}/declarations/{final_decl_no}?{suffix}"),
        status_code=303,
    )


@router.get(
    "/clients/{client_id}/declarations/files/{file_id}/download",
)
async def download_declaration_file(
    request: Request, client_id: str, file_id: int,
):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    f = get_declaration_file(file_id)
    if not f or f.client_id != client_id:
        raise HTTPException(404, "File not found")
    blob = get_backend().get(f.backend_key)
    media = "application/pdf" if f.file_kind == "pdf" else (
        "application/vnd.ms-excel"
    )
    return Response(
        content=blob, media_type=media,
        headers={
            "content-disposition": (
                f'attachment; filename="{f.original_filename}"'
            ),
        },
    )


@router.post("/clients/{client_id}/declarations/files/{file_id}/delete")
async def delete_declaration_file_route(
    request: Request, client_id: str, file_id: int,
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    f = get_declaration_file(file_id)
    if not f or f.client_id != client_id:
        raise HTTPException(404, "File not found")
    decl_no = f.declaration_no
    delete_declaration_file(file_id)
    # Note: backend blob retained (may be referenced by other clients in
    # future multi-tenant scenarios; cleanup is a separate sweep job).
    return RedirectResponse(
        url=f"/clients/{client_id}/declarations/{decl_no}?deleted=1",
        status_code=303,
    )


# ── JSON API (for sister-apps) ──────────────────────────────────────


@router.get("/api/v1/clients/{client_id}/declarations")
async def api_list_declarations(
    request: Request, client_id: str,
    direction: str | None = None,
    has_files: str | None = None,
    q: str | None = None,
    limit: int = 200, offset: int = 0,
):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    if direction and direction not in ("import", "export"):
        raise HTTPException(400, "direction must be 'import' or 'export'")
    has_files_filter: bool | None = None
    if has_files == "yes":
        has_files_filter = True
    elif has_files == "no":
        has_files_filter = False
    summaries = list_declarations_with_status(
        client_id, direction=direction, has_files=has_files_filter,
        search=q, limit=min(limit, 500), offset=max(0, offset),
    )
    return {
        "client_id": client_id,
        "count": len(summaries),
        "items": [
            {
                "declaration_no": s.declaration_no,
                "direction": s.direction,
                "bcct_line_count": s.bcct_line_count,
                "file_count": s.file_count,
                "earliest_bcct_date": (
                    s.earliest_bcct_date.isoformat()
                    if s.earliest_bcct_date else None
                ),
            }
            for s in summaries
        ],
    }


@router.get(
    "/api/v1/clients/{client_id}/declarations/{declaration_no}/files",
)
async def api_list_files(
    request: Request, client_id: str, declaration_no: str,
    direction: str | None = None,
):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    if direction and direction not in ("import", "export"):
        raise HTTPException(400, "direction must be 'import' or 'export'")
    files = list_files_for_declaration(
        client_id, declaration_no, direction=direction,
    )
    return {
        "client_id": client_id,
        "declaration_no": declaration_no,
        "count": len(files),
        "items": [
            {
                "id": f.id,
                "direction": f.direction,
                "file_kind": f.file_kind,
                "original_filename": f.original_filename,
                "declaration_date": (
                    f.declaration_date.isoformat()
                    if f.declaration_date else None
                ),
                "sha256": f.sha256,
                "size_bytes": f.size_bytes,
                "uploaded_at": f.uploaded_at.isoformat(),
                "download_url": (
                    f"/clients/{client_id}/declarations/files/{f.id}/download"
                ),
            }
            for f in files
        ],
    }


def _q(s: str) -> str:
    """Minimal URL-quote for redirect query strings."""
    from urllib.parse import quote
    return quote(s, safe="")
