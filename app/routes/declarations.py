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
    list_files_for_declarations,
)
from app.uploads.declaration_zip import (
    ZipUploadError,
    annotate_dedup_status,
    cancel_staging,
    commit_staged_files,
    extract_to_staging,
    get_staging_path,
    parse_staged_files,
    reap_expired_staging,
)


router = APIRouter()


# ── Web pages ───────────────────────────────────────────────────────


@router.get("/clients/{client_id}/declarations", response_class=HTMLResponse)
async def declarations_index(
    request: Request, client_id: str,
    direction: str | None = None,
    has_files: str | None = None,
    q: str | None = None,
    bulk_inserted: int | None = None,
    bulk_deduped: int | None = None,
    bulk_mismatch: int | None = None,
    bulk_parse_err: int | None = None,
    bulk_store_err: int | None = None,
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
    bulk_toast = None
    if bulk_inserted is not None or bulk_deduped is not None:
        bulk_toast = {
            "inserted": bulk_inserted or 0,
            "deduped": bulk_deduped or 0,
            "mismatch": bulk_mismatch or 0,
            "parse_err": bulk_parse_err or 0,
            "store_err": bulk_store_err or 0,
        }
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
            "bulk_toast": bulk_toast,
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


@router.get("/clients/{client_id}/declarations/download.zip")
async def download_declarations_zip(
    request: Request, client_id: str,
    direction: str | None = None,
    declaration_nos: str | None = None,
    filename: str | None = None,
):
    """Bulk download every uploaded customs file for the requested
    (client_id, direction, declaration_no IN nos) tuple as a single ZIP.

    Cookie-session route for operator use: unauthenticated callers are
    redirected to `/login?next=<this URL>` so the download resumes
    after sign-in. The Bearer-aware list summary lives at
    `/v1/hub/clients/{cid}/declarations`; this download intentionally
    stays cookie-only because it returns file content rather than
    metadata, and CO drives it via the operator's browser (the operator
    is the one logged into Data Hub).

    Route registration order matters: this must come BEFORE the
    `/{declaration_no}` detail route or FastAPI's first-match wins
    rule swallows `download.zip` as a declaration_no.

    Archive layout:
      - All declaration files at the root (no per-declaration subfolders)
        — operator drops them straight into a dossier folder. Filename
        collisions are de-duplicated by suffixing `_1`, `_2`, …
      - `DANH_SACH_TO_KHAI.txt` lists every requested declaration with
        its status (có/thiếu), file count, and included filenames.
      - When zero files match, the archive still contains the manifest
        plus a `NO_FILES_FOUND.txt` marker so the operator gets a
        well-formed ZIP rather than an HTTP error.

    Contract spec:
    `barry-CO-main/.ai/api-requests/2026-05-15-declaration-file-status.md`.
    """
    # Auth: cookie session, with /login?next= bounce when missing.
    user = auth.current_user(request)
    if user is None:
        query = str(request.url.query)
        target = str(request.url.path) + (f"?{query}" if query else "")
        return RedirectResponse(
            url=f"/login?next={_q(target)}", status_code=303,
        )
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    if direction not in ("import", "export"):
        raise HTTPException(400, "direction must be 'import' or 'export'")
    decl_nos = _parse_zip_declaration_nos(declaration_nos)
    if not decl_nos:
        raise HTTPException(400, "declaration_nos is required")
    archive_filename = _safe_archive_filename(
        filename, fallback="declarations.zip",
    )

    files = list_files_for_declarations(
        client_id, decl_nos, direction=direction,
    )
    files_by_decl: dict[str, list] = {d: [] for d in decl_nos}
    for f in files:
        files_by_decl.setdefault(f.declaration_no, []).append(f)

    backend = get_backend()
    zip_bytes = _build_declarations_zip(
        client=client, direction=direction, requested=decl_nos,
        files_by_decl=files_by_decl, backend=backend,
    )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "content-disposition": (
                f'attachment; filename="{archive_filename}"'
            ),
            "content-length": str(len(zip_bytes)),
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


@router.post("/clients/{client_id}/declarations/upload-zip")
async def upload_declaration_zip_preview(
    request: Request, client_id: str,
    file: UploadFile = File(...),
    direction: str = Form(...),
):
    """Step 1 of bulk upload: accept ZIP, extract supported per-decl
    XLS/PDF members into a staging dir, parse + dedup-check, render
    preview. The actual commit happens via `…/upload-zip/<id>/commit`.
    """
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    if direction not in ("import", "export"):
        raise HTTPException(400, "direction must be 'import' or 'export'")

    blob = await file.read()
    # Reap before staging anything new so abandoned previews from earlier
    # sessions don't accumulate. Cheap; no cron needed.
    reap_expired_staging()
    try:
        extract = extract_to_staging(blob)
    except ZipUploadError as exc:
        return RedirectResponse(
            url=(f"/clients/{client_id}/declarations/upload"
                 f"?error={_q(str(exc))}"
                 f"#bulk"),
            status_code=303,
        )

    staged = parse_staged_files(extract.staging_path)
    staged = annotate_dedup_status(
        staged, client_id=client_id, direction=direction,
    )
    counts = {"ok": 0, "duplicate": 0, "mismatch": 0, "parse_error": 0}
    for f in staged:
        counts[f.status] = counts.get(f.status, 0) + 1
    non_ok = [f for f in staged if f.status in ("mismatch", "parse_error")]
    can_commit = (counts["ok"] + counts["duplicate"]) > 0

    return request.app.state.templates.TemplateResponse(
        request, "clients/declaration_zip_preview.html",
        {
            "client": client,
            "stats": stats_for_client(client_id),
            "staging_id": extract.staging_id,
            "direction": direction,
            "total_in_zip": extract.total_in_zip,
            "ignored_non_pattern": extract.ignored_non_pattern,
            "counts": counts,
            "non_ok_files": non_ok,
            "can_commit": can_commit,
            "active_root": "clients",
            "active_tab": "declarations",
        },
    )


@router.post(
    "/clients/{client_id}/declarations/upload-zip/{staging_id}/commit",
)
async def upload_declaration_zip_commit(
    request: Request, client_id: str, staging_id: str,
    direction: str = Form(...),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    if direction not in ("import", "export"):
        raise HTTPException(400, "direction must be 'import' or 'export'")

    staging_path = get_staging_path(staging_id)
    if staging_path is None:
        return RedirectResponse(
            url=(f"/clients/{client_id}/declarations/upload"
                 f"?error={_q('Phiên staging đã hết hạn hoặc không tồn tại. Tải lại ZIP.')}"
                 f"#bulk"),
            status_code=303,
        )

    result = commit_staged_files(
        staging_path,
        client_id=client_id, direction=direction,
        uploaded_by=user.user_id,
    )
    cancel_staging(staging_id)  # always clean up after commit
    query = (
        f"bulk_inserted={result.inserted}"
        f"&bulk_deduped={result.deduped}"
        f"&bulk_mismatch={result.mismatch_skipped}"
        f"&bulk_parse_err={result.parse_error_skipped}"
        f"&bulk_store_err={result.store_errors}"
    )
    return RedirectResponse(
        url=f"/clients/{client_id}/declarations?{query}",
        status_code=303,
    )


@router.post(
    "/clients/{client_id}/declarations/upload-zip/{staging_id}/cancel",
)
async def upload_declaration_zip_cancel(
    request: Request, client_id: str, staging_id: str,
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    cancel_staging(staging_id)
    return RedirectResponse(
        url=f"/clients/{client_id}/declarations/upload#bulk",
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


# ── ZIP download helpers ───────────────────────────────────────────


def _parse_zip_declaration_nos(value: str | None) -> list[str]:
    """Split comma-separated declaration numbers, dedupe, preserve
    order + case. Returns empty list for empty input — caller raises
    400 because the ZIP route makes declaration_nos required."""
    if value is None or not value.strip():
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in value.split(","):
        token = raw.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _safe_archive_filename(value: str | None, *, fallback: str) -> str:
    """Sanitize an operator-supplied archive filename. Caller already
    confirms the user is logged in; we still strip path separators +
    control chars so a malicious referrer can't shape the Content-
    Disposition header. Reserved chars `"`, `\\` are dropped because
    they'd break the quoted form. `..` patterns are refused even after
    sanitization (path-traversal hardening for clients that may treat
    the suggested filename as a save path)."""
    name = (value or "").strip()
    if not name:
        return fallback
    cleaned = "".join(
        c for c in name
        if c.isalnum() or c in "._- ()[]"
    ).strip(" .")
    if not cleaned or ".." in cleaned:
        return fallback
    if not cleaned.lower().endswith(".zip"):
        cleaned += ".zip"
    # Cap length so the header stays sane on legacy clients.
    return cleaned[:120]


def _safe_member_name(value: str) -> str:
    """Sanitize a ZIP member name. Disallow path separators + control
    chars so the archive cannot zip-slip. Empty → fallback."""
    cleaned = "".join(
        c for c in (value or "")
        if c not in "/\\\0" and c >= " "
    ).strip()
    return cleaned or "unnamed_file"


def _unique_member_name(name: str, taken: set[str]) -> str:
    """Suffix `_1`, `_2`, … on collisions, preserving the extension."""
    if name not in taken:
        taken.add(name)
        return name
    if "." in name:
        stem, ext = name.rsplit(".", 1)
        ext = "." + ext
    else:
        stem, ext = name, ""
    n = 1
    while True:
        candidate = f"{stem}_{n}{ext}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
        n += 1


def _build_manifest_text(
    *, client: dict, direction: str, requested: list[str],
    files_by_decl: dict[str, list], member_by_file_id: dict[int, str],
    unresolved_file_ids: set[int] | None = None,
) -> str:
    """Plain-text Vietnamese manifest listing requested declarations,
    grouped by status (đã có / thiếu). One line per file under each
    declaration with the in-archive filename so operator can spot
    duplicates after the dedupe pass.

    `unresolved_file_ids` are files registered in metadata whose blob is
    absent from storage — they can't be embedded, so each is annotated
    `[THIẾU NỘI DUNG]` and counted on a dedicated line (only rendered
    when non-empty, to keep the healthy-case manifest stable)."""
    unresolved_file_ids = unresolved_file_ids or set()
    present: list[str] = []
    missing: list[str] = []
    for decl in requested:
        if files_by_decl.get(decl):
            present.append(decl)
        else:
            missing.append(decl)
    lines: list[str] = []
    lines.append("DANH SÁCH TỜ KHAI")
    lines.append(f"Client: {client.get('name', '')} ({client.get('client_id', '')})")
    lines.append(
        f"Chiều: {'Nhập khẩu (import)' if direction == 'import' else 'Xuất khẩu (export)'}"
    )
    lines.append(f"Tổng tờ khai yêu cầu: {len(requested)}")
    lines.append(f"Đã có file: {len(present)}")
    lines.append(f"Thiếu file: {len(missing)}")
    if unresolved_file_ids:
        lines.append(
            f"File thiếu nội dung trên máy chủ: {len(unresolved_file_ids)}"
        )
    lines.append("")
    lines.append("== Tờ khai đã có file ==")
    if present:
        for decl in present:
            entries = files_by_decl[decl]
            lines.append(f"- {decl}: {len(entries)} file(s)")
            for f in entries:
                member = member_by_file_id.get(f.id, f.original_filename)
                suffix = "  [THIẾU NỘI DUNG]" if f.id in unresolved_file_ids else ""
                lines.append(f"    * {member}{suffix}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("== Tờ khai thiếu file ==")
    if missing:
        for decl in missing:
            lines.append(f"- {decl}")
    else:
        lines.append("(none)")
    lines.append("")
    return "\n".join(lines)


def _build_declarations_zip(
    *, client: dict, direction: str, requested: list[str],
    files_by_decl: dict[str, list], backend,
) -> bytes:
    """Build the ZIP archive in memory. Files at root, deduped names,
    manifest at root, and a NO_FILES_FOUND marker when nothing matched."""
    import io
    import zipfile

    taken: set[str] = set()
    # First pass: stage (file, member_name, blob) so the manifest can
    # reference the post-dedupe filename and, crucially, reflect which
    # blobs actually resolved. A file registered in metadata but absent
    # from storage is staged with blob=None and surfaced (manifest
    # annotation + count + marker) rather than silently dropped.
    staged: list[tuple] = []  # (file_obj, member_name, blob | None)
    member_by_file_id: dict[int, str] = {}
    unresolved_file_ids: set[int] = set()
    for decl in requested:
        for f in files_by_decl.get(decl, []):
            base = _safe_member_name(f.original_filename)
            member = _unique_member_name(base, taken)
            member_by_file_id[f.id] = member
            try:
                blob = backend.get(f.backend_key)
            except FileNotFoundError:
                unresolved_file_ids.add(f.id)
                staged.append((f, member, None))
                continue
            staged.append((f, member, blob))

    manifest = _build_manifest_text(
        client=client, direction=direction, requested=requested,
        files_by_decl=files_by_decl, member_by_file_id=member_by_file_id,
        unresolved_file_ids=unresolved_file_ids,
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f, member, blob in staged:
            if blob is None:
                continue  # registered-but-missing: surfaced below, not written
            zf.writestr(member, blob)
        zf.writestr("DANH_SACH_TO_KHAI.txt", manifest)
        if unresolved_file_ids:
            marker = [
                "Các file dưới đây có trong metadata nhưng thiếu nội dung "
                "trên máy chủ — không thể đưa vào ZIP.",
                "Xem DANH_SACH_TO_KHAI.txt để biết chi tiết.",
                "",
            ]
            for decl in requested:
                for f in files_by_decl.get(decl, []):
                    if f.id in unresolved_file_ids:
                        marker.append(f"- {decl}: {f.original_filename}")
            zf.writestr("FILE_THIEU_NOI_DUNG.txt", "\n".join(marker) + "\n")
        if not staged:
            zf.writestr(
                "NO_FILES_FOUND.txt",
                "Không có file tờ khai nào đã upload cho các tờ khai yêu cầu.\n"
                "Xem DANH_SACH_TO_KHAI.txt cho chi tiết.\n",
            )
    return buf.getvalue()
