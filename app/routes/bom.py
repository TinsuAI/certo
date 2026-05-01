"""BOM routes — nested under /clients/{client_id}/. Plus public proposal POST API."""
from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app import auth, llm
from app.database import connect
from app.parsers.bom import parse_bom_workbook, BomParseError
from app.parsers._excel import compute_file_signature
from app.routes.clients import get_client, stats_for_client
from app.routes._llm_fallback import (
    cache_confirmed_mapping,
    headers_per_sheet,
    lookup_cached_mapping,
    record_mapping_use,
    request_llm_mapping,
)
from app.storage import save_upload, sha256_bytes
from app.stores.staleness import freshness_for_template
from app.stores.bom import (
    create_version,
    list_products_with_bom,
    list_versions_for_product,
    get_version_with_rows,
    submit_proposal,
)
from app.stores.uploads import record_upload

router = APIRouter()
BOM_PROFILES = ["manual_flat", "growatt_multi_workbook", "johnson_sap_exploded"]
PREVIEW_SAMPLE_PRODUCTS = 5
PREVIEW_SAMPLE_ROWS_PER_PRODUCT = 4


@router.get("/clients/{client_id}/bom", response_class=HTMLResponse)
async def list_view(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    products = list_products_with_bom(client_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/bom.html",
        {"client": client, "stats": stats_for_client(client_id),
         "products": products,
         "freshness": freshness_for_template(request, client_id, "bom"),
         "active_root": "clients", "active_tab": "bom"},
    )


@router.get("/clients/{client_id}/bom/upload", response_class=HTMLResponse)
async def upload_view(request: Request, client_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/bom_upload.html",
        {"client": client, "stats": stats_for_client(client_id),
         "profiles": BOM_PROFILES,
         "active_root": "clients", "active_tab": "bom"},
    )


@router.post("/clients/{client_id}/bom/upload")
async def upload_submit(request: Request, client_id: str,
                        profile: str = Form("manual_flat"),
                        file: UploadFile = File(...)):
    """Parse + stash to upload_pending; redirect to preview for confirm.

    Phase 2 universal-preview pattern: staff sees parsed products + sample
    rows before any new BOM version lands. Mandatory sample-row rendering
    in the preview UI is the staff-eyeball guard against LLM-confirmed
    wrong-mapping silent corruption.
    """
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    if profile not in BOM_PROFILES:
        raise HTTPException(400, "Invalid profile")
    blob = await file.read()
    sha = sha256_bytes(blob)
    stored = save_upload(blob, filename=file.filename or "bom.xlsx",
                         module="bom", client_id=client_id)
    upload_id = record_upload(
        client_id=client_id, module="bom",
        original_filename=file.filename or "bom.xlsx",
        stored_path=stored.path, content_sha256=sha, size_bytes=len(blob),
        mime_type=file.content_type, uploader_user_id=user.user_id,
    )
    # ── Step 1: cached mapping for this client + file shape (manual_flat only) ──
    file_signature: str | None = None
    cached_mapping: dict | None = None
    if profile == "manual_flat":
        try:
            sheets = headers_per_sheet(blob)
            if sheets:
                file_signature = compute_file_signature(
                    client_id=client_id, module="bom", headers_per_sheet=sheets,
                )
                cached_mapping = lookup_cached_mapping(
                    client_id=client_id, module="bom", file_signature=file_signature,
                )
        except Exception:  # noqa: BLE001
            pass

    # ── Step 2: parse — cached mapping if present, else rigid, else LLM ──
    products: dict[str, list[dict]] | None = None
    rigid_error: str | None = None
    used_mapping: dict[str, str] | None = None
    proposed_by = "rigid"
    if cached_mapping is not None:
        try:
            products = parse_bom_workbook(blob, profile=profile, mapping_override=cached_mapping)
            record_mapping_use(client_id=client_id, module="bom", file_signature=file_signature)
            used_mapping = cached_mapping
            proposed_by = "llm_cached"
        except BomParseError as e:
            rigid_error = f"cached mapping failed: {e}"
    if products is None:
        try:
            products = parse_bom_workbook(blob, profile=profile)
        except BomParseError as e:
            rigid_error = str(e)

    if products is None:
        # LLM fallback only for manual_flat — other profiles infer from
        # sheet layout, not column matching, so column-mapping override
        # doesn't help them.
        if profile != "manual_flat":
            with connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s",
                        (rigid_error, upload_id))
            raise HTTPException(400, f"Parse error: {rigid_error}")
        try:
            mapping, _headers, _sample, file_sig = request_llm_mapping(
                client_id=client_id, module="bom", blob=blob,
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
            products = parse_bom_workbook(blob, profile="manual_flat", mapping_override=mapping)
        except BomParseError as e:
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
        client_id=client_id, upload_id=upload_id, products=products,
        profile=profile, created_by=user.user_id,
        used_mapping=used_mapping, file_signature=file_signature,
        proposed_by=proposed_by,
    )
    total_rows = sum(len(rows) for rows in products.values())
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.file_uploads set parse_status='pending_preview', row_count=%s, parsed_at=now() where upload_id=%s",
                (total_rows, upload_id))
    return RedirectResponse(
        url=f"/clients/{client_id}/bom/preview/{pending_id}",
        status_code=303,
    )


@router.get("/clients/{client_id}/bom/preview/{pending_id}",
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
                select parsed_rows, diff_summary, expires_at, created_at
                from hub.upload_pending
                where pending_id = %s and client_id = %s and module = 'bom'
                """,
                (pending_id, client_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Pending upload not found or expired")
    parsed_rows, diff_summary, expires_at, created_at = row
    # parsed_rows shape: {"products": {product_code: [row, ...], ...}}
    products = parsed_rows.get("products", {}) if isinstance(parsed_rows, dict) else {}
    profile = (diff_summary or {}).get("profile", "manual_flat")
    summary, sample = _summarize_bom(products)
    return request.app.state.templates.TemplateResponse(
        request, "clients/bom_preview.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "pending_id": pending_id,
            "profile": profile,
            "summary": summary,
            "sample": sample,
            "expires_at": expires_at, "created_at": created_at,
            "active_root": "clients", "active_tab": "bom",
        },
    )


@router.post("/clients/{client_id}/bom/preview/{pending_id}/confirm")
async def preview_confirm(request: Request, client_id: str, pending_id: str):
    """Apply stashed BOM upload as new versions.

    Order matters: load pending (no DELETE yet) → create all versions →
    only then DELETE pending + flip parse_status. If create_version fails
    mid-loop, pending stays so staff can re-trigger; the file_uploads row
    stays in 'pending_preview' status, signalling "not committed". Hash-
    dedup in stores.bom makes a successful retry idempotent on the
    versions already created.
    """
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")

    # Step 1: read pending (no delete yet).
    with connect(user_id=user.user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select parsed_rows, diff_summary, upload_id
                from hub.upload_pending
                where pending_id = %s and client_id = %s and module = 'bom'
                  and expires_at > now()
                """,
                (pending_id, client_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Pending upload not found or expired")
    parsed_rows, diff_summary, upload_id = row
    products = parsed_rows.get("products", {}) if isinstance(parsed_rows, dict) else {}
    profile = (diff_summary or {}).get("profile", "manual_flat")

    # Step 2: create versions outside the pending-row tx. Each create_version
    # manages its own connection + canonicalization + dedup-by-hash. If any
    # version creation raises, propagate — the staff sees an error AND can
    # re-confirm later because we haven't deleted pending yet.
    n = 0
    for product_code, rows in products.items():
        version_id = create_version(
            client_id=client_id, product_code=product_code, rows=rows,
            actor="agency_staff", intent="asserted_technical",
            parent_version_id=None,
            context={"channel": "agency_upload", "profile": profile},
            source_upload_id=upload_id,
        )
        if version_id:
            n += 1

    # Step 3: only on full success — delete pending + flip status.
    with connect(user_id=user.user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from hub.upload_pending
                where pending_id = %s and client_id = %s and module = 'bom'
                """,
                (pending_id, client_id),
            )
            cur.execute(
                "update hub.file_uploads set parse_status='done', "
                "row_count=%s, parsed_at=now() where upload_id=%s",
                (n, upload_id),
            )

    # If this upload used an LLM-proposed mapping, persist it now (the
    # staff just verified the resulting products+rows looked correct).
    if (diff_summary or {}).get("proposed_by") == "llm_proposed":
        used_mapping = diff_summary.get("used_mapping")
        file_signature = diff_summary.get("file_signature")
        if used_mapping and file_signature:
            cache_confirmed_mapping(
                client_id=client_id, module="bom",
                file_signature=file_signature, mapping=used_mapping,
                headers=list(used_mapping.keys()),
                confirmed_by_user_id=user.user_id, proposed_by="llm",
            )
    return RedirectResponse(
        url=f"/clients/{client_id}/bom?ingested={n}", status_code=303,
    )


@router.post("/clients/{client_id}/bom/preview/{pending_id}/reject")
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
                where pending_id = %s and client_id = %s and module = 'bom'
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
        url=f"/clients/{client_id}/bom?rejected=1", status_code=303,
    )


def _stash_pending(*, client_id: str, upload_id: str,
                   products: dict[str, list[dict]],
                   profile: str, created_by: str | None,
                   used_mapping: dict[str, str] | None = None,
                   file_signature: str | None = None,
                   proposed_by: str = "rigid") -> str:
    pending_id = secrets.token_urlsafe(16)
    parsed_payload = {"products": products}
    diff_summary = {
        "profile": profile,
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
                values (%s, %s, 'bom', %s, %s::jsonb, %s::jsonb, %s)
                """,
                (pending_id, client_id, upload_id,
                 json.dumps(parsed_payload, ensure_ascii=False, default=str),
                 json.dumps(diff_summary, ensure_ascii=False, default=str),
                 created_by),
            )
    return pending_id


def _summarize_bom(products: dict[str, list[dict]]) -> tuple[dict, list[dict]]:
    """Return (summary, sample). Sample = top-N products × first M rows each,
    grouped by product so staff sees product diversity (per /rev finding —
    flat sampling hides whether product_code mapping is right across products).
    """
    n_products = len(products)
    n_rows = sum(len(rows) for rows in products.values())
    n_with_qty = sum(
        1 for rows in products.values() for r in rows
        if (r.get("qty_per_unit") or 0) > 0
    )
    n_distinct_materials = len({
        r.get("material_code") for rows in products.values() for r in rows
        if r.get("material_code")
    })
    summary = {
        "n_products": n_products,
        "n_rows": n_rows,
        "n_with_qty": n_with_qty,
        "n_distinct_materials": n_distinct_materials,
    }
    sample = []
    for product_code, rows in list(products.items())[:PREVIEW_SAMPLE_PRODUCTS]:
        sample.append({
            "product_code": product_code,
            "n_rows": len(rows),
            "rows": rows[:PREVIEW_SAMPLE_ROWS_PER_PRODUCT],
        })
    return summary, sample


@router.get("/clients/{client_id}/bom/{product_code:path}/versions", response_class=HTMLResponse)
async def versions_view(request: Request, client_id: str, product_code: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    versions = list_versions_for_product(client_id=client_id, product_code=product_code)
    return request.app.state.templates.TemplateResponse(
        request, "clients/bom_versions.html",
        {"client": client, "stats": stats_for_client(client_id),
         "product_code": product_code, "versions": versions,
         "active_root": "clients", "active_tab": "bom"},
    )


@router.get("/clients/{client_id}/bom/version/{version_id}", response_class=HTMLResponse)
async def version_detail(request: Request, client_id: str, version_id: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    data = get_version_with_rows(version_id)
    if not data or data["version"]["client_id"] != client_id:
        raise HTTPException(404, "Version not found")
    return request.app.state.templates.TemplateResponse(
        request, "clients/bom_version_detail.html",
        {"client": client, "stats": stats_for_client(client_id),
         "version": data["version"], "rows": data["rows"],
         "active_root": "clients", "active_tab": "bom"},
    )


@router.post("/api/v1/hub/products/{product_code:path}/bom/proposals")
async def submit_bom_proposal(request: Request, product_code: str):
    auth.require_user(request)
    body = await request.json()
    client_id = body.get("client_id") or body.get("dncx_id")
    if not client_id or not get_client(client_id):
        raise HTTPException(404, "Client not found")
    actor = body.get("actor", "co_system")
    intent = body.get("intent", "modified_for_case")
    parent_version_id = body.get("parent_version_id")
    context = body.get("context", {})
    rows = body.get("rows", [])
    if not isinstance(rows, list) or not rows:
        raise HTTPException(400, "rows required")
    result = submit_proposal(
        client_id=client_id, product_code=product_code, actor=actor, intent=intent,
        parent_version_id=parent_version_id, context=context, rows=rows,
    )
    return JSONResponse(result)
