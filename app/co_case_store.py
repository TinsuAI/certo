from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook


MAX_SUPPORTING_FILE_BYTES = 20 * 1024 * 1024
ALLOWED_SUPPORTING_SUFFIXES = {".pdf", ".xlsx", ".xls", ".xlsm", ".doc", ".docx", ".jpg", ".jpeg", ".png"}


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
        record = {
            "case_id": case_id,
            "client_id": client["id"],
            "title": clean_text(form.get("title")) or f"Hồ sơ C/O {client['name']}",
            "case_code": clean_text(form.get("case_code")) or "Chưa nhập",
            "destination_market": clean_text(form.get("destination_market")) or "Chưa nhập",
            "agreement": clean_text(form.get("agreement")),
            "co_form_type": clean_text(form.get("co_form_type")),
            "rule": clean_text(form.get("rule")),
            "shipment": {
                "invoice_no": clean_text(form.get("invoice_no")),
                "bill_of_lading_no": clean_text(form.get("bill_of_lading_no")),
            },
            "supporting_files": [],
            "created_at": created_at,
            "updated_at": created_at,
        }
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
        for key in ["title", "case_code", "destination_market", "agreement", "co_form_type", "rule"]:
            if clean_text(case.get(key)):
                record[key] = clean_text(case.get(key))
        shipment = case.get("shipment", {})
        record.setdefault("shipment", {})
        record["shipment"]["invoice_no"] = clean_text(shipment.get("invoice_no"))
        record["shipment"]["bill_of_lading_no"] = clean_text(shipment.get("bill_of_lading_no"))
        record["updated_at"] = now_iso()
        save_state(client["id"], state)
        return dict(record)


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
    case["source_label"] = f"Hồ sơ lưu local: {case['case_code']}"
    case["shipment"] = dict(record.get("shipment", {}))
    case["supporting_files"] = [dict(file_row) for file_row in record.get("supporting_files", [])]
    return case


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
        safe_name = safe_filename(filename or "supporting-file")
        upload_dir = case_upload_root(client["id"], case_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{upload_id}-{safe_name}"
        stored_path = upload_dir / stored_name
        stored_path.write_bytes(content)

        invoice = clean_text(invoice_no) or extract_invoice_hint(filename)
        bill = clean_text(bill_of_lading_no)
        if invoice:
            record.setdefault("shipment", {})["invoice_no"] = invoice
        if bill:
            record.setdefault("shipment", {})["bill_of_lading_no"] = bill

        file_row = {
            "upload_id": upload_id,
            "slot": clean_text(document_slot) or "other",
            "filename": safe_name,
            "stored_path": str(stored_path.relative_to(case_root(client["id"]))),
            "size_bytes": len(content),
            "invoice_no": invoice,
            "bill_of_lading_no": bill,
            "uploaded_at": uploaded_at,
        }
        record.setdefault("supporting_files", []).append(file_row)
        record["updated_at"] = uploaded_at
        save_state(client["id"], state)
        return dict(file_row)


def match_case_bcct_exports(case: dict, source_workspace: dict, client_config: dict) -> list[dict]:
    invoice_no = clean_text(case.get("shipment", {}).get("invoice_no"))
    if not invoice_no:
        return []
    invoice_tokens = invoice_keys(invoice_no)
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
        if not invoice_tokens.intersection(row_tokens):
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
            "invoice_ref": row.get("invoice_ref", ""),
            "transaction_key": row.get("transaction_key", ""),
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
    matches_sheet.append(["Declaration", "Line", "Type", "Item code", "HS", "Quantity", "Unit", "Invoice"])
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

    from io import BytesIO

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


def invoice_keys(value: str) -> set[str]:
    text = clean_text(value).upper()
    if not text:
        return set()
    compact = re.sub(r"[^A-Z0-9]", "", text)
    parts = {re.sub(r"[^A-Z0-9]", "", part) for part in re.split(r"[,;/\s]+", text)}
    return {part for part in {compact, *parts} if part}


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
    path = state_path(client_id)
    if not path.exists():
        return {"schema_version": 1, "client_id": client_id, "cases": []}
    state = json.loads(path.read_text())
    state.setdefault("schema_version", 1)
    state.setdefault("client_id", client_id)
    state.setdefault("cases", [])
    return state


def save_state(client_id: str, state: dict) -> None:
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


def safe_filename(filename: str) -> str:
    name = Path(filename).name.strip() or "upload"
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .") or "upload"


def clean_text(value) -> str:
    return str(value or "").strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
