"""Upload audit — nested under /clients/{client_id}/."""
from __future__ import annotations

import csv
import io
import urllib.parse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from hub.app import auth
from hub.app.database import connect
from hub.app.routes.clients import get_client, stats_for_client

router = APIRouter()

# Only failed/abandoned uploads may be deleted — a 'done' row backs a real
# artifact via source_upload_id and must stay for provenance.
_DELETABLE_STATUSES = ("error", "rejected")

# Preview caps — keep the detail page render cheap even for huge sheets.
_PREVIEW_MAX_ROWS = 50
_PREVIEW_MAX_COLS = 25


@router.get("/clients/{client_id}/uploads", response_class=HTMLResponse)
async def list_view(request: Request, client_id: str, module: str | None = None):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    items = _list_uploads(client_id=client_id, module=module)
    counts = _count_by_status(client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/uploads.html",
        {"client": client, "stats": stats_for_client(client_id),
         "items": items, "selected_module": module, "counts": counts,
         "active_root": "clients", "active_tab": "uploads"},
    )


@router.get("/clients/{client_id}/uploads/{upload_id}", response_class=HTMLResponse)
async def detail_view(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    rec = _get_upload(client_id=client_id, upload_id=upload_id)
    if not rec:
        raise HTTPException(404, "Upload not found")
    preview = _preview_for(rec)
    return request.app.state.templates.TemplateResponse(
        request, "clients/upload_detail.html",
        {"client": client, "stats": stats_for_client(client_id),
         "u": rec, "preview": preview,
         "active_root": "clients", "active_tab": "uploads"},
    )


@router.get("/clients/{client_id}/uploads/{upload_id}/download")
async def download_upload(request: Request, client_id: str, upload_id: str):
    """Stream the original uploaded file back as an attachment."""
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    rec = _get_upload(client_id=client_id, upload_id=upload_id)
    if not rec or not rec.get("stored_path"):
        raise HTTPException(404, "Upload not found")
    from hub.app.storage import get_backend
    try:
        blob = get_backend().get(rec["stored_path"])
    except Exception:  # noqa: BLE001 — blob may be gone / backend unreachable
        raise HTTPException(404, "File no longer available")
    fn = rec.get("original_filename") or f"{upload_id}.bin"
    ascii_fn = fn.encode("ascii", "ignore").decode() or "download"
    quoted = urllib.parse.quote(fn)
    return Response(
        content=blob,
        media_type=rec.get("mime_type") or "application/octet-stream",
        headers={
            "content-disposition": (
                f'attachment; filename="{ascii_fn}"; '
                f"filename*=UTF-8''{quoted}"
            ),
        },
    )


@router.post("/clients/{client_id}/uploads/{upload_id}/delete")
async def delete_upload(request: Request, client_id: str, upload_id: str):
    """Remove a failed/rejected upload row (and its blob). Refuses 'done'
    and other statuses that back a stored artifact."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    with connect(user_id=user.user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select parse_status, stored_path from hub.file_uploads "
                "where upload_id=%s and client_id=%s",
                (upload_id, client_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Upload not found")
            parse_status, stored_path = row
            if parse_status not in _DELETABLE_STATUSES:
                raise HTTPException(
                    400, "Chỉ xoá được upload lỗi hoặc đã bị từ chối.")
            cur.execute(
                "delete from hub.file_uploads where upload_id=%s and client_id=%s",
                (upload_id, client_id),
            )
    if stored_path:
        try:
            from hub.app.storage import get_backend
            get_backend().delete(stored_path)
        except Exception:  # noqa: BLE001 — blob may already be gone
            pass
    return RedirectResponse(
        url=f"/clients/{client_id}/uploads?deleted=1", status_code=303,
    )


def _list_uploads(*, client_id: str, module: str | None) -> list[dict]:
    sql = """
        select f.upload_id, f.module, f.original_filename, f.size_bytes,
               f.parse_status, f.parse_error, f.row_count, f.created_at,
               f.parsed_at, f.uploader_user_id,
               coalesce(u.display_name, u.email) as uploader_name
        from hub.file_uploads f
        left join hub.users u on u.user_id = f.uploader_user_id
        where f.client_id = %s
    """
    params: list = [client_id]
    if module:
        sql += " and f.module = %s"
        params.append(module)
    sql += " order by f.created_at desc limit 500"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _get_upload(*, client_id: str, upload_id: str) -> dict | None:
    sql = """
        select f.upload_id, f.module, f.original_filename, f.stored_path,
               f.storage_backend, f.content_sha256, f.size_bytes, f.mime_type,
               f.parse_status, f.parse_error, f.row_count, f.result,
               f.created_at, f.parsed_at, f.uploader_user_id,
               coalesce(u.display_name, u.email) as uploader_name,
               u.email as uploader_email
        from hub.file_uploads f
        left join hub.users u on u.user_id = f.uploader_user_id
        where f.upload_id = %s and f.client_id = %s
    """
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (upload_id, client_id))
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


def _count_by_status(client_id: str) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select parse_status, count(*) from hub.file_uploads where client_id = %s group by parse_status",
                (client_id,))
            return dict(cur.fetchall())


def _preview_for(rec: dict) -> dict | None:
    """Read the stored blob and render the first rows as a table. Best-effort:
    returns a {kind: ...} dict the template renders, or None when there is no
    stored blob to show."""
    stored_path = rec.get("stored_path")
    if not stored_path:
        return None
    try:
        from hub.app.storage import get_backend
        blob = get_backend().get(stored_path)
    except Exception as e:  # noqa: BLE001
        return {"kind": "error", "message": f"Không đọc được file: {e}"}
    return _build_preview(blob, rec.get("original_filename"), rec.get("mime_type"))


def _build_preview(blob: bytes, filename: str | None, mime: str | None) -> dict:
    name = (filename or "").lower()
    is_excel = (
        name.endswith((".xlsx", ".xlsm", ".xls"))
        or blob[:2] == b"PK"
        or blob[:4] == b"\xd0\xcf\x11\xe0"
    )
    try:
        if is_excel:
            from hub.app.parsers._excel import load_xlsx
            wb = load_xlsx(blob)
            sheets = list(wb.worksheets)
            if not sheets:
                if hasattr(wb, "close"):
                    wb.close()
                return {"kind": "empty"}
            ws = sheets[0]
            rows = []
            for r in ws.iter_rows(min_row=1, max_row=_PREVIEW_MAX_ROWS,
                                  values_only=True):
                rows.append([_fmt_cell(c) for c in r[:_PREVIEW_MAX_COLS]])
            if hasattr(wb, "close"):
                wb.close()
            return {
                "kind": "table",
                "sheet": getattr(ws, "title", None),
                "sheet_count": len(sheets),
                "rows": rows,
                "ncols": max((len(r) for r in rows), default=0),
                "row_capped": len(rows) >= _PREVIEW_MAX_ROWS,
            }
        if name.endswith(".csv") or _looks_textual(blob):
            text = blob.decode("utf-8-sig", errors="replace")
            rows = []
            for i, r in enumerate(csv.reader(io.StringIO(text))):
                if i >= _PREVIEW_MAX_ROWS:
                    break
                rows.append([_fmt_cell(c) for c in r[:_PREVIEW_MAX_COLS]])
            return {
                "kind": "table",
                "sheet": "CSV",
                "sheet_count": 1,
                "rows": rows,
                "ncols": max((len(r) for r in rows), default=0),
                "row_capped": len(rows) >= _PREVIEW_MAX_ROWS,
            }
    except Exception as e:  # noqa: BLE001 — preview must never 500 the page
        return {"kind": "error", "message": str(e)}
    return {"kind": "unsupported"}


def _fmt_cell(v) -> str:
    if v is None:
        return ""
    s = str(v)
    return s if len(s) <= 200 else s[:200] + "…"


def _looks_textual(blob: bytes) -> bool:
    sample = blob[:2048]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False
