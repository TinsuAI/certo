"""Code mappings (BQD = Bảng Quy Đổi) routes."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect
from app.routes.dncxs import get_dncx, list_dncxs
from app.parsers.code_mappings import parse_code_mappings_workbook, CodeMappingsParseError
from app.storage import save_upload, sha256_bytes
from app.stores.code_resolution import resolve_for_dncx, lookup_resolution
from app.stores.uploads import record_upload

router = APIRouter()


def _list_mappings(dncx_id: str, q: str | None = None) -> list[dict]:
    sql = """
        select dncx_id, internal_code, customs_code, category, notes, created_at
        from hub.code_mappings where dncx_id = %s
    """
    params: list = [dncx_id]
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


def _mapping_stats(dncx_id: str) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select count(*) total,
                       count(distinct internal_code) n_internal,
                       count(distinct customs_code) n_customs
                from hub.code_mappings where dncx_id = %s
                """,
                (dncx_id,),
            )
            row = cur.fetchone()
            cur.execute(
                """
                select count(*) from (
                  select internal_code from hub.code_mappings
                  where dncx_id = %s group by internal_code having count(*) > 1
                ) t
                """,
                (dncx_id,),
            )
            (n_1n,) = cur.fetchone()
            return {"total": row[0], "n_internal": row[1], "n_customs": row[2], "n_1n": n_1n}


@router.get("/code-mappings", response_class=HTMLResponse)
async def list_view(request: Request, dncx_id: str | None = None, q: str | None = None):
    user = auth.require_user(request)
    dncxs = list_dncxs()
    if not dncxs:
        return request.app.state.templates.TemplateResponse(
        request,
        "code_mappings/empty.html",
        { "active": "mappings"},
        )
    dncx_id = dncx_id or dncxs[0]["dncx_id"]
    dncx = get_dncx(dncx_id)
    if not dncx:
        raise HTTPException(404, "DNCX not found")
    items = _list_mappings(dncx_id, q)
    stats = _mapping_stats(dncx_id)
    return request.app.state.templates.TemplateResponse(
        request,
        "code_mappings/list.html",
        {
            "dncxs": dncxs,
            "dncx": dncx,
            "items": items,
            "q": q or "",
            "stats": stats,
            "active": "mappings",
        },
    )


@router.get("/code-mappings/upload", response_class=HTMLResponse)
async def upload_view(request: Request, dncx_id: str | None = None):
    user = auth.require_user(request)
    dncxs = list_dncxs()
    if not dncxs:
        return request.app.state.templates.TemplateResponse(
        request,
        "code_mappings/empty.html",
        { "active": "mappings"},
        )
    dncx_id = dncx_id or dncxs[0]["dncx_id"]
    return request.app.state.templates.TemplateResponse(
        request,
        "code_mappings/upload.html",
        { "dncxs": dncxs, "dncx_id": dncx_id, "active": "mappings"},
    )


@router.post("/code-mappings/upload")
async def upload_submit(
    request: Request,
    dncx_id: str = Form(...),
    file: UploadFile = File(...),
):
    user = auth.require_user(request)
    dncx = get_dncx(dncx_id)
    if not dncx:
        raise HTTPException(404, "DNCX not found")
    blob = await file.read()
    sha = sha256_bytes(blob)
    stored = save_upload(blob, filename=file.filename or "bqd.xlsx", module="code_mappings", dncx_id=dncx_id)
    upload_id = record_upload(
        dncx_id=dncx_id, module="code_mappings",
        original_filename=file.filename or "bqd.xlsx",
        stored_path=stored.path, content_sha256=sha, size_bytes=len(blob),
        mime_type=file.content_type, uploader_user_id=user.user_id,
    )
    try:
        rows = parse_code_mappings_workbook(blob)
    except CodeMappingsParseError as e:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s", (str(e), upload_id))
        raise HTTPException(400, f"Parse error: {e}")
    n = _insert_mappings(dncx_id=dncx_id, rows=rows)
    resolve_for_dncx(dncx_id)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("update hub.file_uploads set parse_status='done', row_count=%s, parsed_at=now() where upload_id=%s", (n, upload_id))
    return RedirectResponse(url=f"/code-mappings?dncx_id={dncx_id}", status_code=303)


def _insert_mappings(*, dncx_id: str, rows: list[dict]) -> int:
    n = 0
    with connect() as conn:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    """
                    insert into hub.code_mappings
                      (dncx_id, internal_code, customs_code, category, notes)
                    values (%s, %s, %s, %s, %s)
                    on conflict (dncx_id, internal_code, customs_code) do update set
                      category = excluded.category,
                      notes = excluded.notes
                    """,
                    (dncx_id, r["internal_code"], r["customs_code"], r.get("category"), r.get("notes")),
                )
                n += 1
    return n


@router.post("/code-mappings/resolve")
async def trigger_resolve(
    request: Request,
    dncx_id: str = Form(...),
):
    user = auth.require_user(request)
    if not get_dncx(dncx_id):
        raise HTTPException(404, "DNCX not found")
    resolve_for_dncx(dncx_id)
    return RedirectResponse(url=f"/code-mappings?dncx_id={dncx_id}", status_code=303)


@router.get("/api/v1/hub/materials/resolve")
async def api_resolve(request: Request, dncx_id: str, internal_code: str):
    user = auth.require_user(request)
    if not get_dncx(dncx_id):
        raise HTTPException(404, "DNCX not found")
    res = lookup_resolution(dncx_id=dncx_id, internal_code=internal_code)
    if not res:
        raise HTTPException(404, "no resolution found")
    return res


@router.post("/code-mappings/manual")
async def manual_add(
    request: Request,
    dncx_id: str = Form(...),
    internal_code: str = Form(...),
    customs_code: str = Form(...),
    category: str = Form(""),
    notes: str = Form(""),
):
    user = auth.require_user(request)
    if not get_dncx(dncx_id):
        raise HTTPException(404, "DNCX not found")
    _insert_mappings(
        dncx_id=dncx_id,
        rows=[{"internal_code": internal_code.strip(), "customs_code": customs_code.strip(),
               "category": category.strip() or None, "notes": notes.strip() or None}],
    )
    return RedirectResponse(url=f"/code-mappings?dncx_id={dncx_id}", status_code=303)
