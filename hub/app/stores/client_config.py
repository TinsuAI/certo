"""hub.client_config CRUD + version/hash management.

Per-client master config: declaration-type filters + fiscal year start
month. Carries config_version (monotonic, bumped on save) and
config_hash (sha256 of canonical JSON) for sister-app cache invalidation.

Snapshot semantics: when a client picks a preset, the preset's current
defaults are copied into the client row. Subsequent preset edits do NOT
cascade automatically — staff must explicitly re-apply.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from hub.app.database import connect
from hub.app.stores import client_type_presets


def _canonical_payload(row: dict) -> str:
    """Stable JSON for hashing. Excludes timestamps + version + hash itself."""
    payload = {
        "client_id": row["client_id"],
        "preset_key": row.get("preset_key"),
        "eligible_import_declaration_types": sorted(
            row.get("eligible_import_declaration_types") or []
        ),
        "relevant_export_declaration_types": sorted(
            row.get("relevant_export_declaration_types") or []
        ),
        "fiscal_year_start_month": row.get("fiscal_year_start_month", 1),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def compute_hash(row: dict) -> str:
    return hashlib.sha256(_canonical_payload(row).encode("utf-8")).hexdigest()[:16]


def _row_to_dict(cur, row) -> dict:
    cols = [d.name for d in cur.description]
    return dict(zip(cols, row))


def get(client_id: str) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select client_id, preset_key,
                       eligible_import_declaration_types,
                       relevant_export_declaration_types,
                       fiscal_year_start_month,
                       config_version, config_hash,
                       created_at, updated_at, updated_by
                from hub.client_config where client_id = %s
                """,
                (client_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return _row_to_dict(cur, row)


def get_or_default(client_id: str) -> dict:
    """Return existing config or a virtual default (no DB row yet).

    Default has preset=manual semantics — empty lists, fiscal year=1,
    config_version=0 (signals "not yet configured" to consumers).
    """
    existing = get(client_id)
    if existing is not None:
        return existing
    default = {
        "client_id": client_id,
        "preset_key": None,
        "eligible_import_declaration_types": [],
        "relevant_export_declaration_types": [],
        "fiscal_year_start_month": 1,
        "config_version": 0,
        "config_hash": "",
        "created_at": None,
        "updated_at": None,
        "updated_by": None,
    }
    default["config_hash"] = compute_hash(default)
    return default


def upsert(*, client_id: str, preset_key: str | None,
           eligible_import_declaration_types: list[str],
           relevant_export_declaration_types: list[str],
           fiscal_year_start_month: int = 1,
           user_id: str | None = None) -> dict:
    """Insert or update a client config row. Bumps config_version + hash."""
    if not 1 <= fiscal_year_start_month <= 12:
        raise ValueError("fiscal_year_start_month must be 1..12")
    eligible = sorted({c.strip().upper() for c in eligible_import_declaration_types if c.strip()})
    relevant = sorted({c.strip().upper() for c in relevant_export_declaration_types if c.strip()})
    new_payload = {
        "client_id": client_id,
        "preset_key": preset_key,
        "eligible_import_declaration_types": eligible,
        "relevant_export_declaration_types": relevant,
        "fiscal_year_start_month": fiscal_year_start_month,
    }
    new_hash = compute_hash(new_payload)
    with connect(user_id=user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select config_version, config_hash from hub.client_config where client_id = %s",
                (client_id,),
            )
            existing = cur.fetchone()
            if existing is None:
                cur.execute(
                    """
                    insert into hub.client_config
                      (client_id, preset_key,
                       eligible_import_declaration_types,
                       relevant_export_declaration_types,
                       fiscal_year_start_month,
                       config_version, config_hash, updated_by)
                    values (%s, %s, %s, %s, %s, 1, %s, %s)
                    returning client_id, preset_key,
                              eligible_import_declaration_types,
                              relevant_export_declaration_types,
                              fiscal_year_start_month,
                              config_version, config_hash,
                              created_at, updated_at, updated_by
                    """,
                    (client_id, preset_key, eligible, relevant,
                     fiscal_year_start_month, new_hash, user_id),
                )
            else:
                existing_version, existing_hash = existing
                # No-op when content unchanged: skip version bump.
                if existing_hash == new_hash:
                    cur.execute(
                        """
                        select client_id, preset_key,
                               eligible_import_declaration_types,
                               relevant_export_declaration_types,
                               fiscal_year_start_month,
                               config_version, config_hash,
                               created_at, updated_at, updated_by
                        from hub.client_config where client_id = %s
                        """,
                        (client_id,),
                    )
                    return _row_to_dict(cur, cur.fetchone())
                cur.execute(
                    """
                    update hub.client_config
                    set preset_key = %s,
                        eligible_import_declaration_types = %s,
                        relevant_export_declaration_types = %s,
                        fiscal_year_start_month = %s,
                        config_version = config_version + 1,
                        config_hash = %s,
                        updated_at = now(),
                        updated_by = %s
                    where client_id = %s
                    returning client_id, preset_key,
                              eligible_import_declaration_types,
                              relevant_export_declaration_types,
                              fiscal_year_start_month,
                              config_version, config_hash,
                              created_at, updated_at, updated_by
                    """,
                    (preset_key, eligible, relevant, fiscal_year_start_month,
                     new_hash, user_id, client_id),
                )
            return _row_to_dict(cur, cur.fetchone())


def apply_preset(client_id: str, preset_key: str, *,
                 user_id: str | None = None) -> dict:
    """Snapshot a preset's current defaults into the client row.

    Picks up the preset's current default_eligible_import +
    default_relevant_export and writes them to the client. Bumps
    version. Does NOT touch fiscal_year_start_month.
    """
    preset = client_type_presets.get(preset_key)
    if preset is None:
        raise ValueError(f"Unknown preset_key: {preset_key}")
    if not preset["is_active"]:
        raise ValueError(f"Preset is disabled: {preset_key}")
    existing = get(client_id)
    fiscal = existing["fiscal_year_start_month"] if existing else 1
    return upsert(
        client_id=client_id,
        preset_key=preset_key,
        eligible_import_declaration_types=list(preset["default_eligible_import"] or []),
        relevant_export_declaration_types=list(preset["default_relevant_export"] or []),
        fiscal_year_start_month=fiscal,
        user_id=user_id,
    )


def to_api_payload(row: dict) -> dict[str, Any]:
    """Shape exposed to /v1/hub/dncxs/{id}/client-config."""
    return {
        "schema_version": 1,
        "client_id": row["client_id"],
        "preset_key": row.get("preset_key"),
        "eligible_import_declaration_types": list(
            row.get("eligible_import_declaration_types") or []
        ),
        "relevant_export_declaration_types": list(
            row.get("relevant_export_declaration_types") or []
        ),
        "fiscal_year_start_month": int(row.get("fiscal_year_start_month") or 1),
        "config_version": int(row.get("config_version") or 0),
        "config_hash": row.get("config_hash") or "",
    }
