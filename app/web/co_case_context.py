from __future__ import annotations

import hashlib
import json
import logging
import re
import threading

from app import co_stock_adjustments_store, co_stock_eligibility, co_stock_ledger, co_stock_materializer
from app.bom_service import bom_service
from app.bom_store import attach_case_bom_snapshot
from app.co_case_store import build_case_criteria_rows, case_from_record, co_case_delete_block_reason, co_case_is_completed, co_case_status_view, declaration_refs, get_case_record, get_case_workspace, json_safe, load_state
from app.co_form_config_store import load_co_form_config
from app.origin_material_filters import is_bom_technical_noise, is_declarable_unmatched
from app.co_forms import COMMON_MARKET_PRESETS, common_market_guidance, criteria_preview_for_hs, form_candidates_for_market, prioritized_form_lanes, recommended_form_lane
from app.co_market_hints import infer_market_from_invoice_matches
from app.customs_fx_store import CUSTOMS_FX_CLIENT_ID, get_customs_fx_store
from app.data_hub_client import bom_product_code_from_material_identity
from app.data_hub_settings import data_hub_link_settings
from app.demo_data import DEMO_CASE, SOURCE_NOTES, attach_results, clone_case
from app.origin import evaluate_tariff_shift
from app.portfolio import portfolio_service
from app.source_store import co_stock_rows_from_bcct
from app.web.client_context import case_finished_hs_codes, client_case, resolve_client
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


_CO_CASE_SOURCE_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}
_co_stock_refresh_inflight: set[str] = set()


ORIGIN_SHEET_STATUS_LABELS = {
    "draft": "Chưa tính",
    "bom_loaded": "Đã nạp BOM",
    "calculating": "Đang tính",
    "calculated": "Đã tính",
    "locked": "Chốt",
    "stale": "Cần tính lại",
}
def durable_sheet_status(status) -> str:
    """Coerce the transient `calculating` status to a durable one.

    `calculating` ("Đang tính") is set optimistically in the browser the instant
    staff click "Tính"; it must never persist as a resting state. A sheet found
    resting in it had its calculation interrupted, or an autosave/save captured
    the optimistic value from the form — which silently left the sheet
    un-lockable ("Chốt" requires status `calculated`). Recover it as `stale`
    ("Cần tính lại") so staff simply recalculate, then lock.
    """
    text = str(status or "").strip()
    return "stale" if text == "calculating" else text
def origin_case_revision(case: dict) -> str:
    # Optimistic-concurrency token over USER-EDITABLE case state only.
    #
    # It must NOT include source_snapshot / bom_snapshot / origin_snapshot: those
    # are DERIVED data recomputed on every render (co_case_context recomputes
    # source_snapshot via attach_case_source_summary_snapshot, plus bom/origin
    # snapshots via attach_*). source_snapshot in particular carries live source
    # metadata (bcct_reviewed_row_count, correction_candidate_count, catalog
    # version ids) that drifts continuously on prod as customs data flows. Routes
    # that persist before re-rendering (e.g. lock persists, then rebuilds the
    # source context for the response) therefore rendered a revision that no
    # longer matched the persisted one, so the NEXT action falsely 409'd with
    # "Origin case state changed; reload before saving" — forcing an F5 between
    # every sheet. Hashing only user intent keeps the token stable across benign
    # source refreshes while still catching real concurrent edits (reorder,
    # sheet status transitions, BOM version overrides).
    sheet_statuses = {
        str(code): (state.get("status") if isinstance(state, dict) else str(state or ""))
        for code, state in (case.get("origin_sheet_states") or {}).items()
    }
    payload = json_safe(
        {
            "origin_product_order": origin_product_order(case),
            "origin_sheet_statuses": sheet_statuses,
            "bom_product_artifact_overrides": case.get("bom_product_artifact_overrides", {}),
        }
    )
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


# Fields recomputed on every render — they drift continuously on prod (live
# customs/source metadata) and must not flip the dossier-export staleness key.
# Same rationale as origin_case_revision's snapshot exclusions.
_DOSSIER_REVISION_SKIP_KEYS = frozenset({
    "updated_at",
    "created_at",
    "source_snapshot",
    "bom_snapshot",
    "origin_snapshot",
    "source_invoice_matches",
})


def dossier_content_revision(record: dict) -> str:
    """Opaque content-revision token for a case's dossier export.

    Hashes everything in the persisted case record that affects the exported
    .zip (bảng kê / products, chứng từ, shipment declarations, close-state) and
    excludes derived snapshots that drift on every render. A saved export whose
    token no longer matches the current case is stale and must be regenerated —
    see `app/dossier_export_service.py`.
    """
    payload = json_safe({
        key: value
        for key, value in (record or {}).items()
        if key not in _DOSSIER_REVISION_SKIP_KEYS
    })
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
CO_CASE_WORKFLOW_STEPS = [
    {
        "key": "shipment",
        "label": "Lô hàng",
        "short_label": "1",
        "description": "Thông tin shipment, invoice, B/L và thị trường.",
    },
    {
        "key": "documents",
        "label": "Chứng từ",
        "short_label": "2",
        "description": "Upload BL, Invoice/Packing và các chứng từ bổ sung. TKX query sau khi chốt bảng kê.",
    },
    {
        "key": "origin",
        "label": "Bảng kê C/O",
        "short_label": "3",
        "description": "Tính tuần tự từng sheet, override tiêu chí/ngưỡng, thay NVL, chốt và sinh BOM artifact mới.",
    },
    {
        "key": "exports",
        "label": "TKX / TKN",
        "short_label": "4",
        "description": "Sau khi chốt bảng kê: query TKX/TKN từ Data Hub, bổ sung phần thiếu.",
    },
    {
        "key": "review",
        "label": "Review & Xuất",
        "short_label": "5",
        "description": "Kiểm tra dossier và xuất .zip tổng hợp (chứng từ + TKX/TKN + bảng kê HQ).",
    },
]
CO_CASE_WORKFLOW_STEP_KEYS = {step["key"] for step in CO_CASE_WORKFLOW_STEPS}
def co_case_light_context(client_id: str, case: dict, current_step: str, **extra) -> dict:
    client = resolve_client(client_id)
    fast_origin_context = bool(extra.pop("fast_origin_context", False))
    cached_case_context = fast_origin_context or bool(extra.pop("cached_case_context", False))
    force_source_refresh = bool(extra.pop("force_source_refresh", False))
    use_cached_context = cached_case_context and not force_source_refresh and bool(case.get("source_snapshot"))
    if use_cached_context:
        source_context = cached_origin_source_context(client, case)
    elif current_step == "origin":
        # Origin tab-load: stock from the materialized CO-stock snapshot +
        # narrow export invoice_matches, never the ~40s full BCCT pull.
        source_context = origin_source_context(client, case)
    else:
        # Non-origin steps only need source_summary + invoice_matches; skip the
        # heavy materials + BCCT pagination so the shipment tab (the default
        # landing tab) renders fast instead of ~21s for big clients.
        source_context = co_case_source_context(client, case, skip_heavy_context=True)
    if not use_cached_context:
        # Warm the TTL cache so the next substitute-modal open in this session
        # reuses the same Data Hub fetch (avoids 30s re-pagination for Johnson).
        # Only warm when a real materials pull happened: the converged origin
        # path returns material_rows=[] and must not overwrite the cache the
        # substitute-modal HS heuristic relies on.
        if source_context.get("material_rows"):
            import time
            persisted = case.get("persisted_case_id") or case.get("id") or ""
            shipment = case.get("shipment") or {}
            fingerprint = (
                client.get("id", ""),
                str(persisted),
                str(shipment.get("invoice_no") or ""),
                ",".join(sorted(shipment.get("export_declaration_nos") or [])),
                str(len(case.get("products") or [])),
            )
            _CO_CASE_SOURCE_CACHE[fingerprint] = (time.time(), source_context)
    source_summary = source_context["source_summary"]
    invoice_matches = source_context["invoice_matches"]
    reference_warnings = shipment_reference_warnings(case.get("shipment", {}), invoice_matches)
    case_workspace = extra.pop("case_workspace")
    form_candidates = extra.pop("form_candidates")
    criteria_rows = extra.pop("criteria_rows")
    if current_step == "origin":
        bom_product_codes = co_case_bom_product_codes(case, invoice_matches)
        picker_case_id = str(case.get("persisted_case_id") or case.get("id") or "")
        bom_workspace = (
            bom_service.workspace(client, product_codes=bom_product_codes, case_id=picker_case_id)
            if bom_product_codes
            else minimal_bom_workspace()
        )
        if use_cached_context and case.get("products") and not bom_workspace.get("product_versions"):
            bom_workspace = bom_workspace_from_case_snapshot(case)
    else:
        bom_workspace = minimal_bom_workspace()
    origin_demo_allowed = extra.pop("origin_demo_allowed", True)
    preserve_origin_products = extra.pop("preserve_origin_products", False)
    client = enrich_client_with_source_summary(client, source_summary)
    case = attach_case_source_summary_snapshot(case, source_summary)
    if not use_cached_context:
        case["source_invoice_matches"] = json_safe(invoice_matches)
    if current_step == "origin" and not use_cached_context:
        selected_lane = recommended_form_lane(
            prioritized_form_lanes(case.get("destination_market", ""), co_case_hs_codes(case, invoice_matches))
        )
        case = prepare_case_origin_product_shells(
            case,
            invoice_matches,
            bom_workspace,
            selected_lane,
            preserve_existing=preserve_origin_products,
        )
        case = attach_case_bom_snapshot(case, bom_workspace)
        case = attach_origin_bom_product_codes(case, bom_workspace)
        if case.get("products"):
            case = attach_origin_readiness(case)
            case = attach_results(case)
            case = attach_origin_sheet_states(case)
            criteria_rows = build_case_criteria_rows(case, form_candidates)
    elif current_step == "origin" and case.get("products"):
        if not use_cached_context:
            case = attach_case_bom_snapshot(case, bom_workspace)
            case = attach_origin_bom_product_codes(case, bom_workspace)
        case = attach_origin_readiness(case)
        case = attach_results(case)
        case = attach_origin_sheet_states(case)
        criteria_rows = build_case_criteria_rows(case, form_candidates)
    elif current_step == "origin":
        case = attach_case_bom_snapshot(case, bom_workspace)
    origin_demo_active = origin_demo_allowed and should_show_origin_demo(current_step, case, invoice_matches)
    if origin_demo_active:
        case = attach_origin_demo(case)
        case = attach_origin_readiness(case)
        case = attach_origin_sheet_states(case)
        criteria_rows = build_case_criteria_rows(case, form_candidates)
    form_lanes = prioritized_form_lanes(case.get("destination_market", ""), co_case_hs_codes(case, invoice_matches))
    selected_form_lane = recommended_form_lane(form_lanes)
    invoice_criteria_rows = invoice_match_criteria_rows(invoice_matches, selected_form_lane)
    invoice_lookup_preview = invoice_preview_from_matches(
        case.get("shipment", {}).get("invoice_no", ""),
        invoice_matches,
    )
    if not criteria_rows and invoice_criteria_rows:
        criteria_rows = invoice_criteria_rows
    context = {
        "client": client,
        "case": case,
        "active": "co-case",
        "bom_workspace": bom_workspace,
        "source_workspace": {},
        "client_config": source_summary["client_config"],
        "case_workspace": case_workspace,
        "form_candidates": form_candidates,
        "recommended_form_lane": selected_form_lane,
        "invoice_lookup_preview": invoice_lookup_preview,
        "common_market_presets": COMMON_MARKET_PRESETS,
        "common_market_guidance": common_market_guidance(),
        "co_form_options": [
            {"form_code": row["form_code"], "display_name": row.get("display_name") or row["form_code"]}
            for row in load_co_form_config().get("forms", [])
            if row.get("enabled")
        ],
        "tkx_tkn_summary": case_tkx_tkn_summary(
            case,
            invoice_matches,
            source_context.get("stock_rows") or [],
            source_context.get("declaration_file_counts") or {},
        ),
        "data_hub_base_url": data_hub_link_settings().data_hub_base_url,
        "invoice_matches": invoice_matches,
        "origin_source_context": source_context,
        "shipment_reference_warnings": reference_warnings,
        "invoice_criteria_rows": invoice_criteria_rows,
        "criteria_rows": criteria_rows,
        "origin_demo_active": origin_demo_active,
        "origin_demo_material_count": origin_material_count(case) if origin_demo_active else 0,
        "origin_case_revision": origin_case_revision,
        "source_notes": SOURCE_NOTES,
        "source_backend": source_context["source_backend"],
        **extra,
    }
    context["co_case_active_step"] = current_step
    context["co_case_steps"] = co_case_workflow_steps(
        client_id,
        context["case"],
        current_step,
        invoice_matches=invoice_matches,
        criteria_rows=criteria_rows,
        origin_demo_active=origin_demo_active,
        tkx_tkn_summary=context.get("tkx_tkn_summary"),
    )
    return context
_CO_CASE_SOURCE_CACHE_TTL_SECONDS = 90.0
def co_case_source_context(client: dict, case: dict, *, skip_heavy_context: bool = False) -> dict:
    return portfolio_service.co_case_source_context(
        client, case, skip_heavy_context=skip_heavy_context
    )
def co_case_source_context_cached(client: dict, case: dict) -> dict:
    """TTL-cached source_context for high-frequency endpoints (substitute modal,
    typeahead) where the underlying Data Hub catalog rarely changes within a
    session. Cache key includes case_id + shipment fingerprint so different
    cases / mutated shipments don't collide.

    For Johnson the underlying call paginates 11k materials + 65k BCCT rows
    (multi-second). Without this cache, every modal open re-paginated.

    Stock rows returned by this function ALWAYS reflect the current ledger
    state (used_qty / remaining_qty net of locked claims across all cases).
    """
    import time

    persisted = case.get("persisted_case_id") or case.get("id") or ""
    shipment = case.get("shipment") or {}
    fingerprint = (
        client.get("id", ""),
        str(persisted),
        str(shipment.get("invoice_no") or ""),
        ",".join(sorted(shipment.get("export_declaration_nos") or [])),
        str(len(case.get("products") or [])),
    )
    now = time.time()
    cached = _CO_CASE_SOURCE_CACHE.get(fingerprint)
    if cached and now - cached[0] < _CO_CASE_SOURCE_CACHE_TTL_SECONDS:
        context = cached[1]
    else:
        context = co_case_source_context(client, case)
        _CO_CASE_SOURCE_CACHE[fingerprint] = (now, context)
        if len(_CO_CASE_SOURCE_CACHE) > 32:
            oldest = sorted(_CO_CASE_SOURCE_CACHE.items(), key=lambda kv: kv[1][0])[0][0]
            _CO_CASE_SOURCE_CACHE.pop(oldest, None)
    # Always re-apply the ledger + manual adjustments — claim state changes
    # outside the cache window (sheet lock/unlock invalidates entry, adjustments
    # can be imported any time, but be defensive in case caller bypasses).
    client_id = client.get("id", "")
    used_by_lot = co_stock_ledger.used_qty_by_lot(client_id)
    adjustments = co_stock_adjustments_store.aggregate_by_lookup_key(client_id)
    if context.get("stock_rows"):
        # Don't mutate the cached list in place if someone else holds a reference;
        # snapshot a new list. Fold the static trừ-lùi (idempotent — safe whether
        # rows are materialized-and-folded or freshly derived) then overlay the
        # live cross-case ledger.
        rows = [dict(row) for row in context["stock_rows"]]
        co_stock_adjustments_store.fold_baseline(rows, adjustments or {})
        rows = co_stock_ledger.apply_used_qty(rows, used_by_lot)
        context = {**context, "stock_rows": rows}
    return context
def origin_source_context(client: dict, case: dict) -> dict:
    """Converged source context for the origin tab-load (cold path).

    Replaces the heavy co_case_source_context — whose dominant cost is the full
    list_bcct pull (~40s for Johnson) — with:
      - stock_rows = [] — the tab render shows per-product SHELLS only
        (prepare_case_origin_product_shells takes no stock_rows; allocation/tồn
        happen later in prepare_case_origin_sheet at Load BOM/Tính). Reading the
        full ~60k-row co_stock snapshot here cost 2.6s cold + 540ms/load on
        Johnson for data nothing at render consumes, so it is dropped; /calculate
        reads tồn independently via _calculate_stock_rows_from_snapshot.
      - invoice_matches from a narrow Data Hub fetch (per-declaration / by-codes
        export), persisted on the case downstream for the warm path to reuse;
      - material_rows = [] (unused at tab render; the substitute modal self-fetches).

    This is the COLD path: the warm reuse of case["source_invoice_matches"]
    lives upstream in cached_origin_source_context (gated on use_cached_context).
    We always re-fetch invoice_matches here so a force_source_refresh actually
    refreshes — never serve possibly-stale cached matches when the caller asked
    to bypass the cache.

    Brief: .ai/features/2026-06-08-origin-cold-load-perf.md
    """
    # In file-store mode (tests / offline dev) there is no materialized snapshot
    # and no Data Hub adapter, so use the cheap in-memory heavy path directly.
    if getattr(portfolio_service, "data_hub", None) is None:
        return co_case_source_context(client, case)

    source_summary, source_backend = portfolio_service.source_summary(client)
    client_config = source_summary.get("client_config", {}) if isinstance(source_summary, dict) else {}
    invoice_matches = portfolio_service.origin_invoice_matches(client, case, client_config)

    declaration_file_counts = {"export": {}, "import": {}}
    if hasattr(portfolio_service, "declaration_file_counts"):
        declaration_file_counts = portfolio_service.declaration_file_counts(
            client.get("id", ""), case, invoice_matches
        )
    return {
        "source_backend": source_backend,
        "source_summary": source_summary,
        "invoice_matches": invoice_matches,
        "material_rows": [],
        "stock_rows": [],
        "declaration_file_counts": declaration_file_counts,
    }
def declaration_file_count(
    declaration_file_counts: dict,
    direction: str,
    declaration_no: str,
) -> int:
    key = str(declaration_no or "").strip()
    if not key:
        return 0
    if (direction, key) in declaration_file_counts:
        return int(declaration_file_counts.get((direction, key)) or 0)
    direction_counts = declaration_file_counts.get(direction) if isinstance(declaration_file_counts, dict) else {}
    if isinstance(direction_counts, dict):
        return int(direction_counts.get(key) or 0)
    return 0
def case_tkx_tkn_summary(
    case: dict,
    invoice_matches: list[dict],
    stock_rows: list[dict],
    declaration_file_counts: dict | None = None,
) -> dict:
    """Aggregate TKX (export) and TKN (import) declarations referenced by the case.

    TKX/TKN presence means the declaration file exists, not merely that a BCCT
    row exists. BCCT rows only identify which declarations the case references.
    """
    invoice_matches = invoice_matches or []
    stock_rows = stock_rows or []
    declaration_file_counts = declaration_file_counts or {}
    tkx: dict[str, dict] = {}
    for row in invoice_matches:
        key = str(row.get("declaration_no") or "").strip()
        if not key:
            continue
        file_count = declaration_file_count(declaration_file_counts, "export", key)
        entry = tkx.setdefault(key, {
            "declaration_no": key,
            "in_data_hub": file_count > 0,
            "file_count": file_count,
            "lines": [],
            "declaration_type": str(row.get("declaration_type") or ""),
        })
        entry["lines"].append({
            "line_no": row.get("line_no", ""),
            "item_code": row.get("item_code", ""),
            "hs_code": row.get("hs_code", ""),
            "quantity": row.get("quantity", ""),
            "invoice_ref": row.get("invoice_ref", ""),
        })
    for declared in case.get("shipment", {}).get("export_declaration_nos", []) or []:
        declared_key = str(declared or "").strip()
        if not declared_key or declared_key in tkx:
            continue
        file_count = declaration_file_count(declaration_file_counts, "export", declared_key)
        tkx[declared_key] = {
            "declaration_no": declared_key,
            "in_data_hub": file_count > 0,
            "file_count": file_count,
            "lines": [],
            "declaration_type": "",
        }

    tkn: dict[str, dict] = {}
    for product in case.get("products", []) or []:
        if str(product.get("origin_sheet_status") or "").strip() != "locked":
            continue
        product_code = str(product.get("code") or "").strip()
        for material in product.get("materials", []) or []:
            for line in material.get("allocation_lines", []) or []:
                key = str(line.get("import_declaration_no") or "").strip()
                if not key:
                    continue
                file_count = declaration_file_count(declaration_file_counts, "import", key)
                entry = tkn.setdefault(key, {
                    "declaration_no": key,
                    "in_data_hub": file_count > 0,
                    "file_count": file_count,
                    "lines": [],
                    "products": set(),
                })
                entry["products"].add(product_code)
                entry["lines"].append({
                    "product_code": product_code,
                    "material_code": material.get("material_code", ""),
                    "line_no": line.get("import_line_no", ""),
                    "allocated_qty": line.get("allocated_qty", ""),
                })
    for entry in tkn.values():
        entry["products"] = sorted(entry["products"])
    return {
        "tkx": sorted(tkx.values(), key=lambda e: e["declaration_no"]),
        "tkn": sorted(tkn.values(), key=lambda e: e["declaration_no"]),
        "missing_tkx": [e for e in tkx.values() if not e["in_data_hub"]],
        "missing_tkn": [e for e in tkn.values() if not e["in_data_hub"]],
    }
def cached_origin_source_context(client: dict, case: dict) -> dict:
    cached_matches = case.get("source_invoice_matches") if isinstance(case.get("source_invoice_matches"), list) else []
    invoice_matches = cached_matches or [origin_match_from_existing_product(product) for product in case.get("products", [])]
    # The TKX/TKN file-status panel (exports/review steps) reads
    # declaration_file_counts. The cached path skips the heavy BCCT pull but must
    # still carry this — it's a narrow declarations call, not the 40s catalog
    # pull — otherwise every declaration falsely shows "Thiếu tờ khai".
    declaration_file_counts = {"export": {}, "import": {}}
    if getattr(portfolio_service, "data_hub", None) is not None and hasattr(portfolio_service, "declaration_file_counts"):
        declaration_file_counts = portfolio_service.declaration_file_counts(
            client.get("id", ""), case, invoice_matches
        )
    return {
        "source_backend": "case-snapshot",
        "source_summary": source_summary_from_case_snapshot(client, case),
        "invoice_matches": invoice_matches,
        "material_rows": [],
        "stock_rows": [],
        "declaration_file_counts": declaration_file_counts,
    }
def source_summary_from_case_snapshot(client: dict, case: dict) -> dict:
    snapshot = case.get("source_snapshot") if isinstance(case.get("source_snapshot"), dict) else {}
    counts = client.get("counts") if isinstance(client.get("counts"), dict) else {}
    return {
        "client_config": {
            "config_version": snapshot.get("client_config_version", ""),
            "config_hash": snapshot.get("client_config_hash", ""),
        },
        "material_catalog": {
            "published_row_count": int(counts.get("materials") or 0),
            "latest_version": {
                "version_id": snapshot.get("material_catalog_version_id", ""),
                "version_no": snapshot.get("material_catalog_version_no", ""),
            },
        },
        "product_catalog": {
            "published_row_count": int(counts.get("products") or 0),
            "latest_version": {
                "version_id": snapshot.get("product_catalog_version_id", ""),
                "version_no": snapshot.get("product_catalog_version_no", ""),
            },
        },
        "bcct": {
            "published_row_count": int(counts.get("bcct") or snapshot.get("bcct_reviewed_row_count") or 0),
            "reviewed_row_count": int(snapshot.get("bcct_reviewed_row_count") or 0),
            "correction_candidate_count": int(snapshot.get("correction_candidate_count") or 0),
            "latest_version": {
                "version_id": snapshot.get("bcct_version_id", ""),
                "version_no": snapshot.get("bcct_version_no", ""),
            },
        },
        "co_stock_row_count": int(counts.get("co_stock") or 0),
    }
def bom_workspace_from_case_snapshot(case: dict) -> dict:
    snapshot = case.get("bom_snapshot") if isinstance(case.get("bom_snapshot"), dict) else {}
    composition = [dict(row) for row in snapshot.get("composition", []) if isinstance(row, dict)]
    product_versions = []
    seen = set()
    for row in composition:
        product_code = str(row.get("product_code") or "").strip()
        version_id = str(row.get("product_artifact_id") or row.get("product_version_id") or row.get("artifact_id") or row.get("version_id") or "").strip()
        if not product_code or not version_id or version_id in seen:
            continue
        seen.add(version_id)
        product_versions.append({
            "product_code": product_code,
            "product_artifact_id": version_id,
            "product_version_id": version_id,
            "version_id": version_id,
            "product_artifact_no": row.get("product_artifact_no") or row.get("product_version_no") or row.get("artifact_no") or row.get("version_no") or "",
            "product_version_no": row.get("product_version_no") or row.get("version_no") or "",
            "version_no": row.get("product_version_no") or row.get("version_no") or "",
            "row_count": row.get("row_count", 0),
            "status": row.get("status") or "snapshot",
            "rows": None,
        })
    for product in case.get("products", []):
        product_code = str(product.get("bom_product_code") or product.get("code") or "").strip()
        version_id = str(product.get("bom_product_artifact_id") or product.get("bom_product_version_id") or "").strip()
        if not product_code or not version_id or version_id in seen:
            continue
        seen.add(version_id)
        product_versions.append({
            "product_code": product_code,
            "product_artifact_id": version_id,
            "product_version_id": version_id,
            "version_id": version_id,
            "product_artifact_no": product.get("bom_product_artifact_no") or product.get("bom_product_version_no", ""),
            "product_version_no": product.get("bom_product_version_no", ""),
            "version_no": product.get("bom_product_version_no", ""),
            "row_count": len(product.get("materials", []) or []),
            "status": "snapshot",
            "rows": None,
        })
    options_by_code: dict[str, list[dict]] = {}
    for version in product_versions:
        options_by_code.setdefault(version["product_code"], []).append(version)
    aggregate = {
        "artifact_id": snapshot.get("aggregate_artifact_id") or snapshot.get("aggregate_version_id", ""),
        "artifact_no": snapshot.get("aggregate_artifact_no") or snapshot.get("aggregate_version_no", ""),
        "version_id": snapshot.get("aggregate_artifact_id") or snapshot.get("aggregate_version_id", ""),
        "version_no": snapshot.get("aggregate_artifact_no") or snapshot.get("aggregate_version_no", ""),
        "product_versions": composition,
        "rows": [],
    }
    return {
        "versions": [aggregate] if aggregate["version_id"] else [],
        "product_versions": product_versions,
        "product_version_options_by_code": options_by_code,
        "latest_version": aggregate,
        "latest_rows": [],
    }
def co_case_bom_product_codes(case: dict, invoice_matches: list[dict]) -> list[str]:
    codes = []
    for row in invoice_matches:
        bom_product_code = bom_product_code_from_material_identity(row) or str(row.get("bom_product_code") or "").strip()
        add_bom_code(
            codes,
            bom_product_code or str(row.get("item_code") or row.get("product_code") or row.get("customs_code") or "").strip(),
        )
    for product in case.get("products", []):
        add_bom_code(
            codes,
            str(product.get("bom_product_code") or product.get("code") or product.get("product_code") or "").strip(),
        )
    override_codes = {
        **(case.get("bom_product_version_overrides", {}) or {}),
        **(case.get("bom_product_artifact_overrides", {}) or {}),
    }
    for code in override_codes:
        add_bom_code(codes, str(code or "").strip())
    return codes
def add_bom_code(codes: list[str], code: str) -> None:
    code = str(code or "").strip()
    if code and code not in codes:
        codes.append(code)
def bom_code_candidates(code: str) -> list[str]:
    code = str(code or "").strip()
    if not code:
        return []
    return [code]
def shipment_reference_warnings(shipment: dict, invoice_matches: list[dict]) -> list[str]:
    warnings = [
        str(row.get("reference_warning") or "").strip()
        for row in invoice_matches
        if str(row.get("reference_warning") or "").strip()
    ]
    declarations = declaration_refs(shipment.get("export_declaration_nos"))
    if declarations and not invoice_matches:
        warnings.append(
            f"Chưa thấy dòng BCCT xuất khẩu đã duyệt cho tờ khai {', '.join(declarations)}."
        )
    return unique_texts(warnings)
def primary_shipment_reference(shipment: dict) -> str:
    declarations = declaration_refs(shipment.get("export_declaration_nos"))
    if declarations:
        return "Tờ khai " + ", ".join(declarations)
    invoice_no = str(shipment.get("invoice_no") or "").strip()
    return f"Invoice {invoice_no}" if invoice_no else "Chưa nhập"
def has_shipment_reference(shipment: dict) -> bool:
    return bool(str(shipment.get("invoice_no") or "").strip() or declaration_refs(shipment.get("export_declaration_nos")))
def invoice_preview_from_matches(invoice_no: str, invoice_matches: list[dict]) -> dict:
    invoice_no = str(invoice_no or "").strip()
    inference = infer_market_from_invoice_matches(invoice_matches)
    hs_codes = co_case_hs_codes({"shipment": {"invoice_no": invoice_no}}, invoice_matches)
    suggested_forms = []
    if inference.get("status") == "ready":
        suggested_forms = [
            invoice_form_lane_view(row)
            for row in prioritized_form_lanes(inference["destination_market"], hs_codes)
        ]
    summary = invoice_match_summary(invoice_matches)
    return {
        "status": "found" if invoice_matches else "not_found" if invoice_no else "empty",
        "invoice_no": invoice_no,
        "match_count": len(invoice_matches),
        "matches": [invoice_match_preview_row(row) for row in invoice_matches[:12]],
        "summary": summary,
        "market_inference": market_inference_view(inference),
        "suggested_forms": suggested_forms,
        "options": [],
    }
def invoice_match_summary(invoice_matches: list[dict]) -> dict:
    declarations = sorted({
        str(row.get("declaration_no") or "")
        for row in invoice_matches
        if row.get("declaration_no")
    })
    hs_codes = sorted({
        str(row.get("hs_code") or "")
        for row in invoice_matches
        if row.get("hs_code")
    })
    item_codes = sorted({
        str(row.get("item_code") or "")
        for row in invoice_matches
        if row.get("item_code")
    })
    invoice_refs = sorted({
        str(row.get("invoice_ref") or "")
        for row in invoice_matches
        if row.get("invoice_ref")
    })
    return {
        "declaration_count": len(declarations),
        "declarations": declarations[:8],
        "hs_codes": hs_codes[:12],
        "item_codes": item_codes[:8],
        "invoice_refs": invoice_refs[:4],
    }
def invoice_match_preview_row(row: dict) -> dict:
    return {
        "declaration_no": row.get("declaration_no", ""),
        "line_no": row.get("line_no", ""),
        "declaration_type": row.get("declaration_type", ""),
        "item_code": row.get("item_code", ""),
        "description": row.get("description", ""),
        "hs_code": row.get("hs_code", ""),
        "quantity": row.get("quantity", ""),
        "unit": row.get("unit", ""),
        "customs_value": row.get("customs_value") or row.get("total_value", ""),
        "value_currency": row.get("value_currency") or row.get("currency", ""),
        "invoice_ref": row.get("invoice_ref", ""),
        "unloading_location": row.get("unloading_location") or row.get("destination_location_name", ""),
        "consignee_name": row.get("consignee_name", ""),
    }
def market_inference_view(inference: dict) -> dict:
    status = inference.get("status", "missing")
    hints = inference.get("hints", [])
    if status == "ready" and hints:
        hint = hints[0]
        source_field = str(hint.get("source_field") or "market_hint")
        source_value = str(hint.get("source_value") or hint.get("country_name") or hint.get("country_code") or "")
        explanation = (
            f"Gợi ý từ {source_field} = {source_value}. "
            "Các dòng invoice chỉ có một quốc gia đích đủ độ tin cậy cao."
        )
        action_label = f"Dùng thị trường {inference.get('destination_market', '')}"
    elif status == "conflict":
        markets = ", ".join(
            str(hint.get("country_name") or hint.get("country_code") or "")
            for hint in hints
            if hint.get("country_name") or hint.get("country_code")
        )
        explanation = f"Không tự chọn vì invoice có nhiều gợi ý thị trường: {markets}."
        action_label = ""
    else:
        explanation = "Chưa có market hint đủ tin cậy từ dữ liệu invoice; cần chọn thị trường thủ công."
        action_label = ""
    return {
        **inference,
        "explanation": explanation,
        "action_label": action_label,
    }
def invoice_form_lane_view(row: dict) -> dict:
    return {
        "form_code": row.get("form_code", ""),
        "display_name": row.get("display_name", ""),
        "agreement": row.get("agreement", ""),
        "instrument": row.get("instrument", ""),
        "reason": row.get("reason", ""),
        "recommended": bool(row.get("recommended")),
        "criteria_preview": row.get("criteria_preview", [])[:4],
    }
def should_show_origin_demo(current_step: str, case: dict, invoice_matches: list[dict]) -> bool:
    return current_step == "origin" and not case.get("products") and not invoice_matches
def attach_origin_demo(case: dict) -> dict:
    demo = attach_results(clone_case(DEMO_CASE))
    case = dict(case)
    case["products"] = demo["products"]
    if not case.get("documents"):
        case["documents"] = demo["documents"]
    case["summary"] = demo["summary"]
    case["mode"] = "Demo tự nạp trong tab Xuất xứ"
    case["mode_note"] = "Dùng khi hồ sơ chưa có đủ invoice/BCCT/BOM để tính thật; không ghi vào hồ sơ lưu."
    return case
def origin_material_count(case: dict) -> int:
    return sum(len(product.get("materials", [])) for product in case.get("products", []))
def co_case_hs_codes(case: dict, invoice_matches: list[dict]) -> list[str]:
    product_hs = case_finished_hs_codes(case)
    if product_hs:
        return product_hs
    return [
        str(row.get("hs_code", ""))
        for row in invoice_matches
        if str(row.get("hs_code", "")).strip()
    ]
def prepare_case_origin_products(
    case: dict,
    invoice_matches: list[dict],
    bom_workspace: dict,
    form_lane: dict,
    material_rows: list[dict],
    stock_rows: list[dict],
    *,
    preserve_existing: bool = False,
) -> dict:
    source_matches = (
        invoice_matches
        if invoice_matches
        else [origin_match_from_existing_product(product) for product in case.get("products", [])]
    )
    if not source_matches:
        return case

    ordered_invoice_matches = order_invoice_matches_for_origin(case, source_matches) if invoice_matches else source_matches
    bom_rows_by_product = selected_bom_rows_by_product(case, bom_workspace)
    build_signature = origin_build_signature(ordered_invoice_matches, bom_rows_by_product, material_rows, stock_rows, form_lane)
    if (
        case.get("products")
        and (
            preserve_existing
            or case.get("origin_snapshot", {}).get("build_signature") == build_signature
        )
    ):
        return case

    material_index = material_catalog_index(material_rows)
    stock_pool = case_allocation_pool(case, ordered_invoice_matches, stock_rows)
    products = []
    for product_sequence, match in enumerate(ordered_invoice_matches, start=1):
        product_code = str(match.get("item_code", "")).strip()
        if not product_code:
            continue
        bom_product_code = bom_product_code_from_material_identity(match) or resolve_bom_product_code(
            product_code,
            bom_workspace,
        )
        product_rows = bom_rows_by_product.get(product_code) or bom_rows_by_product.get(bom_product_code, [])
        products.append(origin_product_from_invoice_match(
            match,
            product_rows,
            form_lane,
            material_index,
            stock_pool,
            product_sequence=product_sequence,
            bom_product_code=bom_product_code,
        ))
    if not products:
        return case

    prepared = dict(case)
    prepared["products"] = products
    prepared["mode"] = "Invoice + BCCT + BOM snapshot"
    prepared["mode_note"] = "Sản phẩm lấy từ BCCT xuất khẩu khớp invoice; NVL lấy từ BOM snapshot hiện hành. Đơn giá NVL ưu tiên từ tồn CO/BCCT nhập, nếu thiếu mới fallback danh mục NVL."
    prepared["origin_snapshot"] = {
        "source": "invoice_bcct_bom",
        "build_signature": build_signature,
        "invoice_no": prepared.get("shipment", {}).get("invoice_no", ""),
        "invoice_match_count": len(ordered_invoice_matches),
        "product_order": [product.get("code", "") for product in products],
        "product_count": len(products),
        "material_count": sum(len(product.get("materials", [])) for product in products),
        "stock_row_count": len(stock_rows),
    }
    return prepared
def prepare_case_origin_product_shells(
    case: dict,
    invoice_matches: list[dict],
    bom_workspace: dict,
    form_lane: dict,
    *,
    preserve_existing: bool = True,
) -> dict:
    """Create per-product origin sheets without calculating BOM/material rows.

    The origin page should show the workbook and let staff explicitly load each
    sheet. Allocation and VNM calculation only happen in prepare_case_origin_sheet.
    """
    source_matches = (
        invoice_matches
        if invoice_matches
        else [origin_match_from_existing_product(product) for product in case.get("products", [])]
    )
    if not source_matches:
        return case

    ordered_invoice_matches = order_invoice_matches_for_origin(case, source_matches) if invoice_matches else source_matches
    bom_rows_by_product = selected_bom_rows_by_product(case, bom_workspace)
    existing_by_code = {
        str(product.get("code") or product.get("product_code") or "").strip(): dict(product)
        for product in case.get("products", [])
        if str(product.get("code") or product.get("product_code") or "").strip()
    }
    products = []
    for product_sequence, match in enumerate(ordered_invoice_matches, start=1):
        product_code = str(match.get("item_code") or match.get("product_code") or "").strip()
        if not product_code:
            continue
        existing = existing_by_code.get(product_code)
        if preserve_existing and existing and existing.get("materials"):
            product = dict(existing)
            product["allocation_sequence"] = str(product_sequence)
            products.append(product)
            continue
        bom_product_code = bom_product_code_from_material_identity(match) or resolve_bom_product_code(
            product_code,
            bom_workspace,
        )
        product_rows = bom_rows_by_product.get(product_code) or bom_rows_by_product.get(bom_product_code, [])
        shell = origin_product_shell_from_invoice_match(
            match,
            product_rows,
            form_lane,
            product_sequence=product_sequence,
            bom_product_code=bom_product_code,
        )
        if preserve_existing and existing:
            shell = {
                **shell,
                "materials": existing.get("materials", []),
                "origin_sheet_material_overrides": existing.get("origin_sheet_material_overrides", {}),
            }
        products.append(shell)
    if not products:
        return case

    prepared = dict(case)
    prepared["products"] = products
    prepared["mode"] = "Invoice + BCCT + BOM snapshot"
    prepared["mode_note"] = "Sản phẩm lấy từ BCCT xuất khẩu khớp invoice; bấm Load BOM trên từng sheet để tính NVL và tồn CO."
    prepared["origin_snapshot"] = {
        **dict(prepared.get("origin_snapshot") or {}),
        "source": "invoice_bcct_bom",
        "invoice_no": prepared.get("shipment", {}).get("invoice_no", ""),
        "invoice_match_count": len(ordered_invoice_matches),
        "product_order": [product.get("code", "") for product in products],
        "product_count": len(products),
        "material_count": sum(len(product.get("materials", [])) for product in products),
    }
    return prepared
def prepare_case_origin_sheet(
    case: dict,
    product_code: str,
    invoice_matches: list[dict],
    bom_workspace: dict,
    form_lane: dict,
    material_rows: list[dict],
    stock_rows: list[dict],
    *,
    min_gap_days: int | None = None,
    allocate: bool = True,
) -> dict:
    target_code = str(product_code or "").strip()
    if not target_code:
        return case
    source_matches = (
        invoice_matches
        if invoice_matches
        else [origin_match_from_existing_product(product) for product in case.get("products", [])]
    )
    ordered_invoice_matches = order_invoice_matches_for_origin(case, source_matches) if invoice_matches else source_matches
    target_match = None
    target_sequence = 0
    products_by_code = {str(product.get("code") or product.get("product_code") or "").strip(): product for product in case.get("products", [])}
    stock_pool = case_allocation_pool(case, ordered_invoice_matches, stock_rows, min_gap_days=min_gap_days) if allocate else {}
    for sequence, match in enumerate(ordered_invoice_matches, start=1):
        match_code = str(match.get("item_code") or match.get("product_code") or "").strip()
        if match_code == target_code:
            target_match = match
            target_sequence = sequence
            break
        existing_product = products_by_code.get(match_code)
        if existing_product and allocate:
            apply_existing_origin_product_consumption(existing_product, stock_pool)
    if not target_match:
        return case

    bom_rows_by_product = selected_bom_rows_by_product(case, bom_workspace)
    material_index = material_catalog_index(material_rows)
    bom_product_code = bom_product_code_from_material_identity(target_match) or resolve_bom_product_code(
        target_code,
        bom_workspace,
    )
    product_rows = bom_rows_by_product.get(target_code) or bom_rows_by_product.get(bom_product_code, [])
    recalculated_product = origin_product_from_invoice_match(
        target_match,
        product_rows,
        form_lane,
        material_index,
        stock_pool,
        product_sequence=target_sequence,
        bom_product_code=bom_product_code,
        allocate=allocate,
    )
    products = []
    changed = False
    for product in case.get("products", []):
        code = str(product.get("code") or product.get("product_code") or "").strip()
        if code == target_code and not changed:
            products.append(recalculated_product)
            changed = True
        else:
            products.append(product)
    if not changed:
        products.append(recalculated_product)
    prepared = dict(case)
    prepared["products"] = products
    return prepared
def origin_product_shell_from_invoice_match(
    match: dict,
    bom_rows: list[dict],
    form_lane: dict,
    *,
    product_sequence: int | None = None,
    bom_product_code: str = "",
) -> dict:
    product_code = str(match.get("item_code") or match.get("product_code") or "").strip()
    bom_product_code = str(bom_product_code or product_code).strip()
    finished_hs = str(match.get("hs_code", "")).strip()
    preview = criteria_preview_for_hs(form_lane.get("form_code", ""), finished_hs) if form_lane else {}
    criterion = preview.get("criteria") or "Cần tra cứu PSR theo HS"
    threshold = lvc_threshold_from_criterion(criterion)
    quantity = decimal_value(match.get("quantity", "0"))
    product_value = origin_product_value(match)
    fob = product_value["value"]
    first_row = bom_rows[0] if bom_rows else {}
    product = {
        "code": product_code,
        "bom_product_code": bom_product_code,
        "allocation_sequence": str(product_sequence or ""),
        "name": match.get("description") or product_code,
        "finished_hs": finished_hs,
        "quantity": decimal_text(quantity),
        "unit": match.get("unit", ""),
        "currency": product_value["currency"],
        "fob_currency": product_value["currency"] or match.get("currency", ""),
        "declared_currency": match.get("currency", ""),
        "value_source": product_value["source"],
        "source_declaration_no": match.get("declaration_no", ""),
        "source_declaration_date": match.get("declaration_date") or match.get("registration_date", ""),
        "source_line_no": match.get("line_no", ""),
        "invoice_ref": match.get("invoice_ref", ""),
        "fob": decimal_text(fob) if fob is not None else "",
        "non_origin_value": "",
        "rvc_threshold": decimal_text(threshold) if threshold is not None else "",
        "documented_result": criterion,
        "lvc_percentage": "",
        "lvc_status": "review",
        "lvc_status_label": "Chưa tính",
        "lvc_threshold": decimal_text(threshold) if threshold is not None else "",
        "vnm_value": "",
        "bom_product_artifact_id": first_row.get("product_artifact_id") or first_row.get("product_version_id", ""),
        "bom_product_artifact_no": first_row.get("product_artifact_no") or first_row.get("product_version_no", ""),
        "bom_product_version_id": first_row.get("product_artifact_id") or first_row.get("product_version_id", ""),
        "bom_product_version_no": first_row.get("product_artifact_no") or first_row.get("product_version_no", ""),
        "materials": [],
    }
    return enrich_origin_product(product)
def apply_existing_origin_product_consumption(product: dict, stock_pool: dict[str, list[dict]]) -> None:
    for material in product.get("materials", []) or []:
        material_code = str(material.get("material_code") or material.get("internal_material_code") or "").strip()
        if not material_code:
            continue
        for line in material.get("allocation_lines", []) or []:
            allocated_qty = decimal_value(line.get("allocated_qty"))
            if allocated_qty <= 0:
                continue
            stock = stock_for_existing_allocation_line(stock_pool, material_code, line)
            if not stock:
                continue
            remaining_qty = stock_allocation_remaining_qty(stock)
            stock["_allocation_remaining_qty"] = remaining_qty - allocated_qty
            allocation_context = {
                "product_sequence": line.get("product_sequence") or product.get("allocation_sequence", ""),
                "product_code": line.get("product_code") or product.get("code", ""),
                "product_name": product.get("name", ""),
                "material_sequence": line.get("material_sequence") or material.get("material_sequence", ""),
                "material_code": material_code,
                "material_uom": material.get("uom", ""),
            }
            stock.setdefault("_allocation_consumptions", []).append(stock_allocation_consumption(line, allocation_context))
def stock_for_existing_allocation_line(stock_pool: dict[str, list[dict]], material_code: str, line: dict) -> dict:
    candidates = stock_candidates_for_material(stock_pool, material_code)
    for stock in candidates:
        if allocation_line_matches_stock(line, stock):
            return stock
    return {}
def allocation_line_matches_stock(line: dict, stock: dict) -> bool:
    checks = [
        ("source_row", "source_row"),
        ("import_declaration_no", "import_declaration_no"),
        ("import_line_no", "line_no"),
        ("allocation_code", "allocation_code"),
    ]
    matched = False
    for line_key, stock_key in checks:
        line_value = str(line.get(line_key) or "").strip()
        stock_value = str(stock.get(stock_key) or "").strip()
        if line_value and stock_value:
            if line_value != stock_value:
                return False
            matched = True
    return matched
def order_invoice_matches_for_origin(case: dict, invoice_matches: list[dict]) -> list[dict]:
    order = origin_product_order(case)
    if not order:
        return list(invoice_matches)
    rank = {code: index for index, code in enumerate(order)}

    def sort_key(item: tuple[int, dict]) -> tuple[int, int]:
        index, row = item
        code = str(row.get("item_code") or row.get("product_code") or row.get("customs_code") or "").strip()
        return rank.get(code, len(rank) + index), index

    return [row for _, row in sorted(enumerate(invoice_matches), key=sort_key)]
def origin_product_order(case: dict) -> list[str]:
    raw_order = case.get("origin_product_order") or case.get("origin_snapshot", {}).get("product_order", [])
    if isinstance(raw_order, str):
        candidates = re.split(r"[|,\n]", raw_order)
    elif isinstance(raw_order, (list, tuple)):
        candidates = raw_order
    else:
        candidates = []
    output = []
    for candidate in candidates:
        code = str(candidate or "").strip()
        if code and code not in output:
            output.append(code)
    return output
def _attach_fob_vnd(product: dict) -> None:
    """Compute product.fob_vnd from fob × FX rate at the product's declaration date.

    fob_currency falls back to product.currency (set when the product was built
    from a BCCT match). For VND-native cases, fob_vnd = fob. For non-VND with
    no FX hit, fob_vnd stays empty + fob_fx_source = "missing" so the renderer
    can show a warning instead of a wrong number.
    """
    fob_raw = str(product.get("fob") or "").strip()
    if not fob_raw:
        product["fob_vnd"] = ""
        product["fob_fx_source"] = "missing"
        return
    fob_currency = str(product.get("fob_currency") or product.get("currency") or "").strip().upper()
    try:
        fob_dec = Decimal(fob_raw)
    except (InvalidOperation, ValueError):
        product["fob_vnd"] = ""
        product["fob_fx_source"] = "missing"
        return
    if not fob_currency or fob_currency == "VND":
        product["fob_vnd"] = decimal_text(fob_dec)
        product["fob_fx_source"] = "vnd_native"
        return
    target_date = str(
        product.get("source_declaration_date")
        or product.get("export_declaration_date")
        or product.get("invoice_date")
        or ""
    ).strip()
    try:
        from app.customs_fx_store import CUSTOMS_FX_CLIENT_ID, get_customs_fx_store, lookup_exchange_rate
        rows = get_customs_fx_store().rows(CUSTOMS_FX_CLIENT_ID)
        hit = lookup_exchange_rate(rows, fob_currency, target_date) if target_date else None
    except Exception:  # noqa: BLE001 — fob_vnd is optional; never block render
        hit = None
    if hit and hit.get("rate_vnd_per_unit"):
        try:
            rate = Decimal(str(hit["rate_vnd_per_unit"]))
        except (InvalidOperation, ValueError):
            rate = None
        if rate and rate > 0:
            product["fob_vnd"] = decimal_text(fob_dec * rate)
            product["fob_fx_rate"] = decimal_text(rate)
            product["fob_fx_source"] = "customs_lookup"
            return
    product["fob_vnd"] = ""
    product["fob_fx_source"] = "missing"
def attach_origin_sheet_states(case: dict) -> dict:
    products = case.get("products", [])
    existing = case.get("origin_sheet_states") if isinstance(case.get("origin_sheet_states"), dict) else {}
    normalized = {}
    market = case.get("destination_market", "")
    for product in products:
        code = str(product.get("code") or "").strip()
        if not code:
            continue
        raw_state = existing.get(code) if isinstance(existing.get(code), dict) else {}
        # Default = "draft" (Chưa tính). A sheet only becomes "calculated"
        # after staff explicitly clicks "Tính bảng kê" (which sets it via
        # set_origin_sheet_status). Never auto-mark calculated even when the
        # underlying snapshot has data — staff has to confirm intent.
        default_status = "draft"
        # `durable_sheet_status` rescues any sheet left resting in the transient
        # `calculating` state (interrupted calc / autosaved optimistic status)
        # so it never stays silently un-lockable.
        status = durable_sheet_status(raw_state.get("status") or default_status)
        if status not in ORIGIN_SHEET_STATUS_LABELS:
            status = default_status
        recommendation = sheet_form_recommendation(market, product.get("finished_hs", ""))
        form_override = str(raw_state.get("form_override") or "").strip()
        criteria_override = str(raw_state.get("criteria_override") or "").strip()
        lvc_threshold_override = normalize_threshold(raw_state.get("lvc_threshold_override"))
        rvc_threshold_override = normalize_threshold(raw_state.get("rvc_threshold_override"))
        currency_mode = str(raw_state.get("currency_mode") or "").strip().lower()
        if currency_mode not in SHEET_CURRENCY_MODES:
            currency_mode = "native"
        optimization_mode = str(raw_state.get("optimization_mode") or "").strip().lower()
        if optimization_mode not in SHEET_OPTIMIZATION_MODES:
            optimization_mode = "max_lvc"
        effective_form = form_override or recommendation.get("form_code", "")
        effective_criteria = criteria_override or recommendation.get("criteria_text", "")
        effective_lvc_threshold = lvc_threshold_override or str(product.get("lvc_threshold") or "").strip()
        effective_rvc_threshold = rvc_threshold_override or str(product.get("rvc_threshold") or "").strip()
        state = {
            "status": status,
            "status_label": ORIGIN_SHEET_STATUS_LABELS[status],
            "form_override": form_override,
            "criteria_override": criteria_override,
            "lvc_threshold_override": lvc_threshold_override,
            "rvc_threshold_override": rvc_threshold_override,
            "currency_mode": currency_mode,
            "optimization_mode": optimization_mode,
            "recommended_form_code": recommendation.get("form_code", ""),
            "recommended_form_label": recommendation.get("form_label", ""),
            "recommended_criteria_text": recommendation.get("criteria_text", ""),
            "recommendation_source": recommendation.get("source", ""),
            "effective_form_code": effective_form,
            "effective_criteria_text": effective_criteria,
            "effective_lvc_threshold": effective_lvc_threshold,
            "effective_rvc_threshold": effective_rvc_threshold,
        }
        normalized[code] = state
        product["origin_sheet_state"] = state
        product["origin_sheet_status"] = state["status"]
        product["origin_sheet_status_label"] = state["status_label"]
        product["origin_sheet_form_override"] = form_override
        product["origin_sheet_criteria_override"] = criteria_override
        product["origin_sheet_lvc_threshold_override"] = lvc_threshold_override
        product["origin_sheet_rvc_threshold_override"] = rvc_threshold_override
        product["origin_sheet_currency_mode"] = currency_mode
        product["origin_sheet_optimization_mode"] = optimization_mode
        _attach_fob_vnd(product)
        product["origin_sheet_recommended_form_code"] = state["recommended_form_code"]
        product["origin_sheet_recommended_form_label"] = state["recommended_form_label"]
        product["origin_sheet_recommended_criteria_text"] = state["recommended_criteria_text"]
        product["origin_sheet_effective_form_code"] = effective_form
        product["origin_sheet_effective_criteria_text"] = effective_criteria
        product["origin_sheet_effective_lvc_threshold"] = effective_lvc_threshold
        product["origin_sheet_effective_rvc_threshold"] = effective_rvc_threshold
        material_overrides = raw_state.get("material_overrides") if isinstance(raw_state.get("material_overrides"), dict) else {}
        # Carry overrides on the sheet state so they round-trip through save/calculate.
        state["material_overrides"] = {str(k): dict(v) for k, v in material_overrides.items() if isinstance(v, dict)}
        diff_added = sum(1 for v in state["material_overrides"].values() if v.get("added"))
        diff_removed = sum(1 for v in state["material_overrides"].values() if v.get("deleted"))
        diff_replaced = sum(
            1 for v in state["material_overrides"].values()
            if not v.get("added") and not v.get("deleted") and v.get("material_code") and not v.get("norm_edit_only")
        )
        diff_norm_only = sum(
            1 for v in state["material_overrides"].values()
            if v.get("norm_edit_only") and not v.get("added") and not v.get("deleted")
        )
        state["material_diff_added"] = diff_added
        state["material_diff_removed"] = diff_removed
        state["material_diff_replaced"] = diff_replaced
        state["material_diff_norm_only"] = diff_norm_only
        state["material_diff_total"] = diff_added + diff_removed + diff_replaced + diff_norm_only
        product["origin_sheet_material_overrides"] = state["material_overrides"]
        product["origin_sheet_has_material_overrides"] = state["material_diff_total"] > 0
        product["origin_sheet_material_diff_added"] = diff_added
        product["origin_sheet_material_diff_removed"] = diff_removed
        product["origin_sheet_material_diff_replaced"] = diff_replaced
        product["origin_sheet_material_diff_norm_only"] = diff_norm_only
        product["origin_sheet_material_diff_total"] = state["material_diff_total"]
        proposed_artifact_id = str(raw_state.get("proposed_artifact_id") or "").strip()
        proposed_proposal_id = str(raw_state.get("proposed_proposal_id") or "").strip()
        proposed_status = str(raw_state.get("proposed_status") or "").strip()
        state["proposed_artifact_id"] = proposed_artifact_id
        state["proposed_proposal_id"] = proposed_proposal_id
        state["proposed_status"] = proposed_status
        product["origin_sheet_proposed_artifact_id"] = proposed_artifact_id
        product["origin_sheet_proposed_proposal_id"] = proposed_proposal_id
        product["origin_sheet_proposed_status"] = proposed_status
    for index, product in enumerate(products):
        code = str(product.get("code") or "").strip()
        status = product.get("origin_sheet_status")
        previous_unlocked = [
            str(previous.get("code") or "")
            for previous in products[:index]
            if previous.get("origin_sheet_status") != "locked"
        ]
        later_locked = [
            str(later.get("code") or "")
            for later in products[index + 1:]
            if later.get("origin_sheet_status") == "locked"
        ]
        sequence_reason = ""
        if previous_unlocked:
            sequence_reason = f"Cần chốt các bước trước: {', '.join(previous_unlocked[:5])}."
        elif later_locked:
            sequence_reason = f"Cần mở chốt các bước sau trước: {', '.join(later_locked[:5])}."
        product["origin_can_calculate"] = bool(code and status != "locked" and not sequence_reason)
        product["origin_calculate_block_reason"] = (
            f"Bảng kê {code} đã chốt; cần mở chốt trước khi tính lại."
            if status == "locked"
            else sequence_reason
        )
        product["origin_can_lock"] = bool(code and status == "calculated" and not sequence_reason)
        product["origin_lock_block_reason"] = (
            "" if product["origin_can_lock"] else sequence_reason or f"Chỉ chốt được bảng kê {code} sau khi đã tính."
        )
        product["origin_can_reopen"] = bool(code and status == "locked" and not later_locked)
        product["origin_reopen_block_reason"] = (
            "" if product["origin_can_reopen"] else f"Chỉ được mở chốt từ bước cuối cùng; cần mở chốt {', '.join(later_locked[:5])} trước." if later_locked else ""
        )
    prepared = dict(case)
    prepared["origin_sheet_states"] = normalized
    return prepared
SHEET_CURRENCY_MODES = {"native", "vnd"}
SHEET_OPTIMIZATION_MODES = {"max_lvc", "min_lvc"}
def normalize_threshold(value) -> str:
    text = str(value or "").strip().rstrip("%").strip()
    if not text:
        return ""
    try:
        decimal_value = Decimal(text)
    except (InvalidOperation, ValueError):
        return ""
    if decimal_value < 0 or decimal_value > 100:
        return ""
    return str(decimal_value.quantize(Decimal("0.01")).normalize())
def sheet_form_recommendation(market: str, finished_hs: str) -> dict:
    market = str(market or "").strip()
    finished_hs = str(finished_hs or "").strip()
    if not market or market.lower() == "chưa nhập":
        return {"form_code": "", "form_label": "", "criteria_text": "", "source": "missing_market"}
    lanes = prioritized_form_lanes(market, [finished_hs] if finished_hs else [])
    selected = recommended_form_lane(lanes)
    if not selected:
        return {"form_code": "", "form_label": "", "criteria_text": "", "source": "no_lane"}
    criteria_rows = selected.get("criteria_preview") or []
    criteria_text = ""
    if criteria_rows:
        first = criteria_rows[0]
        criteria_text = str(first.get("criteria") or "").strip()
    return {
        "form_code": str(selected.get("form_code") or "").strip(),
        "form_label": str(selected.get("display_name") or "").strip(),
        "criteria_text": criteria_text,
        "source": "engine",
    }
def origin_sheet_export_blockers(case: dict) -> list[str]:
    blockers = []
    for product in attach_origin_sheet_states(case).get("products", []):
        status = product.get("origin_sheet_status")
        if status in {"draft", "bom_loaded", "stale", "calculating"}:
            blockers.append(str(product.get("code") or "sheet"))
    return blockers
def origin_sheet_action_error(case: dict, product_code: str, action: str) -> str:
    prepared = attach_origin_sheet_states(case)
    products = prepared.get("products", [])
    target_index = next(
        (index for index, product in enumerate(products) if str(product.get("code") or "").strip() == product_code),
        None,
    )
    if target_index is None:
        return f"Không tìm thấy bảng kê {product_code}."
    target = products[target_index]
    status = target.get("origin_sheet_status")
    previous_unlocked = [
        str(product.get("code") or "")
        for product in products[:target_index]
        if product.get("origin_sheet_status") != "locked"
    ]
    later_locked = [
        str(product.get("code") or "")
        for product in products[target_index + 1:]
        if product.get("origin_sheet_status") == "locked"
    ]
    if action in {"calculate", "lock"} and previous_unlocked:
        return f"Cần chốt các bước trước trước khi xử lý {product_code}: {', '.join(previous_unlocked[:5])}."
    if action in {"calculate", "lock"} and later_locked:
        return f"Cần mở chốt các bước sau trước khi xử lý lại {product_code}: {', '.join(later_locked[:5])}."
    if action == "calculate" and status == "locked":
        return f"Bảng kê {product_code} đã chốt; cần mở chốt trước khi tính lại."
    if action == "lock" and status != "calculated":
        return f"Chỉ chốt được bảng kê {product_code} sau khi đã tính."
    if action == "reopen":
        if status != "locked":
            return f"Bảng kê {product_code} chưa chốt."
        if later_locked:
            return f"Chỉ được mở chốt từ bước cuối cùng; cần mở chốt {', '.join(later_locked[:5])} trước."
    return ""
def origin_build_signature(
    invoice_matches: list[dict],
    bom_rows_by_product: dict[str, list[dict]],
    material_rows: list[dict],
    stock_rows: list[dict],
    form_lane: dict,
) -> str:
    payload = {
        "form": {
            "form_code": form_lane.get("form_code", ""),
            "display_name": form_lane.get("display_name", ""),
        },
        "invoice_matches": [
            compact_origin_signature_row(
                row,
                [
                    "transaction_key",
                    "declaration_no",
                    "line_no",
                    "item_code",
                    "hs_code",
                    "quantity",
                    "unit",
                    "customs_value",
                    "foreign_currency_value",
                    "total_value",
                    "currency",
                    "value_currency",
                    "invoice_ref",
                ],
            )
            for row in invoice_matches
        ],
        "bom_rows": [
            compact_origin_signature_row(
                row,
                [
                    "product_code",
                    "product_version_id",
                    "product_version_no",
                    "material_code",
                    "qty_per",
                    "uom",
                    "hs_code",
                    "unit_value",
                    "unit_price",
                ],
            )
            for product_code in sorted(bom_rows_by_product)
            for row in bom_rows_by_product[product_code]
        ],
        "materials": [
            compact_origin_signature_row(
                row,
                ["material_code", "customs_code", "internal_code", "origin_default", "origin_status", "unit_price", "taxable_unit_price"],
            )
            for row in material_rows
        ],
        "stock_rows": [
            compact_origin_signature_row(
                row,
                [
                    "material_code",
                    "allocation_code",
                    "customs_item_code",
                    "source_row",
                    "import_declaration_no",
                    "line_no",
                    "remaining_qty",
                    "available_qty",
                    "customs_value",
                    "currency",
                    "value_currency",
                    "unit_value",
                    "unit_price",
                    "taxable_unit_price",
                    "eligibility_status",
                ],
            )
            for row in stock_rows
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()
def compact_origin_signature_row(row: dict, fields: list[str]) -> dict:
    return {field: str(row.get(field, "")) for field in fields if row.get(field, "") not in (None, "")}
def selected_bom_rows_by_product(
    case: dict,
    bom_workspace: dict,
) -> dict[str, list[dict]]:
    selected_version_id = (
        case.get("bom_artifact_id")
        or case.get("bom_version_id")
        or bom_workspace.get("latest_version", {}).get("artifact_id")
        or bom_workspace.get("latest_version", {}).get("version_id", "")
    )
    aggregate = next(
        (
            version
            for version in bom_workspace.get("versions", [])
            if (version.get("artifact_id") or version.get("version_id")) == selected_version_id
        ),
        bom_workspace.get("latest_version", {}),
    )
    rows = aggregate.get("rows")
    if rows is None:
        rows = bom_workspace.get("latest_rows", [])
    output: dict[str, list[dict]] = {}
    for row in rows or []:
        product_code = str(row.get("product_code", "")).strip()
        if product_code:
            output.setdefault(product_code, []).append(dict(row))

    version_index = {}
    for version in bom_workspace.get("product_versions", []):
        for artifact_key in (version.get("product_artifact_id"), version.get("product_version_id"), version.get("artifact_id"), version.get("version_id")):
            if artifact_key:
                version_index[str(artifact_key)] = version
    composition_by_product = {
        row.get("product_code", ""): row.get("product_artifact_id") or row.get("product_version_id", "")
        for row in aggregate.get("product_versions", [])
    }
    overrides = {
        **dict(case.get("bom_product_version_overrides", {})),
        **dict(case.get("bom_product_artifact_overrides", {})),
    }
    for product in case.get("products", []):
        product_code = str(product.get("code", "")).strip()
        bom_product_code = resolve_bom_product_code(
            str(product.get("bom_product_code") or product_code),
            bom_workspace,
        )
        selected_product_version_id = (
            product.get("bom_product_artifact_id")
            or product.get("bom_product_version_id")
            or overrides.get(product_code)
            or overrides.get(bom_product_code)
            or composition_by_product.get(bom_product_code, "")
            or composition_by_product.get(product_code, "")
        )
        selected_product_version = version_index.get(selected_product_version_id)
        if product_code and not usable_bom_product_version(selected_product_version):
            fallback_version_id = composition_by_product.get(bom_product_code, "") or composition_by_product.get(product_code, "")
            selected_product_version = version_index.get(fallback_version_id) or latest_usable_product_version(
                bom_workspace,
                bom_product_code or product_code,
            )
        if product_code and selected_product_version and selected_product_version.get("rows") is not None:
            output[product_code] = [dict(row) for row in selected_product_version.get("rows", [])]
    return output
def attach_origin_bom_product_codes(
    case: dict,
    bom_workspace: dict,
) -> dict:
    products = []
    changed = False
    for product in case.get("products", []):
        display_code = str(product.get("code") or product.get("product_code") or "").strip()
        bom_product_code = resolve_bom_product_code(
            str(product.get("bom_product_code") or display_code),
            bom_workspace,
        )
        if bom_product_code and bom_product_code != product.get("bom_product_code"):
            updated = dict(product)
            updated["bom_product_code"] = bom_product_code
            products.append(updated)
            changed = True
        else:
            products.append(product)
    if not changed:
        return case
    prepared = dict(case)
    prepared["products"] = products
    return prepared
def resolve_bom_product_code(
    code: str,
    bom_workspace: dict,
) -> str:
    options_by_code = bom_workspace.get("product_version_options_by_code", {})
    latest_product_codes = {
        str(row.get("product_code") or "").strip()
        for row in bom_workspace.get("latest_rows", [])
        if str(row.get("product_code") or "").strip()
    }
    for candidate in bom_code_candidates(code):
        if candidate in options_by_code or candidate in latest_product_codes:
            return candidate
    candidates = bom_code_candidates(code)
    return candidates[0] if candidates else ""
def usable_bom_product_version(version: dict | None) -> bool:
    if not version:
        return False
    if version.get("flatten_status") == "non_flattened":
        return False
    return bool(version.get("rows"))
def latest_usable_product_version(bom_workspace: dict, product_code: str) -> dict:
    versions = [
        version
        for version in bom_workspace.get("product_versions", [])
        if version.get("product_code") == product_code and usable_bom_product_version(version)
    ]
    return max(versions, key=lambda version: int(version.get("product_version_no") or 0), default={})
def material_catalog_index(material_rows: list[dict]) -> dict[str, dict]:
    output = {}
    for row in material_rows:
        for key in [row.get("material_code", ""), row.get("customs_code", ""), row.get("internal_code", "")]:
            if str(key).strip():
                output[str(key).strip()] = row
    return output
def co_stock_key_candidates(row: dict) -> list[str]:
    keys = []
    for value in [row.get("material_code"), row.get("allocation_code"), row.get("customs_item_code")]:
        key = str(value or "").strip()
        if key and key not in keys:
            keys.append(key)
    return keys
def case_allocation_pool(
    case: dict,
    invoice_matches: list[dict],
    stock_rows: list[dict],
    *,
    min_gap_days: int | None = None,
) -> dict[str, list[dict]]:
    """Convenience: resolve the export anchor date for this case and build
    an allocation pool that applies the 2-day rule. Callers that already
    know the threshold can pass `min_gap_days`; otherwise the default
    (`DEFAULT_MIN_GAP_DAYS`) is used."""
    export_date = case_export_anchor_date(case, invoice_matches)
    gap = co_stock_eligibility.DEFAULT_MIN_GAP_DAYS if min_gap_days is None else min_gap_days
    return co_stock_allocation_pool(stock_rows, export_date=export_date, min_gap_days=gap)
def case_export_anchor_date(case: dict, invoice_matches: list[dict]) -> date | None:
    """Earliest BCCT registration_date across the case's matched export
    declarations — the anchor for the 2-day gap rule.

    Returns None when the case has no export anchor (no
    `shipment.export_declaration_nos` set OR no matching BCCT row
    found). The rule then becomes a no-op for this case — we don't
    fabricate a date from invoice_date or today() because either
    could overreject lots.
    """
    if not isinstance(case, dict) or not invoice_matches:
        return None
    shipment_nos = {
        str(value or "").strip()
        for value in (case.get("shipment") or {}).get("export_declaration_nos") or []
        if str(value or "").strip()
    }
    relevant = [
        match for match in invoice_matches
        if isinstance(match, dict)
        and (not shipment_nos or str(match.get("declaration_no") or "").strip() in shipment_nos)
    ]
    return co_stock_eligibility.earliest_export_date(relevant)
def co_stock_allocation_pool(
    stock_rows: list[dict],
    *,
    export_date: date | None = None,
    min_gap_days: int = co_stock_eligibility.DEFAULT_MIN_GAP_DAYS,
) -> dict[str, list[dict]]:
    """Group + sort candidate stock rows by allocation key.

    `export_date` + `min_gap_days` apply the regulatory 2-day rule
    (see `co_stock_eligibility.is_stock_lot_eligible`). Rejected rows
    are NOT dropped — they stay in the pool with an
    `_eligibility_reason` annotation so the substitute modal can
    surface why a candidate was filtered out. Sorting pushes
    rejected rows to the bottom.
    """
    output: dict[str, list[dict]] = {}
    for index, row in enumerate(stock_rows):
        stock = dict(row)
        stock["_allocation_sequence"] = index
        stock["_allocation_remaining_qty"] = stock_available_qty(stock)
        verdict = co_stock_eligibility.is_stock_lot_eligible(
            stock, export_date=export_date, min_gap_days=min_gap_days,
        )
        stock["_eligibility_ok"] = verdict.ok
        stock["_eligibility_reason"] = verdict.reason
        for key in co_stock_key_candidates(stock):
            output.setdefault(key, []).append(stock)
    for rows in output.values():
        rows.sort(key=co_stock_allocation_sort_key)
    return output
def co_stock_allocation_sort_key(row: dict) -> tuple:
    return (
        not co_stock_is_usable(row),
        stock_allocation_remaining_qty(row) <= 0,
        not co_stock_has_value(row),
        str(row.get("declaration_date") or row.get("import_declaration_date") or ""),
        str(row.get("import_declaration_no", "")),
        numeric_sort_text(row.get("line_no", "")),
        int(row.get("_allocation_sequence", 0)),
        str(row.get("source_row", "")),
    )
def numeric_sort_text(value) -> tuple[int, str]:
    text = str(value or "").strip()
    try:
        return int(Decimal(text)), text
    except (InvalidOperation, ValueError):
        return 0, text
def co_stock_is_usable(
    row: dict,
    *,
    export_date: date | None = None,
    min_gap_days: int | None = None,
) -> bool:
    """Boolean wrapper around `co_stock_eligibility.is_stock_lot_eligible`.

    When the row carries the `_eligibility_ok` annotation written by
    `co_stock_allocation_pool`, trust it — the pool has already done
    the work with the right `export_date` / `min_gap_days` context.
    Otherwise compute fresh with the (optional) caller-supplied params.
    """
    if "_eligibility_ok" in row:
        return bool(row["_eligibility_ok"])
    gap = co_stock_eligibility.DEFAULT_MIN_GAP_DAYS if min_gap_days is None else min_gap_days
    verdict = co_stock_eligibility.is_stock_lot_eligible(
        row, export_date=export_date, min_gap_days=gap,
    )
    return verdict.ok
def co_stock_has_value(row: dict) -> bool:
    return bool(first_non_empty([
        row.get("unit_value", ""),
        row.get("unit_price", ""),
        row.get("taxable_unit_price", ""),
        row.get("customs_value", ""),
    ]))
def stock_available_qty(row: dict) -> Decimal:
    return decimal_value(row.get("remaining_qty") or row.get("available_qty") or "0")
def stock_allocation_remaining_qty(row: dict) -> Decimal:
    if "_allocation_remaining_qty" in row:
        value = row.get("_allocation_remaining_qty")
        return value if isinstance(value, Decimal) else decimal_value(value)
    return stock_available_qty(row)
def stock_candidates_for_material(stock_pool: dict, material_code: str) -> list[dict]:
    candidates = stock_pool.get(material_code, [])
    if isinstance(candidates, dict):
        candidates = [candidates]
    output = []
    seen = set()
    for row in candidates or []:
        marker = id(row)
        if marker in seen:
            continue
        output.append(row)
        seen.add(marker)
    return sorted(output, key=co_stock_allocation_sort_key)
def origin_product_from_invoice_match(
    match: dict,
    bom_rows: list[dict],
    form_lane: dict,
    material_index: dict[str, dict],
    stock_pool: dict[str, list[dict]],
    *,
    product_sequence: int | None = None,
    bom_product_code: str = "",
    allocate: bool = True,
) -> dict:
    product_code = str(match.get("item_code", "")).strip()
    bom_product_code = str(bom_product_code or product_code).strip()
    finished_hs = str(match.get("hs_code", "")).strip()
    preview = criteria_preview_for_hs(form_lane.get("form_code", ""), finished_hs) if form_lane else {}
    criterion = preview.get("criteria") or "Cần tra cứu PSR theo HS"
    threshold = lvc_threshold_from_criterion(criterion)
    quantity = decimal_value(match.get("quantity", "0"))
    product_value = origin_product_value(match)
    fob = product_value["value"]
    materials = [
        origin_material_from_bom_row(
            row,
            quantity,
            material_index,
            stock_pool,
            product_sequence=product_sequence,
            product_code=product_code,
            product_name=match.get("description") or product_code,
            material_sequence=material_sequence,
            allocate=allocate,
        )
        for material_sequence, row in enumerate(bom_rows, start=1)
    ]
    if allocate:
        vnm = sum(
            decimal_value(material.get("non_origin_cif_value"))
            for material in materials
        )
        missing_material_values = any(
            material.get("unit_value_missing") or material.get("allocation_status") == "shortage"
            for material in materials
        )
        lvc = calculate_lvc_result(fob, vnm, threshold, missing_material_values, missing_bom_materials=not materials)
    else:
        # Load BOM (cấu trúc): chưa phân bổ tồn ⇒ chưa có VNM/LVC. enrich_origin_product
        # tôn trọng origin_not_calculated để KHÔNG bịa LVC 100% từ vnm=0.
        vnm = Decimal("0")
        lvc = {"percentage": "", "status": "not_calculated", "status_label": "Chưa tính"}
    product = {
        "code": product_code,
        "bom_product_code": bom_product_code,
        "allocation_sequence": str(product_sequence or ""),
        "name": match.get("description") or product_code,
        "finished_hs": finished_hs,
        "quantity": decimal_text(quantity),
        "unit": match.get("unit", ""),
        "currency": product_value["currency"],
        "fob_currency": product_value["currency"] or match.get("currency", ""),
        "declared_currency": match.get("currency", ""),
        "value_source": product_value["source"],
        "source_declaration_no": match.get("declaration_no", ""),
        "source_declaration_date": match.get("declaration_date") or match.get("registration_date", ""),
        "source_line_no": match.get("line_no", ""),
        "invoice_ref": match.get("invoice_ref", ""),
        "fob": decimal_text(fob) if fob is not None else "",
        "non_origin_value": decimal_text(vnm) if (allocate and materials) else "",
        "rvc_threshold": decimal_text(threshold) if threshold is not None else "",
        "documented_result": criterion,
        "origin_not_calculated": not allocate,
        "lvc_percentage": lvc["percentage"],
        "lvc_status": lvc["status"],
        "lvc_status_label": lvc["status_label"],
        "lvc_threshold": decimal_text(threshold) if threshold is not None else "",
        "vnm_value": decimal_text(vnm) if (allocate and materials) else "",
        "bom_product_artifact_id": first_non_empty(row.get("product_artifact_id") or row.get("product_version_id", "") for row in bom_rows),
        "bom_product_artifact_no": first_non_empty(row.get("product_artifact_no") or row.get("product_version_no", "") for row in bom_rows),
        "bom_product_version_id": first_non_empty(row.get("product_artifact_id") or row.get("product_version_id", "") for row in bom_rows),
        "bom_product_version_no": first_non_empty(row.get("product_artifact_no") or row.get("product_version_no", "") for row in bom_rows),
        "materials": materials,
    }
    return enrich_origin_product(product)
def origin_match_from_existing_product(product: dict) -> dict:
    return {
        "item_code": product.get("code", ""),
        "description": product.get("name", ""),
        "hs_code": product.get("finished_hs", ""),
        "quantity": product.get("quantity", ""),
        "unit": product.get("unit") or product.get("export_unit", ""),
        "fob_value": product.get("fob", ""),
        "fob_currency": product.get("currency", ""),
        "currency": product.get("currency", ""),
        "declaration_no": product.get("source_declaration_no", ""),
        "line_no": product.get("source_line_no", ""),
        "invoice_ref": product.get("invoice_ref", ""),
    }
def origin_product_value(match: dict) -> dict:
    value_sources = [
        ("fob_value", match.get("fob_value"), match.get("fob_currency") or match.get("value_currency") or match.get("currency", "")),
        ("customs_value", match.get("customs_value"), match.get("value_currency") or "VND"),
        ("total_value", match.get("total_value"), match.get("value_currency") or "VND"),
        ("foreign_currency_value", match.get("foreign_currency_value"), match.get("currency", "")),
        ("invoice_value", match.get("invoice_value"), match.get("currency", "")),
    ]
    for source, value, currency in value_sources:
        if value not in (None, ""):
            return {"value": decimal_value(value), "currency": currency, "source": source}
    return {"value": None, "currency": "", "source": ""}
def origin_material_structure_only(
    row: dict,
    material: dict,
    material_code: str,
    qty_per: Decimal,
    consumed_qty: Decimal,
    *,
    material_sequence: int | None = None,
) -> dict:
    """Khai triển một dòng NVL theo CẤU TRÚC BOM, KHÔNG phân bổ tồn.

    Dùng cho "Load BOM" (Phase 2): nạp công thức NVL vào bảng kê để xem/sửa
    trước khi "Tính bảng kê". Field cấu trúc (mã, định mức, lượng dùng, xuất xứ,
    mô tả, đơn giá BOM/danh mục) đầy đủ; field phân bổ để TRUNG TÍNH (không dòng
    phân bổ, trị giá rỗng, không cảnh báo thiếu tồn). Cùng shape dict với
    origin_material_from_bom_row để template + sheet_edit_bom_rows + override
    dùng được không đổi.
    """
    origin_details = origin_status_details_from_material(material)
    material_description = row.get("material_name") or material.get("name", "")
    hs_code = row.get("hs_code") or material.get("hs_code", "")
    fallback_unit_value, fallback_unit_value_source = first_decimal_source(
        ("bom", row.get("unit_value")),
        ("bom", row.get("unit_price")),
        ("material_catalog", material.get("unit_price")),
        ("material_catalog", material.get("taxable_unit_price")),
    )
    unit_value_text = decimal_text(fallback_unit_value) if fallback_unit_value is not None else ""
    warnings = []
    if origin_details["source"] == "default_conservative":
        warnings.append(f"{material_code}: chưa có phân loại xuất xứ, đang tính bảo thủ là không xuất xứ.")
    if not material_description:
        warnings.append(f"{material_code}: thiếu tên NVL từ BOM, danh mục NVL và BCCT nhập.")
    return {
        "source_row": f"BOM:{row.get('source', '')}",
        "import_declaration_no": "",
        "import_declaration_date": "",
        "import_line_no": "",
        "material_code": material_code,
        "material_sequence": str(material_sequence or ""),
        "customs_material_code": material.get("customs_code") or material_code,
        "internal_material_code": material.get("internal_code") or material_code,
        "material_description": material_description,
        "material_name_missing": not bool(material_description),
        "hs_code": hs_code,
        "origin_status": origin_details["status"],
        "origin_status_label": origin_details["label"],
        "origin_status_source": origin_details["source"],
        "origin_status_note": origin_details["note"],
        "available_qty": "",
        "consumed_qty": consumed_qty,
        "unit_value": unit_value_text,
        "currency": material.get("value_currency") or material.get("currency", ""),
        "material_value": "",
        "material_value_native": "",
        "material_value_vnd": "",
        "non_origin_cif_value": "",
        "non_origin_cif_value_vnd": "",
        "exchange_rate_source": "",
        "unit_value_missing": not unit_value_text,
        "valuation_status": "not_calculated",
        "valuation_status_label": valuation_status_label("not_calculated"),
        "valuation_source": fallback_unit_value_source,
        "valuation_source_label": valuation_source_label(fallback_unit_value_source),
        "data_status_label": "Chưa tính bảng kê",
        "allocation_status": "pending",
        "allocation_shortage_qty": "",
        "allocation_shortage_trace": "",
        "allocation_lines": [],
        "allocation_summary": "",
        "material_warnings": warnings,
        "material_warnings_text": " | ".join(warnings),
        "bom_qty_per": decimal_text(qty_per),
        "bom_scrap_rate": row.get("scrap_rate", ""),
        "bom_source": row.get("source", ""),
        "bom_row_class": row.get("row_class", ""),
        "customs_relevance": material.get("customs_relevance", ""),
        "item_category": material.get("item_category", ""),
        "material_group": material.get("material_group", ""),
        "uom": row.get("uom", ""),
        "source_document_ref": row.get("source") or row.get("product_version_id", ""),
    }
def origin_material_from_bom_row(
    row: dict,
    export_quantity: Decimal,
    material_index: dict[str, dict],
    stock_pool: dict,
    *,
    product_sequence: int | None = None,
    product_code: str = "",
    product_name: str = "",
    material_sequence: int | None = None,
    allocate: bool = True,
) -> dict:
    material_code = str(row.get("material_code", "")).strip()
    material = material_index.get(material_code, {})
    qty_per = decimal_value(row.get("qty_per", "0"))
    consumed_qty = export_quantity * qty_per
    if not allocate:
        return origin_material_structure_only(
            row,
            material,
            material_code,
            qty_per,
            consumed_qty,
            material_sequence=material_sequence,
        )
    stock_candidates = stock_candidates_for_material(stock_pool, material_code)
    stock = stock_candidates[0] if stock_candidates else {}
    allocation_context = {
        "product_sequence": str(product_sequence or ""),
        "product_code": product_code,
        "product_name": product_name,
        "material_sequence": str(material_sequence or ""),
        "material_code": material_code,
        "material_uom": row.get("uom", ""),
    }
    allocation_lines, shortage_qty, shortage_trace = allocate_material_stock(
        material_code,
        consumed_qty,
        stock_candidates,
        row,
        material,
        allocation_context,
    )
    origin_details = origin_status_details_from_material(material)
    origin_status = origin_details["status"]
    fallback_unit_value, fallback_unit_value_source = first_decimal_source(
        ("bom", row.get("unit_value")),
        ("bom", row.get("unit_price")),
        ("material_catalog", material.get("unit_price")),
        ("material_catalog", material.get("taxable_unit_price")),
    )

    allocated_values = [
        decimal_value(line.get("material_value"))
        for line in allocation_lines
        if line.get("material_value") not in (None, "")
    ]
    mixed_allocation_currency = len(unique_texts(line.get("currency", "") for line in allocation_lines)) > 1
    if allocated_values and not mixed_allocation_currency:
        material_value = sum(allocated_values, Decimal("0"))
    elif not stock_candidates and fallback_unit_value is not None:
        material_value = consumed_qty * fallback_unit_value
    else:
        material_value = None
    # VND-base aggregates — even when mixed currencies make material_value
    # ambiguous, the per-line *_vnd values still sum cleanly because every
    # line was already converted to VND via its own exchange_rate_to_vnd.
    allocated_values_vnd = [
        decimal_value(line.get("material_value_vnd"))
        for line in allocation_lines
        if line.get("material_value_vnd") not in (None, "")
    ]
    if allocated_values_vnd and len(allocated_values_vnd) == len(allocation_lines):
        material_value_vnd = sum(allocated_values_vnd, Decimal("0"))
    else:
        material_value_vnd = None
    vnm_value = material_value if origin_status == "non_origin" and material_value is not None else None
    vnm_value_vnd = material_value_vnd if origin_status == "non_origin" and material_value_vnd is not None else None
    line_fx_sources = unique_texts(line.get("exchange_rate_source", "") for line in allocation_lines)
    aggregated_fx_source = line_fx_sources[0] if len(line_fx_sources) == 1 else ("mixed" if line_fx_sources else "")
    line_unit_missing = any(not line.get("unit_value") for line in allocation_lines)
    unit_value_missing = material_value is None or line_unit_missing
    allocation_status = "covered" if shortage_qty <= 0 else "shortage"
    if mixed_allocation_currency:
        valuation_status = "partial_valuation"
        unit_value_missing = True
    elif unit_value_missing:
        valuation_status = "missing_unit_value"
    elif allocation_status == "shortage":
        valuation_status = "partial_allocation"
    else:
        valuation_status = "ready"
    material_warnings = []
    material_description = row.get("material_name") or material.get("name", "") or stock.get("material_description", "")
    hs_code = row.get("hs_code") or material.get("hs_code", "") or stock.get("hs_code", "")
    if valuation_status == "missing_unit_value":
        material_warnings.append(f"{material_code}: thiếu đơn giá để tính trị giá NVL/VNM.")
    if mixed_allocation_currency:
        material_warnings.append(f"{material_code}: nhiều tiền tệ trong các dòng tồn, chưa cộng VNM tự động.")
    if allocation_status == "shortage" and consumed_qty > 0 and allocation_lines:
        material_warnings.append(
            f"{material_code}: thiếu tồn CO {decimal_text(shortage_qty)} {row.get('uom', '')} để phủ lượng dùng."
        )
    if allocation_status == "shortage" and shortage_trace:
        material_warnings.append(f"{material_code}: tồn CO đã dùng ở bước trước: {shortage_trace}.")
    if origin_details["source"] == "default_conservative":
        material_warnings.append(f"{material_code}: chưa có phân loại xuất xứ, đang tính bảo thủ là không xuất xứ.")
    if not material_description:
        material_warnings.append(f"{material_code}: thiếu tên NVL từ BOM, danh mục NVL và BCCT nhập.")
    unit_value_text = allocation_unit_value_summary(allocation_lines)
    if not unit_value_text and fallback_unit_value is not None:
        unit_value_text = decimal_text(fallback_unit_value)
    valuation_source = allocation_valuation_source(allocation_lines) or fallback_unit_value_source
    allocation_source_rows = unique_texts(line.get("source_row", "") for line in allocation_lines)
    allocation_import_declarations = unique_texts(line.get("import_declaration_no", "") for line in allocation_lines)
    allocation_import_lines = unique_texts(line.get("import_line_no", "") for line in allocation_lines)
    allocation_import_dates = unique_texts(line.get("import_declaration_date", "") for line in allocation_lines)
    available_qty = allocation_available_qty(allocation_lines, stock_candidates)
    currency = allocation_currency_summary(allocation_lines)
    if not currency:
        currency = stock.get("value_currency") or stock.get("currency") or material.get("value_currency") or material.get("currency", "")
    return {
        "source_row": ",".join(allocation_source_rows) or stock.get("source_row") or f"BOM:{row.get('source', '')}",
        "import_declaration_no": ", ".join(allocation_import_declarations) or stock.get("import_declaration_no", ""),
        "import_declaration_date": (
            ", ".join(allocation_import_dates)
            or stock.get("registration_date")
            or stock.get("declaration_date")
            or stock.get("import_declaration_date")
            or ""
        ),
        "import_line_no": ", ".join(allocation_import_lines) or stock.get("line_no", ""),
        "material_code": material_code,
        "material_sequence": str(material_sequence or ""),
        "customs_material_code": material.get("customs_code") or material_code,
        "internal_material_code": material.get("internal_code") or material_code,
        "material_description": material_description,
        "material_name_missing": not bool(material_description),
        "hs_code": hs_code,
        "origin_status": origin_status,
        "origin_status_label": origin_details["label"],
        "origin_status_source": origin_details["source"],
        "origin_status_note": origin_details["note"],
        "available_qty": available_qty,
        "consumed_qty": consumed_qty,
        "unit_value": unit_value_text,
        "currency": currency,
        "material_value": decimal_text(material_value) if material_value is not None else "",
        "material_value_native": decimal_text(material_value) if material_value is not None else "",
        "material_value_vnd": decimal_text(material_value_vnd) if material_value_vnd is not None else "",
        "non_origin_cif_value": decimal_text(vnm_value) if vnm_value is not None else "",
        "non_origin_cif_value_vnd": decimal_text(vnm_value_vnd) if vnm_value_vnd is not None else "",
        "exchange_rate_source": aggregated_fx_source,
        "unit_value_missing": unit_value_missing,
        "valuation_status": valuation_status,
        "valuation_status_label": valuation_status_label(valuation_status),
        "valuation_source": valuation_source,
        "valuation_source_label": valuation_source_label(valuation_source),
        "data_status_label": "Đủ evidence tính VNM" if valuation_status == "ready" else "Cần bổ sung evidence",
        "allocation_status": allocation_status,
        "allocation_shortage_qty": decimal_text(shortage_qty) if shortage_qty > 0 else "",
        "allocation_shortage_trace": shortage_trace,
        "allocation_lines": allocation_lines,
        "allocation_summary": allocation_summary(allocation_lines, allocation_status),
        "material_warnings": material_warnings,
        "material_warnings_text": " | ".join(material_warnings),
        "bom_qty_per": decimal_text(qty_per),
        "bom_scrap_rate": row.get("scrap_rate", ""),
        "bom_source": row.get("source", ""),
        "bom_row_class": row.get("row_class", ""),
        "customs_relevance": material.get("customs_relevance", ""),
        "item_category": material.get("item_category", ""),
        "material_group": material.get("material_group", ""),
        "uom": row.get("uom", ""),
        "source_document_ref": allocation_document_ref(allocation_lines) or row.get("source") or row.get("product_version_id", ""),
    }
def allocate_material_stock(
    material_code: str,
    required_qty: Decimal,
    stock_candidates: list[dict],
    bom_row: dict,
    material: dict,
    allocation_context: dict | None = None,
) -> tuple[list[dict], Decimal, str]:
    remaining_required = required_qty
    lines = []
    if remaining_required <= 0:
        return lines, Decimal("0"), ""
    allocation_context = allocation_context or {}
    for stock in stock_candidates:
        if not co_stock_is_usable(stock):
            continue
        available_qty = stock_allocation_remaining_qty(stock)
        if available_qty <= 0:
            continue
        allocated_qty = min(available_qty, remaining_required)
        if allocated_qty <= 0:
            continue
        line = stock_allocation_line(stock, allocated_qty, available_qty, bom_row, material, allocation_context)
        lines.append(line)
        if "_allocation_remaining_qty" in stock:
            stock["_allocation_remaining_qty"] = available_qty - allocated_qty
        stock.setdefault("_allocation_consumptions", []).append(stock_allocation_consumption(line, allocation_context))
        remaining_required -= allocated_qty
        if remaining_required <= 0:
            break
    shortage_qty = max(remaining_required, Decimal("0"))
    shortage_trace = stock_shortage_trace(stock_candidates, allocation_context) if shortage_qty > 0 else ""
    return lines, shortage_qty, shortage_trace
def stock_allocation_line(
    stock: dict,
    allocated_qty: Decimal,
    available_qty: Decimal,
    bom_row: dict,
    material: dict,
    allocation_context: dict | None = None,
) -> dict:
    allocation_context = allocation_context or {}
    unit_value, unit_value_source = first_decimal_source(
        ("bom", bom_row.get("unit_value")),
        ("bom", bom_row.get("unit_price")),
        ("co_stock", stock.get("unit_value")),
        ("co_stock", stock.get("unit_price")),
        ("co_stock", stock.get("taxable_unit_price")),
        ("material_catalog", material.get("unit_price")),
        ("material_catalog", material.get("taxable_unit_price")),
    )
    material_value = allocated_qty * unit_value if unit_value is not None else None
    fx_rate, fx_source = _allocation_line_fx(stock)
    if unit_value is not None and fx_rate is not None:
        unit_value_vnd = unit_value * fx_rate
        material_value_vnd = allocated_qty * unit_value_vnd
    else:
        unit_value_vnd = None
        material_value_vnd = None
    source_line_ids = stock.get("source_line_ids", [])
    if isinstance(source_line_ids, list):
        source_line_ids_text = ",".join(str(item) for item in source_line_ids if str(item).strip())
    else:
        source_line_ids_text = str(source_line_ids or "")
    return {
        "source_row": stock.get("source_row", ""),
        "source_line_ids": source_line_ids_text,
        "import_declaration_no": stock.get("import_declaration_no", ""),
        "import_declaration_date": (
            stock.get("registration_date")
            or stock.get("declaration_date")
            or stock.get("import_declaration_date")
            or ""
        ),
        "import_line_no": stock.get("line_no", ""),
        "customs_material_code": stock.get("customs_item_code", ""),
        "allocation_code": stock.get("allocation_code", ""),
        "product_sequence": allocation_context.get("product_sequence", ""),
        "product_code": allocation_context.get("product_code", ""),
        "material_sequence": allocation_context.get("material_sequence", ""),
        "opening_qty": decimal_text(available_qty),
        "available_qty": decimal_text(available_qty),
        "remaining_qty": decimal_text(available_qty - allocated_qty),
        "allocated_qty": decimal_text(allocated_qty),
        "unit_value": decimal_text(unit_value) if unit_value is not None else "",
        "unit_value_native": decimal_text(unit_value) if unit_value is not None else "",
        "unit_value_vnd": decimal_text(unit_value_vnd) if unit_value_vnd is not None else "",
        "currency": stock.get("value_currency") or stock.get("currency") or material.get("value_currency") or material.get("currency", ""),
        "material_value": decimal_text(material_value) if material_value is not None else "",
        "material_value_native": decimal_text(material_value) if material_value is not None else "",
        "material_value_vnd": decimal_text(material_value_vnd) if material_value_vnd is not None else "",
        "exchange_rate_to_vnd": decimal_text(fx_rate) if fx_rate is not None else "",
        "exchange_rate_source": fx_source,
        "valuation_source": unit_value_source,
        "valuation_source_label": valuation_source_label(unit_value_source),
        "material_description": stock.get("material_description", ""),
        "hs_code": stock.get("hs_code", ""),
    }
def _allocation_line_fx(stock: dict) -> tuple[Decimal | None, str]:
    """Return (rate, source) parsed from a co_stock row's FX payload fields.

    Materializer writes exchange_rate_to_vnd + exchange_rate_source (phase 1).
    Old snapshots predating phase 1 lack these fields — treat as 'missing'.
    """
    source = (stock.get("exchange_rate_source") or "").strip() or "missing"
    raw = (stock.get("exchange_rate_to_vnd") or "").strip()
    if not raw:
        return None, source
    try:
        return Decimal(raw), source
    except (InvalidOperation, ValueError):
        return None, source
def stock_allocation_consumption(line: dict, allocation_context: dict) -> dict:
    return {
        "product_sequence": allocation_context.get("product_sequence", ""),
        "product_code": allocation_context.get("product_code", ""),
        "product_name": allocation_context.get("product_name", ""),
        "material_sequence": allocation_context.get("material_sequence", ""),
        "material_code": allocation_context.get("material_code", ""),
        "material_uom": allocation_context.get("material_uom", ""),
        "allocated_qty": line.get("allocated_qty", ""),
        "source_row": line.get("source_row", ""),
        "import_declaration_no": line.get("import_declaration_no", ""),
        "import_line_no": line.get("import_line_no", ""),
    }
def stock_shortage_trace(stock_candidates: list[dict], allocation_context: dict) -> str:
    trace = []
    seen = set()
    for stock in stock_candidates:
        for consumption in stock.get("_allocation_consumptions", []):
            if not stock_consumption_is_before(consumption, allocation_context):
                continue
            marker = (
                consumption.get("product_sequence", ""),
                consumption.get("product_code", ""),
                consumption.get("material_sequence", ""),
                consumption.get("material_code", ""),
                consumption.get("source_row", ""),
                consumption.get("allocated_qty", ""),
            )
            if marker in seen:
                continue
            seen.add(marker)
            trace.append(stock_consumption_label(consumption))
    return "; ".join(trace)
def stock_consumption_is_before(consumption: dict, allocation_context: dict) -> bool:
    current_sequence = numeric_sequence(allocation_context.get("product_sequence", ""))
    consumed_sequence = numeric_sequence(consumption.get("product_sequence", ""))
    if current_sequence is None or consumed_sequence is None:
        return False
    return consumed_sequence < current_sequence
def numeric_sequence(value) -> int | None:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return None
def stock_consumption_label(consumption: dict) -> str:
    step = consumption.get("product_sequence", "")
    product = consumption.get("product_code", "")
    qty = consumption.get("allocated_qty", "")
    uom = consumption.get("material_uom", "")
    source = consumption.get("import_declaration_no", "") or consumption.get("source_row", "")
    line_no = consumption.get("import_line_no", "")
    source_ref = f"{source}/{line_no}" if source and line_no else source
    prefix = f"Bước {step} {product}".strip()
    detail = f"{prefix} dùng {qty} {uom}".strip()
    return f"{detail} từ {source_ref}" if source_ref else detail
def allocation_available_qty(allocation_lines: list[dict], stock_candidates: list[dict]) -> Decimal:
    if allocation_lines:
        return sum((decimal_value(line.get("available_qty")) for line in allocation_lines), Decimal("0"))
    return sum(
        (stock_allocation_remaining_qty(row) for row in stock_candidates if co_stock_is_usable(row)),
        Decimal("0"),
    )
def allocation_unit_value_summary(allocation_lines: list[dict]) -> str:
    unit_values = unique_texts(line.get("unit_value", "") for line in allocation_lines)
    if len(unit_values) == 1:
        return unit_values[0]
    if len(unit_values) > 1:
        return "Nhiều đơn giá"
    return ""
def allocation_currency_summary(allocation_lines: list[dict]) -> str:
    currencies = unique_texts(line.get("currency", "") for line in allocation_lines)
    if len(currencies) == 1:
        return currencies[0]
    if len(currencies) > 1:
        return "Nhiều tiền tệ"
    return ""
def allocation_valuation_source(allocation_lines: list[dict]) -> str:
    if not allocation_lines:
        return ""
    sources = unique_texts(line.get("valuation_source", "") for line in allocation_lines)
    if len(allocation_lines) > 1 and sources == ["co_stock"]:
        return "co_stock_allocation"
    if len(sources) == 1:
        return sources[0]
    return "mixed_allocation"
def allocation_summary(allocation_lines: list[dict], allocation_status: str) -> str:
    if not allocation_lines:
        return "Thiếu tồn CO" if allocation_status == "shortage" else ""
    suffix = " + thiếu tồn" if allocation_status == "shortage" else ""
    return f"{len(allocation_lines)} dòng tồn{suffix}"
def allocation_document_ref(allocation_lines: list[dict]) -> str:
    refs = []
    for line in allocation_lines:
        declaration = line.get("import_declaration_no", "")
        line_no = line.get("import_line_no", "")
        if declaration and line_no:
            refs.append(f"{declaration}/{line_no}")
        elif declaration:
            refs.append(declaration)
    return "; ".join(unique_texts(refs))
def valuation_status_label(status: str) -> str:
    return {
        "ready": "Đủ giá trị",
        "missing_unit_value": "Thiếu đơn giá NVL",
        "partial_allocation": "Thiếu tồn CO",
        "partial_valuation": "Tạm tính trị giá",
        "not_calculated": "Chưa tính",
    }.get(status, "Cần bổ sung evidence")
def origin_status_from_material(material: dict) -> str:
    return origin_status_details_from_material(material)["status"]
def origin_status_details_from_material(material: dict) -> dict:
    value = str(material.get("origin_default") or material.get("origin_status") or "").lower()
    if "không" in value or "khong" in value or value == "non_origin":
        return {
            "status": "non_origin",
            "label": "Không xuất xứ",
            "source": "material_catalog",
            "note": "Theo phân loại xuất xứ NVL hiện có.",
        }
    if "có" in value or value == "origin":
        return {
            "status": "origin",
            "label": "Có xuất xứ",
            "source": "material_catalog",
            "note": "Theo phân loại xuất xứ NVL hiện có.",
        }
    return {
        "status": "non_origin",
        "label": "Không xuất xứ",
        "source": "default_conservative",
        "note": "Chưa có phân loại xuất xứ, tạm tính bảo thủ vào VNM.",
    }
def attach_origin_readiness(case: dict) -> dict:
    enriched = dict(case)
    products = [
        enrich_origin_product({**product, "allocation_sequence": product.get("allocation_sequence") or str(index)})
        for index, product in enumerate(enriched.get("products", []), start=1)
    ]
    enriched["products"] = products
    snapshot = dict(enriched.get("origin_snapshot", {}))
    issue_count = sum(len(product.get("origin_warnings", [])) for product in products)
    statuses = [product.get("origin_readiness_status", "review") for product in products]
    if not products:
        readiness_status = "empty"
        readiness_label = "Chưa có dữ liệu xuất xứ"
    elif "blocked" in statuses:
        readiness_status = "blocked"
        readiness_label = "Cần bổ sung evidence"
    elif "fail" in statuses:
        readiness_status = "fail"
        readiness_label = "Có TP không đạt"
    elif "review" in statuses:
        readiness_status = "review"
        readiness_label = "Cần review tiêu chí"
    else:
        readiness_status = "ready"
        readiness_label = "Đủ điều kiện build-down"
    snapshot.update({
        "calculation_method": "build_down_lvc",
        "calculation_method_label": "Build-down LVC/RVC",
        "formula": "(FOB - VNM) / FOB x 100",
        "readiness_status": readiness_status,
        "readiness_label": readiness_label,
        "issue_count": issue_count,
        "product_count": len(products),
    })
    enriched["origin_snapshot"] = snapshot
    return enriched
def enrich_origin_product(product: dict) -> dict:
    enriched = dict(product)
    enriched["allocation_sequence"] = str(enriched.get("allocation_sequence") or "")
    materials = [enrich_origin_material(material) for material in enriched.get("materials", [])]
    enriched["materials"] = materials
    criterion = str(enriched.get("documented_result") or enriched.get("rule") or "")
    missing_unit_material_count = sum(1 for material in materials if material.get("valuation_status") == "missing_unit_value")
    shortage_material_count = sum(1 for material in materials if material.get("allocation_status") == "shortage")
    incomplete_material_count = missing_unit_material_count + shortage_material_count
    if enriched.get("origin_not_calculated"):
        # Load BOM (cấu trúc): chưa phân bổ tồn ⇒ vnm=0 sẽ ra LVC 100% giả.
        # Giữ "Chưa tính" cho tới khi bấm "Tính bảng kê".
        lvc = {"percentage": "", "status": "not_calculated", "status_label": "Chưa tính"}
    else:
        lvc = normalized_lvc_result(enriched, materials, criterion, incomplete_material_count > 0)
    enriched["lvc_percentage"] = lvc["percentage"]
    enriched["lvc_status"] = lvc["status"]
    enriched["lvc_status_label"] = lvc["status_label"]
    enriched["lvc_quality_warning_text"] = (
        f"Thiếu đơn giá {missing_unit_material_count} dòng NVL; LVC đang tạm tính từ các dòng đã có đơn giá."
        if missing_unit_material_count and lvc["percentage"]
        else f"Thiếu tồn CO {shortage_material_count} dòng NVL; LVC đang tạm tính từ phần đã phân bổ."
        if shortage_material_count and lvc["percentage"]
        else ""
    )
    ctc_rule = tariff_shift_rule_from_criterion(criterion)
    lvc_status = str(enriched.get("lvc_status") or "")
    warnings = []
    if not materials:
        warnings.append(f"{enriched.get('code', 'TP')}: chưa có BOM/NVL để tính xuất xứ.")
    if not enriched.get("fob"):
        warnings.append(f"{enriched.get('code', 'TP')}: thiếu FOB/trị giá TP.")
    for material in materials:
        warnings.extend(material.get("material_warnings", []))
    warnings = unique_texts(warnings)
    tariff_shift_status = ""
    tariff_shift_status_label = ""
    tariff_shift_note = ""
    if ctc_rule:
        non_origin_hs = [
            str(material.get("hs_code") or "")
            for material in materials
            if material.get("origin_status") == "non_origin"
        ]
        tariff_shift = evaluate_tariff_shift(str(enriched.get("finished_hs") or ""), non_origin_hs, ctc_rule)
        tariff_shift_status = "skipped" if tariff_shift.skipped else "pass" if tariff_shift.passed else "fail"
        if tariff_shift.skipped:
            tariff_shift_status_label = f"Thiếu HS cho {ctc_rule} preview"
        elif tariff_shift.passed:
            tariff_shift_status_label = f"Đạt {ctc_rule} preview"
        else:
            tariff_shift_status_label = f"Không đạt {ctc_rule} preview"
        tariff_shift_note = f"{ctc_rule} preview chỉ so HS TP với HS NVL không xuất xứ; chưa thay thế PSR engine/legal review."
    if lvc_status in {"missing_value", "missing_bom"} or any(
        material.get("valuation_status") in {"missing_unit_value", "partial_allocation", "partial_valuation"}
        or material.get("allocation_status") == "shortage"
        for material in materials
    ):
        readiness_status = "blocked"
        readiness_label = "Cần bổ sung evidence"
    elif lvc_status == "fail":
        readiness_status = "fail"
        readiness_label = "Không đạt build-down"
    elif ctc_rule:
        readiness_status = "review"
        readiness_label = "Cần review CTC"
    elif lvc_status == "pass":
        readiness_status = "ready"
        readiness_label = "Đủ điều kiện build-down"
    else:
        readiness_status = "review"
        readiness_label = "Cần review tiêu chí"
    enriched.update({
        "origin_method": "build_down_lvc",
        "origin_method_label": "Build-down LVC/RVC",
        "origin_formula": "(FOB - VNM) / FOB x 100",
        "origin_criterion_mode": criterion_mode(criterion),
        "origin_readiness_status": readiness_status,
        "origin_readiness_label": readiness_label,
        "origin_warnings": warnings,
        "origin_warning_summary": origin_warning_summary(enriched, materials, warnings),
        "origin_warnings_text": " | ".join(warnings),
        "tariff_shift_rule": ctc_rule,
        "tariff_shift_status": tariff_shift_status,
        "tariff_shift_status_label": tariff_shift_status_label,
        "tariff_shift_note": tariff_shift_note,
    })
    return enriched
def enrich_origin_material(material: dict) -> dict:
    enriched = dict(material)
    enriched["material_name_missing"] = not bool(str(enriched.get("material_description") or "").strip())
    if not enriched.get("origin_status_label"):
        enriched["origin_status_label"] = "Có xuất xứ" if enriched.get("origin_status") == "origin" else "Không xuất xứ"
    unit_missing = not str(enriched.get("unit_value") or "").strip()
    enriched["valuation_status"] = enriched.get("valuation_status") or ("missing_unit_value" if unit_missing else "ready")
    enriched["valuation_status_label"] = enriched.get("valuation_status_label") or (
        valuation_status_label(enriched["valuation_status"])
    )
    enriched["valuation_source_label"] = enriched.get("valuation_source_label") or valuation_source_label(enriched.get("valuation_source", ""))
    enriched["data_status_label"] = enriched.get("data_status_label") or (
        "Cần bổ sung evidence" if unit_missing else "Đủ evidence tính VNM"
    )
    enriched["allocation_lines"] = list(enriched.get("allocation_lines") or [])
    for allocation in enriched["allocation_lines"]:
        if not allocation.get("opening_qty"):
            allocation["opening_qty"] = allocation.get("available_qty", "")
    enriched["bom_technical_noise"] = is_bom_technical_noise(enriched)
    enriched["declarable_unmatched"] = is_declarable_unmatched(enriched)
    enriched["allocation_status"] = enriched.get("allocation_status") or ("covered" if enriched["allocation_lines"] else "")
    enriched["allocation_summary"] = enriched.get("allocation_summary") or allocation_summary(
        enriched["allocation_lines"],
        enriched["allocation_status"],
    )
    warnings = text_list(enriched.get("material_warnings") or enriched.get("material_warnings_text"))
    if unit_missing and not warnings:
        code = enriched.get("material_code") or enriched.get("internal_material_code") or "NVL"
        warnings.append(f"{code}: thiếu đơn giá để tính trị giá NVL/VNM.")
    if enriched["material_name_missing"]:
        code = enriched.get("material_code") or enriched.get("internal_material_code") or "NVL"
        warnings.append(f"{code}: thiếu tên NVL từ BOM, danh mục NVL và BCCT nhập.")
    if enriched.get("allocation_shortage_trace") and not any("đã dùng ở bước trước" in warning for warning in warnings):
        code = enriched.get("material_code") or enriched.get("internal_material_code") or "NVL"
        warnings.append(f"{code}: tồn CO đã dùng ở bước trước: {enriched['allocation_shortage_trace']}.")
    warnings = unique_texts(warnings)
    enriched["material_warnings"] = warnings
    enriched["material_warnings_text"] = " | ".join(warnings)
    return enriched
def origin_warning_summary(product: dict, materials: list[dict], warnings: list[str]) -> list[dict]:
    summary = []
    if not materials:
        summary.append({
            "kind": "missing_bom",
            "label": "Chưa có BOM/NVL",
            "count": 1,
            "detail": "Không kết luận LVC cho tới khi chọn BOM snapshot có dòng NVL.",
            "examples": product.get("code", ""),
        })
    if not product.get("fob"):
        summary.append({
            "kind": "missing_fob",
            "label": "Thiếu FOB",
            "count": 1,
            "detail": "Cần trị giá TP để tính build-down LVC/RVC.",
            "examples": product.get("code", ""),
        })
    summary.extend(material_issue_summary(materials, "missing_unit_value", "valuation_status", "Thiếu đơn giá NVL", "LVC đang tạm tính từ các dòng đã có đơn giá."))
    shortage_materials = [material for material in materials if material.get("allocation_status") == "shortage"]
    if shortage_materials:
        summary.append(material_summary_row(
            shortage_materials,
            "allocation_shortage",
            "Thiếu tồn CO",
            "LVC đang tạm tính từ phần tồn CO đã phân bổ được.",
        ))
    summary.extend(material_issue_summary(materials, "default_conservative", "origin_status_source", "Chưa phân loại xuất xứ", "Đang tạm tính bảo thủ là không xuất xứ."))
    non_material_rows = [
        material for material in materials
        if material.get("bom_technical_noise") and not material.get("declarable_unmatched")
    ]
    if non_material_rows:
        summary.append(material_summary_row(
            non_material_rows,
            "excluded_non_material",
            "Đã loại phi vật tư",
            "Bản vẽ/tài liệu/nhãn (phi vật tư), không phải NVL khai — đã loại khỏi bảng kê và bản xuất.",
        ))
    declarable_unmatched_rows = [material for material in materials if material.get("declarable_unmatched")]
    if declarable_unmatched_rows:
        summary.append(material_summary_row(
            declarable_unmatched_rows,
            "declarable_unmatched",
            "Vật tư chưa khớp tờ khai — cần đối soát",
            "NVL thật nhưng chưa khớp tờ khai nhập (chưa có HS/CIF), chưa xuất được — cần đối soát trước khi phát hành C/O.",
        ))
    missing_name_materials = [
        material for material in materials
        if material.get("material_name_missing") and not material.get("bom_technical_noise")
    ]
    if missing_name_materials:
        summary.append(material_summary_row(
            missing_name_materials,
            "missing_material_name",
            "Thiếu tên NVL",
            "Không tìm thấy tên trong BOM, danh mục NVL hoặc BCCT nhập.",
        ))
    if summary:
        return summary
    return []
def material_issue_summary(materials: list[dict], value: str, field: str, label: str, detail: str) -> list[dict]:
    rows = [material for material in materials if material.get(field) == value]
    return [material_summary_row(rows, value, label, detail)] if rows else []
def material_summary_row(materials: list[dict], kind: str, label: str, detail: str) -> dict:
    codes = unique_texts(
        material.get("internal_material_code") or material.get("material_code") or "NVL"
        for material in materials
    )
    return {
        "kind": kind,
        "label": label,
        "count": len(materials),
        "detail": detail,
        "examples": ", ".join(codes[:6]),
    }
def tariff_shift_rule_from_criterion(criterion: str) -> str:
    text = criterion.upper()
    for rule in ["CTSH", "CTH", "CC"]:
        if re.search(rf"\b{rule}\b", text):
            return rule
    return ""
def criterion_mode(criterion: str) -> str:
    has_value_content = bool(re.search(r"\b(?:LVC|RVC|AIFTA)\b", criterion, flags=re.IGNORECASE))
    has_tariff_shift = bool(tariff_shift_rule_from_criterion(criterion))
    if has_value_content and has_tariff_shift:
        return "compound"
    if has_value_content:
        return "value_content"
    if has_tariff_shift:
        return "tariff_shift"
    return "manual_review"
def valuation_source_label(source: str) -> str:
    return {
        "bom": "BOM",
        "co_stock": "BCCT nhập/tồn CO",
        "co_stock_allocation": "Tồn CO nhiều lô",
        "mixed_allocation": "Nhiều nguồn giá",
        "material_catalog": "Danh mục NVL",
    }.get(str(source or ""), "Chưa có")
def text_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split("|") if item.strip()]
def unique_texts(values) -> list[str]:
    output = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        output.append(text)
        seen.add(text)
    return output
def lvc_threshold_from_criterion(criterion: str) -> Decimal | None:
    if not criterion:
        return None
    match = re.search(r"(?:LVC|RVC|AIFTA)[^\d]*(\d+(?:[.,]\d+)?)\s*%", criterion, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:FOB|LVC|RVC)", criterion, flags=re.IGNORECASE)
    return decimal_value(match.group(1)) if match else None
def normalized_lvc_result(product: dict, materials: list[dict], criterion: str, missing_material_values: bool) -> dict:
    fob = decimal_value(product.get("fob")) if product.get("fob") not in (None, "") else None
    vnm_source = first_non_empty([product.get("vnm_value"), product.get("non_origin_value")])
    if vnm_source:
        vnm = decimal_value(vnm_source)
    else:
        vnm = sum(
            decimal_value(material.get("non_origin_cif_value"))
            for material in materials
            if material.get("origin_status") == "non_origin"
        )
    threshold_source = first_non_empty([product.get("lvc_threshold"), product.get("rvc_threshold")])
    threshold = decimal_value(threshold_source) if threshold_source else lvc_threshold_from_criterion(criterion)
    return calculate_lvc_result(fob, vnm, threshold, missing_material_values, missing_bom_materials=not materials)
def calculate_lvc_result(
    fob: Decimal | None,
    vnm: Decimal,
    threshold: Decimal | None,
    missing_material_values: bool,
    *,
    missing_bom_materials: bool = False,
) -> dict:
    if fob is None or fob <= 0:
        return {"percentage": "", "status": "missing_value", "status_label": "Thiếu FOB"}
    if missing_bom_materials:
        return {"percentage": "", "status": "missing_bom", "status_label": "Thiếu BOM/NVL"}
    percentage = ((fob - vnm) / fob * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    percentage_text = f"{percentage:.2f}"
    if threshold is None:
        if missing_material_values:
            return {"percentage": percentage_text, "status": "partial_review", "status_label": "Tạm tính LVC"}
        return {"percentage": percentage_text, "status": "review", "status_label": "Thiếu ngưỡng"}
    if percentage >= threshold:
        if missing_material_values:
            return {"percentage": percentage_text, "status": "partial_pass", "status_label": "Tạm đạt LVC"}
        return {"percentage": percentage_text, "status": "pass", "status_label": "Đạt LVC"}
    if missing_material_values:
        return {"percentage": percentage_text, "status": "partial_fail", "status_label": "Tạm không đạt LVC"}
    return {"percentage": percentage_text, "status": "fail", "status_label": "Không đạt LVC"}
def first_non_empty(values) -> str:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return ""
def first_decimal_source(*values: tuple[str, object]) -> tuple[Decimal | None, str]:
    for source, value in values:
        if value not in (None, ""):
            return decimal_value(value), source
    return None, ""
def decimal_value(value) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", "").strip() or "0")
    except (InvalidOperation, ValueError):
        return Decimal("0")
def decimal_text(value: Decimal | str) -> str:
    if isinstance(value, str):
        return value
    if value == value.to_integral():
        return str(value.quantize(Decimal("1")))
    return str(value)
def invoice_match_criteria_rows(invoice_matches: list[dict], form_lane: dict) -> list[dict]:
    if not form_lane:
        return []
    rows = []
    seen = set()
    for row in invoice_matches:
        hs_code = str(row.get("hs_code", "")).strip()
        product_code = str(row.get("item_code", "")).strip()
        key = (product_code, hs_code, str(row.get("declaration_no", "")), str(row.get("line_no", "")))
        if not hs_code or key in seen:
            continue
        seen.add(key)
        preview = criteria_preview_for_hs(form_lane["form_code"], hs_code)
        rows.append({
            "product_code": product_code,
            "product_name": row.get("description", ""),
            "finished_hs": hs_code,
            "form": form_lane["display_name"],
            "agreement": form_lane["agreement"],
            "instrument": form_lane["instrument"],
            "rule": preview["criteria"],
            "rule_note": preview["note"],
            "source_reference": preview["source_reference"],
            "rvc_percentage": "",
            "tariff_shift_status": "Chờ BOM",
            "material_code": "",
            "material_name": "",
            "material_hs": "",
            "origin_status": "BCCT invoice",
            "non_origin_cif_value": "",
            "declaration_no": row.get("declaration_no", ""),
            "line_no": row.get("line_no", ""),
            "quantity": row.get("quantity", ""),
            "unit": row.get("unit", ""),
            "invoice_ref": row.get("invoice_ref", ""),
        })
    return rows
def enrich_client_with_source_summary(client: dict, source_summary: dict) -> dict:
    client["counts"] = {
        **client.get("counts", {}),
        "materials": source_summary["material_catalog"]["published_row_count"],
        "products": source_summary["product_catalog"]["published_row_count"],
        "bcct": source_summary["bcct"]["published_row_count"],
        "co_stock": source_summary["co_stock_row_count"],
    }
    return client
def attach_case_source_summary_snapshot(case: dict, source_summary: dict) -> dict:
    material = source_summary["material_catalog"].get("latest_version") or {}
    product = source_summary["product_catalog"].get("latest_version") or {}
    bcct = source_summary["bcct"].get("latest_version") or {}
    case["source_snapshot"] = {
        "material_catalog_version_id": material.get("version_id", ""),
        "material_catalog_version_no": material.get("version_no", ""),
        "product_catalog_version_id": product.get("version_id", ""),
        "product_catalog_version_no": product.get("version_no", ""),
        "bcct_version_id": bcct.get("version_id", ""),
        "bcct_version_no": bcct.get("version_no", ""),
        "bcct_reviewed_row_count": source_summary["bcct"].get("reviewed_row_count", 0),
        "correction_candidate_count": source_summary["bcct"].get("correction_candidate_count", 0),
        "client_config_version": source_summary["client_config"].get("config_version", ""),
        "client_config_hash": source_summary["client_config"].get("config_hash", ""),
    }
    return case
def minimal_bom_workspace() -> dict:
    return {
        "versions": [],
        "product_versions": [],
        "product_version_options_by_code": {},
        "latest_version": {},
    }
def co_case_context(client_id: str, case_id: str = "", current_step: str = "index", **extra) -> dict:
    client = resolve_client(client_id)
    case_was_supplied = "case" in extra
    case = extra.pop("case", None)
    effective_case_id = case_id or (case or {}).get("persisted_case_id", "")
    workspace = get_case_workspace(client, effective_case_id)
    record = get_case_record(client, effective_case_id) if effective_case_id else None
    if case is None:
        case = client_case(client)
        if record:
            case = case_from_record(case, client, record)
    elif record:
        case.setdefault("persisted_case_id", record["case_id"])
        case["supporting_files"] = [dict(file_row) for file_row in record.get("supporting_files", [])]
        for key in ["bom_snapshot", "origin_snapshot", "source_snapshot", "source_invoice_matches"]:
            if key in record and key not in case:
                case[key] = json_safe(record.get(key))
    case.setdefault("persisted_case_id", "")
    case.setdefault("shipment", {"invoice_no": "", "bill_of_lading_no": ""})
    case["shipment"].setdefault("invoice_no", "")
    case["shipment"]["export_declaration_nos"] = declaration_refs(case["shipment"].get("export_declaration_nos"))
    case["shipment"].setdefault("bill_of_lading_no", "")
    case["shipment_reference_label"] = primary_shipment_reference(case["shipment"])
    if not isinstance(case.get("origin_snapshot"), dict):
        case["origin_snapshot"] = {}
    if not isinstance(case.get("bom_snapshot"), dict):
        case["bom_snapshot"] = {"composition": []}
    case["bom_snapshot"].setdefault("composition", [])
    case.setdefault("supporting_files", [])
    if case.get("products") and current_step != "origin":
        case = attach_results(case)
    if case_was_supplied and current_step == "origin":
        extra.setdefault("preserve_origin_products", True)
    force_source_refresh = bool(extra.pop("force_source_refresh", False))
    if not force_source_refresh and case.get("source_snapshot"):
        extra.setdefault("cached_case_context", True)
    extra["force_source_refresh"] = force_source_refresh
    export_states = (load_state(client_id).get("dossier_exports") or {}) if current_step == "index" else {}
    for dossier in workspace["cases"]:
        dossier["delete_block_reason"] = co_case_delete_block_reason(dossier)
        try:
            dossier["delete_claims_summary"] = co_stock_ledger.claims_summary_for_case(
                client_id, dossier.get("case_id", "")
            )
        except Exception:  # noqa: BLE001
            dossier["delete_claims_summary"] = {"count": 0, "lots": 0}
        if current_step == "index":
            exported = (export_states.get(dossier.get("case_id", "")) or {}).get("status") == "done"
            dossier["status_view"] = co_case_status_view(dossier, exported=exported)
    form_candidates = form_candidates_for_market(case.get("destination_market", ""))
    criteria_rows = build_case_criteria_rows(case, form_candidates)
    context = co_case_light_context(
        client_id,
        case=case,
        current_step=current_step,
        case_workspace=workspace,
        form_candidates=form_candidates,
        criteria_rows=criteria_rows,
        **extra,
    )
    # Tồn CO overview strip on the làm-CO list page (feedback #12). Cheap SQL
    # aggregate (~ms even on 60k-row clients); skip on detail/step pages where
    # the strip isn't shown.
    if current_step == "index":
        try:
            context["co_stock_summary"] = co_stock_materializer.co_stock_summary(client_id)
        except Exception:  # noqa: BLE001
            context["co_stock_summary"] = None
        active_views = [
            dossier["status_view"]
            for dossier in workspace["cases"]
            if not dossier["status_view"]["archived"]
        ]
        context["co_case_summary"] = {
            "total": len(active_views),
            "progress": sum(1 for view in active_views if view["status_key"] == "progress"),
            "done": sum(1 for view in active_views if view["status_key"] == "done"),
            "attention": sum(1 for view in active_views if view["status_key"] == "attention"),
            "exported": sum(1 for view in active_views if view["exported"]),
            "archived": sum(1 for dossier in workspace["cases"] if dossier["status_view"]["archived"]),
        }
    return context
def co_case_workflow_steps(
    client_id: str,
    case: dict,
    current_step: str,
    invoice_matches: list[dict] | None = None,
    criteria_rows: list[dict] | None = None,
    origin_demo_active: bool = False,
    tkx_tkn_summary: dict | None = None,
) -> list[dict]:
    case_id = case.get("persisted_case_id", "")
    base_url = f"/clients/{client_id}/co-case/{case_id}" if case_id else ""
    steps = []
    for step in CO_CASE_WORKFLOW_STEPS:
        href = base_url if step["key"] == "shipment" else f"{base_url}/{step['key']}"
        status = co_case_step_status(
            case,
            step["key"],
            invoice_matches=invoice_matches or [],
            criteria_rows=criteria_rows or [],
            origin_demo_active=origin_demo_active,
            tkx_tkn_summary=tkx_tkn_summary,
        )
        steps.append({
            **step,
            "href": href,
            "active": current_step == step["key"],
            "status": status["status"],
            "status_label": status["label"],
        })
    return steps
def co_case_step_status(
    case: dict,
    step_key: str,
    invoice_matches: list[dict] | None = None,
    criteria_rows: list[dict] | None = None,
    origin_demo_active: bool = False,
    tkx_tkn_summary: dict | None = None,
) -> dict:
    """Per-step status for the case stepper → {"status", "label"}.

    `status` ∈ {done, in_progress, attention, todo}; `label` is contextual per
    step (each step reads in its own terms, not one generic Đủ/Thiếu/Cần soát).
    Step 3 (origin) derives from `products[].origin_sheet_status` — the same
    signal `co_case_status_view` uses for the list page — so the stepper and the
    list never disagree, and a fully-locked case reaches `done` instead of being
    stuck on the old `review`/"Cần soát" forever.
    """
    invoice_matches = invoice_matches or []
    criteria_rows = criteria_rows or []
    shipment = case.get("shipment", {})
    has_reference = has_shipment_reference(shipment)
    has_market = bool(case.get("destination_market") and case.get("destination_market") != "Chưa nhập")
    products = case.get("products") or []
    has_products = bool(products or criteria_rows)
    if step_key == "shipment":
        # Partial = invoice OR market but not both. Name which half is missing
        # instead of a generic "thiếu".
        if has_reference and has_market:
            return {"status": "done", "label": "Đủ"}
        if has_reference:
            return {"status": "attention", "label": "Thiếu thị trường"}
        if has_market:
            return {"status": "attention", "label": "Thiếu invoice"}
        return {"status": "todo", "label": "Chưa nhập"}
    if step_key == "documents":
        if case.get("supporting_files"):
            return {"status": "done", "label": "Đã tải"}
        return {"status": "todo", "label": "Chưa tải"}
    if step_key == "origin":
        if origin_demo_active:
            return {"status": "in_progress", "label": "Xem thử"}
        total = len(products)
        if not total:
            return {"status": "todo", "label": "Chưa có NVL"}
        locked = sum(
            1 for product in products
            if str(product.get("origin_sheet_status") or "").strip().lower() == "locked"
        )
        if locked == total:
            return {"status": "done", "label": f"Đã chốt {locked}/{total}"}
        worked = any(
            str(product.get("origin_sheet_status") or "").strip().lower() not in ("", "draft")
            for product in products
        )
        if locked or worked:
            return {"status": "in_progress", "label": f"Đang làm · {locked}/{total} chốt"}
        return {"status": "todo", "label": "Chưa tính"}
    if step_key == "exports":
        if not has_reference:
            return {"status": "todo", "label": "Chưa có"}
        if not invoice_matches:
            return {"status": "attention", "label": "Thiếu tờ khai"}
        # "done" only when actual declaration files are present — matching the
        # inner page's truth, not just BCCT row presence. Treat a missing summary
        # (caller didn't pass) as still-needs-attention.
        if tkx_tkn_summary is not None:
            missing = (tkx_tkn_summary.get("missing_tkx") or []) or (tkx_tkn_summary.get("missing_tkn") or [])
            if missing:
                return {"status": "attention", "label": "Thiếu tờ khai"}
            return {"status": "done", "label": "Đủ"}
        return {"status": "attention", "label": "Thiếu tờ khai"}
    if step_key == "review":
        if co_case_is_completed(case):
            return {"status": "done", "label": "Đã xuất"}
        if has_reference and invoice_matches and has_products:
            return {"status": "in_progress", "label": "Sẵn sàng"}
        return {"status": "todo", "label": "Chưa sẵn sàng"}
    return {"status": "todo", "label": "Chưa nhập"}
def _refresh_co_stock_delta_or_full(client: dict) -> dict:
    """Pick delta vs full refresh and run it. Records refresh state so the
    next call can decide again. Errors fall back to full on the spot so a
    transient Data Hub issue doesn't strand the operator on an old snapshot."""
    state = co_stock_materializer.read_refresh_state(client["id"]) or {}
    last_server_time = state.get("last_bcct_server_time", "") if state else ""
    data_hub = getattr(portfolio_service, "data_hub", None)
    # A delta only makes sense ON TOP of an existing snapshot. If co_stock_rows is
    # empty but refresh_state still carries a server_time (DB reset, or a first
    # full-pull that recorded server_time without persisting rows), a delta-since
    # finds nothing new and the snapshot stays stranded empty forever. Force a
    # full pull whenever the snapshot is empty.
    snapshot_count = co_stock_materializer.row_count(client["id"])
    # Delta is only sound when one BCCT import row maps to one co_stock lot with a
    # stable per-row `source_row`. Under aggregate_by_declaration_and_allocation_code
    # the lot's `source_row` is a comma-joined set, so per-import-row tombstones
    # never match (phantom stock) and a changed row inserts a duplicate aggregate
    # (double-count). Force full for that policy until delta is aggregate-aware.
    lot_policy = portfolio_service.get_client_config(client).get("co_stock", {}).get("lot_policy", "line_level")
    delta_safe = lot_policy != "aggregate_by_declaration_and_allocation_code"
    if (
        delta_safe
        and last_server_time
        and snapshot_count > 0
        and data_hub is not None
        and hasattr(data_hub, "list_bcct_with_envelope")
    ):
        delta_summary = _try_delta_refresh(client, data_hub, last_server_time)
        if delta_summary is not None:
            return delta_summary
    return _full_refresh(client)
def _try_delta_refresh(client: dict, data_hub, last_server_time: str) -> dict | None:
    """Returns a summary on success, or None if delta path can't be taken
    (e.g. response missing `server_time`, indicating Data Hub doesn't yet
    support the contract on this deployment)."""
    try:
        envelope = data_hub.list_bcct_with_envelope(
            client["id"], since=last_server_time, include_tombstones=True,
        )
    except Exception as exc:  # noqa: BLE001 — log + fall back to full
        logging.getLogger(__name__).warning(
            "co_stock delta refresh pull failed for %s: %s", client["id"], exc
        )
        return None
    server_time = envelope.get("server_time") or ""
    if not server_time:
        return None  # Data Hub on old contract — caller falls back to full.
    delta_items = envelope.get("items") or []
    tombstones = envelope.get("tombstones") or []
    tombstone_source_rows = [
        f"import-row-{hashlib.sha1(str(t.get('transaction_key') or '').encode('utf-8')).hexdigest()[:16]}"
        for t in tombstones
        if isinstance(t, dict) and t.get("transaction_key")
    ]
    client_config = portfolio_service.get_client_config(client)
    from app.source_store import _safe_customs_fx_rows, co_stock_rows_from_bcct
    from app.data_hub_client import normalize_bcct_row
    delta_rows = co_stock_rows_from_bcct(
        [normalize_bcct_row(row) for row in delta_items],
        client_config,
        customs_fx_rows=_safe_customs_fx_rows(),
    )
    summary = co_stock_materializer.refresh_co_stock_for_client(
        client,
        lambda: delta_rows,
        mode="delta",
        tombstone_source_rows=tombstone_source_rows,
    )
    source_summary, _ = portfolio_service.source_summary(client)
    co_stock_materializer.record_refresh_state(
        client["id"],
        snapshot_row_count=co_stock_materializer.row_count(client["id"]),
        bcct_row_count_at_refresh=source_summary.get("bcct", {}).get("published_row_count", 0),
        last_bcct_server_time=server_time,
    )
    summary["server_time"] = server_time
    summary["tombstones_received"] = len(tombstones)
    return summary
def _full_refresh(client: dict) -> dict:
    # Capture the high-water mark BEFORE the data pull. Probing AFTER would record
    # a server_time ahead of the data we persist, so any row created during the
    # pull window (after the snapshot, before the probe) lands in neither this
    # full set nor the next delta (since=that-later-mark) — lost forever. A mark
    # taken before is conservative: the next delta re-pulls the window, and the
    # UPSERT is idempotent. Best-effort — blank when the deployment lacks
    # server_time support, leaving _refresh_co_stock_delta_or_full on full.
    server_time = _probe_server_time(client)
    workspace, _backend = portfolio_service.source_workspace(client)
    summary = co_stock_materializer.refresh_co_stock_for_client(
        client, lambda: workspace.get("co_stock_rows") or [],
    )
    if summary.get("aborted_empty_full_pull"):
        # The pull came back empty over a populated snapshot — snapshot preserved.
        # Do NOT advance refresh_state / server_time: marking the high-water mark
        # over rows we never pulled would strand them out of the next delta.
        return summary
    source_summary, _ = portfolio_service.source_summary(client)
    co_stock_materializer.record_refresh_state(
        client["id"],
        snapshot_row_count=summary.get("rows_persisted", 0),
        bcct_row_count_at_refresh=source_summary.get("bcct", {}).get("published_row_count", 0),
        last_bcct_server_time=server_time,
    )
    if server_time:
        summary["server_time"] = server_time
    return summary
def _probe_server_time(client: dict) -> str:
    data_hub = getattr(portfolio_service, "data_hub", None)
    if data_hub is None:
        return ""
    try:
        # Cheap path: page-1-only probe. Avoids re-paginating the whole BCCT
        # corpus (the full path already pulled it via source_workspace); the
        # only goal is to capture the high-water mark.
        if hasattr(data_hub, "bcct_server_time"):
            return data_hub.bcct_server_time(client["id"]) or ""
        # Fallback for backends/fakes without the cheap probe — discards items.
        if hasattr(data_hub, "list_bcct_with_envelope"):
            envelope = data_hub.list_bcct_with_envelope(client["id"], since="", include_tombstones=False)
            return envelope.get("server_time") or ""
        return ""
    except Exception:  # noqa: BLE001
        return ""
CALCULATE_SNAPSHOT_FRESHNESS_SECONDS = 30
def _co_stock_snapshot_is_fresh(client_id: str) -> bool:
    state = co_stock_materializer.read_refresh_state(client_id) or {}
    refreshed_at = str(state.get("refreshed_at") or "")
    if not refreshed_at:
        return False
    try:
        last = datetime.fromisoformat(refreshed_at)
    except ValueError:
        return False
    age = (datetime.now(last.tzinfo or timezone.utc) - last).total_seconds()
    return age < CALCULATE_SNAPSHOT_FRESHNESS_SECONDS
_co_stock_refresh_inflight_lock = threading.Lock()
def _schedule_background_co_stock_refresh(client: dict) -> None:
    """Refresh the materialized co_stock snapshot OFF the request path.

    Fired when /calculate (or origin load) reads a stale snapshot: the operator
    gets the snapshot we already have immediately, while a daemon thread pulls
    the delta (or full) from Data Hub and re-materializes — so the next
    calculate sees fresh tồn instead of stranding this one on a multi-minute
    re-pull (≈60k rows for a large client). A per-client in-flight guard
    collapses repeated Load BOM clicks into a single refresh.
    """
    client_id = str(client.get("id", "")) if isinstance(client, dict) else ""
    if not client_id:
        return
    with _co_stock_refresh_inflight_lock:
        if client_id in _co_stock_refresh_inflight:
            return
        _co_stock_refresh_inflight.add(client_id)

    def _run() -> None:
        try:
            _refresh_co_stock_delta_or_full(client)
        except Exception as exc:  # noqa: BLE001 — best effort; next click retries
            logging.getLogger(__name__).warning(
                "background co_stock refresh failed for %s: %s", client_id, exc
            )
        finally:
            with _co_stock_refresh_inflight_lock:
                _co_stock_refresh_inflight.discard(client_id)

    threading.Thread(target=_run, name=f"co-stock-refresh-{client_id}", daemon=True).start()
def _calculate_stock_rows_from_snapshot(client: dict) -> list[dict] | None:
    """Returns stock rows ready for `prepare_case_origin_sheet`, decorated with
    current ledger used/remaining qty, or None when the snapshot is empty (no
    DB / never materialized) so the caller's legacy full-pull runs instead — an
    operator never calculates against an empty snapshot.

    The calculation needs only the materialized co_stock snapshot (the tồn lots)
    plus live ledger claims — NOT a fresh Data Hub BCCT pull. So we read the
    snapshot we already have and return immediately. When it is older than
    `CALCULATE_SNAPSHOT_FRESHNESS_SECONDS` we kick a NON-BLOCKING background
    refresh so the next calculate sees fresh tồn, instead of blocking this
    request on a multi-minute synchronous re-pull. The origin UI surfaces the
    snapshot's age, so calculating on it is never silent, and `apply_used_qty`
    keeps available tồn correct against the latest claims regardless of age.
    """
    client_id = str(client.get("id", "")) if isinstance(client, dict) else ""
    if not client_id:
        return None
    rows = co_stock_materializer.read_co_stock_rows_cached(client_id)
    if not rows:
        # Cold start — nothing materialized yet. Defer to the caller's legacy
        # full pull rather than calculate against nothing.
        return None
    if not _co_stock_snapshot_is_fresh(client_id):
        _schedule_background_co_stock_refresh(client)
    # apply_used_qty mutates the rows in place to attach used/remaining,
    # so copy the cached payloads first — the cache must stay clean. The
    # materialized snapshot is already trừ-lùi-folded (refresh + import re-fold
    # keep it authoritative), so the live-ledger overlay alone is correct here;
    # no per-calculate adjustment query on the hot path.
    rows = [dict(r) for r in rows]
    used_by_lot = co_stock_ledger.used_qty_by_lot(client_id)
    return co_stock_ledger.apply_used_qty(rows, used_by_lot)
