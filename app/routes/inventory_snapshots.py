"""Year-end inventory snapshot (chốt tồn kho) tier routes — slice 1.

Same upload → preview → confirm shape as NXT; the snapshot carries a single
snapshot_date instead of a period. Variance (thực đếm − sổ sách) is derived.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from app import auth
from app.parsers import inventory_adapters
from app.parsers.inventory_adapters._common import variance
from app.routes.clients import get_client, stats_for_client
from app.storage import get_backend, save_upload, sha256_bytes
from app.stores import inventory_snapshots as inv_store
from app.stores.uploads import get_upload, record_upload, set_upload_status

router = APIRouter()

MODULE = "inventory"
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

@router.get("/templates/inventory-snapshot.xlsx")
async def download_inventory_template(request: Request):
    auth.require_user(request)
    return Response(
        content=inv_store.render_template_xlsx(),
        media_type=_XLSX_MIME,
        headers={"Content-Disposition":
                 'attachment; filename="mau-ton-kho-cuoi-ky.xlsx"'},
    )


# ── List ─────────────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/inventory-snapshots")
async def list_view(request: Request, client_id: str,
                    saved: str | None = None, error: str | None = None):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/inventory_snapshots.html",
        {"client": client, "stats": stats_for_client(client_id),
         "snapshots": inv_store.list_snapshots(client_id),
         "can_edit": auth.can_edit_client(user, client_id),
         "saved": saved, "error": error,
         "active_root": "clients", "active_tab": "inventory"},
    )


# ── Upload ─────────────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/inventory-snapshots/upload")
async def upload_view(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/inventory_snapshot_upload.html",
        {"client": client, "stats": stats_for_client(client_id),
         "active_root": "clients", "active_tab": "inventory"},
    )


@router.post("/clients/{client_id}/inventory-snapshots/upload")
async def upload_submit(request: Request, client_id: str,
                        file: UploadFile = File(...),
                        snapshot_date: str = Form("")):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")

    blob = await file.read()
    sha = sha256_bytes(blob)
    stored = save_upload(blob, filename=file.filename or "ton-kho.xlsx",
                         module=MODULE, client_id=client_id)
    upload_id = record_upload(
        client_id=client_id, module=MODULE,
        original_filename=file.filename or "ton-kho.xlsx",
        stored_path=stored.path, content_sha256=sha, size_bytes=len(blob),
        mime_type=file.content_type, uploader_user_id=user.user_id,
    )

    result = inventory_adapters.parse_with_fallback(blob)
    if result is None:
        set_upload_status(upload_id, "error",
                          parse_error="No inventory adapter recognized this file.")
        return RedirectResponse(
            url=f"/clients/{client_id}/inventory-snapshots?error=Không nhận diện được định dạng tồn kho",
            status_code=303)
    lines, adapter_name = result
    set_upload_status(upload_id, "pending_preview", row_count=len(lines),
                      result={"snapshot_date": snapshot_date or None,
                              "adapter_name": adapter_name})
    return RedirectResponse(
        url=f"/clients/{client_id}/inventory-snapshots/preview/{upload_id}",
        status_code=303)


# ── Preview ────────────────────────────────────────────────────────────────

def _load_lines(upload: dict) -> tuple[list[dict], str]:
    blob = get_backend().get(upload["stored_path"])
    adapter_name = (upload.get("result") or {}).get("adapter_name")
    if adapter_name and inventory_adapters.resolve(adapter_name):
        return inventory_adapters.parse_with(blob, name=adapter_name), adapter_name
    res = inventory_adapters.parse_with_fallback(blob)
    if res is None:
        raise HTTPException(422, "Re-parse failed")
    return res


def _summarize(lines: list[dict]) -> dict:
    warehouses: set[str] = set()
    discrepancies = 0
    for ln in lines:
        if ln.get("warehouse"):
            warehouses.add(ln["warehouse"])
        v = variance(ln)
        if v is not None and abs(v) > 1e-6:
            discrepancies += 1
    return {"total": len(lines), "warehouses": len(warehouses),
            "discrepancies": discrepancies}


@router.get("/clients/{client_id}/inventory-snapshots/preview/{upload_id}")
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
    for ln in lines:
        ln["variance"] = variance(ln)
    return request.app.state.templates.TemplateResponse(
        request, "clients/inventory_snapshot_preview.html",
        {"client": client, "stats": stats_for_client(client_id),
         "upload_id": upload_id, "adapter_name": adapter_name,
         "snapshot_date": meta.get("snapshot_date") or "",
         "summary": _summarize(lines), "lines": lines[:200],
         "n_shown": min(len(lines), 200),
         "active_root": "clients", "active_tab": "inventory"},
    )


@router.post("/clients/{client_id}/inventory-snapshots/preview/{upload_id}/confirm")
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
            url=f"/clients/{client_id}/inventory-snapshots?error=Upload đã được xử lý",
            status_code=303)
    lines, adapter_name = _load_lines(upload)
    meta = upload.get("result") or {}
    inv_store.create_snapshot(
        client_id=client_id, lines=lines,
        snapshot_date=_as_date(meta.get("snapshot_date")),
        source_kind=adapter_name, adapter_name=adapter_name,
        file_sha256=upload["content_sha256"], file_path=upload["stored_path"],
        created_by=user.user_id,
    )
    set_upload_status(upload_id, "done", row_count=len(lines))
    return RedirectResponse(
        url=f"/clients/{client_id}/inventory-snapshots?saved=Đã lưu {len(lines)} dòng tồn kho",
        status_code=303)


@router.post("/clients/{client_id}/inventory-snapshots/preview/{upload_id}/reject")
async def preview_reject(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    set_upload_status(upload_id, "rejected")
    return RedirectResponse(
        url=f"/clients/{client_id}/inventory-snapshots?saved=Đã bỏ qua",
        status_code=303)
