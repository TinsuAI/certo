from __future__ import annotations

import fcntl
import hashlib
import json
import mimetypes
import os
import re
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from app.co_forms import form_candidates_for_market
from app.workflow_state_store import get_co_case_state_store


MAX_SUPPORTING_FILE_BYTES = 20 * 1024 * 1024
ALLOWED_SUPPORTING_SUFFIXES = {".pdf", ".xlsx", ".xls", ".xlsm", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
ORIGIN_CALCULATION_LOCK_TTL_MINUTES = 60
COMPLETED_CASE_STATUSES = {"completed", "done", "finished", "submitted", "closed"}


def get_case_workspace(client: dict, selected_case_id: str = "") -> dict:
    state = load_state(client["id"])
    cases = sorted(state["cases"], key=lambda row: row["updated_at"], reverse=True)
    selected = next((case for case in cases if case["case_id"] == selected_case_id), None) if selected_case_id else None
    return {
        "cases": [dict(case) for case in cases],
        "selected_case_id": selected["case_id"] if selected else "",
        "selected_case": dict(selected) if selected else None,
    }


def create_case_record(client: dict, form: dict[str, str]) -> dict:
    with case_lock(client["id"]):
        state = load_state(client["id"])
        created_at = now_iso()
        case_id = make_id("co-case")
        invoice_no = clean_text(form.get("invoice_no"))
        export_declaration_nos = declaration_refs(form.get("export_declaration_nos"))
        case_reference = invoice_no or (export_declaration_nos[0] if export_declaration_nos else "")
        record = {
            "case_id": case_id,
            "client_id": client["id"],
            "title": clean_text(form.get("title")) or f"Hồ sơ C/O {client['name']}",
            "case_code": clean_text(form.get("case_code")) or generate_case_code(client, case_reference, created_at, case_id),
            "destination_market": clean_text(form.get("destination_market")) or "Chưa nhập",
            "agreement": clean_text(form.get("agreement")),
            "co_form_type": clean_text(form.get("co_form_type")),
            "rule": clean_text(form.get("rule")),
            "shipment": {
                "invoice_no": invoice_no,
                "export_declaration_nos": export_declaration_nos,
                "bill_of_lading_no": clean_text(form.get("bill_of_lading_no")),
            },
            "supporting_files": [],
            "created_at": created_at,
            "updated_at": created_at,
        }
        apply_form_defaults(record)
        state["cases"].append(record)
        save_state(client["id"], state)
        return dict(record)


def get_case_record(client: dict, case_id: str) -> dict:
    state = load_state(client["id"])
    for record in state["cases"]:
        if record["case_id"] == case_id:
            return dict(record)
    raise KeyError(case_id)


def update_case_record(client: dict, case: dict) -> dict:
    case_id = clean_text(case.get("persisted_case_id") or case.get("id"))
    if not case_id:
        raise KeyError(case_id)
    with case_lock(client["id"]):
        state = load_state(client["id"])
        record = next((row for row in state["cases"] if row["case_id"] == case_id), None)
        if record is None:
            raise KeyError(case_id)
        for key in ["title", "case_code", "destination_market", "agreement", "co_form_type", "rule", "status"]:
            if clean_text(case.get(key)):
                record[key] = clean_text(case.get(key))
        if not clean_text(case.get("co_form_type")):
            apply_form_defaults(record, force=True)
        else:
            apply_form_defaults(record)
        shipment = case.get("shipment", {})
        record.setdefault("shipment", {})
        record["shipment"]["invoice_no"] = clean_text(shipment.get("invoice_no"))
        record["shipment"]["export_declaration_nos"] = declaration_refs(shipment.get("export_declaration_nos"))
        record["shipment"]["bill_of_lading_no"] = clean_text(shipment.get("bill_of_lading_no"))
        if "products" in case:
            record["products"] = persisted_products(case.get("products", []))
        for key in ["origin_product_order", "origin_sheet_states", "bom_artifact_id", "bom_version_id", "bom_product_artifact_overrides", "bom_product_version_overrides", "bom_snapshot", "origin_snapshot", "source_snapshot", "source_invoice_matches"]:
            if key in case:
                record[key] = json_safe(case.get(key))
        if "bom_artifact_id" in case and "bom_version_id" not in case:
            record["bom_version_id"] = json_safe(case.get("bom_artifact_id"))
        if "bom_product_artifact_overrides" in case and "bom_product_version_overrides" not in case:
            record["bom_product_version_overrides"] = json_safe(case.get("bom_product_artifact_overrides"))
        record["updated_at"] = now_iso()
        save_state(client["id"], state)
        return dict(record)


def delete_case_record(client: dict, case_id: str) -> dict:
    case_id = clean_text(case_id)
    if not case_id:
        raise KeyError(case_id)
    with case_lock(client["id"]):
        state = load_state(client["id"])
        record = next((row for row in state["cases"] if row["case_id"] == case_id), None)
        if record is None:
            raise KeyError(case_id)
        block_reason = co_case_delete_block_reason(record, state.get("origin_calculation_lock") or {})
        if block_reason:
            raise ValueError(block_reason)
        state["cases"] = [row for row in state["cases"] if row["case_id"] != case_id]
        save_state(client["id"], state)
    shutil.rmtree(case_upload_root(client["id"], case_id), ignore_errors=True)
    return dict(record)


def co_case_delete_block_reason(case: dict, origin_lock: dict | None = None) -> str:
    if origin_lock and origin_calculation_lock_is_active(origin_lock) and origin_lock.get("case_id") == case.get("case_id"):
        return "Hồ sơ đang giữ phiên tính tồn. Hãy nhả phiên trước khi xoá."
    if co_case_is_completed(case):
        return "Hồ sơ đã hoàn tất nên không thể xoá."
    return ""


def co_case_is_completed(case: dict) -> bool:
    status = clean_text(case.get("status") or case.get("case_status")).lower()
    if status in COMPLETED_CASE_STATUSES:
        return True
    snapshot_status = clean_text((case.get("origin_snapshot") or {}).get("case_status")).lower()
    return snapshot_status in COMPLETED_CASE_STATUSES


def active_origin_calculation_lock(client: dict) -> dict:
    lock = load_state(client["id"]).get("origin_calculation_lock") or {}
    return dict(lock) if origin_calculation_lock_is_active(lock) else {}


def acquire_origin_calculation_lock(client: dict, case_id: str, actor: dict | None = None) -> dict:
    actor = actor or {}
    with case_lock(client["id"]):
        state = load_state(client["id"])
        existing = state.get("origin_calculation_lock") or {}
        if not origin_calculation_lock_is_active(existing):
            existing = {}
        if existing and existing.get("case_id") != case_id:
            return {"acquired": False, "lock": dict(existing)}

        case_record = next((row for row in state["cases"] if row["case_id"] == case_id), {})
        now = datetime.now(timezone.utc).replace(microsecond=0)
        lock = {
            "status": "active",
            "client_id": client["id"],
            "client_name": client.get("name", client["id"]),
            "case_id": case_id,
            "case_code": case_record.get("case_code", case_id),
            "case_title": case_record.get("title", ""),
            "invoice_no": (case_record.get("shipment") or {}).get("invoice_no", ""),
            "export_declaration_nos": declaration_refs((case_record.get("shipment") or {}).get("export_declaration_nos")),
            "actor_id": clean_text(actor.get("id") or actor.get("user_id") or "local"),
            "actor_label": clean_text(actor.get("label") or actor.get("name") or actor.get("email") or "Local user"),
            "acquired_at": existing.get("acquired_at") or now.isoformat(),
            "renewed_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=ORIGIN_CALCULATION_LOCK_TTL_MINUTES)).isoformat(),
        }
        state["origin_calculation_lock"] = lock
        save_state(client["id"], state)
        return {"acquired": True, "lock": dict(lock)}


def release_origin_calculation_lock(client: dict, case_id: str) -> dict:
    with case_lock(client["id"]):
        state = load_state(client["id"])
        existing = state.get("origin_calculation_lock") or {}
        if existing.get("case_id") != case_id:
            return {"released": False, "lock": dict(existing) if origin_calculation_lock_is_active(existing) else {}}
        state["origin_calculation_lock"] = {
            **existing,
            "status": "released",
            "released_at": now_iso(),
        }
        save_state(client["id"], state)
        return {"released": True, "lock": {}}


def origin_calculation_lock_is_active(lock: dict) -> bool:
    if not lock or lock.get("status") != "active":
        return False
    expires_at = parse_timestamp(lock.get("expires_at"))
    return bool(expires_at and expires_at > datetime.now(timezone.utc))


def case_from_record(base_case: dict, client: dict, record: dict) -> dict:
    case = dict(base_case)
    case["id"] = record["case_id"]
    case["persisted_case_id"] = record["case_id"]
    case["customer"] = client["name"]
    case["title"] = record.get("title", case.get("title", ""))
    case["case_code"] = record.get("case_code", case.get("case_code", ""))
    case["destination_market"] = record.get("destination_market", case.get("destination_market", ""))
    case["agreement"] = record.get("agreement") or case.get("agreement", "Chưa chọn")
    case["co_form_type"] = record.get("co_form_type") or case.get("co_form_type", "Chưa chọn")
    case["rule"] = record.get("rule") or case.get("rule", "Cần tra cứu PSR theo HS")
    case["source_label"] = f"Hồ sơ lưu: {case['case_code']}"
    case["shipment"] = dict(record.get("shipment", {}))
    case["supporting_files"] = [dict(file_row) for file_row in record.get("supporting_files", [])]
    if "products" in record:
        case["products"] = restored_products(record.get("products", []))
    for key in ["origin_product_order", "origin_sheet_states", "bom_artifact_id", "bom_version_id", "bom_product_artifact_overrides", "bom_product_version_overrides", "bom_snapshot", "origin_snapshot", "source_snapshot", "source_invoice_matches"]:
        if key in record:
            case[key] = json_safe(record.get(key))
    if "bom_artifact_id" not in case and "bom_version_id" in case:
        case["bom_artifact_id"] = json_safe(case.get("bom_version_id"))
    if "bom_product_artifact_overrides" not in case and "bom_product_version_overrides" in case:
        case["bom_product_artifact_overrides"] = json_safe(case.get("bom_product_version_overrides"))
    return case


def apply_form_defaults(record: dict, force: bool = False) -> None:
    defaults = form_defaults_for_market(record.get("destination_market", ""))
    for key, value in defaults.items():
        if force or not clean_text(record.get(key)):
            record[key] = value


def form_defaults_for_market(destination_market: str) -> dict:
    market = clean_text(destination_market)
    if not market or market == "Chưa nhập":
        return {}
    candidate = next(iter(form_candidates_for_market(market)), {})
    if not candidate:
        return {}
    return {
        "agreement": candidate.get("agreement", ""),
        "co_form_type": candidate.get("display_name", ""),
        "rule": candidate.get("rule_lookup_label", ""),
    }


def save_supporting_file(
    client: dict,
    case_id: str,
    content: bytes,
    filename: str,
    document_slot: str,
    invoice_no: str = "",
    bill_of_lading_no: str = "",
) -> dict:
    validate_supporting_file(content, filename)
    with case_lock(client["id"]):
        state = load_state(client["id"])
        record = next((case for case in state["cases"] if case["case_id"] == case_id), None)
        if record is None:
            raise KeyError(case_id)

        uploaded_at = now_iso()
        upload_id = make_id("support")
        original_filename = Path(filename or "supporting-file").name.strip() or "supporting-file"
        safe_name = safe_filename(original_filename)
        upload_dir = case_upload_root(client["id"], case_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{upload_id}-{safe_name}"
        stored_path = upload_dir / stored_name
        stored_path.write_bytes(content)
        relative_stored_path = str(stored_path.relative_to(case_root(client["id"])))
        mime_type = mimetypes.guess_type(original_filename)[0] or "application/octet-stream"

        invoice = clean_text(invoice_no) or extract_invoice_hint(filename)
        bill = clean_text(bill_of_lading_no)
        if invoice:
            record.setdefault("shipment", {})["invoice_no"] = invoice
        if bill:
            record.setdefault("shipment", {})["bill_of_lading_no"] = bill

        file_row = {
            "upload_id": upload_id,
            "slot": clean_text(document_slot) or "other",
            "original_filename": original_filename,
            "safe_filename": safe_name,
            "filename": safe_name,
            "stored_filename": stored_name,
            "stored_path": relative_stored_path,
            "storage_backend": "filesystem",
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
            "file_ext": Path(original_filename).suffix.lower(),
            "mime_type": mime_type,
            "content_type": mime_type,
            "invoice_no": invoice,
            "bill_of_lading_no": bill,
            "uploaded_at": uploaded_at,
        }
        record.setdefault("supporting_files", []).append(file_row)
        record["updated_at"] = uploaded_at
        save_state(client["id"], state)
        return dict(file_row)


def get_supporting_file(client: dict, case_id: str, upload_id: str) -> tuple[dict, Path]:
    record = get_case_record(client, case_id)
    file_row = next((row for row in record.get("supporting_files", []) if row.get("upload_id") == upload_id), None)
    if not file_row:
        raise KeyError(upload_id)
    root = case_root(client["id"]).resolve()
    stored_path = clean_text(file_row.get("stored_path"))
    if not stored_path:
        raise FileNotFoundError(upload_id)
    path = (root / stored_path).resolve()
    if not path.is_file() or not path.is_relative_to(root):
        raise FileNotFoundError(upload_id)
    return dict(file_row), path


def match_case_bcct_exports(case: dict, source_workspace: dict, client_config: dict) -> list[dict]:
    shipment = case.get("shipment", {})
    invoice_no = clean_text(shipment.get("invoice_no"))
    declaration_nos = declaration_refs(shipment.get("export_declaration_nos"))
    if not invoice_no and not declaration_nos:
        return []
    invoice_tokens = invoice_keys(invoice_no)
    declaration_tokens = {re.sub(r"[^A-Z0-9]", "", ref.upper()) for ref in declaration_nos}
    relevant_types = set(client_config.get("bcct", {}).get("relevant_export_declaration_types", []))
    matches = []
    for row in source_workspace["bcct"]["published_rows"]:
        if row.get("direction") != "export":
            continue
        if row.get("review_status") != "reviewed":
            continue
        if relevant_types and row.get("declaration_type") not in relevant_types:
            continue
        row_tokens = invoice_keys(row.get("invoice_ref", ""))
        row_declaration = re.sub(r"[^A-Z0-9]", "", clean_text(row.get("declaration_no")).upper())
        declaration_match = bool(declaration_tokens and row_declaration in declaration_tokens)
        invoice_match = bool(invoice_tokens and invoice_tokens.intersection(row_tokens))
        if declaration_tokens:
            if not declaration_match:
                continue
            match_source = "declaration"
        else:
            if not invoice_match:
                continue
            match_source = "invoice"
        invoice_mismatch = bool(declaration_match and invoice_tokens and row_tokens and not invoice_match)
        warning = ""
        if invoice_mismatch:
            warning = f"Invoice nhập {invoice_no} không khớp invoice_ref {row.get('invoice_ref', '')} trên tờ khai {row.get('declaration_no', '')}."
        elif declaration_match and invoice_tokens and not row_tokens:
            warning = f"Tờ khai {row.get('declaration_no', '')} không có invoice_ref để đối chiếu với invoice nhập {invoice_no}."
        if declaration_match and not invoice_no and not clean_text(row.get("invoice_ref")):
            warning = f"Tờ khai {row.get('declaration_no', '')} không có invoice_ref."
        if not declaration_match and not invoice_match:
            continue
        matches.append({
            "declaration_no": row.get("declaration_no", ""),
            "line_no": row.get("line_no", ""),
            "declaration_type": row.get("declaration_type", ""),
            "item_code": row.get("item_code", ""),
            "description": row.get("description", ""),
            "hs_code": row.get("hs_code", ""),
            "quantity": row.get("quantity", ""),
            "unit": row.get("unit", ""),
            "customs_value": row.get("customs_value", ""),
            "foreign_currency_value": row.get("foreign_currency_value", ""),
            "currency": row.get("currency", ""),
            "invoice_ref": row.get("invoice_ref", ""),
            "transaction_key": row.get("transaction_key", ""),
            "material_identity": row.get("material_identity", {}),
            "match_source": match_source,
            "invoice_mismatch": invoice_mismatch,
            "reference_warning": warning,
        })
    return matches


def build_case_criteria_rows(case: dict, form_candidates: list[dict]) -> list[dict]:
    primary_form = form_candidates[0]["display_name"] if form_candidates else ""
    rows = []
    for product in case.get("products", []):
        result = product.get("result")
        rvc = getattr(result, "rvc", {})
        tariff_shift = getattr(result, "tariff_shift", {})
        materials = product.get("materials", [])
        if not materials:
            rows.append(criteria_row(product, {}, primary_form, rvc, tariff_shift))
            continue
        for material in materials:
            rows.append(criteria_row(product, material, primary_form, rvc, tariff_shift))
    return rows


def create_case_workbook(case: dict, form_candidates: list[dict], invoice_matches: list[dict], criteria_rows: list[dict]) -> bytes:
    workbook = Workbook()
    case_sheet = workbook.active
    case_sheet.title = "Case"
    case_sheet.append(["Field", "Value"])
    case_sheet.append(["Case code", case.get("case_code", "")])
    case_sheet.append(["Title", case.get("title", "")])
    case_sheet.append(["Customer", case.get("customer", "")])
    case_sheet.append(["Destination market", case.get("destination_market", "")])
    case_sheet.append(["Invoice", case.get("shipment", {}).get("invoice_no", "")])
    case_sheet.append(["Export declarations", ", ".join(declaration_refs(case.get("shipment", {}).get("export_declaration_nos")))])
    case_sheet.append(["Bill of lading", case.get("shipment", {}).get("bill_of_lading_no", "")])

    files_sheet = workbook.create_sheet("Supporting Files")
    files_sheet.append(["Slot", "Filename", "Invoice", "Bill of lading", "Uploaded at"])
    for file_row in case.get("supporting_files", []):
        files_sheet.append([
            file_row.get("slot", ""),
            file_row.get("filename", ""),
            file_row.get("invoice_no", ""),
            file_row.get("bill_of_lading_no", ""),
            file_row.get("uploaded_at", ""),
        ])

    matches_sheet = workbook.create_sheet("BCCT Invoice Matches")
    matches_sheet.append(["Declaration", "Line", "Type", "Item code", "HS", "Quantity", "Unit", "Invoice", "Match source", "Warning"])
    for row in invoice_matches:
        matches_sheet.append([
            row.get("declaration_no", ""),
            row.get("line_no", ""),
            row.get("declaration_type", ""),
            row.get("item_code", ""),
            row.get("hs_code", ""),
            row.get("quantity", ""),
            row.get("unit", ""),
            row.get("invoice_ref", ""),
            row.get("match_source", ""),
            row.get("reference_warning", ""),
        ])

    guidance_sheet = workbook.create_sheet("Form Guidance")
    guidance_sheet.append(["Form", "Agreement", "Instrument", "Rule lookup", "Verification", "Reason"])
    for candidate in form_candidates:
        guidance_sheet.append([
            candidate.get("display_name", ""),
            candidate.get("agreement", ""),
            candidate.get("instrument", ""),
            candidate.get("rule_lookup_label", ""),
            candidate.get("verification_status", ""),
            candidate.get("selection_reason", ""),
        ])

    criteria_sheet = workbook.create_sheet("Criteria")
    criteria_sheet.append([
        "Product code",
        "Finished HS",
        "Form",
        "Rule",
        "RVC %",
        "CTC result",
        "Material code",
        "Material HS",
        "Origin status",
        "Non-origin CIF",
    ])
    for row in criteria_rows:
        criteria_sheet.append([
            row["product_code"],
            row["finished_hs"],
            row["form"],
            row["rule"],
            row["rvc_percentage"],
            row["tariff_shift_status"],
            row["material_code"],
            row["material_hs"],
            row["origin_status"],
            row["non_origin_cif_value"],
        ])

    snapshot_sheet = workbook.create_sheet("Origin Snapshot")
    snapshot = case.get("origin_snapshot", {})
    snapshot_sheet.append(["Field", "Value"])
    snapshot_sheet.append(["Calculation method", snapshot.get("calculation_method", "")])
    snapshot_sheet.append(["Calculation method label", snapshot.get("calculation_method_label", "")])
    snapshot_sheet.append(["Formula", snapshot.get("formula", "")])
    snapshot_sheet.append(["Readiness status", snapshot.get("readiness_status", "")])
    snapshot_sheet.append(["Readiness label", snapshot.get("readiness_label", "")])
    snapshot_sheet.append(["Issue count", snapshot.get("issue_count", "")])
    snapshot_sheet.append([])
    snapshot_sheet.append([
        "Product code",
        "Sequence",
        "Method",
        "Formula",
        "Criterion",
        "Readiness status",
        "Readiness label",
        "LVC %",
        "LVC threshold",
        "Tariff shift rule",
        "Tariff shift preview",
        "Warnings",
    ])
    for product in case.get("products", []):
        snapshot_sheet.append([
            product.get("code", ""),
            product.get("allocation_sequence", ""),
            product.get("origin_method", ""),
            product.get("origin_formula", ""),
            product.get("documented_result", ""),
            product.get("origin_readiness_status", ""),
            product.get("origin_readiness_label", ""),
            product.get("lvc_percentage", ""),
            product.get("lvc_threshold") or product.get("rvc_threshold", ""),
            f"{product.get('tariff_shift_rule')} preview" if product.get("tariff_shift_rule") else "",
            product.get("tariff_shift_status_label", ""),
            " | ".join(text_list(product.get("origin_warnings") or product.get("origin_warnings_text"))),
        ])
        for material in product.get("materials", []):
            snapshot_sheet.append([
                product.get("code", ""),
                product.get("allocation_sequence", ""),
                "material",
                material.get("material_code") or material.get("internal_material_code", ""),
                material.get("material_description", ""),
                material.get("valuation_status", ""),
                material.get("valuation_status_label", ""),
                material.get("material_value", ""),
                material.get("non_origin_cif_value", ""),
                "",
                material.get("valuation_source_label", ""),
                " | ".join(text_list(material.get("material_warnings") or material.get("material_warnings_text"))),
            ])
            for allocation in material.get("allocation_lines", []):
                snapshot_sheet.append([
                    product.get("code", ""),
                    allocation.get("product_sequence") or product.get("allocation_sequence", ""),
                    "allocation",
                    material.get("material_code") or material.get("internal_material_code", ""),
                    allocation_ref(allocation),
                    material.get("allocation_status", ""),
                    allocation.get("allocated_qty", ""),
                    allocation.get("unit_value", ""),
                    allocation.get("material_value", ""),
                    allocation.get("currency", ""),
                    allocation.get("valuation_source_label", ""),
                    allocation.get("source_row", ""),
                ])

    bom_sheet = workbook.create_sheet("LVC Statement")
    bom_sheet.append([
        "Product code",
        "Product sequence",
        "Product name",
        "Finished HS",
        "Invoice",
        "Export declaration",
        "Export line",
        "Export quantity",
        "Export unit",
        "FOB",
        "Export currency",
        "VNM",
        "LVC %",
        "LVC threshold",
        "LVC status",
        "LVC criterion",
        "BOM aggregate version",
        "BOM product version",
        "Material code",
        "Material sequence",
        "Material name",
        "Material HS",
        "Qty per",
        "BOM UOM",
        "Required qty",
        "Unit value",
        "Material currency",
        "Material value",
        "Material origin",
        "Non-origin value (VNM)",
        "Source",
        "Allocation source row",
        "Allocation declaration",
        "Allocation line",
        "Allocation product sequence",
        "Allocation opening qty",
        "Allocated qty",
        "Allocation available qty",
        "Allocation remaining qty",
        "Allocation unit value",
        "Allocation currency",
        "Allocation value",
    ])
    for product in case.get("products", []):
        materials = product.get("materials", []) or [{}]
        for material in materials:
            allocation_lines = material.get("allocation_lines") or [{}]
            for allocation in allocation_lines:
                bom_sheet.append([
                    product.get("code", ""),
                    product.get("allocation_sequence", ""),
                    product.get("name", ""),
                    product.get("finished_hs", ""),
                    case.get("shipment", {}).get("invoice_no", ""),
                    product.get("source_declaration_no", ""),
                    product.get("source_line_no", ""),
                    product.get("quantity", ""),
                    product.get("unit") or product.get("export_unit", ""),
                    product.get("fob", ""),
                    product.get("currency", ""),
                    product.get("vnm_value") or product.get("non_origin_value", ""),
                    product.get("lvc_percentage", ""),
                    product.get("lvc_threshold") or product.get("rvc_threshold", ""),
                    product.get("lvc_status_label", ""),
                    product.get("documented_result", ""),
                    case.get("bom_snapshot", {}).get("aggregate_artifact_id") or case.get("bom_snapshot", {}).get("aggregate_version_id", ""),
                    product.get("bom_product_artifact_id") or product.get("bom_product_version_id", ""),
                    material.get("material_code") or material.get("internal_material_code", ""),
                    material.get("material_sequence", ""),
                    material.get("material_description", ""),
                    material.get("hs_code", ""),
                    material.get("bom_qty_per", ""),
                    material.get("uom", ""),
                    material.get("consumed_qty", ""),
                    material.get("unit_value", ""),
                    material.get("currency") or product.get("currency", ""),
                    material.get("material_value", ""),
                    material.get("origin_status", ""),
                    material.get("non_origin_cif_value", ""),
                    material.get("source_document_ref", ""),
                    allocation.get("source_row", ""),
                    allocation.get("import_declaration_no", ""),
                    allocation.get("import_line_no", ""),
                    allocation.get("product_sequence", ""),
                    allocation.get("opening_qty", ""),
                    allocation.get("allocated_qty", ""),
                    allocation.get("available_qty", ""),
                    allocation.get("remaining_qty", ""),
                    allocation.get("unit_value", ""),
                    allocation.get("currency", ""),
                    allocation.get("material_value", ""),
                ])

    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def criteria_row(product: dict, material: dict, form: str, rvc: Any, tariff_shift: Any) -> dict:
    return {
        "product_code": product.get("code", ""),
        "product_name": product.get("name", ""),
        "finished_hs": product.get("finished_hs", ""),
        "form": form,
        "rule": product.get("documented_result") or "Cần tra cứu PSR theo HS",
        "rvc_percentage": getattr(rvc, "percentage", ""),
        "tariff_shift_status": "Đạt" if getattr(tariff_shift, "passed", False) else "Chưa đủ dữ liệu",
        "material_code": material.get("material_code") or material.get("internal_material_code", ""),
        "material_name": material.get("material_description", ""),
        "material_hs": material.get("hs_code", ""),
        "origin_status": material.get("origin_status", ""),
        "non_origin_cif_value": material.get("non_origin_cif_value", ""),
    }


def allocation_ref(allocation: dict) -> str:
    declaration = allocation.get("import_declaration_no", "")
    line_no = allocation.get("import_line_no", "")
    if declaration and line_no:
        return f"{declaration} / line {line_no}"
    return declaration or allocation.get("source_row", "")


def text_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


COST_BUILDUP_DETAIL_KEYS = (
    "wages",
    "welfare",
    "rent",
    "depreciation",
    "other_mfg",
    "transport_storage",
)
COST_BUILDUP_LEGACY_KEYS = ("labor", "overhead", "other")
COST_BUILDUP_PROFIT_KEY = "profit"


def _sanitize_cost_buildup(raw) -> dict[str, str]:
    """Coerce cost-buildup inputs to non-negative numeric strings.

    Accepts two shapes:
      - New: 6 detail keys (wages, welfare, rent, depreciation, other_mfg,
        transport_storage) + profit.
      - Legacy: labor / overhead / profit / other rollups (pre-2026-05-27).

    Both shapes are preserved as-is — no lossy reshape. The bảng kê engine
    reader normalises at read time. Invalid or negative entries become "".
    """
    all_keys = (
        *COST_BUILDUP_DETAIL_KEYS,
        *COST_BUILDUP_LEGACY_KEYS,
        COST_BUILDUP_PROFIT_KEY,
    )
    if not isinstance(raw, dict):
        return {key: "" for key in all_keys}
    cleaned: dict[str, str] = {}
    for key in all_keys:
        text = str(raw.get(key) or "").strip().replace(",", "")
        if not text:
            cleaned[key] = ""
            continue
        try:
            value = Decimal(text)
        except (InvalidOperation, ValueError):
            cleaned[key] = ""
            continue
        if value < 0:
            cleaned[key] = ""
        else:
            cleaned[key] = str(value)
    return cleaned


def persisted_products(products: list[dict]) -> list[dict]:
    output = []
    for product in products:
        persisted = {
            key: json_safe(value)
            for key, value in product.items()
            if key not in {"materials", "result"}
        }
        persisted["cost_buildup"] = _sanitize_cost_buildup(product.get("cost_buildup"))
        persisted["materials"] = [
            {
                key: json_safe(value)
                for key, value in material.items()
            }
            for material in product.get("materials", [])
        ]
        output.append(persisted)
    return output


def restored_products(products: list[dict]) -> list[dict]:
    restored = []
    for product in products:
        item = dict(product)
        if "bom_product_artifact_id" not in item and item.get("bom_product_version_id"):
            item["bom_product_artifact_id"] = item.get("bom_product_version_id")
        if "bom_product_artifact_no" not in item and item.get("bom_product_version_no"):
            item["bom_product_artifact_no"] = item.get("bom_product_version_no")
        if "bom_product_version_id" not in item and item.get("bom_product_artifact_id"):
            item["bom_product_version_id"] = item.get("bom_product_artifact_id")
        if "bom_product_version_no" not in item and item.get("bom_product_artifact_no"):
            item["bom_product_version_no"] = item.get("bom_product_artifact_no")
        item["materials"] = []
        for material in product.get("materials", []):
            row = dict(material)
            for field in ["available_qty", "consumed_qty", "non_origin_cif_value"]:
                row[field] = decimal_value(row.get(field, "0"))
            item["materials"].append(row)
        restored.append(item)
    return restored


def json_safe(value):
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def decimal_value(value) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", "").strip() or "0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def invoice_keys(value: str) -> set[str]:
    text = clean_text(value).upper()
    if not text:
        return set()
    compact = re.sub(r"[^A-Z0-9]", "", text)
    parts = {re.sub(r"[^A-Z0-9]", "", part) for part in re.split(r"[,;/\s]+", text)}
    return {part for part in {compact, *parts} if part}


def declaration_refs(value) -> list[str]:
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = re.split(r"[,;/\s]+", clean_text(value))
    refs = []
    for raw in raw_values:
        ref = clean_text(raw)
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def extract_invoice_hint(filename: str) -> str:
    text = clean_text(filename).upper()
    match = re.search(r"(INV[-_A-Z0-9.]+)", text)
    return match.group(1).rstrip(".") if match else ""


def validate_supporting_file(content: bytes, filename: str) -> None:
    if len(content) > MAX_SUPPORTING_FILE_BYTES:
        raise ValueError("File supporting vượt quá giới hạn 20 MB.")
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_SUPPORTING_SUFFIXES:
        raise ValueError("Không hỗ trợ định dạng file supporting này.")


def load_state(client_id: str) -> dict:
    store = get_co_case_state_store()
    if store:
        state = store.get_state(client_id)
        if state is not None:
            return normalize_state(client_id, state)
    path = state_path(client_id)
    if not path.exists():
        state = {"schema_version": 1, "client_id": client_id, "cases": []}
    else:
        state = json.loads(path.read_text())
    state = normalize_state(client_id, state)
    if store:
        store.save_state(client_id, state)
    return state


def normalize_state(client_id: str, state: dict) -> dict:
    state.setdefault("schema_version", 1)
    state.setdefault("client_id", client_id)
    state.setdefault("cases", [])
    for case in state["cases"]:
        case.setdefault("supporting_files", [])
        case.setdefault("shipment", {})
        case["shipment"].setdefault("invoice_no", "")
        case["shipment"]["export_declaration_nos"] = declaration_refs(case["shipment"].get("export_declaration_nos"))
        case["shipment"].setdefault("bill_of_lading_no", "")
        for file_row in case["supporting_files"]:
            original_filename = file_row.get("original_filename") or file_row.get("filename", "")
            stored_path = file_row.get("stored_path", "")
            stored_filename = file_row.get("stored_filename") or Path(stored_path).name
            file_row.setdefault("original_filename", original_filename)
            file_row.setdefault("safe_filename", file_row.get("filename") or safe_filename(original_filename))
            file_row.setdefault("stored_filename", stored_filename)
            file_row.setdefault("storage_backend", "filesystem" if stored_path else "")
            file_row.setdefault("file_ext", Path(original_filename).suffix.lower())
            file_row.setdefault("mime_type", mimetypes.guess_type(original_filename)[0] or "")
            file_row.setdefault("content_type", file_row.get("mime_type", ""))
    return state


def save_state(client_id: str, state: dict) -> None:
    store = get_co_case_state_store()
    if store:
        store.save_state(client_id, normalize_state(client_id, state))
        return
    write_json(state_path(client_id), state)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp:
        json.dump(payload, temp, ensure_ascii=False, indent=2, default=str)
        temp.write("\n")
        temp_name = temp.name
    os.replace(temp_name, path)


@contextmanager
def case_lock(client_id: str):
    root = case_root(client_id)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".lock"
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def state_path(client_id: str) -> Path:
    return case_root(client_id) / "cases.json"


def case_upload_root(client_id: str, case_id: str) -> Path:
    return case_root(client_id) / "uploads" / case_id


def case_root(client_id: str) -> Path:
    return store_root() / "clients" / client_id


def store_root() -> Path:
    return Path(os.environ.get("CO_CASE_STORE_ROOT", "data/local/co-cases"))


def make_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def generate_case_code(client: dict, invoice_no: str, created_at: str, case_id: str) -> str:
    client_part = code_part(client.get("code") or client.get("id") or "CLIENT", "CLIENT")
    invoice_part = code_part(invoice_no, "")
    if not invoice_part:
        invoice_part = code_part(created_at[:10].replace("-", ""), "DATE")
    suffix = code_part(case_id.rsplit("-", 1)[-1][:4], "0000")
    return f"CO-{client_part}-{invoice_part}-{suffix}"


def code_part(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", "-", clean_text(value).upper()).strip("-")
    return cleaned or fallback


def safe_filename(filename: str) -> str:
    name = Path(filename).name.strip() or "upload"
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .") or "upload"


def clean_text(value) -> str:
    return str(value or "").strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_timestamp(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
