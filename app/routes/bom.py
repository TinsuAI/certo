"""BOM routes — nested under /clients/{client_id}/. Plus public proposal POST API."""
from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app import auth, llm
from app.database import connect
from app.parsers.bom import parse_bom_workbook, BomParseError
from app.parsers.bom_edges import parse_raw_edges_with_fallback
from app.parsers.bom_adapters.manual_flat import (
    parse_with_skipped as parse_manual_flat_with_skipped,
)
from app.parsers import bom_adapters
from app.parsers._excel import compute_file_signature
from app.routes.clients import get_client, stats_for_client
from app.routes._llm_fallback import (
    cache_confirmed_mapping,
    headers_per_sheet,
    lookup_cached_mapping,
    record_mapping_use,
    request_llm_mapping,
)
from app.routes._mapping_flow import (
    ModuleConfig,
    _load_unmapped,
    _stash_unmapped,
    render_mapping_page_context,
    render_mapping_page_with_llm_suggestion,
)
from app.routes._paging import (
    SortSpec,
    pagination_context,
    parse_page_params,
    sort_link,
)
from app.storage import save_upload, sha256_bytes
from app.stores.staleness import freshness_for_template
from app.stores.bom import (
    count_products_with_bom,
    create_flattened_artifact_set,
    create_raw_artifact,
    create_artifact,
    list_products_with_bom,
    list_artifacts_for_product,
    bom_shape,
    get_lineage_for_artifact,
    get_artifact_with_rows,
    make_bcct_import_lookup,
    make_catalog_lookup,
    make_current_db_btp_lookup,
    submit_proposal,
    validate_proposal_contract,
)
from app.stores import flatten_decisions as decisions_store
from app.stores.uom import make_uom_lookup
from app.stores.uploads import record_upload
from app.flatten import flatten as flatten_engine
from app.flatten.types import FlattenContext, FlattenedVersion, FlattenResult, BomKey, FlattenedRow, UnresolvedNode, Decision
from decimal import Decimal as _Decimal

router = APIRouter()


def _bom_profiles() -> list[str]:
    """Profile list = registered adapter names + technical_flatten meta-profile.
    Computed dynamically so a new adapter dropped into bom_adapters/ is
    automatically offered in the upload form. Legacy aliases (e.g.
    growatt_multi_workbook → sheet_per_product) are accepted via
    bom_adapters.resolve() but only the canonical name appears in the UI.
    """
    return [*bom_adapters.adapter_names(), "technical_raw", "technical_flatten"]


BOM_PROFILES = _bom_profiles()
BOM_LEGACY_PROFILES = {"growatt_multi_workbook", "johnson_sap_exploded"}
PREVIEW_SAMPLE_PRODUCTS = 5
PREVIEW_SAMPLE_ROWS_PER_PRODUCT = 4


BOM_SORT_WHITELIST = {
    # Default — non_flattened first, then last_published.
    "last_published": "a.last_published",
    "product_code": "a.product_code",
    "n_versions": "a.n_artifacts",
    "n_artifacts": "a.n_artifacts",
    "n_logical_versions": "a.n_logical_versions",
}
BOM_SORT_DEFAULT = ("last_published", "desc")


@router.get("/clients/{client_id}/bom", response_class=HTMLResponse)
async def list_view(request: Request, client_id: str,
                    q: str | None = None):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    page_params = parse_page_params(query_params=request.query_params)
    sort = SortSpec.from_params(
        query_params=request.query_params,
        whitelist=BOM_SORT_WHITELIST, default=BOM_SORT_DEFAULT,
    )
    # The default sort puts non_flattened products on top; that
    # invariant is desirable but the user can override by clicking a
    # sortable column header.
    if sort.column == "last_published" and sort.direction == "desc":
        order_by = "a.n_non_flattened desc, a.last_published desc nulls last"
    else:
        order_by = sort.sql_clause(tiebreakers=("a.product_code",)) \
            if sort.column != "product_code" else sort.sql_clause()
    products = list_products_with_bom(
        client_id, q=q,
        order_by=order_by,
        limit=page_params.page_size, offset=page_params.offset,
    )
    total = count_products_with_bom(client_id, q=q)
    paging_ctx = pagination_context(
        request=request, page_params=page_params, total=total,
    )

    def _sort_link(col: str) -> str:
        return sort_link(request=request, column=col, current_sort=sort)
    return request.app.state.templates.TemplateResponse(
        request, "clients/bom.html",
        {"client": client, "stats": stats_for_client(client_id),
         "products": products, "q": q or "",
         "paging": paging_ctx, "sort": sort, "sort_link": _sort_link,
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
    if profile not in BOM_PROFILES and profile not in BOM_LEGACY_PROFILES:
        raise HTTPException(400, "Invalid profile")
    # technical_flatten is a flatten-stage marker, not a parse-stage profile.
    # Parse with manual_flat shape primarily; the route tries the other
    # 2 layout-aware profiles below if the first one yields nothing.
    parse_profile = "manual_flat" if profile == "technical_flatten" else profile
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

    if profile == "technical_raw":
        from pathlib import Path as _Path
        root_hint = _Path(file.filename or "").stem if file.filename else None
        try:
            raw_edges, used_adapter = parse_raw_edges_with_fallback(
                blob, root_code=root_hint,
            )
        except BomParseError as e:
            with connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "update hub.file_uploads set parse_status='error', parse_error=%s, parsed_at=now() where upload_id=%s",
                        (str(e), upload_id),
                    )
            raise HTTPException(400, f"Parse error: {e}") from e
        products = _raw_edges_to_preview_products(raw_edges)
        pending_id = _stash_pending(
            client_id=client_id, upload_id=upload_id, products=products,
            profile=profile, created_by=user.user_id,
            proposed_by=f"parser_fallback:{used_adapter}",
            raw_edges=raw_edges,
        )
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update hub.file_uploads set parse_status='pending_preview', row_count=%s, parsed_at=now() where upload_id=%s",
                    (len(raw_edges), upload_id),
                )
        return RedirectResponse(
            url=f"/clients/{client_id}/bom/preview/{pending_id}",
            status_code=303,
        )

    # ── Step 1: cached mapping for this client + file shape (manual_flat only) ──
    file_signature: str | None = None
    cached_mapping: dict | None = None
    if parse_profile == "manual_flat":
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

    # Slice 3: cache miss for manual_flat (no technical_flatten) →
    # interactive mapping page. Layout-driven adapters + technical_flatten
    # keep the inline rigid+LLM path below.
    if (
        parse_profile == "manual_flat"
        and profile != "technical_flatten"
        and cached_mapping is None
    ):
        _stash_unmapped(
            upload_id=upload_id, file_signature=file_signature,
            extra={"profile": profile},
        )
        return RedirectResponse(
            url=f"/clients/{client_id}/bom/upload/mapping/{upload_id}",
            status_code=303,
        )

    # ── Step 2: parse — cached mapping if present, else rigid, else LLM ──
    products: dict[str, list[dict]] | None = None
    rigid_error: str | None = None
    used_mapping: dict[str, str] | None = None
    proposed_by = "rigid"
    if cached_mapping is not None:
        try:
            products = parse_bom_workbook(blob, profile=parse_profile, mapping_override=cached_mapping)
            record_mapping_use(client_id=client_id, module="bom", file_signature=file_signature)
            used_mapping = cached_mapping
            proposed_by = "llm_cached"
        except BomParseError as e:
            rigid_error = f"cached mapping failed: {e}"
    if products is None:
        try:
            products = parse_bom_workbook(blob, profile=parse_profile)
        except BomParseError as e:
            rigid_error = str(e)

    # technical_flatten is parser-agnostic: try every registered adapter
    # in order via the registry's fallback chain. New adapters dropped
    # into app/parsers/bom_adapters/ are picked up automatically.
    # Pass the upload's filename stem as root_code hint — adapters that
    # need it (sap_indented_walk) consume it, others ignore.
    if products is None and profile == "technical_flatten":
        from pathlib import Path as _Path
        root_hint = _Path(file.filename or "").stem if file.filename else None
        result = bom_adapters.parse_with_fallback(blob, root_code=root_hint)
        if result is not None:
            products, used_adapter = result
            proposed_by = f"parser_fallback:{used_adapter}"
            rigid_error = None

    if products is None:
        # LLM fallback only for manual_flat — other profiles infer from
        # sheet layout, not column matching, so column-mapping override
        # doesn't help them.
        if parse_profile != "manual_flat":
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

    # ── technical_flatten: invoke the flatten engine + stash decisions ──
    flatten_payload: dict | None = None
    if profile == "technical_flatten":
        flatten_payload = _run_flatten_for_upload(
            client_id=client_id, products=products,
        )

    pending_id = _stash_pending(
        client_id=client_id, upload_id=upload_id, products=products,
        profile=profile, created_by=user.user_id,
        used_mapping=used_mapping, file_signature=file_signature,
        proposed_by=proposed_by,
        flatten_payload=flatten_payload,
    )

    if flatten_payload:
        # Stash decisions in their own table so confirm route can audit them.
        decision_objs = [_decision_from_dict(d) for d in flatten_payload["decisions"]]
        id_map = decisions_store.stash_decisions(
            pending_id=pending_id, client_id=client_id, decisions=decision_objs,
        )
        # Persist the index→decision_id map alongside the payload so
        # confirm can re-link by index.
        flatten_payload["decision_id_map"] = {str(i): did for i, did in id_map.items()}
        _update_pending_flatten_payload(pending_id=pending_id, payload=flatten_payload)

    total_rows = sum(len(rows) for rows in products.values())
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update hub.file_uploads set parse_status='pending_preview', row_count=%s, parsed_at=now() where upload_id=%s",
                (total_rows, upload_id))
    if profile == "technical_flatten":
        return RedirectResponse(
            url=f"/clients/{client_id}/bom/flatten-preview/{pending_id}",
            status_code=303,
        )
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
    skipped_rows = (diff_summary or {}).get("skipped_rows") or []
    summary, sample = _summarize_bom(products)
    # Shared-template adapter: provide `summary.total` for shared chrome.
    summary_for_chrome = dict(summary)
    summary_for_chrome["total"] = summary["n_rows"]
    # UoM drift gate (Track C): flatten parsed rows → drift list +
    # blocking flag.
    from app.stores.uom_drift import compute_uom_drifts, has_blocking_drift
    flat_rows: list[dict] = []
    for prod_rows in (products.values() if isinstance(products, dict) else []):
        flat_rows.extend(prod_rows)
    uom_drifts = compute_uom_drifts(client_id, flat_rows)
    return request.app.state.templates.TemplateResponse(
        request, "clients/bom_preview.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "pending_id": pending_id,
            "profile": profile,
            "summary": summary_for_chrome,
            "sample": sample,
            "sample_rows": [],  # BOM uses per-product `sample`; shared sample slot is overridden
            "skipped_rows": skipped_rows,
            "skipped_count": len(skipped_rows),
            "diff_summary": diff_summary or {},
            "required_fields": ["product_code", "material_code", "qty_per_unit"],
            "module_label": "BOM",
            "list_url": f"/clients/{client_id}/bom",
            "expires_at": expires_at, "created_at": created_at,
            "active_root": "clients", "active_tab": "bom",
            "uom_drifts": uom_drifts,
            "uom_drift_blocks_confirm": has_blocking_drift(uom_drifts),
        },
    )


@router.post("/clients/{client_id}/bom/preview/{pending_id}/confirm")
async def preview_confirm(request: Request, client_id: str, pending_id: str):
    """Apply stashed BOM upload as new versions.

    Order matters: load pending (no DELETE yet) → create all versions →
    only then DELETE pending + flip parse_status. If create_artifact fails
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

    # Step 2: create versions outside the pending-row tx. Each create_artifact
    # manages its own connection + canonicalization + dedup-by-hash. If any
    # version creation raises, propagate — the staff sees an error AND can
    # re-confirm later because we haven't deleted pending yet.
    #
    # Adapter resolution for post-ingest hooks:
    # - non-technical_raw: profile IS the adapter name.
    # - technical_raw: actual adapter recorded in diff_summary.proposed_by
    #   as 'parser_fallback:<adapter>' (set by upload route).
    adapter_for_hooks = profile
    if profile == "technical_raw":
        proposed_by = (diff_summary or {}).get("proposed_by", "")
        if isinstance(proposed_by, str) and proposed_by.startswith("parser_fallback:"):
            adapter_for_hooks = proposed_by.split(":", 1)[1]

    n = 0
    created_artifact_ids: list[str] = []
    if profile == "technical_raw":
        raw_edges = parsed_rows.get("raw_edges", []) if isinstance(parsed_rows, dict) else []
        edges_by_root: dict[str, list[dict]] = {}
        for edge in raw_edges:
            root = edge.get("root_code")
            if not root:
                continue
            edges_by_root.setdefault(root, []).append(edge)
        for root_code, edges in edges_by_root.items():
            artifact_id = create_raw_artifact(
                client_id=client_id, product_code=root_code, edges=edges,
                actor="agency_staff", intent="asserted_technical",
                parent_artifact_id=None,
                context={"channel": "agency_upload", "profile": profile},
                source_upload_id=upload_id,
            )
            if artifact_id:
                n += 1
                created_artifact_ids.append(artifact_id)
    else:
        for product_code, rows in products.items():
            artifact_id = create_artifact(
                client_id=client_id, product_code=product_code, rows=rows,
                actor="agency_staff", intent="asserted_technical",
                parent_artifact_id=None,
                context={"channel": "agency_upload", "profile": profile},
                source_upload_id=upload_id,
            )
            if artifact_id:
                n += 1
                created_artifact_ids.append(artifact_id)

    # Step 2b: post-ingest hooks (Track D, Phase B). Adapters declaring
    # post_ingest_hooks (e.g. derive_btp_shallows for sap_indented_walk +
    # multi_sheet_per_root) auto-mint per-BTP raw_graph artifacts so the
    # staleness window for D2 (BTP BOM appears later) is closed when the
    # parent BOM ingests. Hook failure logs + marks the new artifact stale
    # with dim=derive_hook_failed; never bubbles to user.
    for new_aid in created_artifact_ids:
        try:
            bom_adapters.run_post_ingest_hooks(
                adapter_name=adapter_for_hooks,
                artifact_id=new_aid, client_id=client_id,
            )
        except Exception as hook_err:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).exception(
                "post_ingest_hook failed for artifact %s (adapter=%s): %s",
                new_aid, adapter_for_hooks, hook_err,
            )
            with connect() as conn, conn.cursor() as cur:
                cur.execute(
                    "update hub.bom_artifacts set is_stale=true, "
                    "stale_reasons = stale_reasons || jsonb_build_array("
                    "  jsonb_build_object("
                    "    'dim','derive_hook_failed',"
                    "    'source_table','app.parsers.bom_adapters',"
                    "    'source_pk',%s::text,"
                    "    'observed_at',to_char(now() at time zone 'utc',"
                    "      'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')"
                    "  )"
                    "), stale_first_at=coalesce(stale_first_at, now()), "
                    "stale_resolved_at=null "
                    "where artifact_id=%s",
                    (adapter_for_hooks, new_aid),
                )

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


@router.post("/clients/{client_id}/bom/artifact/{artifact_id}/refresh")
async def refresh_artifact_route(
    request: Request, client_id: str, artifact_id: str,
):
    """Track D — clear stale flag + re-derive shape (best-effort).

    Spec: `.ai/features/2026-05-11-bom-staleness-track-d/brief.md`.
    """
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    from app.stores.bom_staleness import refresh_artifact
    try:
        refresh_artifact(client_id, artifact_id,
                         triggered_by_user_id=user.user_id)
    except LookupError:
        raise HTTPException(404, "Artifact not found in this client")
    return RedirectResponse(
        url=f"/clients/{client_id}/bom/artifact/{artifact_id}",
        status_code=303,
    )


@router.get("/clients/{client_id}/bom/stale", response_class=HTMLResponse)
async def list_stale(request: Request, client_id: str):
    """List all stale BOM artifacts for this client.

    Phase 2 step 5 follow-up: dedicated view so staff can find what
    needs refresh without scrolling per-product. Surfaces is_stale +
    has_uom_drift signals across artifacts. Filter: tombstoned
    excluded; published only.
    """
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    can_edit = auth.can_edit_client(user, client_id)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select artifact_id, product_code, flatten_strategy,
                   source_bom_kind, is_stale, stale_reasons,
                   stale_first_at, has_uom_drift, uom_drift_reasons,
                   uom_drift_first_at, published_at
            from hub.bom_artifacts
            where client_id=%s
              and tombstoned_at is null
              and status='published'
              and (is_stale = true or has_uom_drift = true)
            order by coalesce(stale_first_at, uom_drift_first_at) desc,
                     product_code, artifact_id
            """,
            (client_id,),
        )
        rows = []
        for r in cur.fetchall():
            (aid, pc, strat, kind, is_stale, sreas, sat,
             has_drift, dreas, dat, pub_at) = r
            stale_dims = sorted({x.get("dim") for x in (sreas or [])
                                  if x and x.get("dim")})
            drift_dims = sorted({x.get("dim") for x in (dreas or [])
                                  if x and x.get("dim")})
            rows.append({
                "artifact_id": aid, "product_code": pc,
                "flatten_strategy": strat, "source_bom_kind": kind,
                "is_stale": is_stale,
                "stale_dims": stale_dims,
                "stale_first_at": sat,
                "has_uom_drift": has_drift,
                "drift_dims": drift_dims,
                "uom_drift_first_at": dat,
                "published_at": pub_at,
                "is_source": strat in (
                    "manual_flat_as_provided", "no_strategy"),
            })
    return request.app.state.templates.TemplateResponse(
        request, "clients/bom_stale.html",
        {"client": client, "stats": stats_for_client(client_id),
         "rows": rows, "can_edit": can_edit,
         "active_root": "clients", "active_tab": "bom"},
    )


@router.post("/clients/{client_id}/bom/{product_code:path}/refresh")
async def refresh_product_route(
    request: Request, client_id: str, product_code: str,
):
    """Track D — clear stale flag for all derived artifacts of product."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    from app.stores.bom_staleness import refresh_product
    refresh_product(client_id, product_code,
                    triggered_by_user_id=user.user_id)
    return RedirectResponse(
        url=f"/clients/{client_id}/bom", status_code=303,
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


# ── Slice 3: manual_flat mapping page ────────────────────────────────────


def _bom_manual_flat_parser_stub(blob, *, mapping_override=None,
                                  header_row_override=None,
                                  extra_required_fields=None):
    """Adapter so `_mapping_flow.render_mapping_page_context` works for BOM.
    Returns (rows, skipped) where rows = products dict (treated opaquely
    by the helper)."""
    return parse_manual_flat_with_skipped(
        blob, mapping_override=mapping_override,
        header_row_override=header_row_override,
        extra_required_fields=extra_required_fields,
    )


BOM_MAPPING_CFG = ModuleConfig(
    name="bom",
    upload_pending_module="bom",
    save_upload_module="bom",
    fallback_filename="bom.xlsx",
    list_route=lambda cid: f"/clients/{cid}/bom",
    preview_template="clients/bom_preview.html",
    parser_fn=_bom_manual_flat_parser_stub,
    parser_error=BomParseError,
    summarize_fn=lambda _: {},   # not called via this cfg
    ingest_fn=lambda *a, **kw: 0,  # not called via this cfg
    logical_fields=("product_code", "material_code", "qty_per_unit", "uom",
                    "bom_code", "bom_variant_id"),
    min_identifier_fields=frozenset(),
    required_mapped_fields=frozenset({"product_code", "material_code"}),
    extra_required_fields_default=("qty_per_unit",),
)


@router.get("/clients/{client_id}/bom/upload/mapping/{upload_id}",
            response_class=HTMLResponse)
async def mapping_view(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    ctx = render_mapping_page_context(
        client_id=client_id, upload_id=upload_id, cfg=BOM_MAPPING_CFG,
    )
    ctx.update({
        "client": client, "stats": stats_for_client(client_id),
        "module_label": "BOM",
        "active_root": "clients", "active_tab": "bom",
    })
    return request.app.state.templates.TemplateResponse(
        request, "clients/_upload_mapping.html", ctx,
    )


@router.post("/clients/{client_id}/bom/upload/mapping/{upload_id}/llm_suggest",
             response_class=HTMLResponse)
async def mapping_llm_suggest(request: Request, client_id: str, upload_id: str):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    ctx = render_mapping_page_with_llm_suggestion(
        client_id=client_id, upload_id=upload_id, cfg=BOM_MAPPING_CFG,
    )
    ctx.update({
        "client": client, "stats": stats_for_client(client_id),
        "module_label": "BOM",
        "active_root": "clients", "active_tab": "bom",
    })
    return request.app.state.templates.TemplateResponse(
        request, "clients/_upload_mapping.html", ctx,
    )


@router.post("/clients/{client_id}/bom/upload/mapping/{upload_id}/parse")
async def mapping_parse(request: Request, client_id: str, upload_id: str):
    """Parse with staff-confirmed mapping (manual_flat only),
    stash the products + skipped_rows, redirect to existing /preview."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    blob, file_signature, extra = _load_unmapped(upload_id, module="bom")
    profile = (extra or {}).get("profile", "manual_flat")
    form = await request.form()

    column_map: dict[str, str] = {}
    for key, value in form.items():
        if key.startswith("col_") and key.endswith("__field"):
            idx = key[len("col_"):-len("__field")]
            field = (value or "").strip()
            if not field:
                continue
            header_value = (form.get(f"col_{idx}__header") or "").strip()
            if header_value:
                column_map[header_value] = field

    # Form validation: BOM requires product_code + material_code mapped.
    mapped_logical = set(column_map.values())
    missing_mapped = BOM_MAPPING_CFG.required_mapped_fields - mapped_logical
    if missing_mapped:
        raise HTTPException(
            400,
            "Thiếu mapping cho các trường bắt buộc: " +
            ", ".join(sorted(missing_mapped)),
        )

    header_row_override_str = (form.get("header_row_override") or "").strip()
    header_row_override = (
        int(header_row_override_str) if header_row_override_str.isdigit() else None
    )
    extra_required_str = (form.get("extra_required_fields") or "").strip()
    extra_required = (
        [s.strip() for s in extra_required_str.split(",") if s.strip()]
        if extra_required_str else None
    )

    try:
        products, skipped = parse_manual_flat_with_skipped(
            blob, mapping_override=column_map,
            header_row_override=header_row_override,
            extra_required_fields=extra_required,
        )
    except BomParseError as e:
        raise HTTPException(400, f"Parse error: {e}") from e

    pending_id = _stash_pending(
        client_id=client_id, upload_id=upload_id, products=products,
        profile=profile, created_by=user.user_id,
        used_mapping=column_map, file_signature=file_signature,
        proposed_by="manual",
        skipped_rows=skipped,
    )
    total_rows = sum(len(rows) for rows in products.values())
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update hub.file_uploads set parse_status='pending_preview', "
            "row_count=%s, parse_error=NULL, parsed_at=now() where upload_id=%s",
            (total_rows, upload_id),
        )
    return RedirectResponse(
        url=f"/clients/{client_id}/bom/preview/{pending_id}", status_code=303,
    )


def _stash_pending(*, client_id: str, upload_id: str,
                   products: dict[str, list[dict]],
                   profile: str, created_by: str | None,
                   used_mapping: dict[str, str] | None = None,
                   file_signature: str | None = None,
                   proposed_by: str = "rigid",
                   flatten_payload: dict | None = None,
                   raw_edges: list[dict] | None = None,
                   skipped_rows: list[dict] | None = None) -> str:
    pending_id = secrets.token_urlsafe(16)
    parsed_payload = {"products": products}
    if flatten_payload:
        parsed_payload["flatten"] = flatten_payload
    if raw_edges is not None:
        parsed_payload["raw_edges"] = raw_edges
    diff_summary = {
        "profile": profile,
        "used_mapping": used_mapping,
        "file_signature": file_signature,
        "proposed_by": proposed_by,
        "skipped_rows": skipped_rows or [],
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


def _update_pending_flatten_payload(*, pending_id: str, payload: dict) -> None:
    """Re-write parsed_rows.flatten with the latest payload (e.g. once
    decision_ids are assigned)."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update hub.upload_pending
                set parsed_rows = jsonb_set(parsed_rows, '{flatten}', %s::jsonb, true)
                where pending_id = %s
                """,
                (json.dumps(payload, ensure_ascii=False, default=str), pending_id),
            )


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


def _raw_edges_to_preview_products(edges: list[dict]) -> dict[str, list[dict]]:
    products: dict[str, list[dict]] = {}
    for edge in edges:
        root = edge.get("root_code") or edge.get("parent_code") or ""
        if not root:
            continue
        products.setdefault(root, []).append({
            "material_code": edge.get("child_code"),
            "qty_per_unit": edge.get("qty_per_parent"),
            "uom": edge.get("uom"),
            "parent_code": edge.get("parent_code"),
            "level": edge.get("level"),
            "node_path": edge.get("node_path"),
            "sheet_name": edge.get("sheet_name"),
            "source_row_no": edge.get("source_row_no"),
        })
    return products


@router.get("/clients/{client_id}/bom/version/{artifact_id}",
            include_in_schema=False)
async def _alias_artifact_detail(client_id: str, artifact_id: str):
    """Vocab rename alias (D9/D10, removable per BACKLOG)."""
    return RedirectResponse(
        url=f"/clients/{client_id}/bom/artifact/{artifact_id}",
        status_code=308,
    )


@router.get("/clients/{client_id}/bom/{product_code:path}/versions",
            include_in_schema=False)
async def _alias_artifacts_list(client_id: str, product_code: str):
    """Vocab rename alias (D9/D10, removable per BACKLOG)."""
    return RedirectResponse(
        url=f"/clients/{client_id}/bom/{product_code}/artifacts",
        status_code=308,
    )


@router.get("/clients/{client_id}/bom/{product_code:path}/artifacts", response_class=HTMLResponse)
async def artifacts_view(request: Request, client_id: str, product_code: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    artifacts = list_artifacts_for_product(client_id=client_id, product_code=product_code)
    return request.app.state.templates.TemplateResponse(
        request, "clients/bom_artifacts.html",
        {"client": client, "stats": stats_for_client(client_id),
         "product_code": product_code, "artifacts": artifacts,
         "active_root": "clients", "active_tab": "bom"},
    )


@router.get("/clients/{client_id}/bom/artifact/{artifact_id}", response_class=HTMLResponse)
async def artifact_detail(request: Request, client_id: str, artifact_id: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    data = get_artifact_with_rows(artifact_id)
    if not data or data["artifact"]["client_id"] != client_id:
        raise HTTPException(404, "Artifact not found")
    artifact = data["artifact"]
    artifact["bom_shape"] = bom_shape(
        artifact.get("flatten_status") or "",
        artifact.get("flatten_strategy") or "",
    )
    lineage = get_lineage_for_artifact(artifact_id)
    return request.app.state.templates.TemplateResponse(
        request, "clients/bom_artifact_detail.html",
        {"client": client, "stats": stats_for_client(client_id),
         "artifact": artifact, "rows": data["rows"],
         "edges": data.get("edges") or [],
         "lineage": lineage,
         "active_root": "clients", "active_tab": "bom"},
    )


# ─────────────────────────────────────────────────────────────────────
# Phase 3b — Preset UI (list + create + tombstone)
# ─────────────────────────────────────────────────────────────────────


@router.get("/clients/{client_id}/bom/{product_code:path}/presets",
            response_class=HTMLResponse)
async def presets_view(request: Request, client_id: str, product_code: str):
    user = auth.require_user(request)
    auth.require_can_view_client(user, client_id)
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    artifacts = list_artifacts_for_product(client_id=client_id, product_code=product_code)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select preset_id, name, artifact_id, notes, created_at "
            "from hub.bom_presets "
            "where client_id=%s and product_code=%s and tombstoned_at is null "
            "order by created_at desc",
            (client_id, product_code),
        )
        cols = [d[0] for d in cur.description]
        presets = [dict(zip(cols, r)) for r in cur.fetchall()]
    return request.app.state.templates.TemplateResponse(
        request, "clients/bom_presets.html",
        {"client": client, "stats": stats_for_client(client_id),
         "product_code": product_code, "presets": presets,
         "artifacts": artifacts,
         "active_root": "clients", "active_tab": "bom"},
    )


@router.post("/clients/{client_id}/bom/{product_code:path}/presets")
async def presets_create(request: Request, client_id: str, product_code: str,
                         artifact_id: str = Form(...), name: str = Form(...),
                         notes: str | None = Form(None)):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select 1 from hub.bom_artifacts where artifact_id=%s "
            "and client_id=%s and product_code=%s",
            (artifact_id, client_id, product_code),
        )
        if not cur.fetchone():
            raise HTTPException(404, "artifact not found in this product scope")
        cur.execute(
            "select 1 from hub.bom_presets "
            "where client_id=%s and product_code=%s and name=%s "
            "and tombstoned_at is null",
            (client_id, product_code, name),
        )
        if cur.fetchone():
            raise HTTPException(409, f"preset name {name!r} already exists")
        preset_id = "bp_" + secrets.token_urlsafe(12)
        cur.execute(
            "insert into hub.bom_presets (preset_id, client_id, product_code, "
            "artifact_id, name, sourcing_choices, notes, created_by) "
            "values (%s, %s, %s, %s, %s, '{}'::jsonb, %s, %s)",
            (preset_id, client_id, product_code, artifact_id, name,
             notes, user["user_id"]),
        )
    return RedirectResponse(
        url=f"/clients/{client_id}/bom/{product_code}/presets",
        status_code=303,
    )


@router.post("/clients/{client_id}/bom/presets/{preset_id}/tombstone")
async def presets_tombstone(request: Request, client_id: str, preset_id: str,
                            reason: str | None = Form(None)):
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select product_code from hub.bom_presets "
            "where preset_id=%s and client_id=%s",
            (preset_id, client_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "preset not found")
        cur.execute(
            "update hub.bom_presets set tombstoned_at=now(), tombstone_reason=%s "
            "where preset_id=%s",
            (reason, preset_id),
        )
        product_code = row[0]
    return RedirectResponse(
        url=f"/clients/{client_id}/bom/{product_code}/presets",
        status_code=303,
    )


@router.post("/api/v1/hub/products/{product_code:path}/bom/proposals")
async def submit_bom_proposal(request: Request, product_code: str):
    user = auth.require_user(request)
    body = await request.json()
    client_id = body.get("client_id") or body.get("dncx_id")
    if not client_id or not get_client(client_id):
        raise HTTPException(404, "Client not found")
    auth.require_can_edit_client(user, client_id)
    actor = body.get("actor", "co_system")
    intent = body.get("intent", "modified_for_case")
    parent_artifact_id = body.get("parent_artifact_id")
    context = body.get("context", {})
    rows = body.get("rows", [])
    if not isinstance(rows, list) or not rows:
        raise HTTPException(400, "rows required")
    try:
        validate_proposal_contract(
            actor=actor, intent=intent, parent_artifact_id=parent_artifact_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result = submit_proposal(
        client_id=client_id, product_code=product_code, actor=actor, intent=intent,
        parent_artifact_id=parent_artifact_id, context=context, rows=rows,
    )
    return JSONResponse(result)


# ────────────────────────────────────────────────────────────────────────
# technical_flatten — flatten engine integration + preview/confirm.
# ────────────────────────────────────────────────────────────────────────

def _run_flatten_for_upload(*, client_id: str,
                            products: dict[str, list[dict]]) -> dict:
    """Build a FlattenContext from current DB state and run the flatten
    engine. Returns the JSON-serializable payload that goes into
    upload_pending.parsed_rows.flatten."""
    ctx = FlattenContext(
        client_id=client_id,
        catalog=make_catalog_lookup(client_id),
        bcct_import=make_bcct_import_lookup(client_id),
        same_upload_btp=lambda m, b, v: None,   # engine wraps this with parsed
        current_db_btp=make_current_db_btp_lookup(client_id),
        uom=make_uom_lookup(client_id),
        explicit_context=lambda r: r.get("explicit_context"),
    )
    result = flatten_engine(products, ctx)
    return _serialize_flatten_result(result)


def _serialize_flatten_result(result: FlattenResult) -> dict:
    return {
        "versions": [{
            "key": {
                "product_code": v.key.product_code,
                "bom_code": v.key.bom_code,
                "bom_variant_id": v.key.bom_variant_id,
            },
            "source_bom_kind": v.source_bom_kind,
            "flatten_status": v.flatten_status,
            "flatten_strategy": v.flatten_strategy,
            "rows": [{
                "material_code": r.material_code,
                "qty": str(r.qty),
                "uom": r.uom,
                "node_path": r.node_path,
                "classification_evidence": r.classification_evidence,
                "classification_evidence_detail": r.classification_evidence_detail,
                "conversion_evidence": r.conversion_evidence,
                "original_qty": str(r.original_qty) if r.original_qty is not None else None,
                "original_uom": r.original_uom,
            } for r in v.rows],
            "unresolved": [{
                "node_path": u.node_path,
                "material_code": u.material_code,
                "reason": u.reason,
                "evidence": u.evidence,
            } for u in v.unresolved],
            "lineage": v.lineage,
            "requires_decision_ids": v.requires_decision_ids,
        } for v in result.versions],
        "decisions": [{
            "decision_type": d.decision_type,
            "chosen_action": d.chosen_action,
            "alternatives": d.alternatives,
            "evidence": d.evidence,
            "status": d.status,
            "staff_confirmation_required": d.staff_confirmation_required,
            "target_key": {
                "product_code": d.target_key.product_code,
                "bom_code": d.target_key.bom_code,
                "bom_variant_id": d.target_key.bom_variant_id,
            } if d.target_key else None,
            "target_strategy": d.target_strategy,
        } for d in result.decisions],
    }


def _deserialize_flatten_result(payload: dict) -> FlattenResult:
    versions = []
    for vd in payload["versions"]:
        versions.append(FlattenedVersion(
            key=BomKey(
                product_code=vd["key"]["product_code"],
                bom_code=vd["key"].get("bom_code", "") or "",
                bom_variant_id=vd["key"].get("bom_variant_id", "default") or "default",
            ),
            source_bom_kind=vd["source_bom_kind"],
            flatten_status=vd["flatten_status"],
            flatten_strategy=vd["flatten_strategy"],
            rows=[FlattenedRow(
                material_code=r["material_code"],
                qty=_Decimal(r["qty"]),
                uom=r["uom"],
                node_path=r["node_path"],
                classification_evidence=r["classification_evidence"],
                classification_evidence_detail=r.get("classification_evidence_detail") or {},
                conversion_evidence=r.get("conversion_evidence"),
                original_qty=_Decimal(r["original_qty"]) if r.get("original_qty") else None,
                original_uom=r.get("original_uom"),
            ) for r in vd["rows"]],
            unresolved=[UnresolvedNode(
                node_path=u["node_path"],
                material_code=u["material_code"],
                reason=u["reason"],
                evidence=u.get("evidence") or {},
            ) for u in vd["unresolved"]],
            lineage=vd.get("lineage") or {},
            requires_decision_ids=vd.get("requires_decision_ids") or [],
        ))
    decisions = [_decision_from_dict(d) for d in payload["decisions"]]
    return FlattenResult(versions=versions, decisions=decisions)


def _decision_from_dict(d: dict) -> Decision:
    target = d.get("target_key")
    return Decision(
        decision_type=d["decision_type"],
        chosen_action=d["chosen_action"],
        alternatives=d.get("alternatives") or [],
        evidence=d.get("evidence") or {},
        status=d.get("status") or "pending",
        staff_confirmation_required=d.get("staff_confirmation_required", True),
        target_key=BomKey(
            product_code=target["product_code"],
            bom_code=target.get("bom_code", "") or "",
            bom_variant_id=target.get("bom_variant_id", "default") or "default",
        ) if target else None,
        target_strategy=d.get("target_strategy"),
    )


def _summarize_flatten(payload: dict, *, products: dict | None = None,
                       client_id: str | None = None) -> dict:
    """Aggregate stats + classify each product as TP vs BTP.

    BTP detection — two complementary signals:
      1. Catalog category (authoritative): hub.materials.category in
         ('btp_sx','btp_nm') ⇒ definitely BTP. This is the agency's
         declared truth and works for BTP-only uploads where no other
         product references the BTP.
      2. Same-upload reference: code that appears as material_code
         in another product's rows. Catches BTPs that aren't yet in
         catalog at upload time.
    """
    versions = payload["versions"]
    n_tp = len(versions)
    by_status: dict[str, int] = {}
    by_strategy: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for v in versions:
        by_status[v["flatten_status"]] = by_status.get(v["flatten_status"], 0) + 1
        by_strategy[v["flatten_strategy"]] = by_strategy.get(v["flatten_strategy"], 0) + 1
        by_kind[v["source_bom_kind"]] = by_kind.get(v["source_bom_kind"], 0) + 1
    n_unresolved = sum(len(v["unresolved"]) for v in versions)
    n_flattened_rows = sum(len(v["rows"]) for v in versions)
    n_decisions_pending = sum(
        1 for d in payload["decisions"]
        if d.get("staff_confirmation_required") and d.get("status") == "pending"
    )

    product_codes = set(products.keys()) if products else {v["key"]["product_code"] for v in versions}

    # Signal 1: catalog truth.
    catalog_btp: set[str] = set()
    if client_id and product_codes:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select material_code from hub.materials
                    where client_id = %s and material_code = any(%s)
                      and category in ('btp_sx', 'btp_nm')
                    """,
                    (client_id, list(product_codes)),
                )
                catalog_btp = {r[0] for r in cur.fetchall()}

    # Signal 2: same-upload reference.
    referenced_btp: set[str] = set()
    if products:
        for pc, rows in products.items():
            for r in rows:
                mat = (r.get("material_code") or "").strip()
                if mat in product_codes and mat != pc:
                    referenced_btp.add(mat)

    btp_codes = catalog_btp | referenced_btp
    tp_codes = product_codes - btp_codes
    return {
        "n_versions": n_tp,
        "n_tp": len(tp_codes),
        "n_btp": len(btp_codes),
        "tp_codes": tp_codes,
        "btp_codes": btp_codes,
        "by_status": by_status,
        "by_strategy": by_strategy,
        "by_kind": by_kind,
        "n_unresolved": n_unresolved,
        "n_flattened_rows": n_flattened_rows,
        "n_decisions_pending": n_decisions_pending,
        "n_flattened": by_status.get("flattened", 0),
        "n_non_flattened": by_status.get("non_flattened", 0),
    }


# Decision type labels + explanations are i18n keys
# (`flatten.dec.<decision_type>.label` and `.why`) — the template looks
# them up via t(), so adding a new decision_type only requires:
#   1. add to migration's CHECK constraint (or extend it)
#   2. add the label_key + why_key to app/i18n.py
# No changes here.


@router.get("/clients/{client_id}/bom/flatten-preview/{pending_id}",
            response_class=HTMLResponse)
async def flatten_preview_view(request: Request, client_id: str, pending_id: str):
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
                where pending_id = %s and client_id = %s and module = 'bom'
                """,
                (pending_id, client_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Pending upload not found or expired")
    parsed_rows, expires_at, created_at = row
    flatten_payload = (parsed_rows or {}).get("flatten")
    if not flatten_payload:
        raise HTTPException(400, "Pending is not a technical_flatten upload")
    products = (parsed_rows or {}).get("products") or {}
    summary = _summarize_flatten(flatten_payload, products=products,
                                 client_id=client_id)
    decisions = decisions_store.decisions_for_pending(pending_id)

    # Group versions by product_code for the redesigned UI.
    versions_by_product: dict[str, list[dict]] = {}
    for v in flatten_payload["versions"]:
        pc = v["key"]["product_code"]
        versions_by_product.setdefault(pc, []).append(v)
    # Sort: TPs first (have BTPs as material), then BTPs, then unresolved-only.
    def _sort_key(item):
        pc, vlist = item
        worst = "non_flattened" if any(v["flatten_status"] == "non_flattened" for v in vlist) else "flattened"
        is_btp = 1 if pc in summary["btp_codes"] else 0
        return (worst != "non_flattened", is_btp, pc)  # non_flattened first
    versions_grouped = sorted(versions_by_product.items(), key=_sort_key)

    return request.app.state.templates.TemplateResponse(
        request, "clients/bom_flatten_preview.html",
        {
            "client": client, "stats": stats_for_client(client_id),
            "pending_id": pending_id,
            "summary": summary,
            "versions_grouped": versions_grouped,
            "decisions": decisions,
            "expires_at": expires_at, "created_at": created_at,
            "active_root": "clients", "active_tab": "bom",
        },
    )


@router.post("/clients/{client_id}/bom/flatten-preview/{pending_id}/confirm")
async def flatten_preview_confirm(request: Request,
                                  client_id: str, pending_id: str):
    """Apply confirmed flatten variants. For each pending decision the
    form may carry:
        confirm_<decision_id> = on        → status=confirmed
        choose_<decision_id>  = <action>  → chosen_action override
    Variants whose blocking decisions remain `pending` or `rejected`
    are filtered out at materialization."""
    user = auth.require_user(request)
    auth.require_can_edit_client(user, client_id)
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")

    form = await request.form()

    with connect(user_id=user.user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select parsed_rows, upload_id from hub.upload_pending
                where pending_id = %s and client_id = %s and module = 'bom'
                  and expires_at > now()
                """,
                (pending_id, client_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Pending upload not found or expired")
    parsed_rows, upload_id = row
    flatten_payload = (parsed_rows or {}).get("flatten")
    if not flatten_payload:
        raise HTTPException(400, "Pending is not a technical_flatten upload")

    # Apply form decisions to DB.
    decisions = decisions_store.decisions_for_pending(pending_id)
    confirmed_actions: dict[str, str] = {}      # decision_id → chosen_action
    for d in decisions:
        did = d["decision_id"]
        if d["status"] == "auto":
            confirmed_actions[did] = d["chosen_action"]
            continue
        confirm_flag = form.get(f"confirm_{did}")
        chosen = form.get(f"choose_{did}") or d["chosen_action"]
        if confirm_flag == "on":
            decisions_store.confirm_decision(
                decision_id=did, user_id=user.user_id,
                chosen_action=chosen, status="confirmed",
            )
            confirmed_actions[did] = chosen
        else:
            decisions_store.confirm_decision(
                decision_id=did, user_id=user.user_id,
                chosen_action=chosen, status="rejected",
            )

    # Build a publish_filter that drops variants whose blocking decisions
    # weren't confirmed (or whose dual-source decision excluded this strategy).
    decisions_by_target: dict[tuple, list[dict]] = {}
    for d in decisions:
        target = (d.get("product_code") or "")
        decisions_by_target.setdefault(target, []).append(d)

    def publish_filter(v: FlattenedVersion) -> bool:
        relevant = decisions_by_target.get(v.key.product_code, [])
        for d in relevant:
            did = d["decision_id"]
            chosen = confirmed_actions.get(did)   # None ⇒ staff did not confirm
            # Non-flattened publishing requires an explicit confirm
            # (spec §11 — block by default).
            if d["decision_type"] == "non_flattened_publish":
                if v.flatten_status != "non_flattened":
                    continue
                if chosen != "publish_with_review_required":
                    return False
            # Dual-source variants ALL require explicit confirmation
            # (spec §11). chosen=None ⇒ staff did not confirm ⇒ block.
            # Per /rev finding C2: this gate runs regardless of
            # flatten_status. A dual variant that's also non_flattened
            # still needs the dual_source_variant confirm BEFORE the
            # non_flattened_publish gate is consulted.
            if d["decision_type"] == "dual_source_variant":
                if v.flatten_strategy not in (
                        "purchased_btp_as_leaf", "self_produced_btp_exploded"):
                    continue
                if chosen is None:
                    return False
                if chosen == "purchased_btp_as_leaf" \
                        and v.flatten_strategy != "purchased_btp_as_leaf":
                    return False
                if chosen == "self_produced_btp_exploded" \
                        and v.flatten_strategy != "self_produced_btp_exploded":
                    return False
                # chosen == 'publish_both' → both variants pass through.
        return True

    # Re-build FlattenResult from stash, then materialize.
    result = _deserialize_flatten_result(flatten_payload)
    decision_id_map_str = flatten_payload.get("decision_id_map") or {}
    decision_id_map = {int(k): v for k, v in decision_id_map_str.items()}

    materialized = create_flattened_artifact_set(
        client_id=client_id,
        source_upload_id=upload_id,
        result=result,
        decision_id_map=decision_id_map,
        publish_filter=publish_filter,
    )

    # Atomic-ish: only on full success, delete pending + flip status.
    n = len(materialized)
    with connect(user_id=user.user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from hub.upload_pending "
                "where pending_id = %s and client_id = %s and module = 'bom'",
                (pending_id, client_id),
            )
            cur.execute(
                "update hub.file_uploads set parse_status='done', "
                "row_count=%s, parsed_at=now() where upload_id=%s",
                (n, upload_id),
            )
    return RedirectResponse(
        url=f"/clients/{client_id}/bom?ingested={n}", status_code=303,
    )


@router.post("/clients/{client_id}/bom/flatten-preview/{pending_id}/reject")
async def flatten_preview_reject(request: Request,
                                 client_id: str, pending_id: str):
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
                "delete from hub.bom_flatten_decisions where pending_id = %s",
                (pending_id,),
            )
            cur.execute(
                "update hub.file_uploads set parse_status='rejected', parsed_at=now() where upload_id=%s",
                (upload_id,),
            )
    return RedirectResponse(
        url=f"/clients/{client_id}/bom?rejected=1", status_code=303,
    )
