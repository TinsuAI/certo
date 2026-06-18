from __future__ import annotations

import asyncio
import json
import logging
import re

from fastapi import APIRouter
from app import co_auth, co_stock_eligibility, co_stock_ledger, co_stock_materializer, material_search
from app.bom_store import attach_case_bom_snapshot
from app.co_case_store import CaseHasActiveClaimsError, MAX_SUPPORTING_FILE_BYTES, build_case_criteria_rows, case_from_record, co_case_is_completed, co_case_status_view, create_case_record, create_case_workbook, declaration_refs, delete_case_record, delete_supporting_file, get_case_record, get_case_workspace, get_supporting_file, invoice_keys, json_safe, safe_filename, save_supporting_file, set_case_archived, update_case_record
from app.co_form_config_store import load_co_form_config
from app.co_forms import prioritized_form_lanes, recommended_form_lane
from app.data_hub_client import current_data_hub_token
from app.data_hub_settings import data_hub_link_settings
from app.demo_data import attach_results, update_products_from_form
from app.dossier_export_service import dossier_export_result_path, dossier_export_status, submit_dossier_export
from app.portfolio import portfolio_service
from app.source_store import co_stock_rows_from_bcct
from app.web.client_context import default_client_case, effective_min_gap_days, resolve_client, source_workspace_for_client
from app.web.co_case_context import CO_CASE_WORKFLOW_STEP_KEYS, ORIGIN_SHEET_STATUS_LABELS, SHEET_CURRENCY_MODES, SHEET_OPTIMIZATION_MODES, _CO_CASE_SOURCE_CACHE, _calculate_stock_rows_from_snapshot, apply_existing_origin_product_consumption, attach_origin_bom_product_codes, attach_origin_readiness, attach_origin_sheet_states, case_allocation_pool, case_tkx_tkn_summary, co_case_context, co_case_source_context, co_case_source_context_cached, co_stock_is_usable, dossier_content_revision, co_stock_key_candidates, decimal_value, durable_sheet_status, invoice_preview_from_matches, market_inference_view, material_catalog_index, minimal_bom_workspace, normalize_threshold, numeric_sort_text, origin_case_revision, origin_match_from_existing_product, origin_product_from_invoice_match, origin_product_order, origin_sheet_action_error, origin_sheet_export_blockers, prepare_case_origin_sheet, primary_shipment_reference, shipment_reference_warnings
from app.web.deps import large_request_form
from app.web.templating import templates
from app.workbook_io import create_dossier_zip, create_hq_bang_ke_workbook
from datetime import date
from decimal import Decimal, InvalidOperation
from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from urllib.parse import quote


router = APIRouter()

def persisted_origin_case(client: dict, case_id: str) -> dict:
    record = get_case_record(client, case_id)
    case = case_from_record(default_client_case(client), client, record)
    case["persisted_case_id"] = case.get("persisted_case_id") or case_id
    return case
def merge_origin_action_payload(case: dict, payload: dict) -> dict:
    if not isinstance(payload, dict):
        return case
    prepared = dict(case)
    order = payload.get("origin_product_order")
    if isinstance(order, str):
        prepared["origin_product_order"] = origin_product_order({"origin_product_order": order})
    elif isinstance(order, list):
        prepared["origin_product_order"] = [str(code).strip() for code in order if str(code).strip()]
    bom_artifact_id = str(payload.get("bom_artifact_id") or payload.get("bom_version_id") or "").strip()
    if bom_artifact_id:
        prepared["bom_artifact_id"] = bom_artifact_id
        prepared["bom_version_id"] = bom_artifact_id
    overrides = dict(prepared.get("bom_product_artifact_overrides") or {})
    legacy_overrides = dict(prepared.get("bom_product_version_overrides") or {})
    incoming_overrides = payload.get("bom_product_artifact_overrides")
    if isinstance(incoming_overrides, dict):
        for code, artifact_id in incoming_overrides.items():
            code = str(code or "").strip()
            artifact_id = str(artifact_id or "").strip()
            if code and artifact_id:
                overrides[code] = artifact_id
                legacy_overrides[code] = artifact_id
    products_by_code = {
        str(product.get("code") or "").strip(): dict(product)
        for product in prepared.get("products", [])
        if str(product.get("code") or "").strip()
    }
    product_sheet_states: dict[str, dict] = {}
    for incoming in payload.get("products") or []:
        if not isinstance(incoming, dict):
            continue
        code = str(incoming.get("code") or incoming.get("product_code") or "").strip()
        if not code:
            continue
        product = products_by_code.get(code, {"code": code})
        for key in [
            "name",
            "finished_hs",
            "quantity",
            "unit",
            "currency",
            "source_declaration_no",
            "source_line_no",
            "invoice_ref",
            "fob",
            "non_origin_value",
            "rvc_threshold",
            "lvc_threshold",
            "bom_product_code",
            "bom_product_artifact_id",
            "bom_product_artifact_no",
            "bom_product_version_id",
            "bom_product_version_no",
            "origin_sheet_status",
            "origin_sheet_status_label",
        ]:
            if key in incoming:
                product[key] = incoming.get(key)
        if isinstance(incoming.get("cost_buildup"), dict):
            existing_cb = product.get("cost_buildup") if isinstance(product.get("cost_buildup"), dict) else {}
            cb_whitelist = {
                "wages", "welfare", "rent", "depreciation", "other_mfg", "transport_storage",
                "profit",
                "labor", "overhead", "other",  # legacy 4-key shape, still accepted
            }
            product["cost_buildup"] = {**existing_cb, **{k: str(v or "") for k, v in incoming["cost_buildup"].items() if k in cb_whitelist}}
        if isinstance(incoming.get("materials"), list):
            product["materials"] = incoming["materials"]
        if incoming.get("origin_sheet_status") or incoming.get("origin_sheet_status_label"):
            durable = durable_sheet_status(incoming.get("origin_sheet_status"))
            product_sheet_states[code] = {
                "status": durable,
                "status_label": ORIGIN_SHEET_STATUS_LABELS.get(
                    durable, str(incoming.get("origin_sheet_status_label") or "").strip()
                ),
            }
        artifact_id = str(
            product.get("bom_product_artifact_id") or product.get("bom_product_version_id") or ""
        ).strip()
        bom_product_code = str(product.get("bom_product_code") or code).strip()
        if artifact_id:
            overrides[code] = artifact_id
            legacy_overrides[code] = artifact_id
            if bom_product_code:
                overrides[bom_product_code] = artifact_id
                legacy_overrides[bom_product_code] = artifact_id
        products_by_code[code] = product
    if products_by_code:
        ordered = origin_product_order(prepared)
        remainder = [code for code in products_by_code if code not in ordered]
        prepared["products"] = [products_by_code[code] for code in ordered + remainder if code in products_by_code]
    sheet_states = payload.get("origin_sheet_states")
    if not isinstance(sheet_states, dict) and product_sheet_states:
        sheet_states = product_sheet_states
    if isinstance(sheet_states, dict):
        existing_states = prepared.get("origin_sheet_states") if isinstance(prepared.get("origin_sheet_states"), dict) else {}
        merged_states: dict[str, dict] = {
            str(code): dict(state)
            for code, state in existing_states.items()
            if isinstance(state, dict)
        }
        for code, state in sheet_states.items():
            if not isinstance(state, dict):
                continue
            previous = existing_states.get(str(code)) if isinstance(existing_states.get(str(code)), dict) else {}
            merged_states[str(code)] = {**previous, **state}
        prepared["origin_sheet_states"] = merged_states
    prepared["bom_product_artifact_overrides"] = overrides
    prepared["bom_product_version_overrides"] = legacy_overrides
    return prepared
async def origin_case_from_request(request: Request, client: dict, case_id: str) -> tuple[dict, dict]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        case = persisted_origin_case(client, case_id)
        expected_revision = str(payload.get("expected_revision") or "").strip()
        if expected_revision and expected_revision != origin_case_revision(case):
            raise HTTPException(status_code=409, detail="Origin case state changed; reload before saving.")
        return merge_origin_action_payload(case, payload), payload
    form = await large_request_form(request)
    case = update_products_from_form({key: str(value) for key, value in form.items()})
    case["persisted_case_id"] = case.get("persisted_case_id") or case_id
    return case, {key: str(value) for key, value in form.items()}
def record_sheet_lock_claims(client_id: str, case_id: str, product_code: str, case: dict) -> int:
    """Persist allocation lines from a locked sheet to the cross-case stock ledger.

    Reads the sheet's products[*].materials[*].allocation_lines and writes one
    claim per (source_row, material_code) so other cases see remaining_qty drop.
    Idempotent: re-locking the same sheet replaces prior claims for it.

    `case` may be the form-rebuilt case (which strips allocation_lines), so
    fall back to the persisted case from disk to get the canonical allocations.
    """
    target = _sheet_with_allocations(client_id, case_id, product_code, case)
    if not target:
        return 0
    allocations: list[dict] = []
    for material_index, material in enumerate(target.get("materials", []) or []):
        material_code = str(material.get("material_code") or material.get("internal_material_code") or "").strip()
        for line in material.get("allocation_lines", []) or []:
            allocations.append({
                "source_row": line.get("source_row", ""),
                "material_code": material_code,
                "material_index": material_index,
                "claimed_qty": line.get("allocated_qty", "0"),
                "declaration_no": line.get("import_declaration_no", ""),
                "line_no": line.get("import_line_no", ""),
                "customs_code": line.get("customs_material_code", "") or line.get("customs_code", ""),
            })
    return co_stock_ledger.record_sheet_lock(client_id, case_id, product_code, allocations)
def _sheet_with_allocations(client_id: str, case_id: str, product_code: str, case: dict) -> dict | None:
    """Pick the product entry, preferring the in-memory case but falling back to
    the persisted record on disk if its materials lack allocation_lines."""

    def _find(case_obj: dict | None) -> dict | None:
        if not case_obj:
            return None
        return next(
            (p for p in case_obj.get("products", []) if str(p.get("code") or "").strip() == product_code),
            None,
        )

    target = _find(case)
    if target and any(material.get("allocation_lines") for material in target.get("materials", []) or []):
        return target
    try:
        client = resolve_client(client_id)
        persisted = persisted_origin_case(client, case_id)
    except Exception:  # noqa: BLE001
        return target
    persisted_target = _find(persisted)
    return persisted_target or target
def invalidate_co_case_source_cache(client_id: str = "", case_id: str = "") -> None:
    """Clear cache entries — call when case mutates (lock, override, etc.)."""
    if not client_id and not case_id:
        _CO_CASE_SOURCE_CACHE.clear()
        return
    keys_to_drop = [
        key for key in _CO_CASE_SOURCE_CACHE
        if (not client_id or key[0] == client_id) and (not case_id or key[1] == case_id)
    ]
    for key in keys_to_drop:
        _CO_CASE_SOURCE_CACHE.pop(key, None)
def invoice_matches_only(client: dict, shipment: dict) -> list[dict]:
    """Lightweight invoice-match lookup for invoice-preview / search dropdown.

    File-store mode: falls through to match_case_bcct_exports (in-memory,
    surfaces invoice/declaration mismatch warnings).
    Data Hub mode: calls invoice_matches adapter directly (~300-500ms),
    avoiding the full materials + BCCT pagination that co_case_source_context
    would otherwise trigger on every keystroke for big clients.
    """
    invoice_no = str(shipment.get("invoice_no") or "").strip()
    declaration_nos = declaration_refs(shipment.get("export_declaration_nos"))
    data_hub = getattr(portfolio_service, "data_hub", None)
    if data_hub is None or not hasattr(data_hub, "invoice_matches"):
        # File-store / test mode: defer to the existing co_case_source_context
        # (in-memory or fake), which surfaces market_hint + reference_warning
        # via the canonical match path.
        try:
            source_context = co_case_source_context(client, {"shipment": shipment})
        except Exception:  # noqa: BLE001
            source_context = {}
        return source_context.get("invoice_matches") or []
    # Data Hub mode: exact-invoice lookup is indexed.
    try:
        client_config = portfolio_service.get_client_config(client) if hasattr(portfolio_service, "get_client_config") else {}
    except Exception:  # noqa: BLE001
        client_config = {}
    relevant_types = list(client_config.get("bcct", {}).get("relevant_export_declaration_types", []))
    matches: list[dict] = []
    if invoice_no:
        try:
            matches = data_hub.invoice_matches(client["id"], invoice_no, relevant_types)
        except Exception:  # noqa: BLE001
            matches = []
    if declaration_nos and not matches:
        for declaration in declaration_nos:
            matches.extend(declaration_invoice_matches(client, declaration, exact=True, include_invoice=False))
    elif declaration_nos and matches:
        wanted = {re.sub(r"[^A-Z0-9]", "", str(decl).upper()) for decl in declaration_nos}
        matches = [
            row for row in matches
            if re.sub(r"[^A-Z0-9]", "", str(row.get("declaration_no") or "").upper()) in wanted
        ] or matches
    return matches
def preload_co_case_origin_context(client_id: str, case_id: str) -> None:
    client = resolve_client(client_id)
    try:
        record = get_case_record(client, case_id)
    except KeyError:
        return
    if record.get("source_snapshot") and record.get("products"):
        return
    context = co_case_context(
        client_id,
        case_id,
        current_step="origin",
        origin_demo_allowed=False,
        force_source_refresh=True,
    )
    if context.get("origin_demo_active"):
        return
    try:
        update_case_record(client, context["case"])
    except KeyError:
        return
def invoice_lookup_payload(client: dict, invoice_no: str, query: str = "", export_declaration_nos: str | list[str] = "") -> dict:
    invoice_no = str(invoice_no or "").strip()
    declaration_nos = declaration_refs(export_declaration_nos)
    query = str(query or invoice_no or (declaration_nos[0] if declaration_nos else "")).strip()
    options = invoice_search_options(client, query)
    if not invoice_no and not declaration_nos:
        return {
            "status": "empty",
            "invoice_no": "",
            "reference_warnings": [],
            "options": options,
            "match_count": 0,
            "matches": [],
            "summary": {},
            "market_inference": market_inference_view({"status": "missing", "destination_market": "", "hints": []}),
            "suggested_forms": [],
        }
    resolved = resolve_shipment_reference(client, invoice_no, declaration_nos)
    lookup_invoice_no = resolved["invoice_no"]
    try:
        # Lightweight match path — invoice-preview only needs invoice_matches.
        # Calling co_case_source_context here would full-paginate materials + BCCT
        # from Data Hub on every keystroke (seconds per request for large clients).
        invoice_matches = invoice_matches_only(client, resolved["shipment"])
    except Exception as exc:
        return {
            "status": "error",
            "invoice_no": lookup_invoice_no,
            "reference_warnings": [],
            "options": options,
            "match_count": 0,
            "matches": [],
            "summary": {},
            "market_inference": market_inference_view({"status": "missing", "destination_market": "", "hints": []}),
            "suggested_forms": [],
            "message": f"Không tra được invoice: {exc}",
        }
    payload = invoice_preview_from_matches(lookup_invoice_no, invoice_matches)
    payload["reference_warnings"] = shipment_reference_warnings(
        resolved["shipment"],
        invoice_matches,
    )
    payload["options"] = options
    if resolved.get("source_reference"):
        payload["source_reference"] = resolved["source_reference"]
        payload["source_reference_type"] = resolved["source_reference_type"]
        payload["reference_label"] = primary_shipment_reference(resolved["shipment"])
        if not payload.get("invoice_no"):
            payload["invoice_no"] = resolved["source_reference"]
    return payload
def resolve_shipment_reference(client: dict, reference: str, export_declaration_nos: str | list[str] = "") -> dict:
    reference = str(reference or "").strip()
    explicit_declarations = declaration_refs(export_declaration_nos)
    if explicit_declarations:
        matches = []
        for declaration in explicit_declarations:
            matches.extend(declaration_invoice_matches(client, declaration, exact=True, include_invoice=False))
        invoice_refs = sorted({row.get("invoice_ref", "") for row in matches if row.get("invoice_ref")})
        invoice_no = reference if reference and not declaration_invoice_matches(client, reference, exact=True, include_invoice=False) else ""
        if len(invoice_refs) == 1:
            invoice_no = invoice_no or invoice_refs[0]
        return {
            "invoice_no": invoice_no,
            "export_declaration_nos": explicit_declarations,
            "source_reference": ", ".join(explicit_declarations),
            "source_reference_type": "declaration",
            "shipment": {"invoice_no": invoice_no, "export_declaration_nos": explicit_declarations},
        }
    if not reference:
        return {
            "invoice_no": "",
            "export_declaration_nos": [],
            "source_reference": "",
            "source_reference_type": "",
            "shipment": {"invoice_no": "", "export_declaration_nos": []},
        }
    matches = declaration_invoice_matches(client, reference, exact=True, include_invoice=False)
    if matches:
        invoice_refs = sorted({row["invoice_ref"] for row in matches if row.get("invoice_ref")})
        invoice_no = invoice_refs[0] if len(invoice_refs) == 1 else ""
        return {
            "invoice_no": invoice_no,
            "export_declaration_nos": [reference],
            "source_reference": reference,
            "source_reference_type": "declaration",
            "shipment": {"invoice_no": invoice_no, "export_declaration_nos": [reference]},
        }
    return {
        "invoice_no": reference,
        "export_declaration_nos": [],
        "source_reference": "",
        "source_reference_type": "",
        "shipment": {"invoice_no": reference, "export_declaration_nos": []},
    }
def invoice_search_options(client: dict, query: str, limit: int = 10) -> list[dict]:
    query = str(query or "").strip()
    if len(query) < 2:
        return []
    # Use Data Hub invoice-matches adapter when available — it's an indexed
    # query (~300-500ms typical) instead of pulling the full BCCT pagination
    # for every keystroke. Falls back to local indexed lookup only when the
    # Data Hub adapter is not present (file-store mode).
    data_hub = getattr(portfolio_service, "data_hub", None)
    if data_hub is not None and hasattr(data_hub, "invoice_matches"):
        try:
            rows = data_hub.invoice_matches(client["id"], query, [])
        except Exception:  # noqa: BLE001
            rows = []
        if not rows and hasattr(data_hub, "list_bcct"):
            # Try declaration-number lookup (declaration_no exact prefix).
            compact = re.sub(r"[^A-Z0-9]", "", query.upper())
            try:
                bcct_rows = data_hub.list_bcct(client["id"], declaration_no=compact, direction="export")
            except TypeError:
                bcct_rows = []
            except Exception:  # noqa: BLE001
                bcct_rows = []
            rows = [row for row in bcct_rows if row.get("review_status") in ("", "reviewed")]
    else:
        rows = declaration_invoice_matches(client, query, exact=False)
    groups: dict[str, dict] = {}
    for row in rows:
        invoice_ref = row.get("invoice_ref", "")
        option_value = invoice_ref or row.get("declaration_no", "")
        group = groups.setdefault(
            option_value,
            {
                "invoice_no": option_value,
                "row_count": 0,
                "declarations": set(),
                "hs_codes": set(),
                "item_codes": set(),
            },
        )
        group["row_count"] += 1
        if row.get("declaration_no"):
            group["declarations"].add(str(row.get("declaration_no")))
        if row.get("hs_code"):
            group["hs_codes"].add(str(row.get("hs_code")))
        if row.get("item_code"):
            group["item_codes"].add(str(row.get("item_code")))
    options = []
    for group in groups.values():
        options.append({
            "invoice_no": group["invoice_no"],
            "row_count": group["row_count"],
            "declaration_count": len(group["declarations"]),
            "declarations": sorted(group["declarations"])[:4],
            "hs_codes": sorted(group["hs_codes"])[:6],
            "item_codes": sorted(group["item_codes"])[:4],
        })
    return sorted(options, key=lambda row: (-int(row["row_count"]), row["invoice_no"]))[:limit]
def declaration_invoice_matches(client: dict, query: str, exact: bool, include_invoice: bool = True) -> list[dict]:
    query = str(query or "").strip()
    if len(query) < 2:
        return []
    # Fast path for Data Hub mode: indexed invoice/declaration lookup, no
    # full-catalog pagination. Falls back to in-memory workspace for file-store
    # / test mode.
    data_hub = getattr(portfolio_service, "data_hub", None)
    if data_hub is not None and hasattr(data_hub, "invoice_matches"):
        try:
            client_config = portfolio_service.get_client_config(client) if hasattr(portfolio_service, "get_client_config") else {}
        except Exception:  # noqa: BLE001
            client_config = {}
        relevant_types_list = list(client_config.get("bcct", {}).get("relevant_export_declaration_types", []))
        rows: list[dict] = []
        if include_invoice:
            try:
                rows = list(data_hub.invoice_matches(client["id"], query, relevant_types_list))
            except Exception:  # noqa: BLE001
                rows = []
        # Declaration lookup — list_bcct accepts declaration_no kwarg on Data Hub.
        if hasattr(data_hub, "list_bcct"):
            compact = re.sub(r"[^A-Z0-9]", "", query.upper())
            try:
                decl_rows = list(data_hub.list_bcct(client["id"], declaration_no=compact, direction="export"))
            except Exception:  # noqa: BLE001
                decl_rows = []
            seen = {(row.get("declaration_no"), row.get("line_no"), row.get("transaction_key")) for row in rows}
            for row in decl_rows:
                key = (row.get("declaration_no"), row.get("line_no"), row.get("transaction_key"))
                if key not in seen:
                    rows.append(row)
                    seen.add(key)
        return rows
    try:
        source_workspace, _source_backend = source_workspace_for_client(client)
    except Exception:
        return []
    client_config = source_workspace.get("client_config", {})
    relevant_types = set(client_config.get("bcct", {}).get("relevant_export_declaration_types", []))
    query_keys = invoice_keys(query)
    query_compact = next(iter(query_keys), re.sub(r"[^A-Z0-9]", "", query.upper()))
    matches = []
    for row in source_workspace.get("bcct", {}).get("published_rows", []):
        if row.get("direction") != "export":
            continue
        if row.get("review_status") not in ("", "reviewed"):
            continue
        if relevant_types and row.get("declaration_type") not in relevant_types:
            continue
        invoice_ref = str(row.get("invoice_ref") or "").strip()
        row_keys = invoice_keys(invoice_ref)
        row_compact = re.sub(r"[^A-Z0-9]", "", invoice_ref.upper())
        declaration_compact = re.sub(r"[^A-Z0-9]", "", str(row.get("declaration_no") or "").upper())
        invoice_matches = include_invoice and query_compact and (query_compact in row_compact or bool(query_keys.intersection(row_keys)))
        declaration_matches = (
            query_compact == declaration_compact
            if exact
            else query_compact and query_compact in declaration_compact
        )
        if not invoice_matches and not declaration_matches:
            continue
        matches.append({**row, "invoice_ref": invoice_ref})
    return matches
def recalculate_origin_sheet_edits(client: dict, case: dict, product_code: str, *, min_gap_days: int | None = None) -> dict:
    """Recompute one sheet from its saved sheet edits, without changing BOM selection."""
    prepared = attach_origin_sheet_states(case)
    products = prepared.get("products", [])
    target_index = next(
        (index for index, product in enumerate(products) if str(product.get("code") or "").strip() == product_code),
        None,
    )
    if target_index is None:
        return prepared
    target = products[target_index]
    overrides = target.get("origin_sheet_material_overrides") or {}
    if not overrides:
        return prepared

    sheet_rows = sheet_edit_bom_rows(target, overrides)
    material_codes = sorted({
        str(row.get("material_code") or "").strip()
        for row in sheet_rows
        if str(row.get("material_code") or "").strip()
    })
    source_context = {"material_rows": [], "stock_rows": []}
    # Stock MUST come from the same trừ-lùi-FOLDED + live-ledger snapshot the
    # sheet-lock validates against (co_stock_ledger.record_sheet_lock). The
    # narrow list_bcct_by_codes pull below returns RAW BCCT remaining
    # (remaining_qty == quantity, un-folded, blind to other-case claims), so
    # allocating from it over-states tồn — and the subsequent "Chốt" then fails
    # with a spurious "vượt tồn ở N lot" on every lot carrying a trừ-lùi
    # baseline. Mirror the non-override /calculate path so calculate and lock
    # agree; fall back to the raw pull only on a cold/empty snapshot (no fold
    # exists yet there anyway).
    stock_rows: list[dict] = _calculate_stock_rows_from_snapshot(client) or []
    if not stock_rows:
        try:
            narrow_rows = portfolio_service.list_bcct_by_codes(client.get("id", ""), material_codes, direction="import")
        except Exception:  # noqa: BLE001
            narrow_rows = []
        if narrow_rows:
            try:
                client_config = portfolio_service.get_client_config(client) if hasattr(portfolio_service, "get_client_config") else {}
                stock_rows = co_stock_rows_from_bcct(narrow_rows, client_config)
            except Exception:  # noqa: BLE001
                stock_rows = []
        if not stock_rows and not co_auth.data_hub_source_mode_enabled():
            try:
                source_context = co_case_source_context_cached(client, prepared)
                stock_rows = source_context.get("stock_rows") or []
            except Exception:  # noqa: BLE001
                source_context = {"material_rows": [], "stock_rows": []}
                stock_rows = []
    material_index = material_catalog_index(source_context.get("material_rows") or [])
    cached_matches = case.get("source_invoice_matches") if isinstance(case.get("source_invoice_matches"), list) else []
    stock_pool = case_allocation_pool(prepared, cached_matches, stock_rows, min_gap_days=min_gap_days)
    for previous in products[:target_index]:
        apply_existing_origin_product_consumption(previous, stock_pool)

    form_lane = recommended_form_lane(
        prioritized_form_lanes(prepared.get("destination_market", ""), [str(target.get("finished_hs") or "")])
    )
    recalculated = origin_product_from_invoice_match(
        origin_match_from_existing_product(target),
        sheet_rows,
        form_lane,
        material_index,
        stock_pool,
        product_sequence=target_index + 1,
        bom_product_code=str(target.get("bom_product_code") or target.get("code") or ""),
    )
    for key in [
        "bom_product_artifact_id",
        "bom_product_artifact_no",
        "bom_product_version_id",
        "bom_product_version_no",
    ]:
        if target.get(key) and not recalculated.get(key):
            recalculated[key] = target.get(key)

    updated_products = [dict(product) for product in products]
    updated_products[target_index] = recalculated
    prepared["products"] = updated_products
    return attach_origin_sheet_states(prepared)
def sheet_edit_bom_rows(product: dict, overrides: dict) -> list[dict]:
    rows: list[dict] = []
    materials = product.get("materials") or []
    for index, material in enumerate(materials):
        override = overrides.get(str(index)) if isinstance(overrides.get(str(index)), dict) else {}
        if override.get("deleted"):
            # Soft delete: GIỮ dòng trong output (gắn cờ `deleted`) để materials
            # KHÔNG co lại — index ổn định, override các lần xoá sau không lệch
            # sang dòng kế bên (gốc BG1). Phần tính (VNM/LVC/phân bổ) loại trừ
            # theo cờ này; template fold dòng deleted.
            deleted_code = str(material.get("material_code") or material.get("internal_material_code") or "").strip()
            rows.append({
                "product_code": product.get("bom_product_code") or product.get("code") or "",
                "material_code": deleted_code,
                "qty_per": str(material.get("bom_qty_per") or "0"),
                "uom": str(material.get("uom") or ""),
                "material_name": str(material.get("material_description") or ""),
                "hs_code": str(material.get("hs_code") or ""),
                "source": material.get("bom_source") or material.get("source_document_ref") or "sheet_edit",
                "row_class": material.get("bom_row_class") or "",
                "unit_value": material.get("unit_value", ""),
                "deleted": True,
            })
            continue
        replacement_code = str(override.get("material_code") or "").strip()
        original_code = str(material.get("material_code") or material.get("internal_material_code") or "").strip()
        material_code = replacement_code or original_code
        if not material_code:
            continue
        row = {
            "product_code": product.get("bom_product_code") or product.get("code") or "",
            "material_code": material_code,
            "qty_per": str(override.get("norm_per_unit") or material.get("bom_qty_per") or "0"),
            "uom": str(override.get("uom") or material.get("uom") or ""),
            "material_name": str(override.get("name") or ("" if replacement_code else material.get("material_description")) or ""),
            "hs_code": str(override.get("hs_code") or ("" if replacement_code else material.get("hs_code")) or ""),
            "source": material.get("bom_source") or material.get("source_document_ref") or "sheet_edit",
            "row_class": material.get("bom_row_class") or "",
        }
        if not replacement_code:
            row["unit_value"] = material.get("unit_value", "")
        rows.append(row)
    added_items = [
        (key, value)
        for key, value in overrides.items()
        if str(key).startswith("added_") and isinstance(value, dict) and value.get("material_code")
    ]
    added_items.sort(key=lambda item: numeric_sort_text(str(item[0]).split("_", 1)[1] if "_" in str(item[0]) else "0"))
    for _key, value in added_items:
        rows.append({
            "product_code": product.get("bom_product_code") or product.get("code") or "",
            "material_code": str(value.get("material_code") or "").strip(),
            "qty_per": str(value.get("norm_per_unit") or "0"),
            "uom": str(value.get("uom") or ""),
            "material_name": str(value.get("name") or ""),
            "hs_code": str(value.get("hs_code") or ""),
            "source": "sheet_edit_added",
            "row_class": "added",
        })
    return rows
def _hydrate_product_export_declaration_dates(case: dict, client: dict | None = None) -> None:
    """Backfill missing `product.source_declaration_date` from cached matches,
    falling back to Data Hub `list_declarations` for cases saved before
    `enrich_invoice_matches_with_bcct` started forwarding `declaration_date`.

    Read-only patch — operator overrides on `case["products"]` are untouched.
    Cached `case["source_invoice_matches"]` is updated in place so the next
    `update_case_record` call (typically right after export prep) persists the
    backfill, making future renders free.
    """
    products = [p for p in (case.get("products") or []) if not p.get("source_declaration_date")]
    if not products:
        return

    matches = case.get("source_invoice_matches") if isinstance(case.get("source_invoice_matches"), list) else []
    by_decl: dict[str, str] = {}
    for row in matches:
        decl = str(row.get("declaration_no") or "").strip()
        if not decl or decl in by_decl:
            continue
        value = str(row.get("declaration_date") or row.get("registration_date") or "").strip()
        if value:
            by_decl[decl] = value

    missing: list[str] = []
    for product in products:
        decl = str(product.get("source_declaration_no") or "").strip()
        if decl and decl not in by_decl:
            missing.append(decl)

    if missing and client and client.get("id"):
        dates = _fetch_export_declaration_dates(client["id"], sorted(set(missing)))
        by_decl.update({k: v for k, v in dates.items() if v})
        if dates and matches:
            for row in matches:
                decl = str(row.get("declaration_no") or "").strip()
                if decl and not row.get("declaration_date") and dates.get(decl):
                    row["declaration_date"] = dates[decl]

    if not by_decl:
        return
    for product in products:
        decl = str(product.get("source_declaration_no") or "").strip()
        if decl and decl in by_decl:
            product["source_declaration_date"] = by_decl[decl]
def _fetch_export_declaration_dates(client_id: str, declaration_nos: list[str]) -> dict[str, str]:
    """Resolve `earliest_bcct_date` per export declaration_no from Data Hub.

    Returns mapping {declaration_no: "YYYY-MM-DD"}. Empty dict on any error or
    when the active portfolio service doesn't wrap a Data Hub client.
    """
    data_hub = getattr(portfolio_service, "data_hub", None)
    if data_hub is None or not declaration_nos:
        return {}
    try:
        rows = data_hub.list_declarations(
            client_id,
            direction="export",
            declaration_nos=declaration_nos,
        )
    except Exception:  # noqa: BLE001 — best-effort backfill; export must not block
        return {}
    out: dict[str, str] = {}
    for row in rows or []:
        decl = str(row.get("declaration_no") or "").strip()
        date = str(row.get("earliest_bcct_date") or "").strip()
        if decl and date:
            out[decl] = _to_vietnamese_date(date)
    return out
def _to_vietnamese_date(value: str) -> str:
    """Convert "YYYY-MM-DD" (Data Hub ISO) to "DD/MM/YYYY" (bảng kê format)."""
    text = value.strip()
    if not text:
        return ""
    try:
        from datetime import date
        d = date.fromisoformat(text[:10])
        return d.strftime("%d/%m/%Y")
    except ValueError:
        return text
def _hydrate_material_dates_from_stock(case: dict, client: dict) -> None:
    """Backfill missing `import_declaration_date` on materials + allocation lines.

    Materials/allocations saved before `co_stock_rows_from_bcct` started
    copying `registration_date` out of the BCCT payload have empty date
    fields, which leaves col "Ngày" blank on the exported xlsx. Re-running
    Calculate would refresh the snapshot but also wipes operator overrides
    (delete/substitute/norm/added rows), so we look up dates from the
    materialized stock table here instead — read-only, no override loss.
    """
    client_id = str(client.get("id") or "").strip()
    if not client_id:
        return
    rows_to_lookup: set[str] = set()
    for product in case.get("products") or []:
        for material in product.get("materials") or []:
            if not (material.get("import_declaration_date")
                    or material.get("declaration_date")
                    or material.get("registration_date")):
                source_row = str(material.get("source_row") or "").strip()
                if source_row:
                    rows_to_lookup.add(source_row)
            for allocation in material.get("allocation_lines") or []:
                if not (allocation.get("import_declaration_date")
                        or allocation.get("declaration_date")
                        or allocation.get("registration_date")):
                    source_row = str(allocation.get("source_row") or "").strip()
                    if source_row:
                        rows_to_lookup.add(source_row)
    if not rows_to_lookup:
        return
    dates = co_stock_materializer.registration_dates_for_source_rows(client_id, list(rows_to_lookup))
    if not dates:
        return
    for product in case.get("products") or []:
        for material in product.get("materials") or []:
            if not material.get("import_declaration_date"):
                joined = []
                source_row = str(material.get("source_row") or "").strip()
                for piece in [p.strip() for p in source_row.split(",") if p.strip()]:
                    value = dates.get(piece)
                    if value and value not in joined:
                        joined.append(value)
                if joined:
                    material["import_declaration_date"] = ", ".join(joined)
            for allocation in material.get("allocation_lines") or []:
                if not allocation.get("import_declaration_date"):
                    value = dates.get(str(allocation.get("source_row") or "").strip())
                    if value:
                        allocation["import_declaration_date"] = value
def set_origin_sheet_status(case: dict, product_code: str, status: str) -> dict:
    if status not in ORIGIN_SHEET_STATUS_LABELS:
        status = "draft"
    states = dict(case.get("origin_sheet_states") or {})
    previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
    states[product_code] = {
        **previous,
        "status": status,
        "status_label": ORIGIN_SHEET_STATUS_LABELS[status],
    }
    prepared = dict(case)
    prepared["origin_sheet_states"] = states
    return attach_origin_sheet_states(prepared)
def reject_if_sheet_locked(case: dict, product_code: str) -> None:
    """Refuse material/norm mutations on a sheet whose status is `locked`.

    The UI hides the edit buttons when locked (`co_case.html` + JS gate from
    commit `0ca012a`), but those guards can be bypassed by direct POST. Without
    this server check, mutating a locked sheet would leave the ledger holding
    `co_stock_claims` for the old materials while the persisted sheet now lists
    the new ones — a quiet Tồn CO leak. Operator must Mở chốt the sheet first.
    """
    state = (case.get("origin_sheet_states") or {}).get(product_code, {}) or {}
    if state.get("status") == "locked":
        raise HTTPException(
            status_code=409,
            detail=f"Sheet {product_code} đã chốt; mở chốt trước khi sửa NVL.",
        )
def mark_origin_sheets_stale(case: dict, from_index: int) -> dict:
    prepared = attach_origin_sheet_states(case)
    states = dict(prepared.get("origin_sheet_states") or {})
    for index, product in enumerate(prepared.get("products", [])):
        code = str(product.get("code") or "").strip()
        current_status = str(product.get("origin_sheet_status") or "").strip()
        if code and index >= max(from_index, 0) and current_status != "draft":
            previous = states.get(code) if isinstance(states.get(code), dict) else {}
            states[code] = {
                **previous,
                "status": "stale",
                "status_label": ORIGIN_SHEET_STATUS_LABELS["stale"],
            }
    prepared["origin_sheet_states"] = states
    return attach_origin_sheet_states(prepared)
def set_origin_sheet_config_override(
    case: dict, product_code: str, overrides: dict
) -> dict:
    states = dict(case.get("origin_sheet_states") or {})
    previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
    sanitized = {**previous}
    if "form_override" in overrides:
        sanitized["form_override"] = str(overrides.get("form_override") or "").strip()
    if "criteria_override" in overrides:
        sanitized["criteria_override"] = str(overrides.get("criteria_override") or "").strip()
    if "lvc_threshold_override" in overrides:
        sanitized["lvc_threshold_override"] = normalize_threshold(overrides.get("lvc_threshold_override"))
    if "rvc_threshold_override" in overrides:
        sanitized["rvc_threshold_override"] = normalize_threshold(overrides.get("rvc_threshold_override"))
    if "currency_mode" in overrides:
        mode = str(overrides.get("currency_mode") or "").strip().lower()
        sanitized["currency_mode"] = mode if mode in SHEET_CURRENCY_MODES else "native"
    if "optimization_mode" in overrides:
        mode = str(overrides.get("optimization_mode") or "").strip().lower()
        sanitized["optimization_mode"] = mode if mode in SHEET_OPTIMIZATION_MODES else "max_lvc"
    states[product_code] = sanitized
    prepared = dict(case)
    prepared["origin_sheet_states"] = states
    return attach_origin_sheet_states(prepared)
@router.get("/clients/{client_id}/co-case", response_class=HTMLResponse)
async def co_case(request: Request, client_id: str):
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id),
    )
@router.get("/clients/{client_id}/co-case-picker", response_class=HTMLResponse)
async def co_case_picker(request: Request, client_id: str, current: str = ""):
    # Lazy-loaded fragment for the "Đổi hồ sơ" modal switcher. Distinct literal
    # second segment so it never collides with /co-case/{case_id}. Light: only
    # the case state (no Data Hub pull) + a status view per case.
    client = resolve_client(client_id)
    cases = get_case_workspace(client, "").get("cases", [])
    for case in cases:
        case["status_view"] = co_case_status_view(case)
    return templates.TemplateResponse(
        request=request,
        name="_picker_cases.html",
        context={"client": client, "cases": cases, "current_case_id": current},
    )
@router.get("/clients/{client_id}/co-case/invoice-preview")
async def co_case_invoice_preview(client_id: str, invoice_no: str = "", q: str = "", export_declaration_nos: str = ""):
    client = resolve_client(client_id)
    return invoice_lookup_payload(client, invoice_no, q, export_declaration_nos)
@router.post("/clients/{client_id}/co-case/create")
async def create_co_case(request: Request, client_id: str):
    client = resolve_client(client_id)
    form = {key: str(value) for key, value in (await request.form()).items()}
    resolved = resolve_shipment_reference(client, form.get("invoice_no", ""), form.get("export_declaration_nos", ""))
    form["invoice_no"] = resolved["invoice_no"]
    form["export_declaration_nos"] = ", ".join(resolved["export_declaration_nos"])
    record = create_case_record(client, form)
    # Set a short-lived cookie so the case detail page can surface a one-time
    # toast confirming the dossier was created (without changing the redirect
    # URL — many tests + back-references rely on the canonical path).
    response = RedirectResponse(
        f"/clients/{client_id}/co-case/{record['case_id']}",
        status_code=303,
    )
    response.set_cookie(
        "co_case_just_created",
        record["case_id"],
        max_age=60,
        path=f"/clients/{client_id}/co-case/{record['case_id']}",
        httponly=False,
        samesite="lax",
    )
    return response
@router.post("/clients/{client_id}/co-case/{case_id}/delete", response_class=HTMLResponse)
async def delete_co_case(request: Request, client_id: str, case_id: str):
    if not co_auth.can_delete_co_cases(co_auth.current_user(request)):
        raise HTTPException(status_code=403, detail="Không có quyền xoá hồ sơ C/O.")
    client = resolve_client(client_id)
    form = await request.form()
    release_claims = str(form.get("confirm_release_claims") or "").strip() == "1"
    try:
        result = delete_case_record(client, case_id, release_claims=release_claims)
    except KeyError:
        raise HTTPException(status_code=404) from None
    except CaseHasActiveClaimsError as exc:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(client_id, error=str(exc)),
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(client_id, error=str(exc)),
        )
    released = int(result.get("claims_released") or 0)
    flash = (
        f"Đã xoá hồ sơ và nhả {released} dòng tồn về kho."
        if released
        else "Đã xoá hồ sơ."
    )
    redirect = RedirectResponse(f"/clients/{client_id}/co-case", status_code=303)
    # Cookies are latin-1 only; URL-encode the Vietnamese flash text and
    # decode in the template (request.cookies.get(...) | urldecode).
    redirect.set_cookie(
        "co_flash",
        quote(flash, safe=""),
        max_age=15,
        path=f"/clients/{client_id}/co-case",
    )
    return redirect
@router.post("/clients/{client_id}/co-case/{case_id}/archive", response_class=HTMLResponse)
async def archive_co_case(request: Request, client_id: str, case_id: str):
    client = resolve_client(client_id)
    form = await request.form()
    archived = str(form.get("archived") or "1").strip() != "0"
    try:
        set_case_archived(client, case_id, archived)
    except KeyError:
        raise HTTPException(status_code=404) from None
    flash = "Đã lưu trữ hồ sơ." if archived else "Đã bỏ lưu trữ hồ sơ."
    next_url = str(form.get("next_url") or f"/clients/{client_id}/co-case")
    redirect = RedirectResponse(next_url, status_code=303)
    redirect.set_cookie(
        "co_flash",
        quote(flash, safe=""),
        max_age=15,
        path=f"/clients/{client_id}/co-case",
    )
    return redirect
@router.post("/clients/{client_id}/co-case/{case_id}/shipment")
async def update_co_case_shipment(request: Request, client_id: str, case_id: str):
    form = {key: str(value) for key, value in (await request.form()).items()}
    client = resolve_client(client_id)
    resolved = resolve_shipment_reference(client, form.get("invoice_no", ""), form.get("export_declaration_nos", ""))
    update_case_record(
        client,
        {
            **form,
            "id": case_id,
            "persisted_case_id": case_id,
            "shipment": {
                "invoice_no": resolved["invoice_no"],
                "export_declaration_nos": resolved["export_declaration_nos"],
                "bill_of_lading_no": form.get("bill_of_lading_no", ""),
            },
        },
    )
    return RedirectResponse(f"/clients/{client_id}/co-case/{case_id}", status_code=303)
@router.get("/clients/{client_id}/co-case/{case_id}", response_class=HTMLResponse)
async def co_case_detail(request: Request, client_id: str, case_id: str):
    # Run preload in a thread so the case detail page returns immediately.
    # Preload fetches source_context (BCCT pagination) and persists it to the
    # case record; the next /origin click reads the cached snapshot instead of
    # hitting Data Hub again. Background is fine because the shipment tab
    # doesn't need origin context, and /origin has its own fallback if preload
    # hasn't finished yet.
    asyncio.get_event_loop().run_in_executor(
        None, preload_co_case_origin_context, client_id, case_id
    )
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(client_id, case_id, "shipment"),
    )
@router.get("/clients/{client_id}/co-case/{case_id}/export-bang-ke")
async def export_co_case_bang_ke_workbook_get(request: Request, client_id: str, case_id: str):
    return await export_co_case_bang_ke_workbook(request, client_id, case_id)
@router.get("/clients/{client_id}/co-case/{case_id}/{step}", response_class=HTMLResponse)
async def co_case_step(request: Request, client_id: str, case_id: str, step: str):
    if step not in CO_CASE_WORKFLOW_STEP_KEYS:
        raise HTTPException(status_code=404)
    context = co_case_context(
        client_id, case_id, step, requested_sheet=request.query_params.get("sheet")
    )
    if step == "review":
        # Server-render the current export state into the page so the panel shows
        # it immediately — no "Đang tải trạng thái…" placeholder + extra round-trip
        # on load. The JS only polls when the state is actually `running`.
        client = resolve_client(client_id)
        try:
            record = get_case_record(client, case_id)
        except KeyError:
            record = None
        if record is not None:
            context["export"] = dossier_export_status(
                client, case_id, current_revision=dossier_content_revision(record)
            )
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=context,
    )
@router.get("/clients/{client_id}/co-case/{case_id}/origin/calculation-payload")
async def co_case_origin_calculation_payload(client_id: str, case_id: str):
    context = co_case_context(
        client_id,
        case_id,
        current_step="origin",
        origin_demo_allowed=False,
    )
    case = context["case"]
    source_context = context.get("origin_source_context", {})
    return {
        "case_id": case.get("persisted_case_id") or case_id,
        "case_code": case.get("case_code", ""),
        "revision": origin_case_revision(case),
        "source_snapshot": json_safe(case.get("source_snapshot", {})),
        "bom_snapshot": json_safe(case.get("bom_snapshot", {})),
        "origin_snapshot": json_safe(case.get("origin_snapshot", {})),
        "origin_product_order": origin_product_order(case),
        "origin_sheet_states": json_safe(case.get("origin_sheet_states", {})),
        "products": json_safe(case.get("products", [])),
        "form_lane": json_safe(context.get("recommended_form_lane", {})),
        "source": {
            "backend": source_context.get("source_backend", ""),
            "summary": json_safe(source_context.get("source_summary", {})),
            "invoice_matches": json_safe(source_context.get("invoice_matches", [])),
            "material_rows": json_safe(source_context.get("material_rows", [])),
            "stock_rows": json_safe(source_context.get("stock_rows", [])),
        },
    }
def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def _supporting_file_view(client_id: str, case_id: str, row: dict) -> dict:
    upload_id = row.get("upload_id") or ""
    return {
        "upload_id": upload_id,
        "slot": row.get("slot") or "other",
        "name": row.get("original_filename") or row.get("filename") or "supporting-file",
        "size_bytes": row.get("size_bytes") or 0,
        "file_ext": (row.get("file_ext") or "").lstrip("."),
        "mime_type": row.get("mime_type") or "",
        "uploaded_at": row.get("uploaded_at") or "",
        "download_url": f"/clients/{client_id}/co-case/{case_id}/supporting-files/{upload_id}",
    }


@router.post("/clients/{client_id}/co-case/{case_id}/supporting-files")
async def upload_co_case_supporting_file(
    request: Request,
    client_id: str,
    case_id: str,
    file: UploadFile = File(...),
    document_slot: str = Form("other"),
    invoice_no: str = Form(""),
    bill_of_lading_no: str = Form(""),
):
    client = resolve_client(client_id)
    # save_supporting_file bypasses update_case_record's close-state gate;
    # check it explicitly here so closed cases also reject uploads.
    record = get_case_record(client, case_id)
    if record and co_case_is_completed(record):
        message = "Hồ sơ đã đóng — bấm 'Mở lại hồ sơ' ở tab Review & Xuất trước khi upload chứng từ."
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": message}, status_code=409)
        raise HTTPException(status_code=409, detail=message)
    content = await file.read(MAX_SUPPORTING_FILE_BYTES + 1)
    try:
        saved = save_supporting_file(
            client,
            case_id,
            content,
            file.filename or "supporting-file",
            document_slot,
            invoice_no,
            bill_of_lading_no,
        )
    except ValueError as exc:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=400,
            context=co_case_context(client_id, case_id, "documents", error=str(exc)),
        )
    if _wants_json(request):
        return JSONResponse({"ok": True, "file": _supporting_file_view(client_id, case_id, saved)})
    return RedirectResponse(f"/clients/{client_id}/co-case/{case_id}/documents", status_code=303)
@router.delete("/clients/{client_id}/co-case/{case_id}/supporting-files/{upload_id}")
async def delete_co_case_supporting_file(client_id: str, case_id: str, upload_id: str):
    client = resolve_client(client_id)
    record = get_case_record(client, case_id)
    if record and co_case_is_completed(record):
        raise HTTPException(
            status_code=409,
            detail="Hồ sơ đã đóng — không thể xoá chứng từ.",
        )
    try:
        delete_supporting_file(client, case_id, upload_id)
    except KeyError:
        raise HTTPException(status_code=404) from None
    return JSONResponse({"ok": True})
@router.get("/clients/{client_id}/co-case/{case_id}/supporting-files/{upload_id}")
async def download_co_case_supporting_file(client_id: str, case_id: str, upload_id: str):
    try:
        file_row, path = get_supporting_file(resolve_client(client_id), case_id, upload_id)
    except (KeyError, FileNotFoundError):
        raise HTTPException(status_code=404) from None
    return FileResponse(
        path,
        media_type=file_row.get("mime_type") or file_row.get("content_type") or "application/octet-stream",
        filename=file_row.get("original_filename") or file_row.get("filename") or "supporting-file",
    )
@router.post("/clients/{client_id}/co-case/{case_id}/export")
async def export_co_case_workbook(request: Request, client_id: str, case_id: str):
    content_type = request.headers.get("content-type", "")
    posted_case = None
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await large_request_form(request)
        if form:
            posted_case = update_products_from_form({key: str(value) for key, value in form.items()})
            posted_case["persisted_case_id"] = posted_case.get("persisted_case_id") or case_id
    client = resolve_client(client_id)
    context = co_case_context(
        client_id,
        case_id,
        current_step="origin",
        case=posted_case,
        origin_demo_allowed=False,
    )
    blockers = origin_sheet_export_blockers(context["case"])
    should_enforce_sheet_state = bool(posted_case)
    if should_enforce_sheet_state and blockers:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context={
                **context,
                "error": f"Chưa thể export: bảng kê {', '.join(blockers[:5])} cần tính lại hoặc chốt trước.",
            },
        )
    if context["case"].get("persisted_case_id") and not context.get("origin_demo_active"):
        try:
            update_case_record(client, context["case"])
        except KeyError:
            pass
    content = create_case_workbook(
        context["case"],
        context["form_candidates"],
        context["invoice_matches"],
        context["criteria_rows"],
    )
    filename = safe_filename(f"{context['case']['case_code'] or 'co-case'}-dossier.xlsx")
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
@router.post("/clients/{client_id}/co-case/{case_id}/export-bang-ke")
async def export_co_case_bang_ke_workbook(request: Request, client_id: str, case_id: str):
    content_type = request.headers.get("content-type", "")
    posted_case = None
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await large_request_form(request)
        if form:
            posted_case = update_products_from_form({key: str(value) for key, value in form.items()})
            posted_case["persisted_case_id"] = posted_case.get("persisted_case_id") or case_id
    client = resolve_client(client_id)
    case = posted_case or persisted_origin_case(client, case_id)
    # The form-rebuilt case has empty origin_sheet_states (case_from_form starts
    # with {}). Re-hydrate from the persisted DB row so per-sheet overrides
    # (form / criteria / threshold / currency_mode) AND material_overrides
    # (delete / substitute / norm-edit / added rows) are honored by the
    # renderer. Without this, the export ships every material — including
    # ones the operator deleted via Substitute — and always picks the LVC
    # template because effective_criteria is unresolved.
    if posted_case and case_id:
        try:
            persisted = persisted_origin_case(client, case_id)
        except KeyError:
            persisted = None
        if persisted:
            case["origin_sheet_states"] = persisted.get("origin_sheet_states") or {}
    case = attach_origin_sheet_states(case)
    _hydrate_material_dates_from_stock(case, client)
    _hydrate_product_export_declaration_dates(case, client)
    blockers = origin_sheet_export_blockers(case)
    if blockers:
        raise HTTPException(
            status_code=409,
            detail=f"Chưa thể xuất bảng kê: bảng kê {', '.join(blockers[:5])} cần tính lại hoặc chốt trước.",
        )
    if case.get("persisted_case_id"):
        try:
            update_case_record(client, case)
        except KeyError:
            pass
    content = create_hq_bang_ke_workbook(case)
    filename = safe_filename(f"{case['case_code'] or 'co-case'}-bang-ke-hq.xlsx")
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
@router.post("/clients/{client_id}/co-case/{case_id}/export-dossier-zip")
async def export_co_case_dossier_zip(client_id: str, case_id: str):
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    case = attach_origin_sheet_states(case)
    # Hard gate: case must be closed. Close itself already requires every sheet
    # locked, so this implicitly guarantees the TKN summary is complete (it
    # filters to locked sheets — see case_tkx_tkn_summary). Without this gate
    # an operator could ship a dossier whose TKN list silently omits the
    # declarations referenced by half-finished sheets.
    if not co_case_is_completed(case):
        unlocked = [
            str(p.get("code") or "?")
            for p in case.get("products") or []
            if str(p.get("origin_sheet_status") or "").strip() != "locked"
        ]
        if unlocked:
            detail = (
                f"Còn {len(unlocked)} bảng kê chưa chốt: "
                f"{', '.join(unlocked[:5])}{'…' if len(unlocked) > 5 else ''}. "
                "Chốt hết các bảng kê rồi bấm 'Đóng hồ sơ' trước khi xuất file tổng hợp."
            )
        else:
            detail = "Đóng hồ sơ trước khi xuất file tổng hợp (cần khoá để chốt danh sách TKX/TKN)."
        raise HTTPException(status_code=409, detail=detail)
    # The build (source context + DH merged-PDF render) runs ~45s on a large
    # dossier; do it in a background job instead of blocking the request. The
    # saved zip is keyed to the case content-revision so a later reopen+edit
    # marks it stale (see app/dossier_export_service.py).
    record = get_case_record(client, case_id)
    revision = dossier_content_revision(record)
    filename = safe_filename(f"{case.get('case_code') or 'co-case'}-dossier.zip")
    submit_dossier_export(
        client,
        case_id,
        token=current_data_hub_token(),
        current_revision=revision,
        filename=filename,
        builder=lambda: _build_dossier_zip(client, case),
    )
    return RedirectResponse(
        f"/clients/{client_id}/co-case/{case_id}/review",
        status_code=303,
    )


def _build_dossier_zip(client: dict, case: dict) -> tuple[bytes, list[dict]]:
    """Heavy dossier build — runs in the export worker thread.

    Returns `(zip_bytes, embed_failures)`. `embed_failures` are the directions
    whose merged tờ khai PDF could not be embedded (surfaced as dossier
    warnings)."""
    case_id = case.get("persisted_case_id") or case.get("id") or ""
    source_context = co_case_source_context(client, case)
    stock_rows = source_context.get("stock_rows") or []
    # The heavy recompute derives invoice_matches from a live shipment reference
    # (invoice_no / export_declaration_nos). A closed case whose shipment ref was
    # never set still carries the matches persisted during the origin step, so
    # fall back to those — otherwise the TKX (export) declarations vanish and the
    # dossier ships no export declaration files. Recompute file counts from the
    # matches we actually use so the export TKX resolves.
    invoice_matches = source_context.get("invoice_matches") or case.get("source_invoice_matches") or []
    declaration_file_counts = source_context.get("declaration_file_counts") or {}
    if invoice_matches and not source_context.get("invoice_matches") and hasattr(portfolio_service, "declaration_file_counts"):
        declaration_file_counts = portfolio_service.declaration_file_counts(
            client.get("id", ""), case, invoice_matches
        )
    summary = case_tkx_tkn_summary(
        case,
        invoice_matches,
        stock_rows,
        declaration_file_counts,
    )
    supporting_files: list[dict] = []
    for file_row in case.get("supporting_files", []):
        upload_id = file_row.get("upload_id") or ""
        if not upload_id:
            continue
        try:
            row, path = get_supporting_file(client, case_id, upload_id)
        except (KeyError, FileNotFoundError):
            continue
        supporting_files.append({
            "slot": row.get("slot", "other"),
            "filename": row.get("filename", "supporting.bin"),
            "content": path.read_bytes(),
        })
    declaration_pdfs, declaration_pdf_failures = _try_fetch_declaration_pdfs(client, case, summary)
    content = create_dossier_zip(
        case,
        supporting_files,
        summary,
        data_hub_base_url=data_hub_link_settings().data_hub_base_url,
        declaration_pdfs=declaration_pdfs,
        declaration_pdf_failures=declaration_pdf_failures,
    )
    return content, declaration_pdf_failures


@router.get("/clients/{client_id}/co-case/{case_id}/export-dossier-zip/status", response_class=HTMLResponse)
async def export_co_case_dossier_zip_status(request: Request, client_id: str, case_id: str):
    """htmx poll target for the review page — current export job state."""
    client = resolve_client(client_id)
    try:
        record = get_case_record(client, case_id)
    except KeyError:
        raise HTTPException(status_code=404) from None
    export = dossier_export_status(client, case_id, current_revision=dossier_content_revision(record))
    return templates.TemplateResponse(
        request=request,
        name="_dossier_export_status.html",
        context={"client": client, "case_id": case_id, "export": export},
    )


@router.get("/clients/{client_id}/co-case/{case_id}/export-dossier-zip/download")
async def download_co_case_dossier_zip(client_id: str, case_id: str):
    client = resolve_client(client_id)
    try:
        record = get_case_record(client, case_id)
    except KeyError:
        raise HTTPException(status_code=404) from None
    export = dossier_export_status(client, case_id, current_revision=dossier_content_revision(record))
    if not export.get("can_download"):
        # Stale (case changed) or not finished — don't hand back an outdated zip.
        raise HTTPException(
            status_code=409,
            detail="File hồ sơ chưa sẵn sàng hoặc đã lỗi thời — bấm 'Xuất hồ sơ' để tạo lại.",
        )
    result = dossier_export_result_path(client, case_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy file hồ sơ đã xuất.")
    path, filename = result
    return FileResponse(
        path,
        media_type="application/zip",
        filename=filename,
    )


def _try_fetch_declaration_pdfs(
    client: dict, case: dict, tkx_tkn_summary: dict
) -> tuple[dict[str, bytes], list[dict]]:
    """Fetch the merged TKX/TKN declaration PDFs from Data Hub and key them for
    the dossier ("tờ khai ghép").

    Contract: `.ai/api-requests/2026-06-05-declarations-merged-pdf.md`. Each
    direction's declarations are rendered to the official tờ khai layout and
    concatenated into one PDF. A direction whose merged PDF includes zero real
    files is skipped — its absence is already reported in MANIFEST.md.

    Returns `(pdfs, failures)`:
    - `pdfs` is keyed by the filename written under `03-to-khai/`, matching the
      ZIP/bảng-kê naming: `{case_code}-to-khai-xuat.pdf` / `…-to-khai-nhap.pdf`.
    - `failures` lists directions that *had* declarations to embed but whose
      fetch raised (e.g. a render timeout on a large import dossier). The dossier
      surfaces these in README/MANIFEST instead of silently shipping an
      incomplete bundle.
    """
    data_hub = getattr(portfolio_service, "data_hub", None)
    if data_hub is None or not hasattr(data_hub, "download_declarations_pdf"):
        return {}, []
    case_code = (case.get("case_code") or "co-case").strip() or "co-case"
    pdfs: dict[str, bytes] = {}
    failures: list[dict] = []
    # Per-client max size (MB) per merged tờ-khai PDF part → DH splits the import
    # PDF so each part fits the old Ecosys upload limit. CO-side export override
    # on the client (editable even in DH source-mode). Default 2 MB.
    try:
        _mb = float((client.get("export_overrides") or {}).get("tkn_pdf_max_part_mb", 2) or 2)
    except (TypeError, ValueError):
        _mb = 2.0
    max_part_bytes = int(_mb * 1_000_000) if _mb > 0 else None

    def _fetch(direction: str, entries: list[dict], label: str, vi_slug: str) -> None:
        nos = sorted({
            str(entry.get("declaration_no") or "").strip()
            for entry in (entries or [])
            if str(entry.get("declaration_no") or "").strip()
        })
        if not nos:
            return
        filename = safe_filename(f"{case_code}-to-khai-{vi_slug}.pdf")
        try:
            result = data_hub.download_declarations_pdf(
                client["id"], direction=direction, declaration_nos=nos, filename=filename,
                max_part_bytes=max_part_bytes,
            )
        except Exception:  # noqa: BLE001 — record the gap; don't silently drop it
            failures.append({
                "label": label,
                "filename": filename,
                "declaration_count": len(nos),
            })
            return
        # Back-compat: a bare-bytes return (older adapter) embeds as one file.
        if not isinstance(result, dict):
            if isinstance(result, (bytes, bytearray)) and result:
                pdfs[filename] = bytes(result)
            return
        # Skip the info-only PDF Data Hub returns when no declaration has a file.
        if result.get("included") == 0:
            return
        parts = result.get("parts") or []
        if not parts and result.get("content"):
            parts = [{"name": filename, "content": result["content"]}]
        usable = [p for p in parts if isinstance(p.get("content"), (bytes, bytearray)) and p.get("content")]
        if not usable:
            return
        if len(usable) == 1:
            # Single PDF (under the size cap) → the usual numbered slot.
            pdfs[filename] = bytes(usable[0]["content"])
        else:
            # Size-bounded split → one file per part, each ≤ the per-client cap.
            for index, part in enumerate(usable, start=1):
                part_name = safe_filename(f"{case_code}-to-khai-{vi_slug}-part-{index:03d}.pdf")
                pdfs[part_name] = bytes(part["content"])

    _fetch("export", tkx_tkn_summary.get("tkx") or [], "TKX", "xuat")
    _fetch("import", tkx_tkn_summary.get("tkn") or [], "TKN", "nhap")
    return pdfs, failures
@router.post("/clients/{client_id}/co-case/{case_id}/close")
async def close_co_case(request: Request, client_id: str, case_id: str):
    """Mark the case as completed. Pre-conditions:

    - Every product's origin sheet must be in `locked` status. A case with
      a half-finished bảng kê isn't ready to be filed; we refuse rather
      than silently freezing edits on top of incomplete data.
    - The case must currently be open. (Re-closing a closed case is a
      no-op; the route is idempotent in spirit, but `update_case_record`
      treats it as a normal mutation, so no-op early.)

    After close: every mutating endpoint refuses via CaseClosedError.
    Also releases any origin-calculation lock the case holds."""
    client = resolve_client(client_id)
    try:
        record = get_case_record(client, case_id)
    except KeyError:
        raise HTTPException(status_code=404) from None
    if record is None:
        raise HTTPException(status_code=404)
    case = case_from_record(default_client_case(client), client, record)
    # Idempotent: re-clicking close on a closed case redirects without write.
    if co_case_is_completed(case):
        return RedirectResponse(
            f"/clients/{client_id}/co-case/{case_id}/review",
            status_code=303,
        )
    case = attach_origin_sheet_states(case)
    products = case.get("products") or []
    if not products:
        raise HTTPException(
            status_code=409,
            detail="Chưa có bảng kê nào — không thể đóng hồ sơ rỗng.",
        )
    unlocked = [
        p.get("code") or "?"
        for p in products
        if str(p.get("origin_sheet_status") or "").strip() != "locked"
    ]
    if unlocked:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Còn {len(unlocked)} bảng kê chưa chốt: "
                f"{', '.join(unlocked[:5])}{'…' if len(unlocked) > 5 else ''}. "
                "Chốt tất cả ở tab Bảng kê C/O trước khi đóng hồ sơ."
            ),
        )
    try:
        update_case_record(client, {"id": case_id, "persisted_case_id": case_id, "status": "completed"})
    except KeyError:
        raise HTTPException(status_code=404) from None
    return RedirectResponse(
        f"/clients/{client_id}/co-case/{case_id}/review",
        status_code=303,
    )
@router.post("/clients/{client_id}/co-case/{case_id}/reopen-case")
async def reopen_co_case(request: Request, client_id: str, case_id: str):
    """Re-open a completed case for further edits."""
    client = resolve_client(client_id)
    try:
        update_case_record(client, {"id": case_id, "persisted_case_id": case_id, "status": "open"})
    except KeyError:
        raise HTTPException(status_code=404) from None
    return RedirectResponse(
        f"/clients/{client_id}/co-case/{case_id}/review",
        status_code=303,
    )
@router.post("/clients/{client_id}/co-case/{case_id}/origin/save")
async def save_co_case_origin(request: Request, client_id: str, case_id: str):
    client = resolve_client(client_id)
    case, payload = await origin_case_from_request(request, client, case_id)
    try:
        stale_from_index = int(str(payload.get("stale_from_index", "0") or "0"))
    except ValueError:
        stale_from_index = 0
    if payload.get("mark_stale", True):
        case = mark_origin_sheets_stale(case, stale_from_index)
    else:
        case = attach_origin_sheet_states(case)
    try:
        update_case_record(client, case)
    except KeyError:
        raise HTTPException(status_code=404) from None
    return {
        "status": "ok",
        "revision": origin_case_revision(case),
        "stale_from_index": stale_from_index,
        "origin_product_order": origin_product_order(case),
        "origin_sheet_states": json_safe(case.get("origin_sheet_states", {})),
    }
@router.post("/clients/{client_id}/co-case/{case_id}/origin/autosave")
async def autosave_co_case_origin(request: Request, client_id: str, case_id: str):
    client = resolve_client(client_id)
    case, payload = await origin_case_from_request(request, client, case_id)
    try:
        stale_from_index = int(str(payload.get("stale_from_index", "0") or "0"))
    except ValueError:
        stale_from_index = 0
    case = mark_origin_sheets_stale(case, stale_from_index)
    try:
        update_case_record(client, case)
    except KeyError:
        raise HTTPException(status_code=404) from None
    return {
        "status": "ok",
        "revision": origin_case_revision(case),
        "stale_from_index": stale_from_index,
        "origin_product_order": origin_product_order(case),
        "origin_sheet_states": json_safe(case.get("origin_sheet_states", {})),
    }
@router.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/load-bom", response_class=HTMLResponse)
async def load_bom_co_case_origin_sheet(request: Request, client_id: str, case_id: str, product_code: str):
    """Nạp công thức BOM (CẤU TRÚC) vào bảng kê mà KHÔNG phân bổ tồn (Phase 2).

    Khác `/calculate`: không refresh/đọc tồn (nhanh), không phân bổ, không
    cascade-stale các sheet sau. Khai triển NVL để xem/sửa trước khi "Tính bảng
    kê". status → `bom_loaded`. Nạp lại = reset về BOM artifact ⇒ bỏ override cũ.
    """
    client = resolve_client(client_id)
    case, _payload = await origin_case_from_request(request, client, case_id)
    try:
        persisted = get_case_record(client, case_id)
        if persisted.get("origin_sheet_states"):
            case["origin_sheet_states"] = dict(persisted.get("origin_sheet_states") or {})
    except KeyError:
        pass
    target_state = (case.get("origin_sheet_states") or {}).get(product_code) or {}
    if str(target_state.get("status") or "").strip() == "locked":
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(
                client_id,
                case_id,
                current_step="origin",
                case=case,
                error=f"Bảng kê {product_code} đã chốt; mở chốt trước khi nạp lại BOM.",
                preserve_origin_products=True,
                fast_origin_context=True,
            ),
        )
    context = co_case_context(
        client_id,
        case_id,
        current_step="origin",
        case=case,
        message=f"Đã nạp BOM (cấu trúc) vào bảng kê {product_code}; bấm Tính bảng kê để phân bổ tồn.",
        preserve_origin_products=True,
        cached_case_context=True,
    )
    source_context = context.get("origin_source_context", {})
    try:
        client_config_for_rule = (
            portfolio_service.get_client_config(client)
            if hasattr(portfolio_service, "get_client_config") else {}
        )
    except Exception:  # noqa: BLE001
        client_config_for_rule = {}
    min_gap_days = effective_min_gap_days(client, client_config_for_rule)
    context["case"] = prepare_case_origin_sheet(
        context["case"],
        product_code,
        source_context.get("invoice_matches", []),
        context.get("bom_workspace", minimal_bom_workspace()),
        context.get("recommended_form_lane", {}),
        source_context.get("material_rows", []),
        [],  # stock_rows — Load BOM không đụng tồn
        min_gap_days=min_gap_days,
        allocate=False,
    )
    context["case"] = attach_case_bom_snapshot(context["case"], context.get("bom_workspace", minimal_bom_workspace()))
    context["case"] = attach_origin_bom_product_codes(
        context["case"],
        context.get("bom_workspace", minimal_bom_workspace()),
    )
    context["case"] = attach_origin_readiness(context["case"])
    context["case"] = attach_results(context["case"])
    context["case"] = attach_origin_sheet_states(context["case"])
    # Nạp lại cấu trúc = reset về BOM artifact ⇒ bỏ chỉnh sửa client-side cũ (override).
    states = dict(context["case"].get("origin_sheet_states") or {})
    previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
    if previous.get("material_overrides"):
        states[product_code] = {**previous, "material_overrides": {}}
        context["case"]["origin_sheet_states"] = states
    context["case"] = set_origin_sheet_status(context["case"], product_code, "bom_loaded")
    context["criteria_rows"] = build_case_criteria_rows(context["case"], context.get("form_candidates", []))
    if context["case"].get("persisted_case_id") and not context.get("origin_demo_active"):
        update_case_record(client, context["case"])
    return templates.TemplateResponse(request=request, name="co_case.html", context=context)
@router.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/calculate", response_class=HTMLResponse)
async def calculate_co_case_origin_sheet(request: Request, client_id: str, case_id: str, product_code: str):
    client = resolve_client(client_id)
    case, _payload = await origin_case_from_request(request, client, case_id)
    try:
        persisted = get_case_record(client, case_id)
        if persisted.get("origin_sheet_states"):
            case["origin_sheet_states"] = dict(persisted.get("origin_sheet_states") or {})
    except KeyError:
        pass
    action_error = origin_sheet_action_error(case, product_code, "calculate")
    if action_error:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(
                client_id,
                case_id,
                current_step="origin",
                case=case,
                error=action_error,
                preserve_origin_products=True,
                fast_origin_context=True,
            ),
        )
    # Fast path: delta-refresh the materialized stock snapshot (1-2s when
    # the upstream BCCT is quiet, vs 30-45s for a full DH pull every time)
    # and read stock rows from co_stock_rows directly. invoice_matches +
    # material_rows are pulled through the cached snapshot the shipment
    # step already populated. Falls back to the legacy full-pull path when
    # the snapshot is empty (fresh client) or delta refresh errored, so we
    # never silently calculate against stale data.
    snapshot_stock_rows = _calculate_stock_rows_from_snapshot(client)
    if snapshot_stock_rows is not None:
        context = co_case_context(
            client_id,
            case_id,
            current_step="origin",
            case=case,
            message=f"Đã tính bảng kê {product_code}.",
            preserve_origin_products=True,
            cached_case_context=True,
        )
        source_context = context.get("origin_source_context", {})
        stock_rows = snapshot_stock_rows
    else:
        context = co_case_context(
            client_id,
            case_id,
            current_step="origin",
            case=case,
            message=f"Đã tính bảng kê {product_code}.",
            preserve_origin_products=True,
            force_source_refresh=True,
        )
        source_context = context.get("origin_source_context", {})
        stock_rows = source_context.get("stock_rows", [])
    try:
        client_config_for_rule = (
            portfolio_service.get_client_config(client)
            if hasattr(portfolio_service, "get_client_config") else {}
        )
    except Exception:  # noqa: BLE001
        client_config_for_rule = {}
    min_gap_days = effective_min_gap_days(client, client_config_for_rule)
    target_overrides = (
        (context["case"].get("origin_sheet_states") or {}).get(product_code) or {}
    ).get("material_overrides")
    if target_overrides:
        # DU1 — GIỮ chỉnh sửa NVL: tính lại từ override (như đường "Lưu") thay vì
        # khai triển tươi từ BOM artifact (sẽ vứt chỉnh sửa). Hỗ trợ luồng
        # Load BOM → sửa NVL → Tính bảng kê.
        context["case"] = recalculate_origin_sheet_edits(
            client, context["case"], product_code, min_gap_days=min_gap_days
        )
    else:
        context["case"] = prepare_case_origin_sheet(
            context["case"],
            product_code,
            source_context.get("invoice_matches", []),
            context.get("bom_workspace", minimal_bom_workspace()),
            context.get("recommended_form_lane", {}),
            source_context.get("material_rows", []),
            stock_rows,
            min_gap_days=min_gap_days,
        )
    context["case"] = attach_case_bom_snapshot(context["case"], context.get("bom_workspace", minimal_bom_workspace()))
    context["case"] = attach_origin_bom_product_codes(
        context["case"],
        context.get("bom_workspace", minimal_bom_workspace()),
    )
    context["case"] = attach_origin_readiness(context["case"])
    context["case"] = attach_results(context["case"])
    context["case"] = attach_origin_sheet_states(context["case"])
    context["case"] = set_origin_sheet_status(context["case"], product_code, "calculated")
    target_index = next(
        (
            index
            for index, product in enumerate(context["case"].get("products", []))
            if str(product.get("code") or "").strip() == product_code
        ),
        -1,
    )
    if target_index >= 0:
        context["case"] = mark_origin_sheets_stale(context["case"], target_index + 1)
        context["case"] = set_origin_sheet_status(context["case"], product_code, "calculated")
    context["criteria_rows"] = build_case_criteria_rows(context["case"], context.get("form_candidates", []))
    if context["case"].get("persisted_case_id") and not context.get("origin_demo_active"):
        update_case_record(client, context["case"])
    return templates.TemplateResponse(request=request, name="co_case.html", context=context)
@router.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/lock", response_class=HTMLResponse)
async def lock_co_case_origin_sheet(request: Request, client_id: str, case_id: str, product_code: str):
    client = resolve_client(client_id)
    case, _payload = await origin_case_from_request(request, client, case_id)
    action_error = origin_sheet_action_error(case, product_code, "lock")
    if action_error:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(
                client_id,
                case_id,
                current_step="origin",
                case=case,
                error=action_error,
                preserve_origin_products=True,
                fast_origin_context=True,
            ),
        )
    # Capture allocations from the PERSISTED case BEFORE update_case_record
    # rewrites the disk record. The form-rebuilt `case` may have stripped
    # materials/allocation_lines if the AJAX submitter only sent metadata.
    # The ledger writes claims in a single transaction with an availability
    # pre-check; on any failure we must NOT update case state, otherwise the
    # sheet appears locked while no claim was recorded (the ghost-claim bug
    # this code path used to suffer from silent exception swallowing).
    try:
        record_sheet_lock_claims(client_id, case_id, product_code, case)
    except co_stock_ledger.StockOverclaimError as exc:
        detail_lines = [
            f"{v['source_row']}: cần {v['claimed']}, còn {v['available']}"
            f" (gốc {v['bcct_remaining']} - case khác {v['other_claims']})"
            for v in exc.violations[:5]
        ]
        message = (
            f"Không chốt được bảng kê {product_code} vì vượt tồn ở "
            f"{len(exc.violations)} lot: " + "; ".join(detail_lines)
            + ". Hãy tính lại bảng kê để cập nhật phân bổ theo tồn hiện tại."
        )
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(
                client_id,
                case_id,
                current_step="origin",
                case=case,
                error=message,
                preserve_origin_products=True,
                fast_origin_context=True,
            ),
        )
    case = set_origin_sheet_status(case, product_code, "locked")
    update_case_record(client, case)
    invalidate_co_case_source_cache(client_id, case_id)
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(
            client_id,
            case_id,
            current_step="origin",
            case=case,
            message=f"Đã chốt bảng kê {product_code}.",
            preserve_origin_products=True,
            fast_origin_context=True,
        ),
    )
@router.get("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/substitute-candidates")
async def co_case_origin_sheet_substitute_candidates(
    client_id: str,
    case_id: str,
    product_code: str,
    material_code: str = "",
    row_index: int = -1,
    search: str = "",
    seed_hs: str = "",
    limit: int = 20,
):
    if not material_code and not search:
        raise HTTPException(status_code=400, detail="material_code or search query required")
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    target = next((p for p in case.get("products", []) if str(p.get("code") or "").strip() == product_code), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Sheet {product_code} not found in case")
    sheet_state = (case.get("origin_sheet_states") or {}).get(product_code, {}) or {}
    optimization_mode = sheet_state.get("optimization_mode") or "max_lvc"

    # Empty stock summary placeholder. Stock data is fetched lazily by a
    # separate /substitute-stock endpoint so the recommendation list can
    # render in ~300ms (one Data Hub call) instead of waiting for full
    # BCCT pagination (~30s for Johnson). JS merges stock async.
    def empty_stock_summary() -> dict:
        return {
            "lot_count": 0,
            "usable_lot_count": 0,
            "total_remaining_qty": "0",
            "unit_price_min": "",
            "unit_price_max": "",
            "lots": [],
            "pending": True,
        }

    candidates: list[dict] = []
    error_detail = ""
    candidates_source = "data_hub"
    if material_code:
        try:
            raw, source = portfolio_service.list_material_substitutes(
                client_id, material_code, min_score=0.5, limit=min(limit, 50)
            )
        except Exception as exc:  # noqa: BLE001
            raw, source = [], "error"
            error_detail = str(exc)
        candidates_source = source
        for row in raw:
            code = str(row.get("material_b_code") or row.get("material_code") or "").strip()
            if not code:
                continue
            candidates.append({
                "material_code": code,
                "name": row.get("name", ""),
                "category": row.get("category", ""),
                "hs_code": row.get("hs_code", ""),
                "score": float(row.get("combined_score") or row.get("score") or 0.0),
                "raw_scores": row.get("raw_scores") or {},
                "sources": row.get("sources") or [],
                "confirmed": bool(row.get("confirmed")),
                "stock": empty_stock_summary(),
                "kind": "recommended",
            })
        # Heuristic fallback ONLY when Data Hub had nothing: this still needs
        # the materials catalog (one Data Hub list_materials pagination, but
        # cached). Caller can opt out via ?skip_heuristic=1 to keep first call
        # fast even on substitutes-empty.
        if not candidates:
            try:
                cached_ctx = co_case_source_context_cached(client, case)
                material_rows = cached_ctx.get("material_rows") or []
            except Exception:  # noqa: BLE001
                material_rows = []
            heuristic, hs_seed = compute_substitute_heuristic_candidates(
                client_id, material_code, material_rows, lambda _code: empty_stock_summary(),
                fallback_hs=seed_hs,
            )
            candidates_source = "co_heuristic"
            if source == "data_hub_unauthorized":
                error_detail = (
                    "Data Hub trả 401/403 (token thiếu scope hub:read?) — fallback HS-prefix "
                    f"heuristic từ {len(material_rows)} NVL trong catalog."
                )
            else:
                error_detail = (
                    f"Data Hub không có substitute precomputed cho {material_code or '(no code)'}. "
                    f"Fallback heuristic theo HS={hs_seed or 'n/a'} — {len(heuristic)} ứng viên."
                )
            candidates = heuristic
            candidates.sort(key=lambda item: -item.get("score", 0.0))

    search_results: list[dict] = []
    if search:
        raw_search: list[dict] = []
        search_error = ""
        try:
            raw_search = portfolio_service.search_materials(client_id, search, limit=min(limit, 50))
        except Exception as exc:  # noqa: BLE001
            search_error = str(exc)
        fallback_rows = search_case_material_rows(case, search, limit=min(limit, 50))
        seen_search_codes: set[str] = set()
        for row in [*raw_search, *fallback_rows]:
            code = str(row.get("material_code") or row.get("internal_code") or "").strip()
            if not code or code in seen_search_codes:
                continue
            seen_search_codes.add(code)
            search_results.append({
                "material_code": code,
                "name": row.get("name") or row.get("material_description") or "",
                "category": row.get("category", ""),
                "hs_code": row.get("hs_code", ""),
                "score": 0.0,
                "stock": empty_stock_summary(),
                "kind": "search",
            })
            if len(search_results) >= max(1, min(limit, 50)):
                break
        if not raw_search and fallback_rows and not error_detail:
            error_detail = (
                "Data Hub material catalog search unavailable or empty; showing matching NVL "
                "already present in this dossier."
            )
        elif search_error and not error_detail:
            error_detail = search_error

    # Initial sort by score only — re-sorted client-side once stock arrives.
    candidates.sort(key=lambda item: -item.get("score", 0.0))
    return JSONResponse({
        "ok": True,
        "product_code": product_code,
        "material_code": material_code,
        "row_index": row_index,
        "optimization_mode": optimization_mode,
        "candidates": candidates,
        "candidates_source": candidates_source,
        "search_results": search_results,
        "stock_pending": True,
        "stock_url": (
            f"/clients/{client_id}/co-case/{case_id}/origin/sheet/{quote(product_code, safe='')}/substitute-stock"
        ),
        "error": error_detail,
    })
def search_case_material_rows(case: dict, query: str, limit: int = 20) -> list[dict]:
    if not (query or "").strip():
        return []
    max_rows = max(1, min(limit, 100))
    scored: list[tuple[float, int, dict]] = []
    seen: set[str] = set()
    position = 0
    for product in case.get("products", []) or []:
        for material in product.get("materials", []) or []:
            code = str(
                material.get("material_code")
                or material.get("internal_material_code")
                or material.get("internal_code")
                or ""
            ).strip()
            if not code or code in seen:
                continue
            score = material_search.match_score(query, [
                code,
                material.get("internal_code"),
                material.get("internal_material_code"),
                material.get("material_description"),
                material.get("name"),
                material.get("hs_code") or material.get("import_hs"),
            ])
            if score is None:
                continue
            seen.add(code)
            scored.append((score, position, {
                "material_code": code,
                "internal_code": material.get("internal_code") or material.get("internal_material_code") or code,
                "name": material.get("name") or material.get("material_description") or "",
                "material_description": material.get("material_description") or material.get("name") or "",
                "category": material.get("category", ""),
                "hs_code": material.get("hs_code") or material.get("import_hs") or "",
            }))
            position += 1
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [row for _, _, row in scored[:max_rows]]
@router.get("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/substitute-stock")
async def co_case_origin_sheet_substitute_stock(
    client_id: str,
    case_id: str,
    product_code: str,
    codes: str = "",
):
    """Lazy stock-summary endpoint. Returns stock pool entries for the given
    comma-separated material codes. Prefers Data Hub `bcct/by-codes` for a
    narrow lookup (~500ms); falls back to TTL-cached source_context for the
    file-based service.
    """
    requested = [code.strip() for code in (codes or "").split(",") if code.strip()]
    if not requested:
        return JSONResponse({"ok": True, "stock": {}})
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    sheet_state = (case.get("origin_sheet_states") or {}).get(product_code, {}) or {}
    optimization_mode = sheet_state.get("optimization_mode") or "max_lvc"
    cached_matches = case.get("source_invoice_matches") if isinstance(case.get("source_invoice_matches"), list) else []
    client_config = portfolio_service.get_client_config(client) if hasattr(portfolio_service, "get_client_config") else {}
    min_gap = effective_min_gap_days(client, client_config)
    # Substitute feasibility only needs CO stock (tồn) lots per candidate, not
    # raw BCCT — read solely from the materialized CO-stock snapshot. This is
    # the single source of truth: a flaky Data Hub BCCT call can never blank
    # out the suggestions, and we never silently fall back to file-store or a
    # heavy live DH pull (consistent with the no-silent-local-fallback rule).
    # A candidate code absent from the snapshot simply has no tồn. The snapshot
    # may lag BCCT; the response carries `stock_refreshed_at` so the modal shows
    # how fresh the tồn is (empty when the client has never been materialized).
    requested_set = set(requested)
    snapshot_rows = co_stock_materializer.read_co_stock_rows_cached(client_id)
    candidate_rows = [
        row for row in snapshot_rows
        if any(key in requested_set for key in co_stock_key_candidates(row))
    ]
    stock_pool = case_allocation_pool(case, cached_matches, candidate_rows, min_gap_days=min_gap)
    out: dict[str, dict] = {}
    for code in requested:
        lots = stock_pool.get(code, [])
        usable = [lot for lot in lots if co_stock_is_usable(lot)]
        total_remaining = sum(decimal_value(lot.get("remaining_qty") or lot.get("available_qty") or "0") for lot in lots)
        prices = []
        for lot in lots:
            price = decimal_value(lot.get("unit_value") or lot.get("unit_price") or "0")
            if price > 0:
                prices.append(price)
        unit_price_min = min(prices) if prices else None
        unit_price_max = max(prices) if prices else None
        out[code] = {
            "lot_count": len(lots),
            "usable_lot_count": len(usable),
            "total_remaining_qty": str(total_remaining),
            "unit_price_min": str(unit_price_min) if unit_price_min is not None else "",
            "unit_price_max": str(unit_price_max) if unit_price_max is not None else "",
            "lots": [
                {
                    "source_row": lot.get("source_row", ""),
                    "import_declaration_no": lot.get("import_declaration_no", ""),
                    "line_no": lot.get("line_no", ""),
                    "registration_date": str(lot.get("registration_date") or lot.get("declaration_date") or ""),
                    "remaining_qty": str(lot.get("remaining_qty") or lot.get("available_qty") or "0"),
                    "available_qty": str(lot.get("available_qty") or lot.get("remaining_qty") or "0"),
                    "unit_value": str(lot.get("unit_value") or lot.get("unit_price") or ""),
                    "currency": lot.get("currency", ""),
                    "material_description": lot.get("material_description", ""),
                    "hs_code": lot.get("hs_code", ""),
                    "uom": lot.get("uom", ""),
                    "allocation_code": lot.get("allocation_code", ""),
                    "eligibility_ok": bool(lot.get("_eligibility_ok", True)),
                    "eligibility_reason": str(lot.get("_eligibility_reason", "ok")),
                    "eligibility_label": co_stock_eligibility.REJECTION_LABELS.get(
                        str(lot.get("_eligibility_reason", "ok")), ""
                    ),
                }
                for lot in lots[:50]
            ],
        }
    return JSONResponse({
        "ok": True,
        "optimization_mode": optimization_mode,
        "stock": out,
        "stock_refreshed_at": co_stock_materializer.last_refresh_at(client_id),
    })
def compute_substitute_heuristic_candidates(
    client_id: str,
    seed_material_code: str,
    material_rows: list[dict],
    stock_summary,
    *,
    fallback_hs: str = "",
) -> tuple[list[dict], str]:
    """HS-prefix heuristic fallback when Data Hub substitutes endpoint returns nothing.

    Score = 0.5 base for sharing the 4-digit HS prefix, +0.2 for sharing 6-digit,
    +0.2 if the candidate has any usable CO stock lot. Tagged with source="co_heuristic"
    so the UI shows the explanation banner.

    `fallback_hs` is used when the seed material is not in Data Hub catalog (common
    when BOM uses an internal code that hasn't been catalog-resolved). Pass the
    BOM row's HS code so heuristic still has a search seed.
    """
    seed = next(
        (row for row in material_rows if str(row.get("material_code") or "").strip() == seed_material_code),
        None,
    )
    if not seed:
        try:
            seed = portfolio_service.get_material(client_id, seed_material_code)
        except Exception:  # noqa: BLE001
            seed = {}
    seed_hs = re.sub(r"\D+", "", str(seed.get("hs_code") or fallback_hs or ""))[:6]
    if not seed_hs:
        return [], ""
    seed_category = str(seed.get("category") or "").strip().lower()
    output: list[dict] = []
    for row in material_rows:
        code = str(row.get("material_code") or "").strip()
        if not code or code == seed_material_code:
            continue
        candidate_hs = re.sub(r"\D+", "", str(row.get("hs_code") or ""))[:6]
        if not candidate_hs or candidate_hs[:4] != seed_hs[:4]:
            continue
        if seed_category and str(row.get("category") or "").strip().lower() not in {seed_category, ""}:
            continue
        score = 0.5
        if candidate_hs[:6] == seed_hs[:6]:
            score = 0.7
        stock = stock_summary(code)
        if stock.get("usable_lot_count", 0) > 0:
            score += 0.2
        output.append({
            "material_code": code,
            "name": row.get("name", ""),
            "category": row.get("category", ""),
            "hs_code": row.get("hs_code", ""),
            "score": round(score, 4),
            "raw_scores": {"hs_prefix": score},
            "sources": ["co_heuristic_hs_prefix"],
            "confirmed": False,
            "stock": stock,
            "kind": "heuristic",
        })
    return output[:30], seed_hs
@router.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/substitute-row")
async def co_case_origin_sheet_substitute_row(
    request: Request, client_id: str, case_id: str, product_code: str
):
    payload: dict = {}
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
    else:
        form = await large_request_form(request)
        payload = {key: str(value) for key, value in form.items()}
    row_index = payload.get("row_index")
    new_material_code = str(payload.get("new_material_code") or "").strip()
    new_norm = str(payload.get("new_norm_per_unit") or "").strip()
    new_name = str(payload.get("new_name") or "").strip()
    delete = bool(payload.get("delete"))
    if row_index is None or str(row_index).strip() == "":
        raise HTTPException(status_code=400, detail="row_index required")
    raw_key = str(row_index).strip()
    is_added_key = raw_key.startswith("added_")
    if is_added_key:
        key = raw_key
        row_index_int = -1
    else:
        try:
            row_index_int = int(raw_key)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="row_index must be integer or added_<n>") from exc
        key = str(row_index_int)
    if not delete and not new_material_code:
        raise HTTPException(status_code=400, detail="new_material_code required when not deleting")
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    products = case.get("products", [])
    target_index = next(
        (i for i, p in enumerate(products) if str(p.get("code") or "").strip() == product_code),
        None,
    )
    if target_index is None:
        raise HTTPException(status_code=404, detail=f"Sheet {product_code} not found in case")
    reject_if_sheet_locked(case, product_code)
    states = dict(case.get("origin_sheet_states") or {})
    previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
    overrides = dict(previous.get("material_overrides") or {})
    if delete:
        if is_added_key:
            # added rows aren't part of product.materials; "deletion" = drop the override
            # so the row disappears completely from both UI and export.
            overrides.pop(key, None)
        else:
            overrides[key] = {"deleted": True}
    elif is_added_key:
        existing = overrides.get(key) if isinstance(overrides.get(key), dict) else {}
        overrides[key] = {
            **existing,
            "added": True,
            "material_code": new_material_code,
            "norm_per_unit": new_norm,
            "name": new_name,
        }
    else:
        overrides[key] = {
            "material_code": new_material_code,
            "norm_per_unit": new_norm,
            "name": new_name,
        }
    states[product_code] = {**previous, "material_overrides": overrides, "status": "stale", "status_label": ORIGIN_SHEET_STATUS_LABELS["stale"]}
    case["origin_sheet_states"] = states
    case = mark_origin_sheets_stale(case, target_index)
    update_case_record(client, case)
    return JSONResponse({
        "ok": True,
        "product_code": product_code,
        "row_index": row_index_int if not is_added_key else key,
        "applied_override": overrides.get(key, {"deleted": True}),
        "sheet_status": "stale",
    })
@router.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/propose-bom")
async def co_case_origin_sheet_propose_bom(
    request: Request, client_id: str, case_id: str, product_code: str
):
    payload = await read_json_or_form(request)
    actor = str(payload.get("actor") or "co_system").strip() or "co_system"
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    target = next((p for p in case.get("products", []) if str(p.get("code") or "").strip() == product_code), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Sheet {product_code} not found in case")
    state = (case.get("origin_sheet_states") or {}).get(product_code, {}) or {}
    if state.get("status") != "locked":
        raise HTTPException(status_code=409, detail="Chỉ propose được BOM mới sau khi đã chốt sheet.")
    overrides = state.get("material_overrides") or {}
    if not overrides:
        raise HTTPException(status_code=409, detail="Không có thay đổi BOM so với artifact gốc; không cần propose.")
    parent_artifact_id = str(target.get("bom_product_artifact_id") or target.get("bom_product_version_id") or "").strip()
    if not parent_artifact_id:
        raise HTTPException(status_code=409, detail="Sheet chưa gắn BOM artifact gốc; không thể propose BOM mới.")
    bom_product_code = str(target.get("bom_product_code") or target.get("code") or "").strip()
    rows = build_bom_proposal_rows(target, overrides)
    if not rows:
        raise HTTPException(status_code=409, detail="Không có dòng NVL nào để propose.")
    try:
        result = portfolio_service.submit_bom_proposal(
            client_id,
            bom_product_code,
            parent_artifact_id=parent_artifact_id,
            rows=rows,
            context={
                "case_id": case_id,
                "case_code": case.get("case_code", ""),
                "sheet_product_code": product_code,
                "diff_summary": {
                    "added": state.get("material_diff_added", 0),
                    "removed": state.get("material_diff_removed", 0),
                    "replaced": state.get("material_diff_replaced", 0),
                    "norm_only": state.get("material_diff_norm_only", 0),
                },
            },
            actor=actor,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Data Hub propose failed: {exc}") from exc
    states = dict(case.get("origin_sheet_states") or {})
    previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
    states[product_code] = {
        **previous,
        "proposed_artifact_id": str(result.get("artifact_id") or result.get("proposal_id") or ""),
        "proposed_proposal_id": str(result.get("proposal_id") or ""),
        "proposed_status": str(result.get("status") or "submitted"),
    }
    case["origin_sheet_states"] = states
    update_case_record(client, case)
    return JSONResponse({
        "ok": True, "product_code": product_code,
        "proposal": {
            "artifact_id": result.get("artifact_id"),
            "proposal_id": result.get("proposal_id"),
            "status": result.get("status"),
        },
    })
def build_bom_proposal_rows(product: dict, overrides: dict) -> list[dict]:
    """Shape rows for the Data Hub BOM proposal submission.

    Field names match Data Hub's BOM row contract: qty_per_unit + uom are
    typed columns; everything else lands in the row payload jsonb. CO-internal
    overrides store the qty under `norm_per_unit` (operator-facing "định mức")
    — translate that to `qty_per_unit` at the boundary, never inside DH's
    payload. Sending `norm_per_unit` makes DH read qty as 0, which auto-rejects
    every proposal via `qty_delta_exceeds_tolerance` and leaves the qty cell
    blank in the reviewer UI.
    """
    materials = product.get("materials") or []
    output: list[dict] = []
    for index, material in enumerate(materials):
        override = overrides.get(str(index)) if isinstance(overrides.get(str(index)), dict) else {}
        if override.get("deleted") or material.get("deleted"):
            continue
        material_code = override.get("material_code") or material.get("material_code") or material.get("internal_material_code")
        qty = override.get("norm_per_unit") or material.get("bom_qty_per") or "0"
        output.append({
            "material_code": str(material_code or "").strip(),
            "qty_per_unit": str(qty),
            "scrap_rate": str(material.get("bom_scrap_rate") or "0"),
            "uom": str(material.get("uom") or override.get("uom") or ""),
            "name": str(override.get("name") or material.get("material_description") or ""),
            "hs_code": str(material.get("hs_code") or override.get("hs_code") or ""),
            "source_row_index": index,
        })
    for key, value in overrides.items():
        if not key.startswith("added_") or not isinstance(value, dict):
            continue
        output.append({
            "material_code": str(value.get("material_code") or "").strip(),
            "qty_per_unit": str(value.get("norm_per_unit") or "0"),
            "scrap_rate": "0",
            "uom": str(value.get("uom") or ""),
            "name": str(value.get("name") or ""),
            "hs_code": str(value.get("hs_code") or ""),
            "source_row_index": None,
            "added": True,
        })
    return [row for row in output if row["material_code"]]
@router.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/edit-row")
async def co_case_origin_sheet_edit_row(
    request: Request, client_id: str, case_id: str, product_code: str
):
    payload = await read_json_or_form(request)
    row_index = payload.get("row_index")
    new_norm = str(payload.get("new_norm_per_unit") or "").strip()
    if row_index is None or str(row_index).strip() == "" or not new_norm:
        raise HTTPException(status_code=400, detail="row_index and new_norm_per_unit required")
    try:
        row_index_int = int(row_index)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="row_index must be integer") from exc
    try:
        Decimal(new_norm)
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=400, detail="new_norm_per_unit must be numeric") from exc
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    target_index = next(
        (i for i, p in enumerate(case.get("products", [])) if str(p.get("code") or "").strip() == product_code),
        None,
    )
    if target_index is None:
        raise HTTPException(status_code=404, detail=f"Sheet {product_code} not found in case")
    reject_if_sheet_locked(case, product_code)
    states = dict(case.get("origin_sheet_states") or {})
    previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
    overrides = dict(previous.get("material_overrides") or {})
    key = str(row_index_int)
    existing = overrides.get(key) if isinstance(overrides.get(key), dict) else {}
    overrides[key] = {**existing, "norm_per_unit": new_norm, "norm_edit_only": not existing.get("material_code")}
    states[product_code] = {**previous, "material_overrides": overrides, "status": "stale", "status_label": ORIGIN_SHEET_STATUS_LABELS["stale"]}
    case["origin_sheet_states"] = states
    case = mark_origin_sheets_stale(case, target_index)
    update_case_record(client, case)
    return JSONResponse({
        "ok": True, "product_code": product_code,
        "row_index": row_index_int, "applied_override": overrides[key], "sheet_status": "stale",
    })
@router.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/add-row")
async def co_case_origin_sheet_add_row(
    request: Request, client_id: str, case_id: str, product_code: str
):
    payload = await read_json_or_form(request)
    new_material_code = str(payload.get("new_material_code") or "").strip()
    new_norm = str(payload.get("new_norm_per_unit") or "").strip()
    new_name = str(payload.get("new_name") or "").strip()
    new_uom = str(payload.get("new_uom") or "").strip()
    new_hs = str(payload.get("new_hs_code") or "").strip()
    if not new_material_code:
        raise HTTPException(status_code=400, detail="new_material_code required")
    if new_norm:
        try:
            Decimal(new_norm)
        except (InvalidOperation, ValueError) as exc:
            raise HTTPException(status_code=400, detail="new_norm_per_unit must be numeric") from exc
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    target_index = next(
        (i for i, p in enumerate(case.get("products", [])) if str(p.get("code") or "").strip() == product_code),
        None,
    )
    if target_index is None:
        raise HTTPException(status_code=404, detail=f"Sheet {product_code} not found in case")
    reject_if_sheet_locked(case, product_code)
    states = dict(case.get("origin_sheet_states") or {})
    previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
    overrides = dict(previous.get("material_overrides") or {})
    next_added = 1 + max(
        [int(k.split("_", 1)[1]) for k in overrides if k.startswith("added_") and k.split("_", 1)[1].isdigit()] + [-1]
    )
    key = f"added_{next_added}"
    overrides[key] = {
        "added": True,
        "material_code": new_material_code,
        "norm_per_unit": new_norm,
        "name": new_name,
        "uom": new_uom,
        "hs_code": new_hs,
    }
    states[product_code] = {**previous, "material_overrides": overrides, "status": "stale", "status_label": ORIGIN_SHEET_STATUS_LABELS["stale"]}
    case["origin_sheet_states"] = states
    case = mark_origin_sheets_stale(case, target_index)
    update_case_record(client, case)
    return JSONResponse({
        "ok": True, "product_code": product_code, "added_key": key,
        "applied_override": overrides[key], "sheet_status": "stale",
    })
@router.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/save")
async def co_case_origin_sheet_save(
    request: Request, client_id: str, case_id: str, product_code: str
):
    """Batched persistence of client-side bảng kê edits.

    Accepts a JSON payload with four lists/maps:
      replaces: {row_index: {new_material_code, new_norm_per_unit, new_name, new_hs_code}}
      adds: [{key, new_material_code, new_norm_per_unit, new_name, new_uom, new_hs_code}]
      deletes: {row_index: true}
      norm_edits: {row_index: new_norm}

    Each maps to material_overrides entries the existing render path already
    consumes; the sheet is flipped to "stale" so the next /calculate (now
    "Load BOM vào Bảng Kê") re-runs allocation with these overrides.
    """
    payload = await read_json_or_form(request)
    replaces = payload.get("replaces") or {}
    adds = payload.get("adds") or []
    deletes = payload.get("deletes") or {}
    norm_edits = payload.get("norm_edits") or {}
    if not (replaces or adds or deletes or norm_edits):
        raise HTTPException(status_code=400, detail="empty payload")
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    expected_revision = str(payload.get("expected_revision") or "").strip()
    if expected_revision and expected_revision != origin_case_revision(case):
        raise HTTPException(status_code=409, detail="Origin case state changed; reload before saving.")
    case = merge_origin_action_payload(case, payload)
    target_index = next(
        (i for i, p in enumerate(case.get("products", [])) if str(p.get("code") or "").strip() == product_code),
        None,
    )
    if target_index is None:
        raise HTTPException(status_code=404, detail=f"Sheet {product_code} not found in case")
    reject_if_sheet_locked(case, product_code)
    states = dict(case.get("origin_sheet_states") or {})
    previous = states.get(product_code) if isinstance(states.get(product_code), dict) else {}
    overrides = dict(previous.get("material_overrides") or {})

    def _parse_row_index(value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    counts = {"replaces": 0, "adds": 0, "deletes": 0, "norm_edits": 0}

    if isinstance(replaces, dict):
        for raw_index, info in replaces.items():
            row_index = _parse_row_index(raw_index)
            if row_index is None or not isinstance(info, dict):
                continue
            new_material_code = str(info.get("new_material_code") or "").strip()
            if not new_material_code:
                continue
            norm = str(info.get("new_norm_per_unit") or "").strip()
            if norm:
                try:
                    Decimal(norm)
                except (InvalidOperation, ValueError):
                    raise HTTPException(status_code=400, detail=f"replaces[{row_index}].new_norm_per_unit must be numeric")
            overrides[str(row_index)] = {
                "material_code": new_material_code,
                "norm_per_unit": norm,
                "name": str(info.get("new_name") or "").strip(),
                "hs_code": str(info.get("new_hs_code") or "").strip(),
                "uom": str(info.get("new_uom") or "").strip(),
            }
            counts["replaces"] += 1

    if isinstance(norm_edits, dict):
        for raw_index, raw_norm in norm_edits.items():
            row_index = _parse_row_index(raw_index)
            if row_index is None:
                continue
            norm = str(raw_norm or "").strip()
            if not norm:
                continue
            try:
                Decimal(norm)
            except (InvalidOperation, ValueError):
                raise HTTPException(status_code=400, detail=f"norm_edits[{row_index}] must be numeric")
            key = str(row_index)
            existing = overrides.get(key) if isinstance(overrides.get(key), dict) else {}
            overrides[key] = {**existing, "norm_per_unit": norm, "norm_edit_only": not existing.get("material_code")}
            counts["norm_edits"] += 1

    if isinstance(deletes, dict):
        for raw_index, flag in deletes.items():
            if not flag:
                continue
            row_index = _parse_row_index(raw_index)
            if row_index is None:
                continue
            overrides[str(row_index)] = {"deleted": True}
            counts["deletes"] += 1

    used_added_ids = [
        int(k.split("_", 1)[1])
        for k in overrides
        if k.startswith("added_") and k.split("_", 1)[1].isdigit()
    ]
    next_added = (max(used_added_ids) + 1) if used_added_ids else 0
    if isinstance(adds, list):
        for entry in adds:
            if not isinstance(entry, dict):
                continue
            new_material_code = str(entry.get("new_material_code") or "").strip()
            if not new_material_code:
                continue
            norm = str(entry.get("new_norm_per_unit") or "").strip()
            if norm:
                try:
                    Decimal(norm)
                except (InvalidOperation, ValueError):
                    raise HTTPException(status_code=400, detail=f"adds[{new_material_code}].new_norm_per_unit must be numeric")
            key = f"added_{next_added}"
            next_added += 1
            overrides[key] = {
                "added": True,
                "material_code": new_material_code,
                "norm_per_unit": norm,
                "name": str(entry.get("new_name") or "").strip(),
                "uom": str(entry.get("new_uom") or "").strip(),
                "hs_code": str(entry.get("new_hs_code") or "").strip(),
            }
            counts["adds"] += 1

    states[product_code] = {
        **previous,
        "material_overrides": overrides,
        "status": "calculated",
        "status_label": ORIGIN_SHEET_STATUS_LABELS["calculated"],
    }
    case["origin_sheet_states"] = states
    try:
        client_config_for_rule = (
            portfolio_service.get_client_config(client)
            if hasattr(portfolio_service, "get_client_config") else {}
        )
    except Exception:  # noqa: BLE001
        client_config_for_rule = {}
    case = recalculate_origin_sheet_edits(
        client, case, product_code,
        min_gap_days=effective_min_gap_days(client, client_config_for_rule),
    )
    case = set_origin_sheet_status(case, product_code, "calculated")
    case = mark_origin_sheets_stale(case, target_index + 1)
    update_case_record(client, case)
    # Content-negotiate: the browser asks for text/html so it can swap the
    # re-rendered case shell in-place (same path as /calculate + /lock), so
    # "Lưu bảng kê" updates the sheet — and enables "Chốt" — without a full
    # page reload. API/test callers (default Accept) still get the JSON below.
    if "text/html" in (request.headers.get("accept", "") or ""):
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            context=co_case_context(
                client_id,
                case_id,
                current_step="origin",
                case=case,
                message=f"Đã lưu bảng kê {product_code}.",
                preserve_origin_products=True,
                fast_origin_context=True,
            ),
        )
    return JSONResponse({
        "ok": True,
        "product_code": product_code,
        "operations": counts,
        "override_count": len(overrides),
        "sheet_status": "calculated",
        "revision": origin_case_revision(case),
        "origin_product_order": origin_product_order(case),
        "origin_sheet_states": json_safe(case.get("origin_sheet_states", {})),
    })
async def read_json_or_form(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            payload = {}
        return payload if isinstance(payload, dict) else {}
    form = await large_request_form(request)
    return {key: str(value) for key, value in form.items()}
@router.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/recommendation-override")
async def co_case_origin_sheet_recommendation_override(
    request: Request, client_id: str, case_id: str, product_code: str
):
    payload: dict = {}
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
    else:
        form = await large_request_form(request)
        payload = {key: str(value) for key, value in form.items()}
    overrides: dict = {}
    if "form_override" in payload:
        form_override = str(payload.get("form_override") or "").strip()
        if form_override and form_override not in {row["form_code"] for row in load_co_form_config().get("forms", [])}:
            raise HTTPException(status_code=400, detail=f"Unknown form_code {form_override}")
        overrides["form_override"] = form_override
    if "criteria_override" in payload:
        overrides["criteria_override"] = str(payload.get("criteria_override") or "").strip()
    if "lvc_threshold_override" in payload:
        overrides["lvc_threshold_override"] = payload.get("lvc_threshold_override")
    if "rvc_threshold_override" in payload:
        overrides["rvc_threshold_override"] = payload.get("rvc_threshold_override")
    if "currency_mode" in payload:
        mode = str(payload.get("currency_mode") or "").strip().lower()
        if mode and mode not in SHEET_CURRENCY_MODES:
            raise HTTPException(status_code=400, detail=f"Unknown currency_mode {mode}")
        overrides["currency_mode"] = mode or "native"
    if "optimization_mode" in payload:
        mode = str(payload.get("optimization_mode") or "").strip().lower()
        if mode and mode not in SHEET_OPTIMIZATION_MODES:
            raise HTTPException(status_code=400, detail=f"Unknown optimization_mode {mode}")
        overrides["optimization_mode"] = mode or "max_lvc"
    client = resolve_client(client_id)
    case = persisted_origin_case(client, case_id)
    expected_revision = str(payload.get("expected_revision") or "").strip()
    if expected_revision and expected_revision != origin_case_revision(case):
        raise HTTPException(status_code=409, detail="Origin case state changed; reload before saving.")
    case = merge_origin_action_payload(case, payload)
    if not any(str(p.get("code") or "").strip() == product_code for p in case.get("products", [])):
        raise HTTPException(status_code=404, detail=f"Sheet {product_code} not found in case")
    case = set_origin_sheet_config_override(case, product_code, overrides)
    update_case_record(client, case)
    state = (case.get("origin_sheet_states") or {}).get(product_code, {})
    return JSONResponse({
        "ok": True,
        "product_code": product_code,
        "state": {
            "form_override": state.get("form_override", ""),
            "criteria_override": state.get("criteria_override", ""),
            "lvc_threshold_override": state.get("lvc_threshold_override", ""),
            "rvc_threshold_override": state.get("rvc_threshold_override", ""),
            "currency_mode": state.get("currency_mode", "native"),
            "optimization_mode": state.get("optimization_mode", "max_lvc"),
            "effective_form_code": state.get("effective_form_code", ""),
            "effective_criteria_text": state.get("effective_criteria_text", ""),
            "effective_lvc_threshold": state.get("effective_lvc_threshold", ""),
            "effective_rvc_threshold": state.get("effective_rvc_threshold", ""),
        },
    })
@router.post("/clients/{client_id}/co-case/{case_id}/origin/sheet/{product_code}/reopen", response_class=HTMLResponse)
async def reopen_co_case_origin_sheet(request: Request, client_id: str, case_id: str, product_code: str):
    client = resolve_client(client_id)
    case, _payload = await origin_case_from_request(request, client, case_id)
    action_error = origin_sheet_action_error(case, product_code, "reopen")
    if action_error:
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(
                client_id,
                case_id,
                current_step="origin",
                case=case,
                error=action_error,
                preserve_origin_products=True,
                fast_origin_context=True,
            ),
        )
    # Release ledger claims BEFORE updating case state so a DB failure leaves
    # the sheet in a consistent locked state (claims still held, sheet still
    # locked). The previous order (case state first, then release) meant a
    # release failure silently leaked the claim while the UI showed unlocked.
    try:
        co_stock_ledger.record_sheet_release(client_id, case_id, product_code)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "reopen failed for %s/%s/%s: %s", client_id, case_id, product_code, exc
        )
        return templates.TemplateResponse(
            request=request,
            name="co_case.html",
            status_code=409,
            context=co_case_context(
                client_id,
                case_id,
                current_step="origin",
                case=case,
                error=f"Không mở chốt được bảng kê {product_code}: ledger lỗi ({exc}). Hãy thử lại.",
                preserve_origin_products=True,
                fast_origin_context=True,
            ),
        )
    case = set_origin_sheet_status(case, product_code, "calculated")
    update_case_record(client, case)
    invalidate_co_case_source_cache(client_id, case_id)
    return templates.TemplateResponse(
        request=request,
        name="co_case.html",
        context=co_case_context(
            client_id,
            case_id,
            current_step="origin",
            case=case,
            message=f"Đã mở chốt bảng kê {product_code}.",
            preserve_origin_products=True,
            fast_origin_context=True,
        ),
    )
