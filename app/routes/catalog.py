"""Catalog (Materials / Danh mục mã hàng) — nested under /clients/{client_id}/."""
from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth
from app.database import connect
from app.parsers.materials import parse_materials_workbook, MaterialsParseError
from app.routes.clients import get_client, stats_for_client
from app.storage import save_upload, sha256_bytes
from app.stores.staleness import freshness_for_template
from app.stores.uploads import record_upload

router = APIRouter()

CATEGORIES = ["nvl", "btp_sx", "btp_nm", "tp", "ccdc"]
PREVIEW_SAMPLE_ROWS = 20


@router.get("/clients/{client_id}/catalog", response_class=HTMLResponse)
async def list_view(
    request: Request, client_id: str,
    category: str | None = None, q: str | None = None,
    provenance: str | None = None,
):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    items = _query_materials(client_id=client_id, category=category, q=q,
                             provenance=provenance)
    counts = _category_counts(client_id)
    prov_counts = _provenance_counts(client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/catalog.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "items": items, "categories": CATEGORIES,
            "active_category": category, "q": q or "", "counts": counts,
            "active_provenance": provenance,
            "prov_counts": prov_counts,
            "freshness": freshness_for_template(request, client_id, "catalog"),
            "active_root": "clients", "active_tab": "catalog",
        },
    )


@router.get("/clients/{client_id}/catalog/upload", response_class=HTMLResponse)
async def upload_view(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
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
    """Parse + stash to upload_pending; redirect to preview for confirm.

    All upload paths route through preview before any DB write — staff sees
    parsed rows + counts before commit (Phase 2 universal-preview pattern).
    """
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
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
    pending_id = _stash_pending(
        client_id=client_id, upload_id=upload_id, parsed=rows,
        created_by=user.user_id,
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.file_uploads set parse_status='pending_preview', row_count=%s, parsed_at=now() where upload_id=%s",
                (len(rows), upload_id),
            )
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog/preview/{pending_id}",
        status_code=303,
    )


@router.get("/clients/{client_id}/catalog/preview/{pending_id}",
            response_class=HTMLResponse)
async def preview_view(request: Request, client_id: str, pending_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select parsed_rows, expires_at, created_at
                from hub.upload_pending
                where pending_id = %s and client_id = %s and module = 'catalog'
                """,
                (pending_id, client_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Pending upload not found or expired")
    parsed_rows, expires_at, created_at = row
    summary = _summarize_catalog(parsed_rows)
    return request.app.state.templates.TemplateResponse(
        request, "clients/catalog_preview.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "pending_id": pending_id,
            "summary": summary,
            "sample_rows": parsed_rows[:PREVIEW_SAMPLE_ROWS],
            "expires_at": expires_at, "created_at": created_at,
            "active_root": "clients", "active_tab": "catalog",
        },
    )


@router.post("/clients/{client_id}/catalog/preview/{pending_id}/confirm")
async def preview_confirm(request: Request, client_id: str, pending_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    with connect(user_id=user.user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from hub.upload_pending
                where pending_id = %s and client_id = %s and module = 'catalog'
                  and expires_at > now()
                returning parsed_rows, upload_id
                """,
                (pending_id, client_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Pending upload not found or expired")
            parsed_rows, upload_id = row
            n = _insert_materials_with_cursor(
                cur, client_id=client_id, rows=parsed_rows,
                upload_id=upload_id,
            )
            cur.execute(
                "update hub.file_uploads set parse_status='done', parsed_at=now() where upload_id=%s",
                (upload_id,),
            )
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog?ingested={n}", status_code=303,
    )


@router.post("/clients/{client_id}/catalog/preview/{pending_id}/reject")
async def preview_reject(request: Request, client_id: str, pending_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    with connect(user_id=user.user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from hub.upload_pending
                where pending_id = %s and client_id = %s and module = 'catalog'
                returning upload_id
                """,
                (pending_id, client_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Pending upload not found or expired")
            (upload_id,) = row
            cur.execute(
                "update hub.file_uploads set parse_status='rejected', parsed_at=now() where upload_id=%s",
                (upload_id,),
            )
    return RedirectResponse(
        url=f"/clients/{client_id}/catalog?rejected=1", status_code=303,
    )


def _stash_pending(*, client_id: str, upload_id: str,
                   parsed: list[dict], created_by: str | None) -> str:
    pending_id = secrets.token_urlsafe(16)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.upload_pending
                  (pending_id, client_id, module, upload_id,
                   parsed_rows, diff_summary, created_by)
                values (%s, %s, 'catalog', %s, %s::jsonb, '{}'::jsonb, %s)
                """,
                (pending_id, client_id, upload_id,
                 json.dumps(parsed, ensure_ascii=False, default=str),
                 created_by),
            )
    return pending_id


def _summarize_catalog(parsed_rows: list[dict]) -> dict:
    by_cat: dict[str, int] = {}
    by_status: dict[str, int] = {}
    n_with_customs = 0
    n_with_product = 0
    for r in parsed_rows:
        cat = r.get("category") or "—"
        by_cat[cat] = by_cat.get(cat, 0) + 1
        st = r.get("status") or "active"
        by_status[st] = by_status.get(st, 0) + 1
        if r.get("customs_code"):
            n_with_customs += 1
        if r.get("product_code"):
            n_with_product += 1
    return {
        "total": len(parsed_rows),
        "by_category": by_cat,
        "by_status": by_status,
        "n_with_customs_code": n_with_customs,
        "n_with_product_code": n_with_product,
    }


def _query_materials(*, client_id: str, category: str | None,
                     q: str | None, provenance: str | None = None) -> list[dict]:
    """Query catalog rows with provenance signals annotated.

    `provenance` filter values:
      - 'registered'     → only rows with registered_with_hq
      - 'unregistered'   → seen_in_bcct but NOT registered_with_hq (audit case)
      - 'user_added'     → user_added present
    """
    sql = """
        select m.customs_code, m.product_code, m.name, m.category, m.category_override,
               m.status, m.unit, m.hs_code, m.updated_at, m.provenance,
               (m.provenance ? 'registered_with_hq') as is_registered,
               (m.provenance ? 'seen_in_bcct') as is_seen_in_bcct,
               (m.provenance ? 'user_added') as is_user_added,
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
    if provenance == "registered":
        sql += " and (m.provenance ? 'registered_with_hq')"
    elif provenance == "unregistered":
        sql += (" and (m.provenance ? 'seen_in_bcct')"
                " and not (m.provenance ? 'registered_with_hq')")
    elif provenance == "user_added":
        sql += " and (m.provenance ? 'user_added')"
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


def _provenance_counts(client_id: str) -> dict:
    """Counts per provenance facet — drives the filter chip badges and
    the 'X codes seen on declaration but not registered' audit alarm."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                  count(*) as total,
                  count(*) filter (where provenance ? 'registered_with_hq') as registered,
                  count(*) filter (
                    where provenance ? 'seen_in_bcct'
                      and not provenance ? 'registered_with_hq') as unregistered,
                  count(*) filter (where provenance ? 'user_added') as user_added
                from hub.materials where client_id = %s
                """,
                (client_id,),
            )
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, cur.fetchone()))


def _category_counts(client_id: str) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select category, count(*) from hub.materials where client_id = %s group by category",
                (client_id,),
            )
            return dict(cur.fetchall())


def _insert_materials_with_cursor(cur, *, client_id: str, rows: list[dict],
                                  upload_id: str | None = None) -> int:
    """Insert materials on a shared cursor (for transactional confirm flow).

    `upload_id` (when set) is recorded inside provenance.registered_with_hq
    so staff can trace any catalog row back to the upload that registered
    it. Existing seen_in_bcct / user_added provenance keys are preserved
    via the jsonb || merge in the conflict branch.
    """
    n = 0
    for r in rows:
        cur.execute(
            """
            insert into hub.materials
              (client_id, customs_code, product_code, name, category, status,
               unit, hs_code, provenance)
            values (%s, %s, %s, %s, %s, %s, %s, %s,
                    jsonb_build_object('registered_with_hq',
                      jsonb_build_object('first_seen', to_char(now(), 'YYYY-MM-DD'),
                                         'source_upload_id', %s::text)))
            on conflict (client_id, customs_code) do update set
              product_code = excluded.product_code,
              name = excluded.name,
              category = excluded.category,
              status = excluded.status,
              unit = excluded.unit,
              hs_code = excluded.hs_code,
              -- Merge: registered_with_hq overwritten with this upload;
              -- other keys (seen_in_bcct, user_added) preserved.
              provenance = hub.materials.provenance || excluded.provenance,
              updated_at = now()
            """,
            (client_id, r["customs_code"], r.get("product_code"), r.get("name"),
             r["category"], r.get("status", "active"), r.get("unit"), r.get("hs_code"),
             upload_id),
        )
        n += 1
    return n


def _insert_materials(*, client_id: str, rows: list[dict]) -> int:
    """Standalone insert with a fresh connection (used by seed)."""
    with connect() as conn:
        with conn.cursor() as cur:
            return _insert_materials_with_cursor(cur, client_id=client_id, rows=rows)
