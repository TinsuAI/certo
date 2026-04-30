"""Materials (Danh Mục) routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect
from app.routes.dncxs import list_dncxs, get_dncx
from app.parsers.materials import parse_materials_workbook, MaterialsParseError
from app.storage import save_upload, sha256_bytes
from app.stores.uploads import record_upload

router = APIRouter()

CATEGORIES = ["nvl", "btp_sx", "btp_nm", "tp", "ccdc"]


@router.get("/materials", response_class=HTMLResponse)
async def list_view(request: Request, dncx_id: str | None = None,
                    category: str | None = None, q: str | None = None):
    user = auth.require_user(request)
    dncxs = list_dncxs()
    if not dncxs:
        return request.app.state.templates.TemplateResponse(
        request,
        "materials/empty.html",
        { "active": "materials"},
        )
    dncx_id = dncx_id or dncxs[0]["dncx_id"]
    dncx = get_dncx(dncx_id)
    if not dncx:
        raise HTTPException(404, "DNCX not found")
    items = _query_materials(dncx_id=dncx_id, category=category, q=q)
    counts = _category_counts(dncx_id)
    return request.app.state.templates.TemplateResponse(
        request,
        "materials/list.html",
        {
            "dncxs": dncxs,
            "dncx": dncx,
            "items": items,
            "categories": CATEGORIES,
            "active_category": category,
            "q": q or "",
            "counts": counts,
            "active": "materials",
        },
    )


def _query_materials(*, dncx_id: str, category: str | None, q: str | None) -> list[dict]:
    sql = """
        select customs_code, product_code, name, category, status, unit, hs_code, updated_at
        from hub.materials where dncx_id = %s
    """
    params: list = [dncx_id]
    if category:
        sql += " and category = %s"
        params.append(category)
    if q:
        sql += " and (customs_code ilike %s or product_code ilike %s or name ilike %s or hs_code ilike %s)"
        like = f"%{q}%"
        params.extend([like, like, like, like])
    sql += " order by customs_code limit 1000"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _category_counts(dncx_id: str) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select category, count(*) from hub.materials where dncx_id = %s group by category",
                (dncx_id,),
            )
            return dict(cur.fetchall())


@router.get("/materials/upload", response_class=HTMLResponse)
async def upload_view(request: Request, dncx_id: str | None = None):
    user = auth.require_user(request)
    dncxs = list_dncxs()
    if not dncxs:
        return request.app.state.templates.TemplateResponse(
        request,
        "materials/empty.html",
        { "active": "materials"},
        )
    dncx_id = dncx_id or dncxs[0]["dncx_id"]
    return request.app.state.templates.TemplateResponse(
        request,
        "materials/upload.html",
        { "dncxs": dncxs, "dncx_id": dncx_id, "active": "materials"},
    )


@router.post("/materials/upload")
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
    stored = save_upload(blob, filename=file.filename or "materials.xlsx", module="materials", dncx_id=dncx_id)
    upload_id = record_upload(
        dncx_id=dncx_id, module="materials", original_filename=file.filename or "materials.xlsx",
        stored_path=stored.path, content_sha256=sha, size_bytes=len(blob),
        mime_type=file.content_type, uploader_user_id=user.user_id,
    )
    try:
        rows = parse_materials_workbook(blob)
    except MaterialsParseError as e:
        _mark_upload_failed(upload_id, str(e))
        raise HTTPException(400, f"Parse error: {e}")
    inserted = _insert_materials(dncx_id=dncx_id, rows=rows)
    _mark_upload_done(upload_id, row_count=inserted)
    return RedirectResponse(url=f"/materials?dncx_id={dncx_id}", status_code=303)


def _insert_materials(*, dncx_id: str, rows: list[dict]) -> int:
    n = 0
    with connect() as conn:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    """
                    insert into hub.materials
                      (dncx_id, customs_code, product_code, name, category, status, unit, hs_code)
                    values (%s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (dncx_id, customs_code) do update set
                      product_code = excluded.product_code,
                      name = excluded.name,
                      category = excluded.category,
                      status = excluded.status,
                      unit = excluded.unit,
                      hs_code = excluded.hs_code,
                      updated_at = now()
                    """,
                    (dncx_id, r["customs_code"], r.get("product_code"), r.get("name"),
                     r["category"], r.get("status", "active"), r.get("unit"), r.get("hs_code")),
                )
                n += 1
    return n


def _mark_upload_done(upload_id: str, row_count: int) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.file_uploads set parse_status='done', row_count=%s, parsed_at=now() where upload_id=%s",
                (row_count, upload_id),
            )


def _mark_upload_failed(upload_id: str, error: str) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s",
                (error, upload_id),
            )
