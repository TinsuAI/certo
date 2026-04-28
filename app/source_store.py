from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook, load_workbook


CATALOG_MODULES = {"material": "material_catalog", "product": "product_catalog"}
SOURCE_MODULES = {"material_catalog", "product_catalog", "bcct"}
UNIT_ALIASES = {
    "PC": "PCS",
    "PCS": "PCS",
    "PCE": "PCS",
    "PIECE": "PCS",
    "PIECES": "PCS",
    "CAI": "PCS",
    "CÁI": "PCS",
    "KG": "KG",
    "KGS": "KG",
    "EA": "EA",
    "SET": "SET",
}
DIRECTION_ALIASES = {
    "IMPORT": "import",
    "NHAP KHAU": "import",
    "NHẬP KHẨU": "import",
    "NK": "import",
    "EXPORT": "export",
    "XUAT KHAU": "export",
    "XUẤT KHẨU": "export",
    "XK": "export",
}
HEADER_ALIASES = {
    "ma_hq": "customs_code",
    "mã_hq": "customs_code",
    "ma_nvl": "customs_code",
    "mã_nvl": "customs_code",
    "ma_npl": "customs_code",
    "mã_npl": "customs_code",
    "ma_noi_bo": "internal_code",
    "mã_nội_bộ": "internal_code",
    "ten": "name",
    "tên": "name",
    "ten_hang": "name",
    "tên_hàng": "name",
    "mo_ta": "description",
    "mô_tả": "description",
    "ma_tp": "product_code",
    "mã_tp": "product_code",
    "ma_sp": "product_code",
    "mã_sp": "product_code",
    "quy_tac": "rule",
    "quy_tắc": "rule",
    "trang_thai": "status",
    "trạng_thái": "status",
    "ky": "coverage_period",
    "kỳ": "coverage_period",
    "luong": "direction",
    "luồng": "direction",
    "so_tk": "declaration_no",
    "số_tk": "declaration_no",
    "to_khai": "declaration_no",
    "tờ_khai": "declaration_no",
    "ngay_tk": "declaration_date",
    "ngày_tk": "declaration_date",
    "hai_quan": "customs_office",
    "hải_quan": "customs_office",
    "loai_hinh": "declaration_type",
    "loại_hình": "declaration_type",
    "stt_hang": "line_no",
    "stt_hàng": "line_no",
    "ma_hang": "item_code",
    "mã_hàng": "item_code",
    "ma_npl_sp": "item_code",
    "mã_npl_sp": "item_code",
    "so_luong": "quantity",
    "số_lượng": "quantity",
    "don_vi": "unit",
    "đơn_vị": "unit",
    "tri_gia": "customs_value",
    "trị_giá": "customs_value",
    "hoa_don": "invoice_ref",
    "hóa_đơn": "invoice_ref",
}


class SourceParseError(ValueError):
    pass


def get_source_workspace(client: dict) -> dict:
    material = load_module_state(client, "material_catalog")
    product = load_module_state(client, "product_catalog")
    bcct = load_module_state(client, "bcct")
    return {
        "material_catalog": module_workspace(material),
        "product_catalog": module_workspace(product),
        "bcct": module_workspace(bcct),
        "co_stock_rows": co_stock_rows_from_bcct(bcct["published_rows"]),
    }


def enrich_client_with_source_modules(client: dict) -> dict:
    workspace = get_source_workspace(client)
    client["material_catalog"] = [dict(row) for row in workspace["material_catalog"]["published_rows"]]
    client["product_catalog"] = [dict(row) for row in workspace["product_catalog"]["published_rows"]]
    client["bcct_rows"] = [display_bcct_row(row) for row in workspace["bcct"]["published_rows"]]
    client["co_stock"] = [dict(row) for row in workspace["co_stock_rows"]]
    client["counts"] = {
        **client.get("counts", {}),
        "materials": len(client["material_catalog"]),
        "products": len(client["product_catalog"]),
        "bcct": len(client["bcct_rows"]),
        "co_stock": len(client["co_stock"]),
    }
    return client


def attach_case_source_snapshot(case: dict, source_workspace: dict) -> dict:
    material = source_workspace["material_catalog"].get("latest_version") or {}
    product = source_workspace["product_catalog"].get("latest_version") or {}
    bcct = source_workspace["bcct"].get("latest_version") or {}
    reviewed_bcct_rows = [
        row for row in source_workspace["bcct"]["published_rows"]
        if row.get("review_status") == "reviewed"
    ]
    case["source_snapshot"] = {
        "material_catalog_version_id": material.get("version_id", ""),
        "material_catalog_version_no": material.get("version_no", ""),
        "product_catalog_version_id": product.get("version_id", ""),
        "product_catalog_version_no": product.get("version_no", ""),
        "bcct_version_id": bcct.get("version_id", ""),
        "bcct_version_no": bcct.get("version_no", ""),
        "bcct_reviewed_row_count": len(reviewed_bcct_rows),
        "correction_candidate_count": len(source_workspace["bcct"].get("correction_candidates", [])),
    }
    return case


def create_material_catalog_template_workbook(client: dict) -> bytes:
    return create_catalog_template_workbook(client, "material")


def create_product_catalog_template_workbook(client: dict) -> bytes:
    return create_catalog_template_workbook(client, "product")


def create_catalog_template_workbook(client: dict, catalog_type: str) -> bytes:
    module = catalog_module(catalog_type)
    workspace = get_source_workspace(client)[module]
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "NVL" if module == "material_catalog" else "TP"
    if module == "material_catalog":
        worksheet.append(["customs_code", "internal_code", "name", "hs_code", "unit", "role", "origin_default", "status"])
        for row in workspace["published_rows"]:
            worksheet.append([
                row.get("customs_code", ""),
                row.get("internal_code", ""),
                row.get("name", ""),
                row.get("hs_code", ""),
                row.get("unit", ""),
                row.get("role", ""),
                row.get("origin_default", ""),
                row.get("status", "active"),
            ])
    else:
        worksheet.append(["product_code", "name", "hs_code", "rule", "status"])
        for row in workspace["published_rows"]:
            worksheet.append([
                row.get("product_code", ""),
                row.get("name", ""),
                row.get("hs_code", ""),
                row.get("rule", ""),
                row.get("status", "active"),
            ])
    return workbook_to_bytes(workbook)


def create_bcct_template_workbook(client: dict) -> bytes:
    workspace = get_source_workspace(client)["bcct"]
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "BCCT"
    worksheet.append([
        "coverage_period",
        "direction",
        "declaration_no",
        "declaration_date",
        "customs_office",
        "declaration_type",
        "line_no",
        "item_code",
        "description",
        "hs_code",
        "quantity",
        "unit",
        "customs_value",
        "invoice_ref",
    ])
    for row in workspace["published_rows"]:
        worksheet.append([
            row.get("coverage_period", ""),
            row.get("direction", ""),
            row.get("declaration_no", ""),
            row.get("declaration_date", ""),
            row.get("customs_office", ""),
            row.get("declaration_type", ""),
            row.get("line_no", ""),
            row.get("item_code", ""),
            row.get("description", ""),
            row.get("hs_code", ""),
            row.get("quantity", ""),
            row.get("unit", ""),
            row.get("customs_value", ""),
            row.get("invoice_ref", ""),
        ])
    return workbook_to_bytes(workbook)


def process_catalog_upload(client: dict, catalog_type: str, content: bytes, filename: str, upload_scope: str = "full_catalog") -> dict:
    module = catalog_module(catalog_type)
    upload_scope = upload_scope if upload_scope in {"full_catalog", "partial_update"} else "full_catalog"
    with module_lock(client["id"], module):
        state = load_module_state(client, module)
        upload = add_upload_record(client["id"], module, state, content, filename, {"upload_scope": upload_scope})
        try:
            rows = parse_catalog_workbook(content, module)
            assert_unique_keys(rows, key_field(module))
        except SourceParseError as exc:
            upload["parse_status"] = "failed"
            upload["parse_error"] = str(exc)
            append_audit(state, f"{module}.parse.failed", {"upload_id": upload["upload_id"], "error": str(exc)})
            save_module_state(client["id"], module, state)
            return {"status": "failed", "message": str(exc), "upload": upload}

        snapshot_id = write_snapshot(client["id"], module, upload["upload_id"], rows)
        upload["parse_status"] = "parsed"
        upload["snapshot_id"] = snapshot_id
        upload["row_count"] = len(rows)

        result_rows, summary = merge_catalog_rows(state["published_rows"], rows, module, upload_scope)
        if normalized_rows_hash(result_rows) == normalized_rows_hash(state["published_rows"]):
            upload["result"] = "no_change"
            append_audit(state, f"{module}.diff.no_change", {"upload_id": upload["upload_id"]})
            save_module_state(client["id"], module, state)
            return {"status": "no_change", "message": "No catalog changes.", "summary": summary, "upload": upload}

        version = publish_version(client["id"], module, state, result_rows, upload["upload_id"], summary)
        upload["result"] = "new_version"
        upload["created_version_id"] = version["version_id"]
        append_audit(state, f"{module}.version.published", {"version_id": version["version_id"], "upload_id": upload["upload_id"]})
        save_module_state(client["id"], module, state)
        return {"status": "new_version", "message": f"Published {module} v{version['version_no']}.", "summary": summary, "upload": upload, "version": version}


def process_bcct_upload(client: dict, content: bytes, filename: str) -> dict:
    module = "bcct"
    with module_lock(client["id"], module):
        state = load_module_state(client, module)
        upload = add_upload_record(client["id"], module, state, content, filename, {"upload_scope": "append_or_review_by_transaction_key"})
        try:
            rows = parse_bcct_workbook(content)
        except SourceParseError as exc:
            upload["parse_status"] = "failed"
            upload["parse_error"] = str(exc)
            append_audit(state, "bcct.parse.failed", {"upload_id": upload["upload_id"], "error": str(exc)})
            save_module_state(client["id"], module, state)
            return {"status": "failed", "message": str(exc), "upload": upload}

        snapshot_id = write_snapshot(client["id"], module, upload["upload_id"], rows)
        upload["parse_status"] = "parsed"
        upload["snapshot_id"] = snapshot_id
        upload["row_count"] = len(rows)

        existing_by_key = {row["transaction_key"]: row for row in state["published_rows"]}
        added_rows = []
        unchanged_rows = 0
        new_candidates = []
        for row in rows:
            existing = existing_by_key.get(row["transaction_key"])
            if existing is None:
                published_row = {
                    **row,
                    "source_upload_id": upload["upload_id"],
                    "review_status": "reviewed",
                }
                if row["direction"] == "import":
                    published_row["import_row_id"] = import_row_id(row["transaction_key"])
                added_rows.append(published_row)
                existing_by_key[row["transaction_key"]] = published_row
                continue
            if bcct_rows_equal(existing, row):
                unchanged_rows += 1
                continue
            candidate = correction_candidate(existing, row, upload["upload_id"])
            if not correction_candidate_exists(state["correction_candidates"], candidate):
                new_candidates.append(candidate)

        if added_rows:
            state["published_rows"].extend(added_rows)
            state["published_rows"].sort(key=lambda row: (row["direction"], row["declaration_no"], row["line_no"], row["item_code"]))
        state["correction_candidates"].extend(new_candidates)

        summary = {
            "added_rows": len(added_rows),
            "unchanged_rows": unchanged_rows,
            "correction_candidates": len(new_candidates),
            "published_rows": len(state["published_rows"]),
        }
        upload["result"] = "review_required" if new_candidates else ("new_version" if added_rows else "no_change")
        upload["diff_summary"] = summary

        version = None
        if added_rows:
            version = publish_version(client["id"], module, state, state["published_rows"], upload["upload_id"], summary)
            upload["created_version_id"] = version["version_id"]
        append_audit(state, "bcct.diff.completed", {"upload_id": upload["upload_id"], **summary})
        save_module_state(client["id"], module, state)

        status = "review_required" if new_candidates else ("new_version" if added_rows else "no_change")
        message = "BCCT has correction candidates." if new_candidates else ("Published BCCT rows." if added_rows else "No BCCT changes.")
        return {"status": status, "message": message, "summary": summary, "upload": upload, "version": version, "correction_candidates": new_candidates}


def parse_catalog_workbook(content: bytes, module: str) -> list[dict]:
    workbook = load_workbook(BytesIO(content), data_only=True)
    worksheet = workbook["NVL"] if module == "material_catalog" and "NVL" in workbook.sheetnames else workbook.active
    worksheet = workbook["TP"] if module == "product_catalog" and "TP" in workbook.sheetnames else worksheet
    headers = [normalize_header(cell_text(cell.value)) for cell in worksheet[1]]
    rows = []
    for values in iter_rows_as_dicts(worksheet, headers):
        if module == "material_catalog":
            customs_code = cell_text(values.get("customs_code"))
            if not customs_code:
                continue
            rows.append({
                "customs_code": customs_code,
                "internal_code": cell_text(values.get("internal_code")) or customs_code,
                "name": cell_text(values.get("name") or values.get("description")),
                "hs_code": cell_text(values.get("hs_code") or values.get("hs")),
                "unit": normalize_unit(values.get("unit")),
                "role": cell_text(values.get("role")) or "NVL",
                "origin_default": cell_text(values.get("origin_default") or values.get("origin")),
                "status": normalize_status(values.get("status")),
            })
        else:
            product_code = cell_text(values.get("product_code") or values.get("customs_code"))
            if not product_code:
                continue
            rows.append({
                "product_code": product_code,
                "name": cell_text(values.get("name") or values.get("description")),
                "hs_code": cell_text(values.get("hs_code") or values.get("hs")),
                "rule": cell_text(values.get("rule") or values.get("origin_rule")),
                "status": normalize_status(values.get("status")),
            })
    if not rows:
        raise SourceParseError("Workbook has no catalog rows.")
    return rows


def parse_bcct_workbook(content: bytes) -> list[dict]:
    workbook = load_workbook(BytesIO(content), data_only=True)
    worksheet = workbook["BCCT"] if "BCCT" in workbook.sheetnames else workbook.active
    headers = [normalize_header(cell_text(cell.value)) for cell in worksheet[1]]
    rows = []
    for values in iter_rows_as_dicts(worksheet, headers):
        direction = normalize_direction(values.get("direction"))
        declaration_no = cell_text(values.get("declaration_no"))
        line_no = cell_text(values.get("line_no") or values.get("stt") or values.get("stt_hang"))
        item_code = cell_text(values.get("item_code") or values.get("material_code") or values.get("product_code"))
        if not any([direction, declaration_no, line_no, item_code]):
            continue
        if not all([direction, declaration_no, line_no, item_code]):
            raise SourceParseError("BCCT rows require direction, declaration_no, line_no, and item_code.")
        quantity = normalize_decimal(values.get("quantity") or values.get("qty"))
        unit = normalize_unit(values.get("unit") or values.get("uom"))
        row = {
            "coverage_period": cell_text(values.get("coverage_period") or values.get("period")),
            "direction": direction,
            "declaration_no": declaration_no,
            "declaration_date": cell_text(values.get("declaration_date")),
            "customs_office": cell_text(values.get("customs_office")),
            "declaration_type": cell_text(values.get("declaration_type")),
            "line_no": line_no,
            "item_code": item_code,
            "description": cell_text(values.get("description") or values.get("name")),
            "hs_code": cell_text(values.get("hs_code") or values.get("hs")),
            "quantity": quantity,
            "unit": unit,
            "customs_value": normalize_decimal(values.get("customs_value") or values.get("value")),
            "invoice_ref": cell_text(values.get("invoice_ref") or values.get("invoice")),
        }
        row["transaction_key"] = transaction_key(row)
        rows.append(row)
    if not rows:
        raise SourceParseError("Workbook has no BCCT rows.")
    assert_unique_keys(rows, "transaction_key", allow_identical=True)
    return rows


def merge_catalog_rows(existing_rows: list[dict], uploaded_rows: list[dict], module: str, upload_scope: str) -> tuple[list[dict], dict]:
    key = key_field(module)
    existing = {row[key]: dict(row) for row in existing_rows}
    uploaded = {row[key]: dict(row) for row in uploaded_rows}
    result = {}
    added = changed = unchanged = inactive_pending_review = 0

    if upload_scope == "partial_update":
        result = {row_key: dict(row) for row_key, row in existing.items()}
        for row_key, row in uploaded.items():
            if row_key not in existing:
                added += 1
            elif normalized_row(row) != normalized_row(existing[row_key]):
                changed += 1
            else:
                unchanged += 1
            result[row_key] = row
    else:
        for row_key, row in uploaded.items():
            if row_key not in existing:
                added += 1
            elif normalized_row(row) != normalized_row(existing[row_key]):
                changed += 1
            else:
                unchanged += 1
            result[row_key] = row
        for row_key, row in existing.items():
            if row_key not in uploaded:
                retained = dict(row)
                if retained.get("status") != "inactive_pending_review":
                    inactive_pending_review += 1
                retained["status"] = "inactive_pending_review"
                result[row_key] = retained

    return sorted(result.values(), key=lambda row: row[key]), {
        "added": added,
        "changed": changed,
        "unchanged": unchanged,
        "inactive_pending_review": inactive_pending_review,
        "total_rows": len(result),
    }


def load_module_state(client: dict, module: str) -> dict:
    path = state_path(client["id"], module)
    if path.exists():
        return migrate_state(read_json(path), client, module)
    state = seed_module_state(client, module)
    save_module_state(client["id"], module, state)
    return state


def seed_module_state(client: dict, module: str) -> dict:
    rows = seed_rows(client, module)
    state = {
        "schema_version": 1,
        "client_id": client["id"],
        "module": module,
        "published_rows": rows,
        "versions": [],
        "uploads": [],
        "correction_candidates": [],
        "audit_events": [],
        "next_version_no": 1,
    }
    if rows:
        publish_version(client["id"], module, state, rows, "", {"seeded_rows": len(rows)})
        append_audit(state, f"{module}.version.seeded", {"rows": len(rows)})
    return state


def seed_rows(client: dict, module: str) -> list[dict]:
    if module == "material_catalog":
        return [normalize_seed_material(row) for row in client.get("material_catalog", [])]
    if module == "product_catalog":
        return [normalize_seed_product(row) for row in client.get("product_catalog", [])]
    rows = []
    for index, row in enumerate(client.get("bcct_rows", []), start=1):
        normalized = normalize_seed_bcct(row, index)
        if normalized:
            rows.append(normalized)
    return rows


def normalize_seed_material(row: dict) -> dict:
    customs_code = cell_text(row.get("customs_code"))
    return {
        "customs_code": customs_code,
        "internal_code": cell_text(row.get("internal_code")) or customs_code,
        "name": cell_text(row.get("name")),
        "hs_code": cell_text(row.get("hs_code")),
        "unit": normalize_unit(row.get("unit")),
        "role": cell_text(row.get("role")) or "NVL",
        "origin_default": cell_text(row.get("origin_default")),
        "status": normalize_status(row.get("status")),
    }


def normalize_seed_product(row: dict) -> dict:
    return {
        "product_code": cell_text(row.get("product_code")),
        "name": cell_text(row.get("name")),
        "hs_code": cell_text(row.get("hs_code")),
        "rule": cell_text(row.get("rule")),
        "status": normalize_status(row.get("status")),
    }


def normalize_seed_bcct(row: dict, index: int) -> dict:
    direction = normalize_direction(row.get("direction"))
    declaration_no = cell_text(row.get("declaration_no"))
    item_code = cell_text(row.get("item_code"))
    if not direction or not declaration_no or not item_code:
        return {}
    normalized = {
        "coverage_period": cell_text(row.get("period") or row.get("coverage_period")),
        "direction": direction,
        "declaration_no": declaration_no,
        "declaration_date": cell_text(row.get("declaration_date")),
        "customs_office": cell_text(row.get("customs_office")),
        "declaration_type": cell_text(row.get("declaration_type")),
        "line_no": cell_text(row.get("line_no") or index),
        "item_code": item_code,
        "description": cell_text(row.get("description")),
        "hs_code": cell_text(row.get("hs_code")),
        "quantity": normalize_decimal(row.get("qty") or row.get("quantity")),
        "unit": normalize_unit(row.get("unit")),
        "customs_value": normalize_decimal(row.get("customs_value")),
        "invoice_ref": cell_text(row.get("invoice_ref")),
        "source_upload_id": "",
        "review_status": "reviewed",
    }
    normalized["transaction_key"] = transaction_key(normalized)
    if normalized["direction"] == "import":
        normalized["import_row_id"] = import_row_id(normalized["transaction_key"])
    return normalized


def publish_version(client_id: str, module: str, state: dict, rows: list[dict], upload_id: str, summary: dict) -> dict:
    version_no = state["next_version_no"]
    rows_hash = normalized_rows_hash(rows)
    version = {
        "version_id": f"{module}-v{version_no}-{rows_hash[:10]}",
        "version_no": version_no,
        "created_at": now_iso(),
        "source_upload_id": upload_id,
        "row_count": len(rows),
        "rows_hash": rows_hash,
        "summary": summary,
    }
    state["next_version_no"] += 1
    state["latest_version"] = version
    state["published_rows"] = [dict(row) for row in rows]
    state["versions"].insert(0, version)
    version_dir = module_root(client_id, module) / "versions" / f"v{version_no}"
    write_json(version_dir / "version.json", version)
    write_json(version_dir / "rows.json", rows)
    write_json(version_dir / "diff.json", summary)
    return version


def add_upload_record(client_id: str, module: str, state: dict, content: bytes, filename: str, extra: dict) -> dict:
    upload_id = make_id("upload")
    upload_dir = module_root(client_id, module) / "uploads" / upload_id
    raw_dir = upload_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name or "upload.xlsx"
    (raw_dir / safe_name).write_bytes(content)
    upload = {
        "upload_id": upload_id,
        "filename": safe_name,
        "created_at": now_iso(),
        "content_sha256": hashlib.sha256(content).hexdigest(),
        **extra,
    }
    state["uploads"].insert(0, upload)
    append_audit(state, f"{module}.uploaded", {"upload_id": upload_id, "filename": safe_name})
    return upload


def write_snapshot(client_id: str, module: str, upload_id: str, rows: list[dict]) -> str:
    snapshot_id = make_id("snapshot")
    snapshot_dir = module_root(client_id, module) / "snapshots" / snapshot_id
    write_json(snapshot_dir / "snapshot.json", {"snapshot_id": snapshot_id, "upload_id": upload_id, "row_count": len(rows), "created_at": now_iso()})
    write_json(snapshot_dir / "rows.json", rows)
    return snapshot_id


def co_stock_rows_from_bcct(rows: list[dict]) -> list[dict]:
    output = []
    for row in rows:
        if row.get("direction") != "import":
            continue
        quantity = row.get("quantity", "")
        output.append({
            "source_row": row.get("import_row_id") or import_row_id(row["transaction_key"]),
            "import_declaration_no": row.get("declaration_no", ""),
            "line_no": row.get("line_no", ""),
            "material_code": row.get("item_code", ""),
            "available_qty": quantity,
            "used_qty": "0",
            "remaining_qty": quantity,
        })
    return output


def display_bcct_row(row: dict) -> dict:
    return {
        "period": row.get("coverage_period", ""),
        "declaration_no": row.get("declaration_no", ""),
        "direction": "Nhập khẩu" if row.get("direction") == "import" else "Xuất khẩu",
        "item_code": row.get("item_code", ""),
        "qty": row.get("quantity", ""),
        "line_no": row.get("line_no", ""),
        "transaction_key": row.get("transaction_key", ""),
        "review_status": row.get("review_status", ""),
    }


def module_workspace(state: dict) -> dict:
    return {
        "module": state["module"],
        "published_rows": [dict(row) for row in state["published_rows"]],
        "latest_version": state.get("latest_version"),
        "versions": [dict(version) for version in state["versions"]],
        "uploads": [dict(upload) for upload in state["uploads"]],
        "correction_candidates": [dict(candidate) for candidate in state.get("correction_candidates", [])],
        "audit_events": [dict(event) for event in state.get("audit_events", [])],
    }


def assert_unique_keys(rows: list[dict], field: str, allow_identical: bool = False) -> None:
    seen = {}
    conflicts = []
    for row in rows:
        key = row[field]
        prior = seen.get(key)
        if prior is None:
            seen[key] = row
            continue
        if allow_identical and normalized_row(prior) == normalized_row(row):
            continue
        conflicts.append(key)
    if conflicts:
        raise SourceParseError(f"Duplicate row keys: {', '.join(conflicts[:5])}")


def bcct_rows_equal(existing: dict, incoming: dict) -> bool:
    fields = [
        "direction",
        "declaration_no",
        "declaration_date",
        "customs_office",
        "declaration_type",
        "line_no",
        "item_code",
        "description",
        "hs_code",
        "quantity",
        "unit",
        "customs_value",
        "invoice_ref",
    ]
    return {field: cell_text(existing.get(field)) for field in fields} == {field: cell_text(incoming.get(field)) for field in fields}


def correction_candidate(existing: dict, incoming: dict, upload_id: str) -> dict:
    return {
        "candidate_id": make_id("correction"),
        "status": "correction_candidate",
        "transaction_key": incoming["transaction_key"],
        "created_at": now_iso(),
        "source_upload_id": upload_id,
        "existing_row": dict(existing),
        "incoming_row": dict(incoming),
    }


def correction_candidate_exists(candidates: list[dict], candidate: dict) -> bool:
    incoming_hash = normalized_rows_hash([candidate["incoming_row"]])
    for existing in candidates:
        if existing.get("transaction_key") != candidate["transaction_key"]:
            continue
        if normalized_rows_hash([existing.get("incoming_row", {})]) == incoming_hash:
            return True
    return False


def iter_rows_as_dicts(worksheet, headers: list[str]):
    for row in worksheet.iter_rows(min_row=2, values_only=True):
        values = {headers[index]: row[index] for index in range(min(len(headers), len(row))) if headers[index]}
        if any(cell_text(value) for value in values.values()):
            yield values


def key_field(module: str) -> str:
    return "customs_code" if module == "material_catalog" else "product_code"


def catalog_module(catalog_type: str) -> str:
    if catalog_type in CATALOG_MODULES:
        return CATALOG_MODULES[catalog_type]
    if catalog_type in CATALOG_MODULES.values():
        return catalog_type
    raise SourceParseError(f"Unknown catalog type: {catalog_type}")


def transaction_key(row: dict) -> str:
    return "||".join([row["direction"], row["declaration_no"], row["line_no"], row["item_code"]])


def import_row_id(transaction_key_value: str) -> str:
    return f"import-row-{hashlib.sha1(transaction_key_value.encode('utf-8')).hexdigest()[:16]}"


def normalize_header(value: str) -> str:
    header = cell_text(value).lower().strip().replace(" ", "_").replace(".", "_").replace("/", "_")
    return HEADER_ALIASES.get(header, header)


def normalize_status(value) -> str:
    status = cell_text(value)
    return status or "active"


def normalize_direction(value) -> str:
    direction = cell_text(value)
    return DIRECTION_ALIASES.get(direction.upper(), direction.lower())


def normalize_unit(value) -> str:
    unit = cell_text(value).upper()
    return UNIT_ALIASES.get(unit, unit)


def normalize_decimal(value) -> str:
    text = cell_text(value)
    if not text:
        return ""
    try:
        decimal = Decimal(text)
    except InvalidOperation:
        return text
    if decimal == decimal.to_integral():
        return str(decimal.quantize(Decimal("1")))
    return format(decimal.normalize(), "f")


def cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def normalized_row(row: dict) -> dict:
    return {key: cell_text(value) for key, value in sorted(row.items()) if key not in {"source_upload_id", "review_status", "import_row_id"}}


def normalized_rows_hash(rows: list[dict]) -> str:
    payload = [normalized_row(row) for row in rows]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def append_audit(state: dict, event: str, details: dict) -> None:
    state.setdefault("audit_events", []).insert(0, {"event": event, "created_at": now_iso(), "details": details})


def migrate_state(state: dict, client: dict, module: str) -> dict:
    state.setdefault("schema_version", 1)
    state.setdefault("client_id", client["id"])
    state.setdefault("module", module)
    state.setdefault("published_rows", [])
    state.setdefault("versions", [])
    state.setdefault("uploads", [])
    state.setdefault("correction_candidates", [])
    state.setdefault("audit_events", [])
    state.setdefault("next_version_no", len(state["versions"]) + 1)
    state["next_version_no"] = max(state["next_version_no"], len(state["versions"]) + 1)
    if state["versions"] and "latest_version" not in state:
        state["latest_version"] = state["versions"][0]
    return state


def save_module_state(client_id: str, module: str, state: dict) -> None:
    write_json(state_path(client_id, module), state)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_name, path)


def workbook_to_bytes(workbook: Workbook) -> bytes:
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


@contextmanager
def module_lock(client_id: str, module: str):
    root = module_root(client_id, module)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".lock"
    with lock_path.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def state_path(client_id: str, module: str) -> Path:
    return module_root(client_id, module) / "state.json"


def module_root(client_id: str, module: str) -> Path:
    if module not in SOURCE_MODULES:
        raise SourceParseError(f"Unknown source module: {module}")
    return source_root() / "clients" / client_id / module.replace("_", "-")


def source_root() -> Path:
    return Path(os.environ.get("SOURCE_STORE_ROOT", "data/local/source-modules"))


def make_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:8]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
