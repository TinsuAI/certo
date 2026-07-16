#!/usr/bin/env python
"""Onboard growatt-vn: set its CO-owned allocation strategy to `description_regex` (#14).

growatt-vn's published BOM uses dotted internal codes (`005.0001100`) while its
import lots carry short customs codes (`DIOT`) with the internal code embedded in
`goods_name` parentheses `(920.0042600)`. Under the default `same_as_customs_code`
only 4.5% of BOM codes match a lot; under `description_regex` 96% match. This is a
per-client CO-owned config value (not a code default — Johnson must stay
`same_as_customs_code`), so it is seeded through the CO-owned save path added by #14
(the pre-#14 path raised read-only in DH+DB prod).

Idempotent: re-running is a no-op when the effective strategy is already
`description_regex`. After the save it forces one full co_stock re-derivation so the
snapshot immediately reflects the new codes (the delta path would re-derive nothing).

Run in the target environment (prod/nightly) with .env configured:
    uv run python scripts/seed_growatt_vn_allocation.py [--client growatt-vn] [--no-refresh]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

from app.client_config_store import DEFAULT_DESCRIPTION_REGEX
from app.portfolio import portfolio_service
from app.web.client_context import resolve_client
from app.web.co_case_context import _refresh_co_stock_delta_or_full


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", default="growatt-vn")
    parser.add_argument("--no-refresh", action="store_true",
                        help="skip the forced full co_stock re-derivation after the save")
    args = parser.parse_args()

    client = resolve_client(args.client)
    config = portfolio_service.get_client_config(client)
    current = config["allocation_code"].get("strategy")
    print(f"[{args.client}] current allocation strategy: {current}")

    if current == "description_regex":
        print("Already description_regex — nothing to seed.")
        return 0

    config["allocation_code"]["strategy"] = "description_regex"
    if not (config["allocation_code"].get("description_regex") or "").strip():
        config["allocation_code"]["description_regex"] = DEFAULT_DESCRIPTION_REGEX
    config["allocation_code"]["fallback"] = "same_as_customs_code"
    saved = portfolio_service.save_client_config(client, config)
    print(f"Saved allocation strategy: {saved['allocation_code']['strategy']} "
          f"(regex={saved['allocation_code']['description_regex']!r})")

    if args.no_refresh:
        print("Skipped co_stock refresh (--no-refresh). Next 'Refresh tồn' will go full.")
        return 0

    print("Forcing full co_stock re-derivation (config fingerprint changed)…")
    summary = _refresh_co_stock_delta_or_full(client)
    print(f"Refresh mode={summary.get('mode', 'full')} "
          f"rows_persisted={summary.get('rows_persisted', '?')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
