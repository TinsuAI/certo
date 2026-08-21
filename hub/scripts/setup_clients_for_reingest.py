"""Create empty client rows + sane client_config for the wipe+re-ingest scenario.

Phase A of the v3 wipe+re-ingest plan: after `dropdb && createdb` and
running migrations, this script creates the 5 client rows the demo box
expects, with `bom_proposal_mode='manual'` so the auto-rule does NOT
silently reject re-ingest BOMs (per critic round 3 finding 2).

Re-ingest scripts (smoke_real_uploads + ingest_technical_raw_batch) then
populate real data per-client. After re-ingest is done and verified, flip
`bom_proposal_mode` back to 'auto' (or 'manual' permanently) per agency
preference.

Idempotent — re-running upserts the rows without disturbing data.

Usage:
    uv run python scripts/setup_clients_for_reingest.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from hub.app.routes.clients import upsert_client


CLIENTS = [
    dict(
        client_id="growatt-vn", name="Growatt VN", tax_code="0307123456",
        code_resolution_mode="batch_aggregate_resolution",
        notes="Reference Growatt — 1:n BQD with BCCT-aggregate disambiguation.",
    ),
    dict(
        client_id="johnson-vn", name="Johnson VN", tax_code="0309876543",
        code_resolution_mode="identity",
        notes="Identity mode — customs_code IS internal_code.",
    ),
    dict(
        client_id="dke-vietnam-d0e3", name="DKE Vietnam", tax_code=None,
        code_resolution_mode="identity",
        notes="DKE — identity mode placeholder.",
    ),
    dict(
        client_id="do-thanh-vietnam-2614", name="Do Thanh Vietnam", tax_code=None,
        code_resolution_mode="identity",
        notes="Do Thanh — identity mode placeholder.",
    ),
    dict(
        client_id="demo-precision-manufactu-480e",
        name="Demo Precision Manufacturing",
        tax_code=None,
        code_resolution_mode="identity",
        notes="Synthetic demo company. Populated by scripts/feed_demo_company.py.",
    ),
]


def main() -> int:
    print("Creating/upserting 5 client rows with bom_proposal_mode='manual':")
    for c in CLIENTS:
        upsert_client(
            client_id=c["client_id"],
            name=c["name"],
            tax_code=c.get("tax_code"),
            code_resolution_mode=c["code_resolution_mode"],
            # CRITICAL for re-ingest window — disables auto-rule rejection
            # per critic round 3 finding 2. Flip back to 'auto' after Phase B.
            bom_proposal_mode="manual",
            bom_proposal_qty_tolerance_pct=5.0,
            bom_approver_tier="edit",
            status="active",
            notes=c.get("notes"),
        )
        print(f"  ✓ {c['client_id']:35s} ({c['name']})")
    print()
    print("Done. Re-ingest scripts can now populate real data per client.")
    print("After re-ingest is verified, run flip_bom_proposal_mode.py "
          "to switch back to 'auto' if desired.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
