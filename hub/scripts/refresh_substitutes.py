"""Materialize substitute candidates for one client (Feature 4 P5).

Thin CLI wrapper around `app.stores.material_substitutes.refresh_candidates`
so the web admin page can spawn it as a detached subprocess (the function
takes minutes — too long to block an HTTP response).

Honors `hub.clients.substitute_rules` toggles: same_hs (P4), trigram
(P5a), embedding (P5b). Idempotent.

Usage:
    uv run python scripts/refresh_substitutes.py --client johnson-vn
    uv run python scripts/refresh_substitutes.py --client johnson-vn \\
        --same-hs-cap 30 --trigram-threshold 0.5
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from hub.app.stores.material_substitutes import refresh_candidates


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--same-hs-cap", type=int, default=30,
                    help="skip HS groups larger than this (avoid noise)")
    ap.add_argument("--trigram-threshold", type=float, default=0.5)
    ap.add_argument("--trigram-limit", type=int, default=10,
                    help="top-N trigram candidates per material")
    args = ap.parse_args()

    print(f"client_id        = {args.client}")
    print(f"same_hs_cap      = {args.same_hs_cap}")
    print(f"trigram_threshold= {args.trigram_threshold}")
    print(f"trigram_limit    = {args.trigram_limit}")
    print()

    t0 = time.monotonic()
    stats = refresh_candidates(
        client_id=args.client,
        trigram_threshold=args.trigram_threshold,
        trigram_limit_per_material=args.trigram_limit,
        same_hs_max_group_size=args.same_hs_cap,
    )
    elapsed = time.monotonic() - t0

    print(f"  same_hs:   {stats.same_hs_inserted}")
    print(f"  trigram:   {stats.trigram_inserted}")
    print(f"  embedding: {stats.embedding_inserted}")
    print(f"  applied:   {stats.rules_applied}")
    print(f"  skipped:   {stats.rules_skipped}")
    print(f"  elapsed:   {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
