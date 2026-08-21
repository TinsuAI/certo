"""Backfill the corroborated NB codes the derive gap leaves queued (#53).

`derive_from_bcct` auto-creates a material for every declared HQ code at
ingest. An NB code extracted from the parens of the same `goods_name`, on the
same declaration line, never derives — it queues. #52 fixed and backfilled the
HQ side of that asymmetry; this repairs the NB side.

Predicate — pending discovery rows corroborated by at least two of the three
streams, excluding machinery, whose category the discovery view can infer:

    array_length(sources, 1) >= 2
      and customs_relevance is distinct from 'excluded_non_material'
      and _derive_bulk_attrs(row) is not None

Two sources, not one, because the paren extract is the only guessed stream: a
regex over free text. BOM and BQD rows are exact strings out of client-authored
files, so a bad parser rule produces bcct-only strings, which stay queued.
`bcct_nb_codes` is delete-and-rebuild per client (ADR-0001), so one bad rule
edit re-mints the whole extraction — the second source is what keeps that out
of a table with no delete path that CO reads live. bom-only codes stay queued
too; provenance.py:150-153 says not to auto-derive supplier-internal BOM codes.

Writes through `bulk_accept_codes`, so the rows get the discovery view's
category, code_kind and uom, the NB<->HQ automap and one batched staleness
propagation. `derive_from_bcct` would do none of that and hardcodes
category='nvl', which would mislabel the export-only finished products — CO
filters on `category != "tp"`.

The discovery filter cannot express "≥2 sources" (its source is single-valued),
which is why this is a script and not a button press. The audit event records
an ops actor: nobody approved these, an ingest asymmetry skipped them.

Usage:
    uv run python scripts/backfill_nb_two_source.py --client growatt-vn
    uv run python scripts/backfill_nb_two_source.py --client growatt-vn --commit
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from app.stores.catalog_discovery import (
    _derive_bulk_attrs, bulk_accept_codes, discovery_rows,
)

ACTOR = "ops:backfill-nb-two-source-53"
PREDICATE = {
    "min_sources": 2,
    "exclude_machinery": True,
    "status": "pending",
    "reason": "issue #53 — NB codes corroborated by >=2 of bcct/bom/bqd are "
              "facts the client declared and carries in their own BOM/BQD, "
              "not guesses awaiting judgement; the HQ side already derives "
              "automatically at ingest",
}


def corroborated_rows(client_id: str) -> list[dict]:
    return [
        r for r in discovery_rows(client_id)
        if r["status"] == "pending"
        and r.get("customs_relevance") != "excluded_non_material"
        and len(r["sources"] or []) >= 2
        and _derive_bulk_attrs(r) is not None
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--client", required=True)
    ap.add_argument("--commit", action="store_true",
                    help="apply; without it the script only reports")
    args = ap.parse_args()

    rows = corroborated_rows(args.client)
    if not rows:
        print(f"{args.client}: no corroborated NB backlog — nothing to backfill.")
        return 0

    by_kind = Counter(r["code_kind"] for r in rows)
    by_cat = Counter(_derive_bulk_attrs(r)["category"] for r in rows)
    by_src = Counter(tuple(sorted(r["sources"] or [])) for r in rows)
    print(f"{args.client}: {len(rows)} corroborated codes with no material row")
    print(f"  code_kind {dict(by_kind)}")
    print(f"  category  {dict(by_cat)}")
    for src, n in sorted(by_src.items(), key=lambda kv: -kv[1]):
        print(f"  sources   {'+'.join(src):20} {n}")
    print("  sample: " + ", ".join(r["code"] for r in rows[:5]))

    if not args.commit:
        print("\n(dry-run) nothing written. Re-run with --commit to apply.")
        return 0

    result = bulk_accept_codes(args.client, rows=rows, actor=ACTOR,
                               predicate=PREDICATE)
    print(f"\naccepted {result['accepted']}, skipped {result['skipped']}")
    left = corroborated_rows(args.client)
    print(f"remaining corroborated backlog: {len(left)}")
    return 0 if not left else 1


if __name__ == "__main__":
    raise SystemExit(main())
