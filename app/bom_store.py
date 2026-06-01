from __future__ import annotations

import fcntl
import hashlib
import json
import mimetypes
import os
import re
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

from app.workflow_state_store import get_bom_state_store
from app.bom_workbook_io import (
    GROWATT_REQUIRED_HEADERS,
    JOHNSON_REQUIRED_HEADERS,
    MANUAL_HEADER_ALIASES,
    cell_text,
    header_key,
    normalized_bom_row,
    parse_bom_workbook,
    parse_growatt_workbook,
    parse_int,
    parse_johnson_workbook,
    parse_manual_flat_workbook,
    quantity_text,
)
from app.bom_composition import (
    compose_rows_from_composition,
    compose_rows_from_product_versions,
    composition_entry,
    flattened_product_versions,
    group_rows_by_product,
    latest_composition_map,
    latest_product_version,
    latest_published_version,
    product_version_options_by_code,
    with_aggregate_rows,
)


BOM_PROFILE_OPTIONS = [
    {"value": "manual_flat", "label": "Manual flat BOM"},
    {"value": "growatt_multi_workbook", "label": "Growatt multi-workbook"},
    {"value": "johnson_sap_exploded", "label": "Johnson SAP exploded"},
]

UPLOAD_MODE_OPTIONS = [
    {"value": "direct_bom", "label": "Upload BOM trực tiếp"},
    {"value": "technical_bom", "label": "Upload BOM kỹ thuật"},
]

UPLOAD_SCOPE_OPTIONS = [
    {"value": "full_aggregate", "label": "BOM tổng hợp đầy đủ"},
    {"value": "partial_product", "label": "Chỉ cập nhật TP trong file"},
]

CODE_SYSTEM_OPTIONS = [
    {"value": "single_code", "label": "Một mã"},
    {"value": "customs_internal_mapping_required", "label": "Cần map mã HQ/nội bộ"},
]


class BomParseError(ValueError):
    pass


def get_bom_workspace(client: dict) -> dict:
    state = load_state(client)
    latest = with_aggregate_rows(state, latest_published_version(state))
    product_versions = flattened_product_versions(state)
    return {
        "config": state["config"],
        "versions": sorted(state["versions"], key=lambda row: row["version_no"], reverse=True),
        "product_versions": product_versions,
        "product_version_options_by_code": product_version_options_by_code(product_versions),
        "product_composition": latest.get("product_versions", []),
        "uploads": sorted(state["uploads"], key=lambda row: row["created_at"], reverse=True),
        "audit": list(reversed(state["audit"][-12:])),
        "latest_version": latest,
        "latest_rows": latest.get("rows", []),
        "profile_options": BOM_PROFILE_OPTIONS,
        "upload_mode_options": UPLOAD_MODE_OPTIONS,
        "upload_scope_options": UPLOAD_SCOPE_OPTIONS,
        "code_system_options": CODE_SYSTEM_OPTIONS,
    }


def update_bom_config(client: dict, form: dict[str, str]) -> dict:
    with client_store_lock(client["id"]):
        state = ensure_persisted_state(client)
        config = state["config"]
        config["bom_profile"] = clean_choice(form.get("bom_profile"), {row["value"] for row in BOM_PROFILE_OPTIONS}, config["bom_profile"])
        config["default_import_mode"] = clean_choice(
            form.get("default_import_mode"),
            {row["value"] for row in UPLOAD_MODE_OPTIONS},
            config["default_import_mode"],
        )
        config["code_system_mode"] = clean_choice(
            form.get("code_system_mode"),
            {row["value"] for row in CODE_SYSTEM_OPTIONS},
            config["code_system_mode"],
        )
        config["updated_at"] = now_iso()
        append_audit(state, "bom.config.updated", {"config": config})
        save_state(client["id"], state)
        return state


def process_bom_upload(
    client: dict,
    content: bytes,
    filename: str,
    upload_mode: str,
    upload_scope: str | None = None,
    accept_review_required: bool = False,
) -> dict:
    with client_store_lock(client["id"]):
        return _process_bom_upload(client, content, filename, upload_mode, upload_scope, accept_review_required)


def _process_bom_upload(
    client: dict,
    content: bytes,
    filename: str,
    upload_mode: str,
    upload_scope: str | None,
    accept_review_required: bool,
) -> dict:
    state = ensure_persisted_state(client)
    config = state["config"]
    upload_mode = clean_choice(upload_mode, {row["value"] for row in UPLOAD_MODE_OPTIONS}, config["default_import_mode"])
    upload_scope = clean_choice(upload_scope, {row["value"] for row in UPLOAD_SCOPE_OPTIONS}, default_upload_scope(upload_mode))
    profile = "manual_flat" if upload_mode == "direct_bom" else config["bom_profile"]
    content_sha256 = hashlib.sha256(content).hexdigest()
    duplicate_upload = next((row for row in state["uploads"] if row["content_sha256"] == content_sha256), None)

    upload_id = make_id("upload", content_sha256)
    upload_dir = client_root(client["id"]) / "uploads" / upload_id
    raw_dir = upload_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    original_filename = Path(filename or "bom.xlsx").name.strip() or "bom.xlsx"
    safe_name = safe_filename(original_filename)
    stored_filename = f"{upload_id}-{safe_name}"
    raw_path = raw_dir / stored_filename
    raw_path.write_bytes(content)
    relative_storage_path = str(raw_path.relative_to(client_root(client["id"])))
    mime_type = mimetypes.guess_type(original_filename)[0] or "application/octet-stream"

    upload_record = {
        "upload_id": upload_id,
        "original_filename": original_filename,
        "safe_filename": safe_name,
        "stored_filename": stored_filename,
        "content_sha256": content_sha256,
        "size_bytes": len(content),
        "file_size": len(content),
        "stored_path": relative_storage_path,
        "storage_path": relative_storage_path,
        "storage_backend": "filesystem",
        "file_ext": Path(original_filename).suffix.lower(),
        "mime_type": mime_type,
        "content_type": mime_type,
        "profile_used": profile,
        "upload_mode": upload_mode,
        "upload_scope": upload_scope,
        "accept_review_required": accept_review_required,
        "parse_status": "pending",
        "created_at": now_iso(),
    }
    state["uploads"].append(upload_record)
    append_audit(state, "bom.uploaded", {"upload_id": upload_id, "filename": filename, "profile": profile})

    if duplicate_upload:
        upload_record["duplicate_of"] = duplicate_upload["upload_id"]
        append_audit(state, "bom.upload.duplicate_detected", {"upload_id": upload_id, "duplicate_of": duplicate_upload["upload_id"]})

    try:
        parsed_rows = parse_bom_workbook(content, filename, profile, upload_mode)
    except BomParseError as exc:
        upload_record["parse_status"] = "failed"
        upload_record["parse_error"] = str(exc)
        append_audit(state, "bom.parse.failed", {"upload_id": upload_id, "error": str(exc)})
        save_state(client["id"], state)
        return {"status": "failed", "message": str(exc), "upload": upload_record}

    duplicates = duplicate_row_keys(parsed_rows)
    if duplicates:
        message = "BOM có dòng trùng khóa TP/BOM/NVL/ĐVT. Hãy gộp hoặc tách mã BOM rõ ràng trước khi publish."
        upload_record["parse_status"] = "failed"
        upload_record["parse_error"] = message
        upload_record["duplicate_rows"] = duplicates[:20]
        append_audit(state, "bom.parse.failed", {"upload_id": upload_id, "error": message, "duplicates": duplicates[:20]})
        save_state(client["id"], state)
        return {"status": "failed", "message": message, "upload": upload_record, "duplicate_rows": duplicates[:20]}

    snapshot_hash = hash_rows(parsed_rows)
    snapshot_id = make_id("snapshot", snapshot_hash)
    upload_record["parse_status"] = "parsed"
    upload_record["snapshot_id"] = snapshot_id
    upload_record["normalized_hash"] = snapshot_hash
    upload_record["row_count"] = len(parsed_rows)
    append_audit(state, "bom.parse.completed", {"upload_id": upload_id, "snapshot_id": snapshot_id, "row_count": len(parsed_rows)})
    state.setdefault("snapshot_rows", {})[snapshot_id] = [dict(row) for row in parsed_rows]

    if write_bom_artifacts():
        snapshot_dir = client_root(client["id"]) / "snapshots" / snapshot_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        write_json(snapshot_dir / "snapshot.json", {
            "snapshot_id": snapshot_id,
            "upload_id": upload_id,
            "client_id": client["id"],
            "profile": profile,
            "upload_mode": upload_mode,
            "normalized_hash": snapshot_hash,
            "row_count": len(parsed_rows),
            "created_at": now_iso(),
        })
        write_json(snapshot_dir / "rows.json", parsed_rows)

    if requires_review_before_publish(parsed_rows, upload_mode, profile) and not accept_review_required:
        upload_record["parse_status"] = "review_required"
        upload_record["result"] = "review_required"
        append_audit(state, "bom.publish.blocked_for_review", {"upload_id": upload_id, "profile": profile})
        save_state(client["id"], state)
        return {
            "status": "review_required",
            "message": "BOM kỹ thuật Growatt đã parse nhưng còn cần review flatten leaf/BTP. Tick chấp nhận flat hiện tại nếu muốn publish demo.",
            "upload": upload_record,
            "diff": {"summary": {"added": 0, "removed": 0, "changed": 0, "unchanged": 0, "changed_products": 0}, "has_material_change": False},
            "product_results": [],
        }

    parsed_groups = group_rows_by_product(parsed_rows)
    latest = with_aggregate_rows(state, latest_published_version(state))
    latest_map = latest_composition_map(state)
    composition_map = {} if upload_scope == "full_aggregate" else dict(latest_map)
    product_results = []
    changed_product_versions = []
    for product_code, product_rows in parsed_groups.items():
        previous_product_version = latest_product_version(state, product_code)
        previous_rows = previous_product_version.get("rows", []) if previous_product_version else []
        diff = diff_rows(previous_rows, product_rows)
        product_result = {
            "product_code": product_code,
            "status": "no_change",
            "previous_version_no": previous_product_version.get("product_version_no", 0) if previous_product_version else 0,
            "new_version_no": previous_product_version.get("product_version_no", 0) if previous_product_version else 0,
            "diff_summary": diff["summary"],
        }
        if diff["has_material_change"]:
            product_version = publish_product_version(
                state,
                client,
                product_code,
                product_rows,
                diff,
                snapshot_id,
                upload_id,
                profile,
            )
            product_result.update({
                "status": "new_version",
                "new_version_no": product_version["product_version_no"],
                "product_version_id": product_version["product_version_id"],
            })
            changed_product_versions.append(product_version)
            composition_map[product_code] = composition_entry(product_version)
        elif previous_product_version:
            if product_code not in latest_map:
                product_result["status"] = "reinstated"
            composition_map[product_code] = composition_entry(previous_product_version)
        product_results.append(product_result)

    if upload_scope == "full_aggregate":
        for product_code in sorted(set(latest_map) - set(parsed_groups)):
            previous_entry = latest_map[product_code]
            product_results.append({
                "product_code": product_code,
                "status": "retired",
                "previous_version_no": previous_entry.get("product_version_no", 0),
                "new_version_no": 0,
                "diff_summary": {
                    "added": 0,
                    "removed": previous_entry.get("row_count", 0),
                    "changed": 0,
                    "unchanged": 0,
                },
            })

    upload_record["product_results"] = product_results
    upload_record["diff_summary"] = merge_diff_summaries(product_results)
    append_audit(state, "bom.diff.completed", {"upload_id": upload_id, "products": product_results})

    composition = sorted(composition_map.values(), key=lambda row: row["product_code"])
    aggregate_rows = compose_rows_from_composition(state, composition)
    aggregate_diff = diff_rows(latest.get("rows", []), aggregate_rows)
    aggregate_diff["summary"]["changed_products"] = upload_record["diff_summary"]["changed_products"]
    composition_hash = hash_aggregate_composition(composition)
    latest_composition_hash = latest.get("composition_hash") or hash_aggregate_composition(latest.get("product_versions", []))
    composition_changed = composition_hash != latest_composition_hash

    if not changed_product_versions and not composition_changed:
        upload_record["result"] = "no_material_change"
        save_state(client["id"], state)
        return {
            "status": "no_change",
            "message": "File đã parse thành công. Không có thay đổi BOM nên không tạo artifact mới.",
            "upload": upload_record,
            "diff": {"summary": upload_record["diff_summary"], "has_material_change": False},
            "product_results": product_results,
        }

    next_version_no = max((version["version_no"] for version in state["versions"]), default=0) + 1
    previous_version_id = latest.get("version_id", "")
    for version in state["versions"]:
        if version["status"] == "published":
            version["status"] = "superseded"

    refresh_product_version_statuses(state, composition)
    composition = refresh_composition_entries(state, composition)
    version_id = f"bom-v{next_version_no}-{composition_hash[:10]}"
    new_version = {
        "version_id": version_id,
        "version_no": next_version_no,
        "aggregate_version_no": next_version_no,
        "status": "published",
        "source_snapshot_id": snapshot_id,
        "source_upload_id": upload_id,
        "previous_version_id": previous_version_id,
        "version_hash": composition_hash,
        "composition_hash": composition_hash,
        "product_versions": composition,
        "changed_products": [result["product_code"] for result in product_results if result["status"] != "no_change"],
        "row_count": len(aggregate_rows),
        "diff_summary": aggregate_diff["summary"],
        "created_by": "demo-user",
        "published_by": "demo-user",
        "created_at": now_iso(),
        "published_at": now_iso(),
        "rows": aggregate_rows,
    }
    state["versions"].append(new_version)
    upload_record["result"] = "new_version"
    upload_record["created_version_id"] = version_id
    upload_record["created_aggregate_version_no"] = next_version_no

    if write_bom_artifacts():
        version_dir = client_root(client["id"]) / "versions" / f"v{next_version_no}"
        version_dir.mkdir(parents=True, exist_ok=True)
        write_json(version_dir / "version.json", {key: value for key, value in new_version.items() if key != "rows"})
        write_json(version_dir / "rows.json", aggregate_rows)
        write_json(version_dir / "diff.json", aggregate_diff)

    append_audit(state, "bom.aggregate_version.published", {
        "version_id": version_id,
        "version_no": next_version_no,
        "upload_id": upload_id,
        "changed_products": [result["product_code"] for result in product_results if result["status"] != "no_change"],
    })
    save_state(client["id"], state)
    product_version_text = ", ".join(
        product_result_text(result)
        for result in product_results
        if result["status"] != "no_change"
    )
    return {
        "status": "new_version",
        "message": f"Đã tạo BOM composition #{next_version_no}. TP đổi artifact: {product_version_text}.",
        "upload": upload_record,
        "version": new_version,
        "diff": aggregate_diff,
        "product_results": product_results,
    }


def create_bom_template_workbook(client: dict) -> bytes:
    state = load_state(client)
    rows = with_aggregate_rows(state, latest_published_version(state)).get("rows", [])
    wb = Workbook()
    ws = wb.active
    ws.title = "BOM"
    ws.append(["product_code", "bom_code", "bom_variant_id", "material_code", "material_name", "qty_per", "uom", "scrap_rate"])
    for row in rows:
        ws.append([
            row.get("product_code", ""),
            row.get("bom_code", ""),
            row.get("bom_variant_id", ""),
            row.get("material_code", ""),
            row.get("material_name", ""),
            row.get("qty_per", ""),
            row.get("uom", ""),
            row.get("scrap_rate", ""),
        ])
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def seed_rows_from_client(client: dict) -> list[dict]:
    return [
        normalized_bom_row(
            product_code=row.get("product_code", ""),
            bom_code=row.get("product_code", ""),
            bom_variant_id=row.get("version", "seed"),
            material_code=row.get("material_code", ""),
            material_name=row.get("material_name", ""),
            qty_per=row.get("qty_per", "0"),
            uom=row.get("uom", ""),
            scrap_rate=row.get("scrap_rate", ""),
            source=row.get("source", "seed"),
            row_class=row.get("state", "seed"),
        )
        for row in client.get("bom_rows", [])
    ]


def load_state(client: dict) -> dict:
    store = get_bom_state_store()
    if store:
        state = store.get_state(client["id"])
        if state is not None:
            return normalize_state(client, state)
    path = state_path(client["id"])
    if path.exists():
        state = normalize_state(client, json.loads(path.read_text()))
    else:
        state = seed_state(client)
    if store:
        store.save_state(client["id"], state)
    return state


def ensure_persisted_state(client: dict) -> dict:
    store = get_bom_state_store()
    if store:
        state = store.get_state(client["id"])
        if state is not None:
            return normalize_state(client, state)
    path = state_path(client["id"])
    if path.exists():
        raw_state = json.loads(path.read_text())
        state = normalize_state(client, raw_state)
        if raw_state.get("schema_version") != 2 or "product_versions" not in raw_state:
            save_state(client["id"], state)
        return state
    state = seed_state(client)
    save_state(client["id"], state)
    return state


def seed_state(client: dict) -> dict:
    rows = seed_rows_from_client(client)
    created_at = now_iso()
    product_versions = {}
    for product_code, product_rows in group_rows_by_product(rows).items():
        version_hash = hash_rows(product_rows)
        product_version = {
            "product_version_id": f"tp-{safe_filename(product_code)}-v1-{version_hash[:10]}",
            "version_id": f"tp-{safe_filename(product_code)}-v1-{version_hash[:10]}",
            "product_code": product_code,
            "product_version_no": 1,
            "version_no": 1,
            "status": "current",
            "source_snapshot_id": "seed",
            "source_upload_id": "",
            "previous_product_version_id": "",
            "version_hash": version_hash,
            "row_count": len(product_rows),
            "diff_summary": {"seeded": len(product_rows)},
            "created_by": "seed",
            "published_by": "seed",
            "created_at": created_at,
            "published_at": created_at,
            "rows": product_rows,
        }
        product_versions[product_code] = [product_version]
    composition = [
        composition_entry(version)
        for versions in product_versions.values()
        for version in versions
        if version["status"] == "current"
    ]
    composition.sort(key=lambda row: row["product_code"])
    aggregate_rows = compose_rows_from_product_versions(product_versions, composition)
    composition_hash = hash_aggregate_composition(composition)
    state = {
        "schema_version": 2,
        "client_id": client["id"],
        "config": default_config(client, created_at),
        "product_versions": product_versions,
        "versions": [
            {
                "version_id": f"seed-v1-{composition_hash[:10]}",
                "version_no": 1,
                "aggregate_version_no": 1,
                "status": "published",
                "source_snapshot_id": "seed",
                "source_upload_id": "",
                "previous_version_id": "",
                "version_hash": composition_hash,
                "composition_hash": composition_hash,
                "product_versions": composition,
                "changed_products": [row["product_code"] for row in composition],
                "row_count": len(aggregate_rows),
                "diff_summary": {"seeded": len(aggregate_rows), "changed_products": len(composition)},
                "created_by": "seed",
                "published_by": "seed",
                "created_at": created_at,
                "published_at": created_at,
                "rows": aggregate_rows,
            }
        ],
        "uploads": [],
        "audit": [
            {
                "event": "bom.version.seeded",
                "at": created_at,
                "actor": "system",
                "details": {"row_count": len(aggregate_rows), "composition_hash": composition_hash},
            }
        ],
    }
    return state


def normalize_state(client: dict, state: dict) -> dict:
    if state.get("schema_version") == 2 and "product_versions" in state:
        return state

    created_at = now_iso()
    product_versions: dict[str, list[dict]] = {}
    aggregate_versions = []
    for aggregate in sorted(state.get("versions", []), key=lambda row: row.get("version_no", 0)):
        composition = []
        for product_code, product_rows in group_rows_by_product(aggregate.get("rows", [])).items():
            version_hash = hash_rows(product_rows)
            existing = next(
                (version for version in product_versions.get(product_code, []) if version["version_hash"] == version_hash),
                None,
            )
            if existing:
                product_version = existing
            else:
                previous = latest_product_version({"product_versions": product_versions}, product_code)
                diff = diff_rows(previous.get("rows", []) if previous else [], product_rows)
                product_version_no = max(
                    (version["product_version_no"] for version in product_versions.get(product_code, [])),
                    default=0,
                ) + 1
                for version in product_versions.get(product_code, []):
                    if version["status"] == "current":
                        version["status"] = "historical"
                product_version = {
                    "product_version_id": f"tp-{safe_filename(product_code)}-v{product_version_no}-{version_hash[:10]}",
                    "version_id": f"tp-{safe_filename(product_code)}-v{product_version_no}-{version_hash[:10]}",
                    "product_code": product_code,
                    "product_version_no": product_version_no,
                    "version_no": product_version_no,
                    "status": "current",
                    "source_snapshot_id": aggregate.get("source_snapshot_id", "legacy"),
                    "source_upload_id": aggregate.get("source_upload_id", ""),
                    "previous_product_version_id": previous.get("product_version_id", "") if previous else "",
                    "version_hash": version_hash,
                    "row_count": len(product_rows),
                    "diff_summary": diff["summary"] if diff["has_material_change"] else {"seeded": len(product_rows)},
                    "created_by": aggregate.get("created_by", "migration"),
                    "published_by": aggregate.get("published_by", "migration"),
                    "created_at": aggregate.get("created_at", created_at),
                    "published_at": aggregate.get("published_at", aggregate.get("created_at", created_at)),
                    "rows": product_rows,
                }
                product_versions.setdefault(product_code, []).append(product_version)
            composition.append(composition_entry(product_version))

        composition.sort(key=lambda row: row["product_code"])
        aggregate_rows = compose_rows_from_product_versions(product_versions, composition)
        composition_hash = hash_aggregate_composition(composition)
        migrated_aggregate = dict(aggregate)
        migrated_aggregate.update({
            "aggregate_version_no": aggregate.get("version_no", len(aggregate_versions) + 1),
            "version_hash": composition_hash,
            "composition_hash": composition_hash,
            "product_versions": composition,
            "changed_products": [row["product_code"] for row in composition],
            "row_count": len(aggregate_rows),
            "rows": aggregate_rows,
        })
        aggregate_versions.append(migrated_aggregate)

    if not aggregate_versions:
        migrated = seed_state(client)
        migrated["config"] = state.get("config", migrated["config"])
        migrated["uploads"] = state.get("uploads", [])
        migrated["audit"] = state.get("audit", migrated["audit"])
        return migrated

    state["schema_version"] = 2
    state["product_versions"] = product_versions
    state["versions"] = aggregate_versions
    state.setdefault("uploads", [])
    state.setdefault("audit", [])
    state["audit"].append({
        "event": "bom.state.migrated_to_product_versions",
        "at": created_at,
        "actor": "system",
        "details": {"aggregate_versions": len(aggregate_versions), "product_codes": len(product_versions)},
    })
    return state


def default_config(client: dict, created_at: str) -> dict:
    profile = {
        "growatt": "growatt_multi_workbook",
        "johnson": "johnson_sap_exploded",
    }.get(client["id"], "manual_flat")
    code_system_mode = "customs_internal_mapping_required" if client["id"] == "growatt" else "single_code"
    return {
        "client_id": client["id"],
        "bom_profile": profile,
        "default_import_mode": "direct_bom",
        "code_system_mode": code_system_mode,
        "diff_tolerance": "0.000001",
        "created_at": created_at,
        "updated_at": created_at,
    }


def default_upload_scope(upload_mode: str) -> str:
    return "partial_product" if upload_mode == "technical_bom" else "full_aggregate"


def duplicate_row_keys(rows: list[dict]) -> list[dict]:
    seen = {}
    duplicates = []
    for row in rows:
        row_key = row["row_key"]
        if row_key in seen:
            duplicates.append({
                "row_key": row_key,
                "first_source": seen[row_key],
                "duplicate_source": row.get("source", ""),
            })
        else:
            seen[row_key] = row.get("source", "")
    return duplicates


def requires_review_before_publish(rows: list[dict], upload_mode: str, profile: str) -> bool:
    if upload_mode != "technical_bom" or profile != "growatt_multi_workbook":
        return False
    return any(row.get("row_class") == "needs_graph_flatten_review" for row in rows)


def product_result_text(result: dict) -> str:
    if result["status"] == "retired":
        return f"{result['product_code']} #{result['previous_version_no']} -> retired"
    if result["status"] == "reinstated":
        return f"{result['product_code']} reinstated #{result['new_version_no']}"
    return f"{result['product_code']} #{result['previous_version_no']} -> #{result['new_version_no']}"


def diff_rows(previous_rows: list[dict], new_rows: list[dict]) -> dict:
    previous = {row["row_key"]: row for row in previous_rows}
    new = {row["row_key"]: row for row in new_rows}
    added = [new[key] for key in sorted(new.keys() - previous.keys())]
    removed = [previous[key] for key in sorted(previous.keys() - new.keys())]
    changed = []
    unchanged = []
    for key in sorted(previous.keys() & new.keys()):
        before = comparable_row(previous[key])
        after = comparable_row(new[key])
        if before == after:
            unchanged.append(new[key])
        else:
            changed.append({"before": previous[key], "after": new[key]})
    return {
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "unchanged": len(unchanged),
        },
        "has_material_change": bool(added or removed or changed),
        "added": added[:50],
        "removed": removed[:50],
        "changed": changed[:50],
    }


def publish_product_version(
    state: dict,
    client: dict,
    product_code: str,
    product_rows: list[dict],
    diff: dict,
    snapshot_id: str,
    upload_id: str,
    profile: str,
) -> dict:
    previous = latest_product_version(state, product_code)
    next_version_no = max(
        (version["product_version_no"] for version in state["product_versions"].get(product_code, [])),
        default=0,
    ) + 1
    for version in state["product_versions"].get(product_code, []):
        if version["status"] == "current":
            version["status"] = "historical"

    version_hash = hash_rows(product_rows)
    product_version_id = f"tp-{safe_filename(product_code)}-v{next_version_no}-{version_hash[:10]}"
    product_version = {
        "product_version_id": product_version_id,
        "version_id": product_version_id,
        "product_code": product_code,
        "product_version_no": next_version_no,
        "version_no": next_version_no,
        "status": "current",
        "source_snapshot_id": snapshot_id,
        "source_upload_id": upload_id,
        "previous_product_version_id": previous.get("product_version_id", "") if previous else "",
        "profile": profile,
        "version_hash": version_hash,
        "row_count": len(product_rows),
        "diff_summary": diff["summary"],
        "created_by": "demo-user",
        "published_by": "demo-user",
        "created_at": now_iso(),
        "published_at": now_iso(),
        "rows": sorted([dict(row) for row in product_rows], key=lambda row: row["row_key"]),
    }
    state["product_versions"].setdefault(product_code, []).append(product_version)

    if write_bom_artifacts():
        version_dir = client_root(client["id"]) / "product-versions" / safe_filename(product_code) / f"v{next_version_no}"
        version_dir.mkdir(parents=True, exist_ok=True)
        write_json(version_dir / "version.json", {key: value for key, value in product_version.items() if key != "rows"})
        write_json(version_dir / "rows.json", product_version["rows"])
        write_json(version_dir / "diff.json", diff)

    append_audit(state, "bom.product_version.published", {
        "product_code": product_code,
        "product_version_no": next_version_no,
        "upload_id": upload_id,
    })
    return product_version


def attach_case_bom_snapshot(case: dict, bom_workspace: dict) -> dict:
    versions = bom_workspace.get("versions", [])
    latest = bom_workspace.get("latest_version", {})
    selected_version_id = case.get("bom_artifact_id") or case.get("bom_version_id") or latest.get("artifact_id") or latest.get("version_id", "")
    aggregate = next(
        (
            version
            for version in versions
            if (version.get("artifact_id") or version.get("version_id")) == selected_version_id
        ),
        latest,
    )
    selected_version_id = aggregate.get("artifact_id") or aggregate.get("version_id", selected_version_id)

    version_index = {}
    for version in bom_workspace.get("product_versions", []):
        for artifact_key in (version.get("product_artifact_id"), version.get("product_version_id"), version.get("artifact_id"), version.get("version_id")):
            if artifact_key:
                version_index[str(artifact_key)] = version
    composition_by_product = {
        row["product_code"]: dict(row)
        for row in aggregate.get("product_versions", [])
    }
    overrides = {
        **dict(case.get("bom_product_version_overrides", {})),
        **dict(case.get("bom_product_artifact_overrides", {})),
    }
    snapshot_composition = []
    seen_product_versions = set()

    for product in case.get("products", []):
        product_code = product.get("code", "")
        selected_product_version_id = product.get("bom_product_artifact_id") or product.get("bom_product_version_id") or overrides.get(product_code)
        if not selected_product_version_id:
            selected_product_version_id = (
                composition_by_product.get(product_code, {}).get("product_artifact_id")
                or composition_by_product.get(product_code, {}).get("product_version_id", "")
            )
        selected_product_version = version_index.get(selected_product_version_id)
        if not usable_product_version(selected_product_version):
            fallback_version_id = (
                composition_by_product.get(product_code, {}).get("product_artifact_id")
                or composition_by_product.get(product_code, {}).get("product_version_id", "")
            )
            selected_product_version = version_index.get(fallback_version_id) or latest_usable_product_version(
                bom_workspace,
                product_code,
            )
        if selected_product_version:
            product_artifact_id = selected_product_version.get("product_artifact_id") or selected_product_version.get("product_version_id", "")
            product_artifact_no = selected_product_version.get("product_artifact_no") or selected_product_version.get("product_version_no", "")
            product["bom_product_artifact_id"] = product_artifact_id
            product["bom_product_artifact_no"] = product_artifact_no
            product["bom_product_version_id"] = product_artifact_id
            product["bom_product_version_no"] = product_artifact_no
            if product_artifact_id not in seen_product_versions:
                snapshot_composition.append(composition_entry(selected_product_version))
                seen_product_versions.add(product_artifact_id)
        else:
            product["bom_product_artifact_id"] = ""
            product["bom_product_artifact_no"] = ""
            product["bom_product_version_id"] = ""
            product["bom_product_version_no"] = ""

    case["bom_artifact_id"] = selected_version_id
    case["bom_version_id"] = selected_version_id
    case["bom_snapshot"] = {
        "aggregate_artifact_id": selected_version_id,
        "aggregate_artifact_no": aggregate.get("artifact_no") or aggregate.get("version_no", 0),
        "aggregate_version_id": selected_version_id,
        "aggregate_version_no": aggregate.get("version_no", 0),
        "composition": sorted(snapshot_composition, key=lambda row: row["product_code"]),
    }
    return case


def usable_product_version(version: dict | None) -> bool:
    if not version:
        return False
    if version.get("flatten_status") == "non_flattened":
        return False
    return bool(version.get("rows"))


def latest_usable_product_version(bom_workspace: dict, product_code: str) -> dict:
    versions = [
        version
        for version in bom_workspace.get("product_versions", [])
        if version.get("product_code") == product_code and usable_product_version(version)
    ]
    return max(versions, key=lambda version: int(version.get("product_version_no") or 0), default={})


def refresh_product_version_statuses(state: dict, composition: list[dict]) -> None:
    current_ids = {row.get("product_artifact_id") or row["product_version_id"] for row in composition}
    for versions in state.get("product_versions", {}).values():
        for version in versions:
            version["status"] = "current" if version["product_version_id"] in current_ids else "historical"


def refresh_composition_entries(state: dict, composition: list[dict]) -> list[dict]:
    version_index = {
        version["product_version_id"]: version
        for versions in state.get("product_versions", {}).values()
        for version in versions
    }
    return [
        composition_entry(version_index[row["product_version_id"]])
        for row in composition
        if row["product_version_id"] in version_index
    ]


def merge_diff_summaries(product_results: list[dict]) -> dict:
    summary = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0, "changed_products": 0}
    for result in product_results:
        if result["status"] != "no_change":
            summary["changed_products"] += 1
        for key in ["added", "removed", "changed", "unchanged"]:
            summary[key] += result.get("diff_summary", {}).get(key, 0)
    return summary


def hash_rows(rows: list[dict]) -> str:
    payload = [comparable_row(row) for row in rows]
    payload.sort(key=lambda row: (row["product_code"], row["bom_code"], row["material_code"], row["uom"]))
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def hash_aggregate_composition(composition: list[dict]) -> str:
    payload = [
        {
            "product_code": row["product_code"],
            "product_version_id": row["product_version_id"],
            "product_version_no": row["product_version_no"],
            "version_hash": row["version_hash"],
        }
        for row in composition
    ]
    payload.sort(key=lambda row: row["product_code"])
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def comparable_row(row: dict) -> dict:
    return {
        "product_code": row.get("product_code", ""),
        "bom_code": row.get("bom_code", ""),
        "bom_variant_id": row.get("bom_variant_id", ""),
        "material_code": row.get("material_code", ""),
        "material_name": row.get("material_name", ""),
        "qty_per": quantity_text(row.get("qty_per", "0")),
        "uom": row.get("uom", ""),
        "scrap_rate": row.get("scrap_rate", ""),
    }


def save_state(client_id: str, state: dict) -> None:
    store = get_bom_state_store()
    if store:
        store.save_state(client_id, state)
        return
    root = client_root(client_id)
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "state.json", state)


def write_bom_artifacts() -> bool:
    return get_bom_state_store() is None


def state_path(client_id: str) -> Path:
    return client_root(client_id) / "state.json"


def client_root(client_id: str) -> Path:
    return get_store_root() / "clients" / safe_filename(client_id)


def get_store_root() -> Path:
    return Path(os.environ.get("BOM_STORE_ROOT", "data/local/bom-builder"))


@contextmanager
def client_store_lock(client_id: str):
    root = client_root(client_id)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".lock"
    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def append_audit(state: dict, event: str, details: dict) -> None:
    state["audit"].append({"event": event, "at": now_iso(), "actor": "demo-user", "details": details})


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.replace(temp_path, path)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def make_id(prefix: str, seed: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:12]}-{seed[:10]}"


def safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", filename.strip()).strip("-")
    return cleaned or "file"


def clean_choice(value: str | None, allowed: set[str], fallback: str) -> str:
    return value if value in allowed else fallback
