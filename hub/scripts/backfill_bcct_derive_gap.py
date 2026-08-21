"""Backfill the materials BCCT ingest should have derived (#52).

`_insert_bcct` inserted declaration rows without deriving the catalog rows
their codes name, so the ad-hoc bulk ingest behind Growatt's 2026-05-27
onboarding left declared HQ codes with no material row. Those codes then sat
in the discovery queue as if a human had to approve a fact the client had
already declared to customs. The code path is fixed separately; this repairs
the data left behind.

Predicate — pending discovery rows whose code came from the HQ side of a
declaration:

    code_kind in ('hq','unified') and 'bcct' = any(sources)

NB codes are regex-derived guesses and stay in the queue. bqd-only codes were
never declared. The discovery filter cannot express this predicate (its kind
is single-valued), which is why this is a script and not two button presses.

Writes through `bulk_accept_codes` — the shipped store function — so the rows
get the discovery view's category, code_kind and uom, the NB<->HQ automap and
one batched staleness propagation. `derive_from_bcct` would do none of that
and hardcodes category='nvl', mislabelling every export-only finished product.

The audit event records an ops actor, not an operator: nobody approved these,
an ingest bug skipped them.

Usage:
    uv run python scripts/backfill_bcct_derive_gap.py --client growatt-vn
    uv run python scripts/backfill_bcct_derive_gap.py --client growatt-vn --commit
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from hub.app.stores.catalog_discovery import bulk_accept_codes, discovery_rows

ACTOR = "ops:backfill-derive-gap-52"
PREDICATE = {
    "code_kind": ["hq", "unified"],
    "source": "bcct",
    "status": "pending",
    "reason": "issue #52 — ad-hoc BCCT ingest called _insert_bcct, which did "
              "not derive; these codes were declared to customs, not approved "
              "by anyone",
}


def gap_rows(client_id: str) -> list[dict]:
    return [
        r for r in discovery_rows(client_id)
        if r["status"] == "pending"
        and r["code_kind"] in ("hq", "unified")
        and "bcct" in (r["sources"] or [])
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--client", required=True)
    ap.add_argument("--commit", action="store_true",
                    help="apply; without it the script only reports")
    args = ap.parse_args()

    rows = gap_rows(args.client)
    if not rows:
        print(f"{args.client}: no gap — nothing to backfill.")
        return 0

    by_kind = Counter(r["code_kind"] for r in rows)
    by_cat = Counter(r.get("suggested_category") or "<none>" for r in rows)
    print(f"{args.client}: {len(rows)} declared HQ codes with no material row")
    print(f"  code_kind          {dict(by_kind)}")
    print(f"  suggested_category {dict(by_cat)}")
    print("  sample: " + ", ".join(r["code"] for r in rows[:5]))

    if not args.commit:
        print("\n(dry-run) nothing written. Re-run with --commit to apply.")
        return 0

    result = bulk_accept_codes(args.client, rows=rows, actor=ACTOR,
                              predicate=PREDICATE)
    print(f"\naccepted {result['accepted']}, skipped {result['skipped']}")
    left = gap_rows(args.client)
    print(f"remaining gap: {len(left)}")
    return 0 if not left else 1


if __name__ == "__main__":
    raise SystemExit(main())
