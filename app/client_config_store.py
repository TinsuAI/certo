from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


DECLARATION_TYPE_PRESETS = {
    "dncx": {
        # E13 is on-spot domestic purchase (nhập tại chỗ "từ nội địa") — 83% of
        # Growatt's on-spot volume; omitting it silently drops those lots for any
        # DNCX client onboarded via this preset (ADR 2026-07-11). Live saved
        # configs are not rewritten by this default.
        "eligible_import_declaration_types": ["E11", "E13", "E15"],
        "relevant_export_declaration_types": ["E42"],
    },
    "sxxk": {
        "eligible_import_declaration_types": ["E31"],
        "relevant_export_declaration_types": ["E62"],
    },
    "gia_cong": {
        "eligible_import_declaration_types": ["E21", "E23"],
        "relevant_export_declaration_types": ["E52", "E54"],
    },
    "manual": {
        "eligible_import_declaration_types": [],
        "relevant_export_declaration_types": [],
    },
}

ALLOCATION_CODE_STRATEGIES = {"same_as_customs_code", "description_regex", "manual_review"}
ALLOCATION_CODE_FALLBACKS = {"same_as_customs_code", "requires_review"}
CO_STOCK_LOT_POLICIES = {"line_level", "aggregate_by_declaration_and_allocation_code", "manual_review"}
DEFAULT_DESCRIPTION_REGEX = r"\(([A-Z0-9][A-Z0-9._/-]{3,})\)"


def get_client_config(client: dict) -> dict:
    path = config_path(client["id"])
    if path.exists():
        return migrate_config(read_json(path), client)
    config = default_config(client)
    write_config(client["id"], config)
    return config


def save_client_config(client: dict, config: dict) -> dict:
    next_config = migrate_config(config, client)
    validate_config(next_config)
    existing = get_client_config(client)
    next_config["config_version"] = existing.get("config_version", 1) + 1
    next_config["updated_at"] = now_iso()
    stamp_config_hash(next_config)
    with config_lock(client["id"]):
        write_config(client["id"], next_config)
    return next_config


def default_config(client: dict) -> dict:
    preset = "dncx" if client["id"] == "growatt" else "manual"
    now = now_iso()
    config = {
        "schema_version": 1,
        "client_id": client["id"],
        "config_version": 1,
        "created_at": now,
        "updated_at": now,
        "bcct": {
            "declaration_type_preset": preset,
            **DECLARATION_TYPE_PRESETS[preset],
        },
        "co_stock": {
            "lot_policy": "line_level",
        },
        "allocation_code": {
            "strategy": "description_regex" if client["id"] == "growatt" else "same_as_customs_code",
            "description_regex": DEFAULT_DESCRIPTION_REGEX,
            "fallback": "same_as_customs_code",
        },
        "features": {
            # Bulk "chọn NVL rác → xoá" on the per-sheet grid AND the aggregate
            # "Tổng hợp NVL" sheet. Opt-in per company (default off).
            "bulk_delete_junk_rows": False,
        },
    }
    stamp_config_hash(config)
    return config


def migrate_config(config: dict, client: dict) -> dict:
    default = default_config(client)
    merged = {
        **default,
        **config,
        "client_id": client["id"],
    }
    merged["bcct"] = {**default["bcct"], **config.get("bcct", {})}
    merged["co_stock"] = {**default["co_stock"], **config.get("co_stock", {})}
    merged["allocation_code"] = {**default["allocation_code"], **config.get("allocation_code", {})}
    merged["features"] = {**default["features"], **config.get("features", {})}
    merged.setdefault("config_version", 1)
    merged.setdefault("created_at", default["created_at"])
    merged.setdefault("updated_at", default["updated_at"])
    normalize_declaration_type_list(merged["bcct"], "eligible_import_declaration_types")
    normalize_declaration_type_list(merged["bcct"], "relevant_export_declaration_types")
    validate_config(merged)
    stamp_config_hash(merged)
    return merged


def validate_config(config: dict) -> None:
    if config["co_stock"].get("lot_policy") not in CO_STOCK_LOT_POLICIES:
        raise ValueError("Invalid CO stock source-line policy.")
    allocation = config["allocation_code"]
    if allocation.get("strategy") not in ALLOCATION_CODE_STRATEGIES:
        raise ValueError("Invalid allocation code strategy.")
    if allocation.get("fallback") not in ALLOCATION_CODE_FALLBACKS:
        raise ValueError("Invalid allocation code fallback.")
    if allocation.get("strategy") == "description_regex":
        try:
            re.compile(allocation.get("description_regex") or "")
        except re.error as exc:
            raise ValueError(f"Invalid allocation code regex: {exc}") from exc


def resolve_allocation_code(row: dict, config: dict) -> dict:
    identity = row.get("material_identity") if isinstance(row.get("material_identity"), dict) else {}
    identity_internal_code = cell_text(identity.get("internal_code"))
    if identity_internal_code:
        return _resolved_allocation(identity_internal_code, "material_identity", "high")

    allocation = config["allocation_code"]
    item_code = cell_text(row.get("item_code"))
    strategy = allocation.get("strategy")
    if strategy == "same_as_customs_code":
        return _resolved_allocation(item_code, "strategy_customs", "high")
    if strategy == "manual_review":
        return _review_allocation("manual_review", "manual")

    pattern = re.compile(allocation.get("description_regex") or "")
    matches = [match for match in pattern.findall(cell_text(row.get("description"))) if cell_text(match)]
    matches = [cell_text(match[0] if isinstance(match, tuple) else match) for match in matches]
    unique_matches = list(dict.fromkeys(matches))
    if len(unique_matches) == 1:
        return _resolved_allocation(unique_matches[0], "strategy_regex", "high")
    if len(unique_matches) > 1:
        return _review_allocation("multiple_regex_matches")
    if allocation.get("fallback") == "same_as_customs_code":
        return _resolved_allocation(item_code, "fallback_customs", "low")
    return _review_allocation("no_regex_match")


def _resolved_allocation(code: str, source: str, confidence: str) -> dict:
    # `source` = provenance, `confidence` = quality ordinal only — the
    # primary-vs-fallback distinction lives in `source`, not `confidence`.
    # Value-set: GLOSSARY "Material & lot codes"; invariants pinned by
    # tests/test_allocation_code_provenance.py.
    return {
        "allocation_code": code,
        "source": source,
        "confidence": confidence,
        "status": "resolved",
        "reason": "",
    }


def _review_allocation(reason: str, source: str = "") -> dict:
    return {
        "allocation_code": "",
        "source": source,
        "confidence": "low",
        "status": "unresolved",
        "reason": reason,
    }


def config_payload(config: dict) -> dict:
    return {
        key: value
        for key, value in config.items()
        if key != "config_hash"
    }


def stamp_config_hash(config: dict) -> None:
    payload = json.dumps(config_payload(config), ensure_ascii=False, sort_keys=True)
    config["config_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def normalize_declaration_type_list(config: dict, key: str) -> None:
    value = config.get(key, [])
    if isinstance(value, str):
        value = re.split(r"[\s,]+", value)
    config[key] = sorted({cell_text(item).upper() for item in value if cell_text(item)})


def config_root() -> Path:
    return Path(os.environ.get("CLIENT_CONFIG_ROOT", "data/local/client-config"))


def config_path(client_id: str) -> Path:
    return config_root() / "clients" / client_id / "config.json"


def write_config(client_id: str, config: dict) -> None:
    write_json(config_path(client_id), config)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_name, path)


@contextmanager
def config_lock(client_id: str):
    root = config_path(client_id).parent
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".lock"
    with lock_path.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def cell_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()
