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
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from app.co_forms import form_candidates_for_market
from app.workflow_state_store import get_co_case_state_store


MAX_SUPPORTING_FILE_BYTES = 20 * 1024 * 1024
ALLOWED_SUPPORTING_SUFFIXES = {".pdf", ".xlsx", ".xls", ".xlsm", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
COMPLETED_CASE_STATUSES = {"completed", "done", "finished", "submitted", "closed"}

# material_overrides key scheme: "material_sequence" = keys are the 1-based BOM
# row sequence (plus added_<n>), replacing the legacy 0-based render index.
OVERRIDE_KEY_SCHEME = "material_sequence"


def migrated_override_keys(state: dict) -> dict:
    """Migrate one sheet state's override maps from legacy positional keys
    (0-based render index) to material_sequence keys (index+1 — deterministic
    because material_sequence is assigned as enumerate(bom_rows, start=1)).
    The stamped `override_key_scheme` makes this idempotent: a state written or
    already migrated under the new scheme is returned unchanged."""
    if not isinstance(state, dict):
        return state
    if state.get("override_key_scheme") == OVERRIDE_KEY_SCHEME:
        return state

    def migrate_map(overrides: dict) -> dict:
        migrated = {}
        for key, value in (overrides or {}).items():
            text = str(key)
            if text.isdigit():
                migrated[str(int(text) + 1)] = value
            else:
                migrated[text] = value
        return migrated

    out = dict(state)
    if isinstance(state.get("material_overrides"), dict):
        out["material_overrides"] = migrate_map(state["material_overrides"])
    if isinstance(state.get("override_history"), list):
        out["override_history"] = [
            migrate_map(snapshot) for snapshot in state["override_history"] if isinstance(snapshot, dict)
        ]
    if isinstance(state.get("override_redo"), list):
        out["override_redo"] = [
            migrate_map(snapshot) for snapshot in state["override_redo"] if isinstance(snapshot, dict)
        ]
    out["override_key_scheme"] = OVERRIDE_KEY_SCHEME
    return out


class CaseClosedError(ValueError):
    """Raised when a mutating call lands on a case whose status is in
    COMPLETED_CASE_STATUSES. Surfaces as HTTP 409 at the route boundary."""


class CaseHasActiveClaimsError(ValueError):
    """Raised by `delete_case_record` when the case still holds locked
    `co_stock_claims` rows AND the caller did not pass `release_claims=True`.

    The route handler turns this into a 409 + Vietnamese explanation so the
    operator gets a chance to confirm they really want the claims released
    along with the case. Carries `claims_count` and `lots_count` for
    surface-level messaging.
    """

    def __init__(self, claims_count: int, lots_count: int):
        self.claims_count = int(claims_count)
        self.lots_count = int(lots_count)
        super().__init__(
            f"Hồ sơ đang giữ {self.claims_count} dòng tồn trên {self.lots_count} lot. "
            "Bấm xoá lại để xác nhận nhả tồn + xoá hồ sơ."
        )


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
        _persist_case_row(client["id"], record, expected_revision=0)
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
        # Centralised close-state gate: every mutating route in app/main.py goes
        # through update_case_record, so blocking here covers shipment edits,
        # origin sheet save/lock/reopen, recommendation overrides, etc. The
        # carve-out is the /reopen-case endpoint which passes status="open" or
        # "reopen" to re-open the case.
        existing_status = clean_text(record.get("status") or "").lower()
        incoming_status = clean_text(case.get("status") or "").lower()
        if existing_status in COMPLETED_CASE_STATUSES and incoming_status not in ("open", "reopen"):
            raise CaseClosedError(
                "Hồ sơ đã đóng — bấm 'Mở lại hồ sơ' ở tab Review & Xuất trước khi sửa."
            )
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
        _persist_case_row(client["id"], record)
        return dict(record)


def _persist_case_row(client_id: str, record: dict, *, expected_revision: int | None = None) -> None:
    """Phase 2.4 helper — keep per-row `co_cases` in sync with the legacy
    save_state path. Under the surrounding case_lock the optimistic check
    can't actually conflict, but we still pass the current revision so
    Phase 3.2 (drop the case_lock band-aid) inherits a working retry
    surface. `expected_revision=0` means "this is a fresh insert".
    """
    from app.workflow_state_store import CaseRevisionConflict, get_co_case_state_store

    store = get_co_case_state_store()
    if store is None:
        return
    case_id = record.get("case_id", "")
    if not case_id:
        return
    revision = expected_revision
    if revision is None:
        loaded = store.get_case(client_id, case_id)
        revision = loaded[1] if loaded else 0
    for attempt in range(3):
        try:
            store.save_case_record(client_id, record, revision)
            return
        except CaseRevisionConflict as exc:
            revision = exc.current_revision
            if attempt == 2:
                raise


def _persist_case_supporting_files(client_id: str, record: dict) -> None:
    """Phase 3.2 prereq — per-case wipe + rewrite of `co_supporting_files`.

    Called by every mutator that touches `record["supporting_files"]`
    (currently `save_supporting_file`; create/update don't normally
    change file lists but call this for safety). Phase 2.5's save_state
    no longer manages the table per-client, so this is the only place
    the per-case file rows are kept in sync with the in-memory record.
    """
    from app.workflow_state_store import (
        co_supporting_file_record,
        get_co_case_state_store,
    )

    store = get_co_case_state_store()
    if store is None:
        return
    case_id = record.get("case_id", "")
    if not case_id:
        return
    files = [
        co_supporting_file_record(client_id, case_id, file_row)
        for file_row in record.get("supporting_files", []) or []
    ]
    store.save_case_supporting_files(client_id, case_id, files)


def delete_case_record(client: dict, case_id: str, *, release_claims: bool = False) -> dict:
    """Delete a case record. Returns the deleted record + `claims_released`.

    When the case still holds active `co_stock_claims`, refuses unless
    `release_claims=True` (raises `CaseHasActiveClaimsError` carrying the
    claim/lot count for surface messaging). This guards against the silent
    Tồn CO leak audit gap HIGH #2 where deleting a case used to leave
    orphan claims pinning lots forever.

    When `release_claims=True`, every locked claim for the case is
    released (status → 'released', `claim_release` events emitted) BEFORE
    the case row is removed, so the ledger never points at a dead case_id.
    """
    from app import co_stock_ledger

    case_id = clean_text(case_id)
    if not case_id:
        raise KeyError(case_id)
    claims_released = 0
    with case_lock(client["id"]):
        state = load_state(client["id"])
        record = next((row for row in state["cases"] if row["case_id"] == case_id), None)
        if record is None:
            raise KeyError(case_id)
        block_reason = co_case_delete_block_reason(record)
        if block_reason:
            raise ValueError(block_reason)
        summary = co_stock_ledger.claims_summary_for_case(client["id"], case_id)
        if summary.get("count", 0) > 0:
            if not release_claims:
                raise CaseHasActiveClaimsError(summary["count"], summary["lots"])
            claims_released = co_stock_ledger.release_all_claims_for_case(client["id"], case_id)
        state["cases"] = [row for row in state["cases"] if row["case_id"] != case_id]
        save_state(client["id"], state)
        from app.workflow_state_store import get_co_case_state_store
        store = get_co_case_state_store()
        if store is not None:
            store.delete_case(client["id"], case_id)
    shutil.rmtree(case_upload_root(client["id"], case_id), ignore_errors=True)
    result = dict(record)
    result["claims_released"] = claims_released
    return result


def co_case_delete_block_reason(case: dict) -> str:
    if co_case_is_completed(case):
        return "Hồ sơ đã hoàn tất nên không thể xoá."
    return ""


def co_case_is_completed(case: dict) -> bool:
    status = clean_text(case.get("status") or case.get("case_status")).lower()
    if status in COMPLETED_CASE_STATUSES:
        return True
    snapshot_status = clean_text((case.get("origin_snapshot") or {}).get("case_status")).lower()
    return snapshot_status in COMPLETED_CASE_STATUSES


def co_case_status_view(case: dict, *, exported: bool = False) -> dict:
    """Cheap per-case status for the list page + company dashboard.

    Derives everything from the persisted record only — no source-context or
    Data Hub calls. `exported` is the dossier-export "done" flag (read by the
    caller from `state["dossier_exports"]`). Shared single source of truth so
    the list and the dashboard never disagree on a case's status.
    """
    shipment = case.get("shipment") or {}
    invoice_no = clean_text(shipment.get("invoice_no"))
    declarations = shipment.get("export_declaration_nos") or []
    bill_no = clean_text(shipment.get("bill_of_lading_no"))
    products = case.get("products") or []
    sheets_total = len(products)
    sheets_locked = sum(
        1 for product in products
        if clean_text(product.get("origin_sheet_status")).lower() == "locked"
    )
    completed = co_case_is_completed(case)

    issues: list[str] = []
    if not invoice_no and not declarations:
        issues.append("Thiếu invoice/tờ khai")
    if not bill_no:
        issues.append("Thiếu B/L")
    if not products:
        issues.append("Chưa có bảng kê")
    elif sheets_locked < sheets_total:
        issues.append(f"{sheets_total - sheets_locked} bảng kê chưa chốt")

    if completed:
        status_key, status_label = "done", "Đã chốt"
    elif not invoice_no and not declarations:
        status_key, status_label = "attention", "Có vấn đề"
    elif not bill_no:
        status_key, status_label = "attention", "Có vấn đề"
    elif not products:
        status_key, status_label = "attention", "Có vấn đề"
    else:
        status_key, status_label = "progress", "Đang xử lý"

    if invoice_no:
        reference = f"Invoice {invoice_no}"
    elif declarations:
        reference = "Tờ khai " + ", ".join(str(d) for d in declarations)
    else:
        reference = "Chưa nhập tham chiếu"

    return {
        "case_id": case.get("case_id"),
        "case_code": case.get("case_code") or case.get("case_id"),
        "title": case.get("title") or "",
        "destination_market": case.get("destination_market") or "",
        "co_form_type": case.get("co_form_type") or "",
        "reference": reference,
        "status_key": status_key,
        "status_label": status_label,
        "completed": completed,
        "exported": bool(exported),
        "archived": bool(case.get("archived")),
        "sheets_total": sheets_total,
        "sheets_locked": sheets_locked,
        "issues": [] if completed else issues,
        "updated_at": case.get("updated_at") or "",
    }


def set_case_archived(client: dict, case_id: str, archived: bool) -> dict:
    """Flip a case's `archived` flag. Bypasses the `update_case_record`
    close-gate on purpose: archiving a *completed* case is the common path,
    and archive state is orthogonal to the edit/close lifecycle."""
    case_id = clean_text(case_id)
    with case_lock(client["id"]):
        state = load_state(client["id"])
        record = next((row for row in state["cases"] if row["case_id"] == case_id), None)
        if record is None:
            raise KeyError(case_id)
        record["archived"] = bool(archived)
        record["updated_at"] = now_iso()
        save_state(client["id"], state)
        _persist_case_row(client["id"], record)
        return dict(record)


def case_from_record(base_case: dict, client: dict, record: dict) -> dict:
    case = dict(base_case)
    case["id"] = record["case_id"]
    case["persisted_case_id"] = record["case_id"]
    legal_name = clean_text(client.get("legal_name") or "")
    case["customer"] = legal_name or client["name"]
    case["customer_legal_name"] = legal_name
    case["customer_tax_code"] = clean_text(client.get("tax_code") or "")
    case["title"] = record.get("title", case.get("title", ""))
    case["case_code"] = record.get("case_code", case.get("case_code", ""))
    case["destination_market"] = record.get("destination_market", case.get("destination_market", ""))
    case["agreement"] = record.get("agreement") or case.get("agreement", "Chưa chọn")
    case["co_form_type"] = record.get("co_form_type") or case.get("co_form_type", "Chưa chọn")
    case["rule"] = record.get("rule") or case.get("rule", "Cần tra cứu PSR theo HS")
    case["status"] = clean_text(record.get("status") or case.get("status", ""))
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
    if isinstance(case.get("origin_sheet_states"), dict):
        case["origin_sheet_states"] = {
            code: migrated_override_keys(state)
            for code, state in case["origin_sheet_states"].items()
        }
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
        _persist_case_row(client["id"], record)
        _persist_case_supporting_files(client["id"], record)
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


def delete_supporting_file(client: dict, case_id: str, upload_id: str) -> dict:
    with case_lock(client["id"]):
        state = load_state(client["id"])
        record = next((case for case in state["cases"] if case["case_id"] == case_id), None)
        if record is None:
            raise KeyError(case_id)
        files = record.get("supporting_files", [])
        index = next((i for i, row in enumerate(files) if row.get("upload_id") == upload_id), None)
        if index is None:
            raise KeyError(upload_id)
        removed = files.pop(index)
        stored_path = clean_text(removed.get("stored_path"))
        if stored_path:
            root = case_root(client["id"]).resolve()
            target = (root / stored_path).resolve()
            if target.is_file() and target.is_relative_to(root):
                try:
                    target.unlink()
                except OSError:
                    pass
        record["updated_at"] = now_iso()
        save_state(client["id"], state)
        _persist_case_row(client["id"], record)
        _persist_case_supporting_files(client["id"], record)
        return dict(removed)


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
        # DB is the single source of truth: when a database is configured we
        # never read from — nor re-seed back into the DB from — the legacy
        # cases.json file store (doing so resurrected deleted cases). A missing
        # DB row means an empty case list, not a fallback to disk.
        state = store.get_state(client_id)
        if state is None:
            state = {"schema_version": 1, "client_id": client_id, "cases": []}
        return normalize_state(client_id, state)
    # File-mode only (no BARRY_DATABASE_URL): the on-disk cases.json store used
    # by the file-mode test suite and DB-less runs.
    path = state_path(client_id)
    if not path.exists():
        state = {"schema_version": 1, "client_id": client_id, "cases": []}
    else:
        state = json.loads(path.read_text())
    return normalize_state(client_id, state)


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
    """Same-host serialization for load-mutate-save sequences against a
    client's case state.

    Phase 3.2 final: the Postgres advisory lock that this context manager
    used to also acquire is gone. Per-case writes in Postgres mode now
    rely entirely on:

    - `co_cases.revision` optimistic concurrency (Phase 2.1 + 2.2) for
      the case rows themselves
    - `co_supporting_files` per-case wipe + rewrite via
      `save_case_supporting_files` (Phase 3.2 prereq) so two operators
      uploading to different cases of the same client no longer touch
      each other's file rows
    - `co_stock_claims` FK with ON DELETE CASCADE (Phase 3.1) so any
      delete that bypasses the application path can't strand claims

    What's left is the local file lock — fcntl.LOCK_EX on
    `data/cases/{client_id}/.lock`. It still matters for the file-mode
    backend (single-server dev / tests without BARRY_DATABASE_URL),
    and as a same-process belt-and-braces for the Postgres backend.
    True cross-host serialization is no longer needed because every
    Postgres write is per-case + optimistic.
    """
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
