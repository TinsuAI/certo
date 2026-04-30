"""BCCT (customs declaration registry) routes."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect
from app.routes.dncxs import get_dncx, list_dncxs
from app.parsers.bcct import parse_bcct_workbook, BcctParseError
from app.parsers.goods_name import internal_code_parser_for
from app.storage import save_upload, sha256_bytes
from app.stores.code_resolution import resolve_for_dncx
from app.stores.uploads import record_upload

router = APIRouter()


def _list_bcct(dncx_id: str, year: int | None, direction: str | None,
               q: str | None) -> list[dict]:
    sql = """
        select transaction_key, line_no, declaration_no, declaration_type, direction,
               registration_date, customs_code, internal_code, goods_name, hs_code,
               quantity, unit, total_value, currency, origin
        from hub.bcct_rows where dncx_id = %s
    """
    params: list = [dncx_id]
    if year:
        sql += " and year = %s"
        params.append(year)
    if direction:
        sql += " and direction = %s"
        params.append(direction)
    if q:
        sql += """ and (declaration_no ilike %s or customs_code ilike %s
                        or internal_code ilike %s or goods_name ilike %s)"""
        like = f"%{q}%"
        params.extend([like, like, like, like])
    sql += " order by registration_date desc nulls last, declaration_no, line_no limit 1000"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _years(dncx_id: str) -> list[int]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select distinct year from hub.bcct_rows where dncx_id = %s order by year desc",
                (dncx_id,),
            )
            return [y for (y,) in cur.fetchall()]


@router.get("/bcct", response_class=HTMLResponse)
async def list_view(request: Request, dncx_id: str | None = None,
                    year: int | None = None, direction: str | None = None,
                    q: str | None = None):
    user = auth.require_user(request)
    dncxs = list_dncxs()
    if not dncxs:
        return request.app.state.templates.TemplateResponse(
        request,
        "bcct/empty.html",
        { "active": "bcct"},
        )
    dncx_id = dncx_id or dncxs[0]["dncx_id"]
    dncx = get_dncx(dncx_id)
    if not dncx:
        raise HTTPException(404, "DNCX not found")
    years = _years(dncx_id)
    items = _list_bcct(dncx_id, year, direction, q)
    return request.app.state.templates.TemplateResponse(
        request,
        "bcct/list.html",
        {
            "dncxs": dncxs,
            "dncx": dncx,
            "items": items,
            "years": years,
            "year": year,
            "direction": direction,
            "q": q or "",
            "active": "bcct",
        },
    )


@router.get("/bcct/upload", response_class=HTMLResponse)
async def upload_view(request: Request, dncx_id: str | None = None):
    user = auth.require_user(request)
    dncxs = list_dncxs()
    if not dncxs:
        return request.app.state.templates.TemplateResponse(
        request,
        "bcct/empty.html",
        { "active": "bcct"},
        )
    dncx_id = dncx_id or dncxs[0]["dncx_id"]
    return request.app.state.templates.TemplateResponse(
        request,
        "bcct/upload.html",
        { "dncxs": dncxs, "dncx_id": dncx_id, "active": "bcct"},
    )


@router.post("/bcct/upload")
async def upload_submit(
    request: Request,
    dncx_id: str = Form(...),
    year: int = Form(...),
    file: UploadFile = File(...),
):
    user = auth.require_user(request)
    dncx = get_dncx(dncx_id)
    if not dncx:
        raise HTTPException(404, "DNCX not found")
    blob = await file.read()
    sha = sha256_bytes(blob)
    stored = save_upload(blob, filename=file.filename or "bcct.xlsx", module="bcct", dncx_id=dncx_id)
    upload_id = record_upload(
        dncx_id=dncx_id, module="bcct",
        original_filename=file.filename or "bcct.xlsx",
        stored_path=stored.path, content_sha256=sha, size_bytes=len(blob),
        mime_type=file.content_type, uploader_user_id=user.user_id,
    )
    try:
        rows = parse_bcct_workbook(blob)
    except BcctParseError as e:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s", (str(e), upload_id))
        raise HTTPException(400, f"Parse error: {e}")
    parser = internal_code_parser_for(dncx_id, dncx["code_resolution_mode"])
    n = _insert_bcct(dncx_id=dncx_id, year=year, rows=rows, upload_id=upload_id, parser=parser)
    resolve_for_dncx(dncx_id)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("update hub.file_uploads set parse_status='done', row_count=%s, parsed_at=now() where upload_id=%s", (n, upload_id))
    return RedirectResponse(url=f"/bcct?dncx_id={dncx_id}&year={year}", status_code=303)


def _insert_bcct(*, dncx_id: str, year: int, rows: list[dict],
                 upload_id: str, parser) -> int:
    n = 0
    with connect() as conn:
        with conn.cursor() as cur:
            for r in rows:
                customs_code = r.get("customs_code")
                goods_name = r.get("goods_name") or ""
                internal_code = parser(goods_name) if parser else customs_code
                cur.execute(
                    """
                    insert into hub.bcct_rows
                      (dncx_id, year, transaction_key, line_no, declaration_no,
                       declaration_type, direction, registration_date, customs_code,
                       internal_code, goods_name, hs_code, quantity, unit, quantity_2, unit_2,
                       unit_price, total_value, currency, origin, invoice_ref,
                       upload_id, payload)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s::jsonb)
                    on conflict (dncx_id, year, transaction_key, line_no) do update set
                      declaration_no = excluded.declaration_no,
                      customs_code = excluded.customs_code,
                      internal_code = excluded.internal_code,
                      goods_name = excluded.goods_name,
                      quantity = excluded.quantity,
                      total_value = excluded.total_value,
                      upload_id = excluded.upload_id,
                      indexed_at = now()
                    """,
                    (
                        dncx_id, year, r["transaction_key"], r.get("line_no", "0"),
                        r.get("declaration_no"), r.get("declaration_type"),
                        r.get("direction"), r.get("registration_date"),
                        customs_code, internal_code, goods_name, r.get("hs_code"),
                        r.get("quantity"), r.get("unit"),
                        r.get("quantity_2"), r.get("unit_2"),
                        r.get("unit_price"), r.get("total_value"),
                        r.get("currency"), r.get("origin"), r.get("invoice_ref"),
                        upload_id, "{}",
                    ),
                )
                n += 1
    return n
