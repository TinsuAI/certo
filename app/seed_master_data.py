"""One-time seed loader for master-data tables.

Reads YAML seeds from data/seeds/ and inserts rows into:
- hub.declaration_type_catalog
- hub.client_type_presets

Idempotent: only seeds when the target table is empty. After first run
the tables are the source of truth — staff edit via admin UI; this
loader is a no-op on subsequent startups.

To force re-seed (overwrite existing rows): scripts/reseed_master_data.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.database import connect

SEEDS_ROOT = Path(__file__).resolve().parent.parent / "data" / "seeds"


def _load_yaml(name: str) -> dict[str, Any]:
    path = SEEDS_ROOT / name
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def seed_declaration_types() -> int:
    """Seed declaration_type_catalog if empty. Returns rows inserted."""
    data = _load_yaml("declaration_types.yaml")
    rows = data.get("declaration_types") or []
    if not rows:
        return 0
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from hub.declaration_type_catalog")
            (existing,) = cur.fetchone()
            if existing > 0:
                return 0
            for row in rows:
                cur.execute(
                    """
                    insert into hub.declaration_type_catalog
                      (code, direction, description, notes)
                    values (%s, %s, %s, %s)
                    on conflict (code) do nothing
                    """,
                    (
                        row["code"],
                        row["direction"],
                        row.get("description", ""),
                        row.get("notes", ""),
                    ),
                )
    return len(rows)


def seed_client_type_presets() -> int:
    """Seed client_type_presets if empty. Returns rows inserted."""
    data = _load_yaml("client_type_presets.yaml")
    rows = data.get("presets") or []
    if not rows:
        return 0
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from hub.client_type_presets")
            (existing,) = cur.fetchone()
            if existing > 0:
                return 0
            for row in rows:
                cur.execute(
                    """
                    insert into hub.client_type_presets
                      (preset_key, display_name, default_eligible_import,
                       default_relevant_export, is_system, notes)
                    values (%s, %s, %s, %s, %s, %s)
                    on conflict (preset_key) do nothing
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


def seed_master_data_if_empty() -> dict[str, int]:
    """Run all idempotent seeders. Called from app startup after migrations."""
    return {
        "declaration_types": seed_declaration_types(),
        "client_type_presets": seed_client_type_presets(),
    }
