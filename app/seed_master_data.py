"""Seed loader for master-data tables.

Reads YAML seeds from data/seeds/ and writes rows into:
- hub.declaration_type_catalog
- hub.client_type_presets

Behavior is controlled by DATA_HUB_REFERENCE_DATA_MODE:

  oneshot         seed only when the target table is empty (default;
                  matches pre-flag behavior)
  upsert          INSERT ... ON CONFLICT DO UPDATE every call;
                  YAML wins over existing rows for shared columns
  migration_only  no-op; reference data only changes via numbered
                  SQL migrations

Per-env recommendation (see docs/release-engineering.md §4):
dev/demo = upsert (fast YAML iteration); prod = migration_only.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from app.database import connect

SEEDS_ROOT = Path(__file__).resolve().parent.parent / "data" / "seeds"

VALID_MODES = ("oneshot", "upsert", "migration_only")
DEFAULT_MODE = "oneshot"
ENV_VAR = "DATA_HUB_REFERENCE_DATA_MODE"


def _resolve_mode(mode: str | None) -> str:
    if mode is None:
        mode = os.environ.get(ENV_VAR, DEFAULT_MODE)
    if mode not in VALID_MODES:
        raise ValueError(
            f"{ENV_VAR}={mode!r} is invalid; "
            f"expected one of {VALID_MODES}"
        )
    return mode


def _load_yaml(name: str) -> dict[str, Any]:
    path = SEEDS_ROOT / name
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def seed_declaration_types(mode: str = DEFAULT_MODE) -> int:
    """Seed declaration_type_catalog. Returns rows written."""
    if mode == "migration_only":
        return 0
    data = _load_yaml("declaration_types.yaml")
    rows = data.get("declaration_types") or []
    if not rows:
        return 0
    with connect() as conn, conn.cursor() as cur:
        if mode == "oneshot":
            cur.execute("select count(*) from hub.declaration_type_catalog")
            (existing,) = cur.fetchone()
            if existing > 0:
                return 0
            conflict_clause = "on conflict (code) do nothing"
        else:  # upsert
            conflict_clause = (
                "on conflict (code) do update set "
                "direction = excluded.direction, "
                "description = excluded.description, "
                "notes = excluded.notes"
            )
        for row in rows:
            cur.execute(
                f"""
                insert into hub.declaration_type_catalog
                  (code, direction, description, notes)
                values (%s, %s, %s, %s)
                {conflict_clause}
                """,
                (
                    row["code"],
                    row["direction"],
                    row.get("description", ""),
                    row.get("notes", ""),
                ),
            )
    return len(rows)


def seed_client_type_presets(mode: str = DEFAULT_MODE) -> int:
    """Seed client_type_presets. Returns rows written."""
    if mode == "migration_only":
        return 0
    data = _load_yaml("client_type_presets.yaml")
    rows = data.get("presets") or []
    if not rows:
        return 0
    with connect() as conn, conn.cursor() as cur:
        if mode == "oneshot":
            cur.execute("select count(*) from hub.client_type_presets")
            (existing,) = cur.fetchone()
            if existing > 0:
                return 0
            conflict_clause = "on conflict (preset_key) do nothing"
        else:  # upsert
            conflict_clause = (
                "on conflict (preset_key) do update set "
                "display_name = excluded.display_name, "
                "default_eligible_import = excluded.default_eligible_import, "
                "default_relevant_export = excluded.default_relevant_export, "
                "is_system = excluded.is_system, "
                "notes = excluded.notes"
            )
        for row in rows:
            cur.execute(
                f"""
                insert into hub.client_type_presets
                  (preset_key, display_name, default_eligible_import,
                   default_relevant_export, is_system, notes)
                values (%s, %s, %s, %s, %s, %s)
                {conflict_clause}
                """,
                (
                    row["preset_key"],
                    row["display_name"],
                    row.get("default_eligible_import") or [],
                    row.get("default_relevant_export") or [],
                    bool(row.get("is_system", False)),
                    row.get("notes", ""),
                ),
            )
    return len(rows)


def seed_master_data(mode: str | None = None) -> dict[str, int]:
    """Run all seeders under the given mode (or env-driven default)."""
    resolved = _resolve_mode(mode)
    return {
        "declaration_types": seed_declaration_types(resolved),
        "client_type_presets": seed_client_type_presets(resolved),
    }


def seed_master_data_if_empty() -> dict[str, int]:
    """Compat shim: env-driven seed.

    Kept so existing callers (app/main.py, tests/conftest.py) don't have
    to change. Behavior is now controlled by DATA_HUB_REFERENCE_DATA_MODE.
    """
    return seed_master_data()
