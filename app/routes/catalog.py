"""Catalog (Materials / Danh mục mã hàng) — nested under /clients/{client_id}/."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect
from app.parsers.materials import parse_materials_workbook, MaterialsParseError
from app.routes.clients import get_client, stats_for_client
from app.storage import save_upload, sha256_bytes
from app.stores.uploads import record_upload

router = APIRouter()

CATEGORIES = ["nvl", "btp_sx", "btp_nm", "tp", "ccdc"]


@router.get("/clients/{client_id}/catalog", response_class=HTMLResponse)
async def list_view(
    request: Request, client_id: str,
    category: str | None = None, q: str | None = None,
):
    auth.require_user(request)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    items = _query_materials(client_id=client_id, category=category, q=q)
    counts = _category_counts(client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/catalog.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "items": items, "categories": CATEGORIES,
            "active_category": category, "q": q or "", "counts": counts,
            "active_root": "clients", "active_tab": "catalog",
        },
    )


@router.get("/clients/{client_id}/catalog/upload", response_class=HTMLResponse)
async def upload_view(request: Request, client_id: str):
    auth.require_user(request)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/catalog_upload.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "active_root": "clients", "active_tab": "catalog",
        },
    )


@router.post("/clients/{client_id}/catalog/upload")
async def upload_submit(
    request: Request, client_id: str,
    file: UploadFile = File(...),
):
    user = auth.require_user(request)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    blob = await file.read()
    sha = sha256_bytes(blob)
    stored = save_upload(blob, filename=file.filename or "materials.xlsx",
                         module="materials", client_id=client_id)
    upload_id = record_upload(
        client_id=client_id, module="materials",
        original_filename=file.filename or "materials.xlsx",
        stored_path=stored.path, content_sha256=sha, size_bytes=len(blob),
        mime_type=file.content_type, uploader_user_id=user.user_id,
    )
    try:
        rows = parse_materials_workbook(blob)
    except MaterialsParseError as e:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s",
                    (str(e), upload_id),
                )
        raise HTTPException(400, f"Parse error: {e}")
    n = _insert_materials(client_id=client_id, rows=rows)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.file_uploads set parse_status='done', row_count=%s, parsed_at=now() where upload_id=%s",
                (n, upload_id),
            )
    return RedirectResponse(url=f"/clients/{client_id}/catalog", status_code=303)


def _query_materials(*, client_id: str, category: str | None, q: str | None) -> list[dict]:
    sql = """
        select m.customs_code, m.product_code, m.name, m.category, m.category_override,
               m.status, m.unit, m.hs_code, m.updated_at,
               exists (
                 select 1 from hub.bcct_rows b
                 where b.client_id = m.client_id
                   and b.customs_code = m.customs_code
                   and b.direction = 'import'
               ) as has_imports,
               exists (
                 select 1 from hub.bom_versions v
                 where v.client_id = m.client_id
                   and v.product_code = m.customs_code
                   and v.tombstoned_at is null
                   and v.status = 'published'
               ) as has_bom
        from hub.materials m
        where m.client_id = %s
    """
    params: list = [client_id]
    if category:
        sql += " and m.category = %s"
        params.append(category)
    if q:
        sql += (" and (m.customs_code ilike %s or m.product_code ilike %s "
                "or m.name ilike %s or m.hs_code ilike %s)")
        like = f"%{q}%"
        params.extend([like, like, like, like])
    sql += " order by m.customs_code limit 1000"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            for r in rows:
                r["is_dual_source"] = bool(r.get("has_imports") and r.get("has_bom"))
            return rows


def _category_counts(client_id: str) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select category, count(*) from hub.materials where client_id = %s group by category",
                (client_id,),
            )
            return dict(cur.fetchall())


def _insert_materials(*, client_id: str, rows: list[dict]) -> int:
    n = 0
    with connect() as conn:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    """
                    insert into hub.materials
                      (client_id, customs_code, product_code, name, category, status, unit, hs_code)
                    values (%s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (client_id, customs_code) do update set
                      product_code = excluded.product_code,
                      name = excluded.name,
                      category = excluded.category,
                      status = excluded.status,
                      unit = excluded.unit,
                      hs_code = excluded.hs_code,
                      updated_at = now()
                    """,
                    (client_id, r["customs_code"], r.get("product_code"), r.get("name"),
                     r["category"], r.get("status", "active"), r.get("unit"), r.get("hs_code")),
                )
                n += 1
    return n
