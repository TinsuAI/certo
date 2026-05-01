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
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.parser_mappings
                  set use_count = use_count + 1, last_used_at = now()
                where client_id = %s and module = 'bcct' and file_signature = %s
                  and confirmed_at is not null
                returning mapping
                """,
                (client_id, file_signature),
            )
            row = cur.fetchone()
            return row[0] if row else None


@router.get("/clients/{client_id}/bcct", response_class=HTMLResponse)
async def list_view(request: Request, client_id: str,
                    year: int | None = None, direction: str | None = None,
                    q: str | None = None):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    items = _list_bcct(client_id, year, direction, q)
    years = _years(client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/bcct.html",
        {"client": client, "stats": stats_for_client(client_id),
         "items": items, "years": years,
         "year": year, "direction": direction, "q": q or "",
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

    return _ingest_rows(
        client_id=client_id, client=client,
        rows=rows, upload_id=upload_id,
    )


def _ingest_rows(*, client_id: str, client: dict, rows: list[dict],
                 upload_id: str) -> RedirectResponse:
    parser = internal_code_parser_for(client_id, client["code_resolution_mode"])
    rows_with_date = [r for r in rows if r.get("registration_date")]
    skipped = len(rows) - len(rows_with_date)
    n = _insert_bcct(client_id=client_id, rows=rows_with_date,
                     upload_id=upload_id, parser=parser)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.file_uploads set parse_status='done', row_count=%s, parsed_at=now() where upload_id=%s",
                (n, upload_id))
    redirect_url = f"/clients/{client_id}/bcct"
    if skipped:
        redirect_url += f"?skipped={skipped}"
    return RedirectResponse(url=redirect_url, status_code=303)


async def _request_llm_mapping(
    request: Request, *, client_id: str, upload_id: str,
    blob: bytes, file_signature: str | None, rigid_error: str,
) -> RedirectResponse:
    """When rigid+cache fail, ask the LLM for a mapping proposal. Stash on
    the upload row; redirect to the propose UI for staff confirmation."""
    cfg = llm.LLMConfig.load()
    if not cfg.is_enabled() or file_signature is None:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s",
                    (rigid_error, upload_id))
        raise HTTPException(400, f"Parse error: {rigid_error}")

    headers, sample_rows = _sample_rows_first_sheet(blob)
    try:
        proposed = llm.propose_header_mapping(
            client_id=client_id, module="bcct",
            headers=headers, sample_rows=sample_rows, cfg=cfg,
        )
    except (llm.LLMUnavailable, llm.LLMProposalError) as e:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s",
                    (f"{rigid_error}; LLM: {e}", upload_id))
        raise HTTPException(400, f"Parse error (LLM unavailable): {e}")

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
    return request.app.state.templates.TemplateResponse(
        request, "clients/bcct_parse_mapping.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "upload_id": upload_id, "filename": filename,
            "headers": result.get("headers", []),
            "samples": result.get("sample_rows", []),
            "proposed": result.get("proposed_mapping", {}),
            "rigid_error": result.get("rigid_error", ""),
            "active_root": "clients", "active_tab": "bcct",
        },
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
    blob = Path(stored_path).read_bytes()
    rows = parse_bcct_workbook(blob, mapping_override=mapping)
    return _ingest_rows(client_id=client_id, client=client,
                        rows=rows, upload_id=upload_id)


def _list_bcct(client_id: str, year: int | None, direction: str | None,
               q: str | None) -> list[dict]:
    sql = """
        select transaction_key, line_no, declaration_no, declaration_type, direction,
               registration_date, customs_code, internal_code, goods_name, hs_code,
               quantity, unit, total_value, currency, origin
        from hub.bcct_rows where client_id = %s
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
                 upload_id: str, parser) -> int:
    """Insert BCCT rows. `year` column is GENERATED ALWAYS AS STORED in the
    DB (from `registration_date`), so it's not in the column list."""
    import json
    n = 0
    with connect() as conn:
        with conn.cursor() as cur:
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
