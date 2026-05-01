"""BCCT routes — nested under /clients/{client_id}/."""
from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth, llm
from app.database import connect
from app.parsers._excel import compute_file_signature, header_row, load_xlsx
from app.parsers.bcct import parse_bcct_workbook, BcctParseError
from app.parsers.goods_name import internal_code_parser_for
from app.routes.clients import get_client, stats_for_client
from app.storage import save_upload, sha256_bytes
from app.stores.uploads import record_upload

router = APIRouter()


def _headers_per_sheet(blob: bytes) -> list[list[str]]:
    """Extract the best header row from each sheet for signature + LLM input."""
    wb = load_xlsx(blob)
    out: list[list[str]] = []
    for ws in wb.worksheets:
        hdr = header_row(ws, max_scan=20)
        if hdr:
            out.append([h for h in hdr[1] if h])
    return out


def _sample_rows_first_sheet(blob: bytes, n: int = 5) -> tuple[list[str], list[list]]:
    """Return (headers, first n data rows) of the first plausible sheet — used
    to brief the LLM."""
    wb = load_xlsx(blob)
    for ws in wb.worksheets:
        hdr = header_row(ws, max_scan=20)
        if not hdr:
            continue
        header_idx, headers = hdr
        rows: list[list] = []
        for raw in ws.iter_rows(min_row=header_idx + 1, values_only=True):
            if all(c is None or (isinstance(c, str) and not c.strip()) for c in raw):
                continue
            rows.append(list(raw))
            if len(rows) >= n:
                break
        return [h for h in headers if h], rows
    return [], []


def _lookup_cached_mapping(*, client_id: str, file_signature: str) -> dict | None:
    """Read-only lookup. `use_count` is incremented separately by
    `_record_mapping_use` only AFTER the cached mapping was actually
    used to parse successfully — otherwise the counter overcounts when
    cached mapping fails and the route falls back to rigid (or LLM)."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select mapping from hub.parser_mappings
                where client_id = %s and module = 'bcct' and file_signature = %s
                  and confirmed_at is not null
                """,
                (client_id, file_signature),
            )
            row = cur.fetchone()
            return row[0] if row else None


def _record_mapping_use(*, client_id: str, file_signature: str) -> None:
    """Bump usage counter after a cached mapping successfully parses."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.parser_mappings
                  set use_count = use_count + 1, last_used_at = now()
                where client_id = %s and module = 'bcct' and file_signature = %s
                """,
                (client_id, file_signature),
            )


@router.get("/clients/{client_id}/bcct", response_class=HTMLResponse)
async def list_view(request: Request, client_id: str,
                    year: int | None = None, direction: str | None = None,
                    q: str | None = None,
                    ingested: int | None = None,
                    new: int | None = None,
                    updated: int | None = None,
                    deleted: int | None = None,
                    noop: int | None = None,
                    skipped: int | None = None):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    items = _list_bcct(client_id, year, direction, q)
    years = _years(client_id)
    upload_summary = None
    if ingested is not None:
        upload_summary = {
            "ingested": ingested or 0,
            "new": new or 0, "updated": updated or 0,
            "deleted": deleted or 0, "noop": noop or 0,
            "skipped": skipped or 0,
        }
    return request.app.state.templates.TemplateResponse(
        request, "clients/bcct.html",
        {"client": client, "stats": stats_for_client(client_id),
         "items": items, "years": years,
         "year": year, "direction": direction, "q": q or "",
         "upload_summary": upload_summary,
         "active_root": "clients", "active_tab": "bcct"},
    )


@router.get("/clients/{client_id}/bcct/upload", response_class=HTMLResponse)
async def upload_view(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/bcct_upload.html",
        {"client": client, "stats": stats_for_client(client_id),
         "active_root": "clients", "active_tab": "bcct"},
    )


@router.post("/clients/{client_id}/bcct/upload")
async def upload_submit(request: Request, client_id: str,
                        file: UploadFile = File(...)):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    blob = await file.read()
    sha = sha256_bytes(blob)
    stored = save_upload(blob, filename=file.filename or "bcct.xlsx",
                         module="bcct", client_id=client_id)
    upload_id = record_upload(
        client_id=client_id, module="bcct",
        original_filename=file.filename or "bcct.xlsx",
        stored_path=stored.path, content_sha256=sha, size_bytes=len(blob),
        mime_type=file.content_type, uploader_user_id=user.user_id,
    )

    # ── Step 1: cached parser_mapping for this client + file shape? ──
    file_signature = None
    cached_mapping = None
    try:
        sheets = _headers_per_sheet(blob)
        if sheets:
            file_signature = compute_file_signature(
                client_id=client_id, module="bcct",
                headers_per_sheet=sheets,
            )
            cached_mapping = _lookup_cached_mapping(
                client_id=client_id, file_signature=file_signature,
            )
    except Exception:  # noqa: BLE001 — best-effort; falls through to rigid
        pass

    # ── Step 2: parse — cached mapping if present, else rigid, else LLM ──
    rows: list[dict] | None = None
    rigid_error: str | None = None
    if cached_mapping is not None:
        try:
            rows = parse_bcct_workbook(blob, mapping_override=cached_mapping)
            _record_mapping_use(client_id=client_id, file_signature=file_signature)
        except BcctParseError as e:
            rigid_error = f"cached mapping failed: {e}"
    if rows is None:
        try:
            rows = parse_bcct_workbook(blob)
        except BcctParseError as e:
            rigid_error = str(e)

    if rows is None:
        # Rigid + cached both failed. Fall back to LLM if enabled.
        return await _request_llm_mapping(
            request, client_id=client_id, upload_id=upload_id,
            blob=blob, file_signature=file_signature,
            rigid_error=rigid_error or "unknown",
        )

    # Stash request.state.user for downstream ingest/audit attribution.
    request.state.user = user
    return _ingest_rows(
        client_id=client_id, client=client,
        rows=rows, upload_id=upload_id, request=request,
    )


def _ingest_rows(*, client_id: str, client: dict, rows: list[dict],
                 upload_id: str, request: Request | None = None,
                 confirm_diffs: bool = False, confirm_orphans: bool = False,
                 ) -> RedirectResponse:
    """Ingest parsed BCCT rows. If existing rows would change (DIFF) or
    rows in DB scope are missing from upload (ORPHAN), block and route to
    a preview-confirm flow unless confirm_* flags are explicitly set.

    confirm_diffs=False (default): UPDATE on existing rows is gated. NEW-only
    uploads still flow straight through.
    """
    parser = internal_code_parser_for(client_id, client["code_resolution_mode"])
    rows_with_date = [r for r in rows if r.get("registration_date")]
    skipped = len(rows) - len(rows_with_date)

    diff_summary = _classify_rows(client_id=client_id, parsed=rows_with_date,
                                  parser=parser)

    needs_confirm = bool(diff_summary["diff"]) or bool(diff_summary["orphan"])
    if needs_confirm and not (confirm_diffs and confirm_orphans):
        # Stash for staff confirm. Preserve user_id of the uploader so
        # confirm step can attribute changes correctly.
        actor_id = request.state.user.user_id if (request and hasattr(request.state, "user")) else None
        pending_id = _stash_pending(
            client_id=client_id, upload_id=upload_id, parsed=rows_with_date,
            diff_summary=diff_summary, created_by=actor_id,
        )
        return RedirectResponse(
            url=f"/clients/{client_id}/bcct/upload/preview/{pending_id}",
            status_code=303,
        )

    # NEW-only OR confirmed → apply.
    user_id = request.state.user.user_id if (request and hasattr(request.state, "user")) else None
    n = _apply_bcct_rows(client_id=client_id, rows=rows_with_date,
                        upload_id=upload_id, parser=parser,
                        orphans_to_delete=diff_summary["orphan"] if confirm_orphans else [],
                        user_id=user_id)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.file_uploads set parse_status='done', row_count=%s, parsed_at=now() where upload_id=%s",
                (n, upload_id))
    # Return query string so the list view can flash a toast. Counts:
    #   ingested = total rows applied (insert+update)
    #   new      = brand-new rows (DB had nothing at this PK)
    #   updated  = existing rows confirmed for overwrite
    #   noop     = identical rows (skipped silently)
    #   skipped  = rows missing registration_date (rejected)
    new_count = diff_summary.get("new", 0)
    updated_count = len(diff_summary.get("diff", [])) if confirm_diffs else 0
    deleted_count = len(diff_summary.get("orphan", [])) if confirm_orphans else 0
    noop_count = diff_summary.get("noop", 0)
    qs = (
        f"?ingested={n}&new={new_count}&updated={updated_count}"
        f"&deleted={deleted_count}&noop={noop_count}"
    )
    if skipped:
        qs += f"&skipped={skipped}"
    return RedirectResponse(url=f"/clients/{client_id}/bcct{qs}",
                            status_code=303)


# Fields whose change matters for the diff. Excludes purely-derived fields
# (year is GENERATED) and bookkeeping (upload_id, indexed_at).
_DIFF_FIELDS = (
    "declaration_no", "declaration_type", "direction", "customs_code",
    "internal_code", "goods_name", "hs_code", "quantity", "unit", "total_value",
    "currency", "origin", "invoice_ref",
    "exporter_name", "exporter_tax_code", "consignee_name", "incoterms",
    "weight", "weight_unit", "package_count", "package_unit",
    "invoice_date", "departure_date",
    "destination_code", "destination_name",
    "transport_mode", "exchange_rate",
)


def _classify_rows(*, client_id: str, parsed: list[dict], parser) -> dict:
    """Categorize parsed rows vs DB state. Returns:
        {new: int, noop: int, diff: list[{key, old, new, changed_fields}],
         orphan: list[{key, decl_no, line_no}], total: int}
    Orphans are scoped to declarations present in the upload (per critic):
    a partial re-upload of just one declaration shouldn't soft-delete others.
    """
    if not parsed:
        return {"new": 0, "noop": 0, "diff": [], "orphan": [], "total": 0}
    keys_in_upload: set[tuple[str, str]] = set()
    decl_nos_in_upload: set[str] = set()
    rows_by_key: dict[tuple[str, str], dict] = {}
    for r in parsed:
        decl = r.get("declaration_no")
        line = r.get("line_no", "0")
        txn = r.get("transaction_key")
        keys_in_upload.add((txn, line))
        if decl:
            decl_nos_in_upload.add(decl)
        rows_by_key[(txn, line)] = r

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select transaction_key, line_no, declaration_no, "
                "       declaration_type, direction, customs_code, internal_code, "
                "       goods_name, hs_code, quantity, unit, total_value, currency, "
                "       origin, invoice_ref, "
                "       exporter_name, exporter_tax_code, consignee_name, incoterms, "
                "       weight, weight_unit, package_count, package_unit, "
                "       invoice_date, departure_date, "
                "       destination_code, destination_name, "
                "       transport_mode, exchange_rate "
                "from hub.bcct_rows where client_id = %s "
                "  and declaration_no = any(%s)",
                (client_id, list(decl_nos_in_upload) if decl_nos_in_upload else [None]),
            )
            db_rows = {(r[0], r[1]): r for r in cur.fetchall()}

    diff: list[dict] = []
    orphan: list[dict] = []
    new_count = 0
    noop_count = 0

    db_field_names = list(_DIFF_FIELDS)

    for key, parsed_row in rows_by_key.items():
        db_row = db_rows.get(key)
        if db_row is None:
            new_count += 1
            continue
        # Compute internal_code the same way _apply_bcct_rows will so we
        # don't false-flag identity-mode rows as DIFF.
        if parser is None:
            parsed_internal = parsed_row.get("customs_code")
        else:
            parsed_internal = parser(parsed_row.get("goods_name") or "")
        # db_row layout: (txn, line, then _DIFF_FIELDS in order)
        db_dict = dict(zip(["transaction_key", "line_no"] + db_field_names, db_row))
        merged_parsed = dict(parsed_row)
        merged_parsed["internal_code"] = parsed_internal
        changed: list[str] = []
        for f in _DIFF_FIELDS:
            old_v = db_dict.get(f)
            new_v = merged_parsed.get(f)
            if _coerce(old_v) != _coerce(new_v):
                changed.append(f)
        if not changed:
            noop_count += 1
        else:
            diff.append({
                "key": list(key),
                "decl_no": parsed_row.get("declaration_no"),
                "line_no": parsed_row.get("line_no"),
                "old": {f: _serialize(db_dict.get(f)) for f in changed},
                "new": {f: _serialize(merged_parsed.get(f)) for f in changed},
                "changed_fields": changed,
            })

    # Orphans: rows in DB whose declaration_no is in upload but key not in upload.
    for db_key, db_row in db_rows.items():
        if db_key not in keys_in_upload:
            orphan.append({
                "key": list(db_key),
                "decl_no": db_row[2],
                "line_no": db_row[1],
            })

    return {
        "new": new_count, "noop": noop_count,
        "diff": diff, "orphan": orphan,
        "total": len(parsed),
    }


def _coerce(v):
    """Cross-type comparison helper for diff. Decimal vs float etc."""
    from decimal import Decimal
    if v is None or v == "":
        return None
    if isinstance(v, (int, Decimal, float)):
        return float(v)
    return str(v).strip()


def _serialize(v):
    """JSON-safe serialize for stashed diff payload."""
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    from decimal import Decimal
    if isinstance(v, Decimal):
        return float(v)
    return v


def _stash_pending(*, client_id: str, upload_id: str, parsed: list[dict],
                   diff_summary: dict, created_by: str | None) -> str:
    """Insert into upload_pending; return the new pending_id."""
    import secrets
    pending_id = secrets.token_urlsafe(16)
    serialized_rows = [
        {k: _serialize(v) for k, v in r.items()}
        for r in parsed
    ]
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.upload_pending
                  (pending_id, client_id, module, upload_id, parsed_rows,
                   diff_summary, created_by)
                values (%s, %s, 'bcct', %s, %s::jsonb, %s::jsonb, %s)
                """,
                (pending_id, client_id, upload_id,
                 json.dumps(serialized_rows, ensure_ascii=False, default=str),
                 json.dumps(diff_summary, ensure_ascii=False, default=str),
                 created_by),
            )
    return pending_id


def _apply_bcct_rows(*, client_id: str, rows: list[dict], upload_id: str | None,
                    parser, orphans_to_delete: list[dict],
                    user_id: str | None) -> int:
    """Insert/update parsed rows; delete confirmed orphans. SHARED CONNECTION
    so the whole apply runs in a single transaction — partial failure
    (insert succeeds, delete crashes) cannot leave the DB inconsistent.
    """
    with connect(user_id=user_id) as conn:
        with conn.cursor() as cur:
            n = _insert_bcct_with_cursor(
                cur, client_id=client_id, rows=rows,
                upload_id=upload_id, parser=parser,
            )
            for o in orphans_to_delete:
                txn, line = o["key"]
                cur.execute(
                    "delete from hub.bcct_rows where client_id=%s "
                    "  and transaction_key=%s and line_no=%s",
                    (client_id, txn, line),
                )
    return n


async def _request_llm_mapping(
    request: Request, *, client_id: str, upload_id: str,
    blob: bytes, file_signature: str | None, rigid_error: str,
) -> RedirectResponse:
    """When rigid+cache fail, ask the LLM for a mapping proposal. Stash on
    the upload row; redirect to the propose UI for staff confirmation."""
    cfg = llm.LLMConfig.load()
    if not cfg.is_enabled():
        # LLM not configured. Tell the user directly + point at the
        # settings page. Don't conflate with a configured-but-failed call.
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s",
                    (rigid_error, upload_id))
        raise HTTPException(
            400,
            f"File không khớp parser tự động: {rigid_error}. "
            f"Bật LLM Smart Parser ở /admin/settings/technical hoặc upload "
            f"file đúng format BCCT.",
        )
    if file_signature is None:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s",
                    (rigid_error, upload_id))
        raise HTTPException(
            400,
            f"File không có sheet nhận được header (rỗng?): {rigid_error}",
        )

    headers, sample_rows = _sample_rows_first_sheet(blob)
    try:
        proposed = llm.propose_header_mapping(
            client_id=client_id, module="bcct",
            headers=headers, sample_rows=sample_rows, cfg=cfg,
        )
    except (llm.LLMUnavailable, llm.LLMProposalError) as e:
        # LLM IS configured but the call failed. Could be: bad model
        # name, wrong base_url, timeout, malformed response, budget
        # exceeded, etc. Log full detail server-side; surface a useful
        # message that points at where to fix it without echoing the
        # raw SDK error (which on some lib versions includes the
        # request URL + Authorization header).
        import logging
        logging.getLogger(__name__).exception("LLM proposal failed")
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s",
                    (f"{rigid_error}; LLM: {type(e).__name__}: {e}", upload_id))
        # Friendlier surface message — point at settings + upload-audit
        # for full server log. Type name is safe to show.
        kind = type(e).__name__
        raise HTTPException(
            400,
            f"Parser cứng từ chối + LLM gọi không thành công ({kind}). "
            f"Kiểm tra cấu hình tại /admin/settings/technical "
            f"(base_url, model, api_key) hoặc xem chi tiết tại "
            f"/clients/{client_id}/uploads.",
        )

    payload = {
        "file_signature": file_signature,
        "proposed_mapping": proposed,
        "headers": headers,
        "sample_rows": sample_rows[:5],
        "rigid_error": rigid_error,
    }
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.file_uploads
                  set parse_status='proposed_mapping', result=%s::jsonb, parsed_at=now()
                where upload_id=%s
                """,
                (json.dumps(payload, ensure_ascii=False, default=str), upload_id),
            )
    return RedirectResponse(
        url=f"/clients/{client_id}/bcct/parse-mapping/{upload_id}",
        status_code=303,
    )


@router.get("/clients/{client_id}/bcct/parse-mapping/{upload_id}",
            response_class=HTMLResponse)
async def parse_mapping_view(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select original_filename, parse_status, result
                from hub.file_uploads
                where upload_id=%s and client_id=%s and module='bcct'
                """,
                (upload_id, client_id),
            )
            row = cur.fetchone()
    if not row or row[1] != "proposed_mapping":
        raise HTTPException(404, "No pending mapping for this upload")
    filename, _, result = row
    # Pull the canonical logical-field list for BCCT so the template can
    # render a <select> instead of a free-text input.
    from app.llm import _TARGET_FIELDS_BY_MODULE
    return request.app.state.templates.TemplateResponse(
        request, "clients/bcct_parse_mapping.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "upload_id": upload_id, "filename": filename,
            "headers": result.get("headers", []),
            "samples": result.get("sample_rows", []),
            "proposed": result.get("proposed_mapping", {}),
            "rigid_error": result.get("rigid_error", ""),
            "logical_fields": _TARGET_FIELDS_BY_MODULE["bcct"],
            "active_root": "clients", "active_tab": "bcct",
        },
    )


@router.post("/clients/{client_id}/bcct/parse-mapping/{upload_id}/reject")
async def parse_mapping_reject(request: Request, client_id: str, upload_id: str):
    """Staff explicitly says 'this file isn't BCCT'. Mark the upload as
    rejected so it shows up cleanly in the audit page; do NOT save any
    LLM mapping (mapping was speculative and shouldn't influence future
    uploads of the same shape — they may genuinely be valid for this
    client even though this one upload was misrouted)."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    form = await request.form()
    note = (form.get("reject_note") or "Rejected via parse-mapping UI").strip()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.file_uploads
                  set parse_status='rejected',
                      parse_error=%s,
                      parsed_at=now()
                where upload_id=%s and client_id=%s and module='bcct'
                  and parse_status='proposed_mapping'
                returning upload_id
                """,
                (f"{note} (by {user.user_id})", upload_id, client_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Pending mapping not found or already resolved")
    return RedirectResponse(
        url=f"/clients/{client_id}/uploads?module=bcct", status_code=303,
    )


@router.post("/clients/{client_id}/bcct/parse-mapping/{upload_id}/confirm")
async def parse_mapping_confirm(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select stored_path, parse_status, result
                from hub.file_uploads
                where upload_id=%s and client_id=%s and module='bcct'
                """,
                (upload_id, client_id),
            )
            row = cur.fetchone()
    if not row or row[1] != "proposed_mapping":
        raise HTTPException(404, "No pending mapping for this upload")
    stored_path, _, result = row

    form = await request.form()
    # Per-header overrides: any field named map__<header> in the form.
    mapping: dict[str, str] = {}
    for k, v in form.items():
        if k.startswith("map__"):
            header = k[5:]
            field = (v or "").strip()
            if field:
                mapping[header] = field
    if not mapping:
        raise HTTPException(400, "No fields confirmed; cancel and try again.")

    file_signature = result.get("file_signature")
    # Persist mapping for future uploads of the same shape
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.parser_mappings
                  (client_id, module, file_signature, mapping, sample_headers,
                   proposed_by, confirmed_by, confirmed_at)
                values (%s, 'bcct', %s, %s::jsonb, %s::jsonb, 'llm', %s, now())
                on conflict (client_id, module, file_signature) do update set
                  mapping = excluded.mapping,
                  confirmed_by = excluded.confirmed_by,
                  confirmed_at = now()
                """,
                (client_id, file_signature, json.dumps(mapping, ensure_ascii=False),
                 json.dumps(result.get("headers", [])), user.user_id),
            )

    # Re-read the original blob from disk (LocalFS for now) and parse with the mapping.
    from pathlib import Path
    try:
        blob = Path(stored_path).read_bytes()
    except FileNotFoundError:
        # Blob missing (cleanup, FS issue, manually deleted). The
        # file_uploads row still exists; mark it errored and tell the
        # user instead of 500-ing.
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update hub.file_uploads set parse_status='error', "
                    "  parse_error=%s, parsed_at=now() where upload_id=%s",
                    (f"Stored blob missing: {stored_path}", upload_id),
                )
        raise HTTPException(
            410,
            "File blob đã không còn trong storage. Hãy upload lại file.",
        )
    rows = parse_bcct_workbook(blob, mapping_override=mapping)
    request.state.user = user
    return _ingest_rows(client_id=client_id, client=client,
                        rows=rows, upload_id=upload_id, request=request)


# ── Confirm-on-update preview/confirm routes ─────────────────────────────

@router.get("/clients/{client_id}/bcct/upload/preview/{pending_id}",
            response_class=HTMLResponse)
async def upload_preview_view(request: Request, client_id: str, pending_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select diff_summary, expires_at, created_at
                from hub.upload_pending
                where pending_id = %s and client_id = %s and module = 'bcct'
                """,
                (pending_id, client_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Pending upload not found or expired")
    diff_summary, expires_at, created_at = row
    return request.app.state.templates.TemplateResponse(
        request, "clients/bcct_upload_preview.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "pending_id": pending_id,
            "summary": diff_summary,
            "expires_at": expires_at, "created_at": created_at,
            "active_root": "clients", "active_tab": "bcct",
        },
    )


@router.get("/clients/{client_id}/bcct/history/{transaction_key}/{line_no}",
            response_class=HTMLResponse)
async def bcct_row_history(request: Request, client_id: str,
                           transaction_key: str, line_no: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    with connect() as conn:
        with conn.cursor() as cur:
            # LEFT JOIN hub.users so 'Ai' column shows the human's email +
            # display_name, not the raw u_xxx id. Sentinel actors
            # ('system', 'ops:script') don't match a user row → JOIN
            # returns NULL on email/name and template falls back to raw.
            cur.execute(
                """
                select h.action, h.changed_by, h.changed_at, h.upload_id,
                       h.old_row, h.new_row,
                       u.email as actor_email,
                       u.display_name as actor_display_name
                from hub.bcct_row_history h
                left join hub.users u on u.user_id = h.changed_by
                where h.client_id = %s and h.transaction_key = %s
                  and h.line_no = %s
                order by h.changed_at desc
                limit 200
                """,
                (client_id, transaction_key, line_no),
            )
            cols = [d[0] for d in cur.description]
            events = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.execute(
                """
                select declaration_no, registration_date, customs_code,
                       internal_code, goods_name, quantity, unit, total_value
                from hub.bcct_rows
                where client_id = %s and transaction_key = %s and line_no = %s
                """,
                (client_id, transaction_key, line_no),
            )
            current_row = cur.fetchone()
    # Compute changed fields per event for the template
    for ev in events:
        old_row = ev.get("old_row") or {}
        new_row = ev.get("new_row") or {}
        if ev["action"] == "delete":
            ev["changed_fields"] = list(old_row.keys())
        else:
            ev["changed_fields"] = sorted(
                k for k in (old_row.keys() | new_row.keys())
                if old_row.get(k) != new_row.get(k)
            )
    return request.app.state.templates.TemplateResponse(
        request, "clients/bcct_history.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "transaction_key": transaction_key, "line_no": line_no,
            "events": events,
            "current_row": current_row,
            "active_root": "clients", "active_tab": "bcct",
        },
    )


@router.post("/clients/{client_id}/bcct/upload/preview/{pending_id}/confirm")
async def upload_preview_confirm(request: Request, client_id: str, pending_id: str):
    """Apply a stashed upload, honouring the user's confirm choices.

    CRITICAL: this path uses the *stashed* diff_summary as the single source
    of truth for what's NEW / DIFF / ORPHAN. It does NOT re-classify after
    filtering rows, because filtering would turn unconfirmed-DIFF rows into
    new ORPHANs (they're now missing from `rows`), and a `confirm_orphans=
    True` would then DELETE rows the user explicitly chose to preserve.
    """
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")

    form = await request.form()
    confirm_diffs = form.get("confirm_diffs") == "on"
    confirm_orphans = form.get("confirm_orphans") == "on"

    # Single-use: DELETE in same tx as load. Double-click → second click 404s.
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from hub.upload_pending
                where pending_id = %s and client_id = %s and module = 'bcct'
                returning upload_id, parsed_rows, diff_summary
                """,
                (pending_id, client_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Pending upload not found or already applied")
    upload_id, parsed_rows, diff_summary = row

    # parsed_rows is jsonb so dates come back as strings; coerce back to
    # date for the DB insert.
    from datetime import date as _date
    def _restore_dates(r):
        for k in ("registration_date", "invoice_date", "departure_date"):
            v = r.get(k)
            if isinstance(v, str) and len(v) >= 10:
                try:
                    r[k] = _date.fromisoformat(v[:10])
                except ValueError:
                    r[k] = None
        return r
    parsed_rows = [_restore_dates(r) for r in parsed_rows]

    # Use stashed diff to bucket rows. Don't re-classify.
    diff_keys = {tuple(d["key"]) for d in diff_summary.get("diff", [])}
    # Rows to apply:
    #   • all NEW + NOOP rows (always — NOOPs are no-op upserts, NEWs insert)
    #   • DIFF rows iff confirm_diffs (otherwise the existing DB row is
    #     left untouched)
    rows_to_apply: list[dict] = []
    for r in parsed_rows:
        key = (r.get("transaction_key"), r.get("line_no", "0"))
        if key in diff_keys:
            if confirm_diffs:
                rows_to_apply.append(r)
            # else: skip — leave DB row as-is
        else:
            rows_to_apply.append(r)

    orphans_to_delete = diff_summary.get("orphan", []) if confirm_orphans else []

    parser = internal_code_parser_for(client_id, client["code_resolution_mode"])
    n = _apply_bcct_rows(
        client_id=client_id, rows=rows_to_apply, upload_id=upload_id,
        parser=parser, orphans_to_delete=orphans_to_delete,
        user_id=user.user_id,
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.file_uploads set parse_status='done', "
                "  row_count=%s, parsed_at=now() where upload_id=%s",
                (n, upload_id),
            )
    return RedirectResponse(
        url=f"/clients/{client_id}/bcct", status_code=303,
    )


def _list_bcct(client_id: str, year: int | None, direction: str | None,
               q: str | None) -> list[dict]:
    sql = """
        select b.transaction_key, b.line_no, b.declaration_no, b.declaration_type,
               b.direction, b.registration_date, b.customs_code, b.internal_code,
               b.goods_name, b.hs_code, b.quantity, b.unit, b.total_value,
               b.currency, b.origin,
               coalesce(h.event_count, 0) as history_count,
               h.last_changed_at
        from hub.bcct_rows b
        left join (
          select client_id, transaction_key, line_no,
                 count(*) as event_count,
                 max(changed_at) as last_changed_at
          from hub.bcct_row_history
          group by client_id, transaction_key, line_no
        ) h on h.client_id = b.client_id
           and h.transaction_key = b.transaction_key
           and h.line_no = b.line_no
        where b.client_id = %s
    """
    params: list = [client_id]
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


def _years(client_id: str) -> list[int]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select distinct year from hub.bcct_rows where client_id = %s order by year desc",
                (client_id,))
            return [y for (y,) in cur.fetchall()]


def _insert_bcct(*, client_id: str, rows: list[dict],
                 upload_id: str | None, parser, user_id: str | None = None) -> int:
    """Insert BCCT rows. Opens its own connection. For multi-step apply
    paths (e.g. confirm flow that also DELETEs orphans), call
    `_insert_bcct_with_cursor` directly to share the transaction."""
    with connect(user_id=user_id) as conn:
        with conn.cursor() as cur:
            return _insert_bcct_with_cursor(
                cur, client_id=client_id, rows=rows,
                upload_id=upload_id, parser=parser,
            )


def _insert_bcct_with_cursor(cur, *, client_id: str, rows: list[dict],
                             upload_id: str | None, parser) -> int:
    """Insert/upsert BCCT rows on the given cursor. `year` is GENERATED
    ALWAYS AS STORED (from registration_date); not in the column list."""
    import json
    n = 0
    for r in rows:
        customs_code = r.get("customs_code")
        goods_name = r.get("goods_name") or ""
        # internal_code is the AGENCY's ERP/internal code, distinct from
        # the HQ-assigned customs_code. BCCT files don't carry an
        # internal-code column natively (if they do, staff added it
        # post-export). Hub derives it from goods_name via per-client
        # parser. NULL is the correct state when the parser can't
        # extract — staff/BQD pairs it explicitly later. Don't conflate
        # with customs_code unless the client opted into identity mode.
        if parser is None:
            # identity mode: client declares internal == customs
            internal_code = customs_code
        else:
            internal_code = parser(goods_name)
        payload_json = json.dumps(r.get("payload") or {}, ensure_ascii=False)
        cur.execute(
            """
            insert into hub.bcct_rows
              (client_id, transaction_key, line_no, declaration_no,
               declaration_type, direction, registration_date, customs_code,
               internal_code, goods_name, hs_code, quantity, unit,
               quantity_2, unit_2, unit_price, total_value, currency, origin,
               invoice_ref,
               exporter_name, exporter_tax_code, consignee_name, incoterms,
               weight, weight_unit, package_count, package_unit,
               invoice_date, departure_date,
               destination_code, destination_name,
               transport_mode, exchange_rate,
               upload_id, payload)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s::jsonb)
            on conflict (client_id, year, transaction_key, line_no) do update set
              declaration_no = excluded.declaration_no,
              customs_code = excluded.customs_code,
              internal_code = excluded.internal_code,
              goods_name = excluded.goods_name,
              quantity = excluded.quantity,
              total_value = excluded.total_value,
              exporter_name = excluded.exporter_name,
              exporter_tax_code = excluded.exporter_tax_code,
              consignee_name = excluded.consignee_name,
              incoterms = excluded.incoterms,
              weight = excluded.weight,
              weight_unit = excluded.weight_unit,
              package_count = excluded.package_count,
              package_unit = excluded.package_unit,
              invoice_date = excluded.invoice_date,
              departure_date = excluded.departure_date,
              destination_code = excluded.destination_code,
              destination_name = excluded.destination_name,
              transport_mode = excluded.transport_mode,
              exchange_rate = excluded.exchange_rate,
              payload = excluded.payload,
              upload_id = excluded.upload_id,
              indexed_at = now()
            """,
            (client_id, r["transaction_key"], r.get("line_no", "0"),
             r.get("declaration_no"), r.get("declaration_type"),
             r.get("direction"), r.get("registration_date"),
             customs_code, internal_code, goods_name, r.get("hs_code"),
             r.get("quantity"), r.get("unit"),
             r.get("quantity_2"), r.get("unit_2"),
             r.get("unit_price"), r.get("total_value"),
             r.get("currency"), r.get("origin"), r.get("invoice_ref"),
             r.get("exporter_name"), r.get("exporter_tax_code"),
             r.get("consignee_name"), r.get("incoterms"),
             r.get("weight"), r.get("weight_unit"),
             r.get("package_count"), r.get("package_unit"),
             r.get("invoice_date"), r.get("departure_date"),
             r.get("destination_code"), r.get("destination_name"),
             r.get("transport_mode"), r.get("exchange_rate"),
             upload_id, payload_json))
        n += 1
    return n
