#!/usr/bin/env python
"""Onboard/maintain growatt-vn's CO-owned allocation config (#14).

growatt-vn's published BOM uses dotted internal codes (`005.0001100`, `001.SK0002900`)
while its import lots carry short customs codes (`DIOT`, `DAYTINHIEU`) with the internal
code embedded in the lot description parentheses `(920.0042600)`. Under the default
`same_as_customs_code` only ~4.5% of BOM codes match a lot; under `description_regex`
~96% match. This is a per-client CO-owned config value (not a code default — Johnson must
stay `same_as_customs_code`), so it is written through the CO-owned save path added by #14
(the pre-#14 path raised read-only in DH+DB prod).

Two config fields are normalized here:
- strategy      -> `description_regex`
- description_regex -> CALIBRATED_DESCRIPTION_REGEX (below)

Why the calibrated regex, not the broad default: a lot description often carries TWO
parentheticals — a manufacturer part number and the internal code, e.g.
`...20ohm/TH/5mm/M(SCK10202MSY). Hàng mới 100%(012.0001400)`. The broad default
`\\(([A-Z0-9][A-Z0-9._/-]{3,})\\)` matches BOTH, and `resolve_allocation_code` then blanks
the code as ambiguous (`multiple_regex_matches`) — so a fully-stocked material (here
`012.0001400`, tens of thousands of units) reads as a shortage. The calibrated regex
`\\(\\s*([A-Z0-9]+\\.[A-Z0-9]+)\\s*\\)` matches only a single alphanumeric·dot·alphanumeric
token filling the whole parenthesis: it keeps every real code shape (`012.0001400`,
`B700.0141600`, `PE07.0073300`, `001.SK0002900`) and rejects the part numbers and spec
fragments (`SCK10202MSY`, `150W`, `380-415`, `1.25-16MM2`). Measured on growatt-vn: 848→849
BOM-code matches on a sample case and 38→0 ambiguity-blanked lots, no regression. The fix
lives in this per-client config (the seam #14 built), not in the shared resolver — the
resolver's multi-match ambiguity guard stays intact as a general safety net.

Idempotent: a no-op when strategy/regex/fallback already match the calibrated target.
Otherwise it saves and forces one full co_stock re-derivation so the snapshot immediately
reflects the new codes (the delta path would re-derive nothing on unchanged rows).

Run in the target environment (prod/nightly) with .env configured:
    uv run python scripts/seed_growatt_vn_allocation.py [--client growatt-vn] [--no-refresh]

Or in-container without a code deploy (self-contained; no import of the code default):
    docker exec -i <co-app-1> /app/.venv/bin/python - < scripts/seed_growatt_vn_allocation.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Works both as a file (local) and piped via stdin in-container (`python - < this`),
# where __file__ is undefined — fall back to the working directory (/app in the image).
try:
    ROOT = Path(__file__).resolve().parents[1]
except NameError:
    ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

from app.portfolio import portfolio_service
from app.web.client_context import resolve_client
from app.web.co_case_context import _refresh_co_stock_delta_or_full

# Single alphanumeric·dot·alphanumeric token filling the whole parenthesis. Kept as a
# self-contained constant (not imported from app.client_config_store) so this script sets
# the intended value even when piped into a container whose deployed code default differs.
CALIBRATED_DESCRIPTION_REGEX = r"\(\s*([A-Z0-9]+\.[A-Z0-9]+)\s*\)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", default="growatt-vn")
    parser.add_argument("--no-refresh", action="store_true",
                        help="skip the forced full co_stock re-derivation after the save")
    args = parser.parse_args()

    client = resolve_client(args.client)
    config = portfolio_service.get_client_config(client)
    allocation = config["allocation_code"]
    print(f"[{args.client}] current strategy={allocation.get('strategy')!r} "
          f"regex={allocation.get('description_regex')!r} fallback={allocation.get('fallback')!r}")

    target = {
        "strategy": "description_regex",
        "description_regex": CALIBRATED_DESCRIPTION_REGEX,
        "fallback": "same_as_customs_code",
    }
    if all(allocation.get(k) == v for k, v in target.items()):
        print("Already calibrated — nothing to seed.")
        return 0

    allocation.update(target)
    saved = portfolio_service.save_client_config(client, config)["allocation_code"]
    print(f"Saved strategy={saved['strategy']!r} regex={saved['description_regex']!r} "
          f"fallback={saved['fallback']!r}")

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
