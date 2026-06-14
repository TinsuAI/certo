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
from app.parsers._excel import compute_file_signature
from app.parsers.nxt_adapters._common import ALIASES, closing_implied
from app.parsers.nxt_adapters.manual_generic import ManualGenericNxtAdapter
from app.routes._llm_fallback import (
    cache_confirmed_mapping, headers_per_sheet, lookup_cached_mapping,
    record_mapping_use, request_llm_mapping, sample_rows_first_sheet,
)
from app.routes.clients import get_client, stats_for_client
from app.storage import get_backend, save_upload, sha256_bytes
from app.stores import nxt as nxt_store
from app.stores import settlement_adapter_binding as binding
from app.stores.uploads import get_upload, record_upload, set_upload_status

router = APIRouter()

MODULE = "nxt"
_XLSX_MIME = ("application/vnd.openxmlformats-officedocument."
              "spreadsheetml.sheet")

# Logical fields staff can map a column to on the mapping page.
LOGICAL_FIELDS: list[tuple[str, str]] = [
    ("internal_code", "Mã nội bộ"),
    ("customs_code", "Mã hải quan"),
    ("name", "Tên"),
    ("uom", "ĐVT"),
    ("opening", "Tồn đầu kỳ"),
    ("inbound_total", "Nhập trong kỳ"),
    ("outbound_total", "Xuất (tổng)"),
    ("out_tai_xuat", "Xuất: tái xuất"),
    ("out_chuyen_mdsd", "Xuất: chuyển MĐSD"),
    ("out_xuat_sx", "Xuất: sản xuất"),
    ("out_xuat_khac", "Xuất: khác"),
    ("closing_reported", "Tồn cuối kỳ"),
    ("note", "Ghi chú"),
]


def _file_signature(client_id: str, blob: bytes) -> str | None:
    try:
        sheets = headers_per_sheet(blob)
        if not sheets:
            return None
        return compute_file_signature(
            client_id=client_id, module=MODULE, headers_per_sheet=sheets)
    except Exception:  # noqa: BLE001
        return None


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
         "adapters": nxt_adapters.adapter_names(),
         "default_adapter": binding.get_default_adapter(client_id, MODULE),
         "active_root": "clients", "active_tab": "nxt"},
    )


@router.post("/clients/{client_id}/nxt/default-adapter")
async def set_default_adapter(request: Request, client_id: str,
                              adapter: str = Form(...)):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    try:
        binding.set_default_adapter(client_id, MODULE, adapter)
    except ValueError:
        raise HTTPException(400, "invalid_adapter")
    return RedirectResponse(
        url=f"/clients/{client_id}/nxt/upload", status_code=303)


@router.post("/clients/{client_id}/nxt/upload")
async def upload_submit(request: Request, client_id: str,
                        file: UploadFile = File(...),
                        period_from: str = Form(""),
                        period_to: str = Form(""),
                        adapter: str = Form("auto")):
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
    meta = {"period_from": period_from or None, "period_to": period_to or None}

    # 1. Cached confirmed mapping for this workbook shape → manual_generic.
    sig = _file_signature(client_id, blob)
    if sig:
        cached = lookup_cached_mapping(
            client_id=client_id, module=MODULE, file_signature=sig)
        if cached:
            try:
                lines = ManualGenericNxtAdapter().parse(blob, mapping_override=cached)
            except Exception:  # noqa: BLE001 — stale cache → fall through
                lines = None
            if lines:
                record_mapping_use(
                    client_id=client_id, module=MODULE, file_signature=sig)
                return _stash_and_preview(
                    client_id, upload_id, lines, "manual_generic", meta,
                    mapping_override=cached)

    # 2. Effective adapter: explicit pick → per-client binding → auto-detect.
    chosen = (adapter or "auto").strip()
    if chosen == "auto":
        chosen = binding.get_default_adapter(client_id, MODULE)
    lines: list[dict] | None = None
    adapter_name: str | None = None
    if chosen != "auto" and nxt_adapters.resolve(chosen):
        try:
            lines = nxt_adapters.parse_with(blob, name=chosen)
            adapter_name = chosen
        except Exception:  # noqa: BLE001 — fall back to auto-detect
            lines = None
    if lines is None:
        result = nxt_adapters.parse_with_fallback(blob)
        if result is not None:
            lines, adapter_name = result

    # 3. Nothing parsed → route to the column-mapping page (no error).
    if not lines:
        set_upload_status(upload_id, "needs_mapping",
                          result={**meta, "file_signature": sig})
        return RedirectResponse(
            url=f"/clients/{client_id}/nxt/upload/mapping/{upload_id}",
            status_code=303)

    return _stash_and_preview(client_id, upload_id, lines, adapter_name, meta)


def _stash_and_preview(client_id, upload_id, lines, adapter_name, meta,
                       mapping_override=None):
    result = {**meta, "adapter_name": adapter_name}
    if mapping_override:
        result["mapping_override"] = mapping_override
    set_upload_status(upload_id, "pending_preview", row_count=len(lines),
                      result=result)
    return RedirectResponse(
        url=f"/clients/{client_id}/nxt/preview/{upload_id}", status_code=303)


# ── Column-mapping page (unknown headers → confirm → cache) ──────────────

def _rigid_suggestions(headers: list[str]) -> dict[int, str]:
    from app.parsers._excel import index_headers
    return {idx: field for field, idx in index_headers(headers, ALIASES).items()}


def _mapping_context(request, client_id, upload_id, blob, *,
                     llm_proposed=None, llm_error=None):
    headers, sample_rows = sample_rows_first_sheet(blob)
    rigid = _rigid_suggestions(headers)
    llm_proposed = llm_proposed or {}
    columns = []
    for idx, h in enumerate(headers):
        columns.append({
            "idx": idx, "header": h,
            "suggested": llm_proposed.get(h) or rigid.get(idx, ""),
        })
    return {
        "client": get_client(client_id),
        "stats": stats_for_client(client_id),
        "upload_id": upload_id, "columns": columns,
        "fields": LOGICAL_FIELDS,
        "sample_rows": [list(r)[:len(headers)] for r in sample_rows],
        "llm_error": llm_error,
        "active_root": "clients", "active_tab": "nxt",
    }


@router.get("/clients/{client_id}/nxt/upload/mapping/{upload_id}")
async def mapping_view(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    upload = get_upload(upload_id, client_id=client_id)
    if not upload or upload["module"] != MODULE:
        raise HTTPException(404, "Upload not found")
    blob = get_backend().get(upload["stored_path"])
    return request.app.state.templates.TemplateResponse(
        request, "clients/nxt_mapping.html",
        _mapping_context(request, client_id, upload_id, blob))


@router.post("/clients/{client_id}/nxt/upload/mapping/{upload_id}/llm")
async def mapping_llm_suggest(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    upload = get_upload(upload_id, client_id=client_id)
    if not upload or upload["module"] != MODULE:
        raise HTTPException(404, "Upload not found")
    blob = get_backend().get(upload["stored_path"])
    proposed: dict = {}
    err = None
    try:
        proposed, _h, _s, _sig = request_llm_mapping(
            client_id=client_id, module=MODULE, blob=blob,
            rigid_error="manual mapping requested")
    except Exception as e:  # noqa: BLE001
        err = f"LLM không khả dụng: {e}"
    return request.app.state.templates.TemplateResponse(
        request, "clients/nxt_mapping.html",
        _mapping_context(request, client_id, upload_id, blob,
                         llm_proposed=proposed, llm_error=err))


@router.post("/clients/{client_id}/nxt/upload/mapping/{upload_id}/parse")
async def mapping_parse(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    upload = get_upload(upload_id, client_id=client_id)
    if not upload or upload["module"] != MODULE:
        raise HTTPException(404, "Upload not found")
    blob = get_backend().get(upload["stored_path"])
    form = await request.form()

    override: dict[str, str] = {}
    for key, value in form.items():
        if key.startswith("col_") and key.endswith("__field"):
            field = (value or "").strip()
            if not field:
                continue
            header = (form.get(f"col_{key[4:-7]}__header") or "").strip()
            if header:
                override[header] = field

    try:
        lines = ManualGenericNxtAdapter().parse(blob, mapping_override=override)
    except Exception as e:  # noqa: BLE001
        ctx = _mapping_context(request, client_id, upload_id, blob,
                               llm_error=f"Mapping chưa hợp lệ: {e}")
        return request.app.state.templates.TemplateResponse(
            request, "clients/nxt_mapping.html", ctx)

    sig = _file_signature(client_id, blob)
    if sig:
        cache_confirmed_mapping(
            client_id=client_id, module=MODULE, file_signature=sig,
            mapping=override,
            headers=[c["header"] for c in _mapping_context(
                request, client_id, upload_id, blob)["columns"]],
            confirmed_by_user_id=user.user_id, proposed_by="manual")
    meta = {k: (upload.get("result") or {}).get(k)
            for k in ("period_from", "period_to")}
    return _stash_and_preview(client_id, upload_id, lines, "manual_generic", meta,
                              mapping_override=override)


# ── Preview ────────────────────────────────────────────────────────────────

def _load_lines(upload: dict) -> tuple[list[dict], str]:
    blob = get_backend().get(upload["stored_path"])
    result = upload.get("result") or {}
    adapter_name = result.get("adapter_name")
    override = result.get("mapping_override")
    if adapter_name and nxt_adapters.resolve(adapter_name):
        return (nxt_adapters.parse_with(blob, name=adapter_name,
                                        mapping_override=override),
                adapter_name)
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
