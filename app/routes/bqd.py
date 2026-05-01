"""Code mappings (BQD = Bảng Quy Đổi) — nested under /clients/{client_id}/."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect
from app.parsers.code_mappings import parse_code_mappings_workbook, CodeMappingsParseError
from app.routes.clients import get_client, stats_for_client
from app.storage import save_upload, sha256_bytes
from app.stores.uploads import record_upload

router = APIRouter()


@router.get("/clients/{client_id}/bqd", response_class=HTMLResponse)
async def list_view(request: Request, client_id: str, q: str | None = None):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    items = _list_mappings(client_id, q)
    stats_basic = _mapping_stats(client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/bqd.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "items": items, "q": q or "",
            "mapping_stats": stats_basic,
            "active_root": "clients", "active_tab": "bqd",
        },
    )


@router.get("/clients/{client_id}/bqd/upload", response_class=HTMLResponse)
async def upload_view(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/bqd_upload.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "active_root": "clients", "active_tab": "bqd",
        },
    )


@router.post("/clients/{client_id}/bqd/upload")
async def upload_submit(
    request: Request, client_id: str,
    file: UploadFile = File(...),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    blob = await file.read()
    sha = sha256_bytes(blob)
    stored = save_upload(blob, filename=file.filename or "bqd.xlsx",
                         module="code_mappings", client_id=client_id)
    upload_id = record_upload(
        client_id=client_id, module="code_mappings",
        original_filename=file.filename or "bqd.xlsx",
        stored_path=stored.path, content_sha256=sha, size_bytes=len(blob),
        mime_type=file.content_type, uploader_user_id=user.user_id,
    )
    try:
        rows = parse_code_mappings_workbook(blob)
    except CodeMappingsParseError as e:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s",
                    (str(e), upload_id),
                )
        raise HTTPException(400, f"Parse error: {e}")
    n = _insert_mappings(client_id=client_id, rows=rows)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.file_uploads set parse_status='done', row_count=%s, parsed_at=now() where upload_id=%s",
                (n, upload_id),
            )
    return RedirectResponse(url=f"/clients/{client_id}/bqd", status_code=303)


@router.post("/clients/{client_id}/bqd/manual")
async def manual_add(
    request: Request, client_id: str,
    internal_code: str = Form(...),
    customs_code: str = Form(...),
    category: str = Form(""),
    notes: str = Form(""),
):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    _insert_mappings(
        client_id=client_id,
        rows=[{
            "internal_code": internal_code.strip(),
            "customs_code": customs_code.strip(),
            "category": category.strip() or None,
            "notes": notes.strip() or None,
        }],
    )
    return RedirectResponse(url=f"/clients/{client_id}/bqd", status_code=303)


def _list_mappings(client_id: str, q: str | None = None) -> list[dict]:
    sql = """
        select internal_code, customs_code, category, notes, created_at
        from hub.code_mappings where client_id = %s
    """
    params: list = [client_id]
    if q:
        sql += " and (internal_code ilike %s or customs_code ilike %s)"
        like = f"%{q}%"
        params.extend([like, like])
    sql += " order by internal_code, customs_code limit 2000"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _mapping_stats(client_id: str) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select count(*) total,
                       count(distinct internal_code) n_internal,
                       count(distinct customs_code) n_customs
                from hub.code_mappings where client_id = %s
                """,
                (client_id,),
            )
            row = cur.fetchone()
            cur.execute(
                """
                select count(*) from (
                  select internal_code from hub.code_mappings
                  where client_id = %s group by internal_code having count(*) > 1
                ) t
                """,
                (client_id,),
            )
            (n_1n,) = cur.fetchone()
            return {"total": row[0], "n_internal": row[1], "n_customs": row[2], "n_1n": n_1n}


def _insert_mappings(*, client_id: str, rows: list[dict]) -> int:
    n = 0
    with connect() as conn:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    """
                    insert into hub.code_mappings
                      (client_id, internal_code, customs_code, category, notes)
                    values (%s, %s, %s, %s, %s)
                    on conflict (client_id, internal_code, customs_code) do update set
                      category = excluded.category,
                      notes = excluded.notes
                    """,
                    (client_id, r["internal_code"], r["customs_code"],
                     r.get("category"), r.get("notes")),
                )
                n += 1
    return n
