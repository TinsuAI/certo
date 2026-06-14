"""NXT (Nhập-Xuất-Tồn) tier routes — system_template happy path (slice 1).

Flow: upload → parse via adapter registry (parse_with_fallback) → stash the
file in hub.file_uploads (period + adapter in result jsonb) → preview → confirm
writes an immutable nxt_artifact. system_template needs no mapping page; the
slice-2 manual_generic adapter will add one.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from app import auth
from app.parsers import nxt_adapters
from app.parsers.nxt_adapters._common import closing_implied
from app.routes.clients import get_client, stats_for_client
from app.storage import get_backend, save_upload, sha256_bytes
from app.stores import nxt as nxt_store
from app.stores.uploads import get_upload, record_upload, set_upload_status

router = APIRouter()

MODULE = "nxt"
_XLSX_MIME = ("application/vnd.openxmlformats-officedocument."
              "spreadsheetml.sheet")


def _parse_date(s: str | None):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _as_date(v):
    if isinstance(v, date):
        return v
    return _parse_date(v) if isinstance(v, str) else None


# ── Template download (global) ───────────────────────────────────────────

@router.get("/templates/nxt.xlsx")
async def download_nxt_template(request: Request):
    auth.require_user(request)
    return Response(
        content=nxt_store.render_template_xlsx(),
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="mau-nxt.xlsx"'},
    )


# ── List ─────────────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/nxt")
async def list_view(request: Request, client_id: str,
                    saved: str | None = None, error: str | None = None):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/nxt.html",
        {"client": client, "stats": stats_for_client(client_id),
         "artifacts": nxt_store.list_artifacts(client_id),
         "can_edit": auth.can_edit_client(user, client_id),
         "saved": saved, "error": error,
         "active_root": "clients", "active_tab": "nxt"},
    )


# ── Upload ─────────────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/nxt/upload")
async def upload_view(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/nxt_upload.html",
        {"client": client, "stats": stats_for_client(client_id),
         "active_root": "clients", "active_tab": "nxt"},
    )


@router.post("/clients/{client_id}/nxt/upload")
async def upload_submit(request: Request, client_id: str,
                        file: UploadFile = File(...),
                        period_from: str = Form(""),
                        period_to: str = Form("")):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")

    blob = await file.read()
    sha = sha256_bytes(blob)
    stored = save_upload(blob, filename=file.filename or "nxt.xlsx",
                         module=MODULE, client_id=client_id)
    upload_id = record_upload(
        client_id=client_id, module=MODULE,
        original_filename=file.filename or "nxt.xlsx",
        stored_path=stored.path, content_sha256=sha, size_bytes=len(blob),
        mime_type=file.content_type, uploader_user_id=user.user_id,
    )

    result = nxt_adapters.parse_with_fallback(blob)
    if result is None:
        set_upload_status(upload_id, "error",
                          parse_error="No NXT adapter recognized this file.")
        return RedirectResponse(
            url=f"/clients/{client_id}/nxt?error=Không nhận diện được định dạng NXT",
            status_code=303)
    lines, adapter_name = result
    set_upload_status(upload_id, "pending_preview", row_count=len(lines),
                      result={"period_from": period_from or None,
                              "period_to": period_to or None,
                              "adapter_name": adapter_name})
    return RedirectResponse(
        url=f"/clients/{client_id}/nxt/preview/{upload_id}", status_code=303)


# ── Preview ────────────────────────────────────────────────────────────────

def _load_lines(upload: dict) -> tuple[list[dict], str]:
    blob = get_backend().get(upload["stored_path"])
    adapter_name = (upload.get("result") or {}).get("adapter_name")
    if adapter_name and nxt_adapters.resolve(adapter_name):
        return nxt_adapters.parse_with(blob, name=adapter_name), adapter_name
    res = nxt_adapters.parse_with_fallback(blob)
    if res is None:
        raise HTTPException(422, "Re-parse failed")
    return res


def _summarize(lines: list[dict]) -> dict:
    by_role: dict[str, int] = {}
    mismatches = 0
    for ln in lines:
        role = ln.get("reported_role") or "?"
        by_role[role] = by_role.get(role, 0) + 1
        ci = closing_implied(ln)
        cr = ln.get("closing_reported")
        if ci is not None and cr is not None and abs(ci - cr) > 1e-6:
            mismatches += 1
    return {"total": len(lines), "by_role": by_role, "mismatches": mismatches}


@router.get("/clients/{client_id}/nxt/preview/{upload_id}")
async def preview_view(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    upload = get_upload(upload_id, client_id=client_id)
    if not upload or upload["module"] != MODULE:
        raise HTTPException(404, "Upload not found")
    lines, adapter_name = _load_lines(upload)
    meta = upload.get("result") or {}
    # Annotate lines with the runtime-derived closing_implied for the preview.
    for ln in lines:
        ln["closing_implied"] = closing_implied(ln)
    return request.app.state.templates.TemplateResponse(
        request, "clients/nxt_preview.html",
        {"client": client, "stats": stats_for_client(client_id),
         "upload_id": upload_id, "adapter_name": adapter_name,
         "period_from": meta.get("period_from") or "",
         "period_to": meta.get("period_to") or "",
         "summary": _summarize(lines), "lines": lines[:200],
         "n_shown": min(len(lines), 200),
         "active_root": "clients", "active_tab": "nxt"},
    )


@router.post("/clients/{client_id}/nxt/preview/{upload_id}/confirm")
async def preview_confirm(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    upload = get_upload(upload_id, client_id=client_id)
    if not upload or upload["module"] != MODULE:
        raise HTTPException(404, "Upload not found")
    if upload["parse_status"] not in ("pending_preview", "error"):
        return RedirectResponse(
            url=f"/clients/{client_id}/nxt?error=Upload đã được xử lý",
            status_code=303)
    lines, adapter_name = _load_lines(upload)
    meta = upload.get("result") or {}
    nxt_store.create_artifact(
        client_id=client_id, lines=lines,
        period_from=_as_date(meta.get("period_from")),
        period_to=_as_date(meta.get("period_to")),
        source_kind=adapter_name, adapter_name=adapter_name,
        file_sha256=upload["content_sha256"], file_path=upload["stored_path"],
        created_by=user.user_id,
    )
    set_upload_status(upload_id, "done", row_count=len(lines))
    return RedirectResponse(
        url=f"/clients/{client_id}/nxt?saved=Đã lưu {len(lines)} dòng NXT",
        status_code=303)


@router.post("/clients/{client_id}/nxt/preview/{upload_id}/reject")
async def preview_reject(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    set_upload_status(upload_id, "rejected")
    return RedirectResponse(url=f"/clients/{client_id}/nxt?saved=Đã bỏ qua",
                            status_code=303)
