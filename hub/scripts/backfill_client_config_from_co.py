#!/usr/bin/env -S uv run python
"""One-time backfill of hub.client_config from CO local JSON files.

Reads barry-CO-main/data/local/client-config/clients/*/config.json
and creates matching hub.client_config rows. Maps CO `client_id` →
Data Hub `client_id` via the table below (client IDs differ between
the two systems).

Idempotent on `(client_id)` — re-running with the same input does NOT
bump version.

Usage:
  uv run python scripts/backfill_client_config_from_co.py            # dry-run
  uv run python scripts/backfill_client_config_from_co.py --confirm  # apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CO_ROOT = Path("/home/vp/workspace/client/barry-CO-main/data/local/client-config/clients")

# CO client_id (slug) -> Data Hub client_id.
# Curated map; if a CO client isn't here, the script skips it with a
# warning rather than guessing.
CLIENT_ID_MAP = {
    "growatt": "growatt-vn",
    "do-thanh": "do-thanh-vietnam-2614",
    "johnson": "johnson-vn",
}


def load_co_config(co_id: str) -> dict | None:
    path = CO_ROOT / co_id / "config.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true",
                        help="Apply changes (default: dry-run).")
    args = parser.parse_args()

    if not CO_ROOT.exists():
        print(f"CO config root not found: {CO_ROOT}", file=sys.stderr)
        return 2

    plan: list[tuple[str, str, dict]] = []
    for co_id, dh_id in CLIENT_ID_MAP.items():
        cfg = load_co_config(co_id)
        if cfg is None:
            print(f"[skip] no config.json for CO client '{co_id}'")
            continue
        plan.append((co_id, dh_id, cfg))

    if not plan:
        print("No CO configs found. Nothing to backfill.")
        return 0

    for co_id, dh_id, cfg in plan:
        bcct = cfg.get("bcct", {})
        preset = bcct.get("declaration_type_preset")
        eligible = bcct.get("eligible_import_declaration_types", []) or []
        relevant = bcct.get("relevant_export_declaration_types", []) or []
        print(f"\n  CO id  : {co_id}")
        print(f"  DH id  : {dh_id}")
        print(f"  preset : {preset}")
        print(f"  import : {eligible}")
        print(f"  export : {relevant}")

    if not args.confirm:
        print("\nDry-run. Re-run with --confirm to apply.")
        return 0

    from app.routes.clients import get_client
    from app.stores import client_config

    applied = 0
    skipped_missing = 0
    skipped_existing = 0
    for co_id, dh_id, cfg in plan:
        if not get_client(dh_id):
            print(f"[skip] DH client '{dh_id}' not found in hub.clients")
            skipped_missing += 1
            continue
        existing = client_config.get(dh_id)
        if existing is not None:
            print(f"[skip] DH client '{dh_id}' already has client_config "
                  f"(v{existing['config_version']}); leave as-is")
            skipped_existing += 1
            continue
        bcct = cfg.get("bcct", {})
        preset = bcct.get("declaration_type_preset")
        client_config.upsert(
            client_id=dh_id,
            preset_key=preset if preset and preset != "manual" else None,
            eligible_import_declaration_types=bcct.get("eligible_import_declaration_types", []) or [],
            relevant_export_declaration_types=bcct.get("relevant_export_declaration_types", []) or [],
            fiscal_year_start_month=1,
            user_id=None,
        )
        print(f"[ok]   seeded {dh_id} from CO '{co_id}'")
        applied += 1

    print(f"\nApplied: {applied}; skipped (missing client): {skipped_missing}; "
          f"skipped (already configured): {skipped_existing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
