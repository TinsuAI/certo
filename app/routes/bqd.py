"""Code mappings (BQD = Bảng Quy Đổi) — nested under /clients/{client_id}/."""
from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth, llm
from app.database import connect
from app.parsers.code_mappings import parse_code_mappings_workbook, CodeMappingsParseError
from app.routes.clients import get_client, stats_for_client
from app.routes._llm_fallback import (
    cache_confirmed_mapping,
    headers_per_sheet,
    lookup_cached_mapping,
    record_mapping_use,
    request_llm_mapping,
)
from app.parsers._excel import compute_file_signature
from app.storage import save_upload, sha256_bytes
from app.stores.staleness import freshness_for_template
from app.stores.uploads import record_upload

router = APIRouter()

PREVIEW_SAMPLE_ROWS = 20


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
            "freshness": freshness_for_template(request, client_id, "bqd"),
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
    """Parse + stash to upload_pending; redirect to preview for confirm.

    All upload paths route through preview before any DB write — staff sees
    parsed rows + counts before commit. Same pattern as BCCT confirm-on-update
    gate, simpler payload (no diff vs DB; BQD is upsert-on-conflict).
    """
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

    # ── Step 1: cached mapping for this client + file shape? ──
    file_signature: str | None = None
    cached_mapping: dict | None = None
    try:
        sheets = headers_per_sheet(blob)
        if sheets:
            file_signature = compute_file_signature(
                client_id=client_id, module="bqd", headers_per_sheet=sheets,
            )
            cached_mapping = lookup_cached_mapping(
                client_id=client_id, module="bqd", file_signature=file_signature,
            )
    except Exception:  # noqa: BLE001 — best-effort
        pass

    # ── Step 2: parse — cached mapping if present, else rigid, else LLM ──
    rows: list[dict] | None = None
    rigid_error: str | None = None
    used_mapping: dict[str, str] | None = None
    proposed_by = "rigid"
    if cached_mapping is not None:
        try:
            rows = parse_code_mappings_workbook(blob, mapping_override=cached_mapping)
            record_mapping_use(client_id=client_id, module="bqd", file_signature=file_signature)
            used_mapping = cached_mapping
            proposed_by = "llm_cached"
        except CodeMappingsParseError as e:
            rigid_error = f"cached mapping failed: {e}"
    if rows is None:
        try:
            rows = parse_code_mappings_workbook(blob)
        except CodeMappingsParseError as e:
            rigid_error = str(e)

    if rows is None:
        # Rigid + cached both failed. Fall back to LLM.
        try:
            mapping, _headers, _sample, file_sig = request_llm_mapping(
                client_id=client_id, module="bqd", blob=blob,
                rigid_error=rigid_error or "unknown",
            )
        except (llm.LLMUnavailable, llm.LLMProposalError) as e:
            with connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s",
                        (f"{rigid_error}; LLM: {type(e).__name__}: {e}", upload_id),
                    )
            raise HTTPException(400, str(e))
        try:
            rows = parse_code_mappings_workbook(blob, mapping_override=mapping)
        except CodeMappingsParseError as e:
            with connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s",
                        (f"LLM mapping unparseable: {e}", upload_id),
                    )
            raise HTTPException(400, f"LLM mapping rejected by parser: {e}")
        used_mapping = mapping
        file_signature = file_sig
        proposed_by = "llm_proposed"

    pending_id = _stash_pending(
        client_id=client_id, upload_id=upload_id, parsed=rows,
        created_by=user.user_id, used_mapping=used_mapping,
        file_signature=file_signature, proposed_by=proposed_by,
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.file_uploads set parse_status='pending_preview', row_count=%s, parsed_at=now() where upload_id=%s",
                (len(rows), upload_id),
            )
    return RedirectResponse(
        url=f"/clients/{client_id}/bqd/preview/{pending_id}",
        status_code=303,
    )


@router.get("/clients/{client_id}/bqd/preview/{pending_id}",
            response_class=HTMLResponse)
async def preview_view(request: Request, client_id: str, pending_id: str):
    """Render preview: counters + sample rows. Staff confirms or rejects."""
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
                where pending_id = %s and client_id = %s and module = 'bqd'
                """,
                (pending_id, client_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Pending upload not found or expired")
    parsed_rows, expires_at, created_at = row
    summary = _summarize_bqd(parsed_rows)
    return request.app.state.templates.TemplateResponse(
        request, "clients/bqd_preview.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "pending_id": pending_id,
            "summary": summary,
            "sample_rows": parsed_rows[:PREVIEW_SAMPLE_ROWS],
            "expires_at": expires_at, "created_at": created_at,
            "active_root": "clients", "active_tab": "bqd",
        },
    )


@router.post("/clients/{client_id}/bqd/preview/{pending_id}/confirm")
async def preview_confirm(request: Request, client_id: str, pending_id: str):
    """Apply stashed BQD upload. Single-use: DELETE in same tx as load."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    with connect(user_id=user.user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from hub.upload_pending
                where pending_id = %s and client_id = %s and module = 'bqd'
                  and expires_at > now()
                returning parsed_rows, diff_summary, upload_id
                """,
                (pending_id, client_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Pending upload not found or expired")
            parsed_rows, diff_summary, upload_id = row
            n = _insert_mappings_with_cursor(
                cur, client_id=client_id, rows=parsed_rows,
            )
            cur.execute(
                "update hub.file_uploads set parse_status='done', parsed_at=now() where upload_id=%s",
                (upload_id,),
            )
    # If this upload used an LLM-proposed mapping, persist it now (the
    # staff just verified the resulting rows looked correct in preview).
    if (diff_summary or {}).get("proposed_by") == "llm_proposed":
        used_mapping = diff_summary.get("used_mapping")
        file_signature = diff_summary.get("file_signature")
        if used_mapping and file_signature:
            cache_confirmed_mapping(
                client_id=client_id, module="bqd",
                file_signature=file_signature, mapping=used_mapping,
                headers=list(used_mapping.keys()),
                confirmed_by_user_id=user.user_id, proposed_by="llm",
            )
    return RedirectResponse(
        url=f"/clients/{client_id}/bqd?ingested={n}", status_code=303,
    )


@router.post("/clients/{client_id}/bqd/preview/{pending_id}/reject")
async def preview_reject(request: Request, client_id: str, pending_id: str):
    """Reject stashed upload — discard pending row + mark file_upload errored."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    with connect(user_id=user.user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from hub.upload_pending
                where pending_id = %s and client_id = %s and module = 'bqd'
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
        url=f"/clients/{client_id}/bqd?rejected=1", status_code=303,
    )


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
    with connect() as conn:
        with conn.cursor() as cur:
            _insert_mappings_with_cursor(
                cur,
                client_id=client_id,
                rows=[{
                    "internal_code": internal_code.strip(),
                    "customs_code": customs_code.strip(),
                    "category": category.strip() or None,
                    "notes": notes.strip() or None,
                }],
            )
    return RedirectResponse(url=f"/clients/{client_id}/bqd", status_code=303)


# ── helpers ────────────────────────────────────────────────────────────────

def _stash_pending(*, client_id: str, upload_id: str,
                   parsed: list[dict], created_by: str | None,
                   used_mapping: dict[str, str] | None = None,
                   file_signature: str | None = None,
                   proposed_by: str = "rigid") -> str:
    """Insert parsed rows into upload_pending; return new pending_id.

    `used_mapping` / `file_signature` / `proposed_by` carry LLM-proposal
    state into the preview→confirm flow. On confirm, an LLM-proposed
    mapping is persisted to parser_mappings (cache hit on future uploads).
    """
    pending_id = secrets.token_urlsafe(16)
    diff_summary = {
        "used_mapping": used_mapping,
        "file_signature": file_signature,
        "proposed_by": proposed_by,
    }
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.upload_pending
                  (pending_id, client_id, module, upload_id,
                   parsed_rows, diff_summary, created_by)
                values (%s, %s, 'bqd', %s, %s::jsonb, %s::jsonb, %s)
                """,
                (pending_id, client_id, upload_id,
                 json.dumps(parsed, ensure_ascii=False, default=str),
                 json.dumps(diff_summary, ensure_ascii=False, default=str),
                 created_by),
            )
    return pending_id


def _summarize_bqd(parsed_rows: list[dict]) -> dict:
    """Counts for the preview header strip — total + per-category breakdown."""
    by_cat: dict[str, int] = {}
    distinct_internal: set[str] = set()
    distinct_customs: set[str] = set()
    for r in parsed_rows:
        cat = r.get("category") or "—"
        by_cat[cat] = by_cat.get(cat, 0) + 1
        distinct_internal.add(r["internal_code"])
        distinct_customs.add(r["customs_code"])
    return {
        "total": len(parsed_rows),
        "by_category": by_cat,
        "n_distinct_internal": len(distinct_internal),
        "n_distinct_customs": len(distinct_customs),
        "n_one_to_many": sum(
            1 for ic in distinct_internal
            if sum(1 for r in parsed_rows if r["internal_code"] == ic) > 1
        ),
    }


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


def _insert_mappings_with_cursor(cur, *, client_id: str, rows: list[dict]) -> int:
    """Insert mappings on a shared cursor (for transactional confirm flow)."""
    n = 0
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


def _insert_mappings(*, client_id: str, rows: list[dict]) -> int:
    """Standalone insert with a fresh connection (used by seed).

    Most upload paths go through `_insert_mappings_with_cursor` inside the
    confirm transaction. This wrapper is for non-transactional callers.
    """
    with connect() as conn:
        with conn.cursor() as cur:
            return _insert_mappings_with_cursor(cur, client_id=client_id, rows=rows)
