"""Settlement-flavored canonical-code resolver — CLI tool, NOT part of hub runtime.

This is a BCQT-flavored algorithm that picks a canonical customs_code (HQ) per
internal_code (NB) by aggregating BCCT import quantities. It was previously
hosted in `app/stores/code_resolution.py` and materialized into hub schema; that
created cross-app coupling (hub master-data system held a settlement-side view).

Per 2026-05-02 decision (see .ai/features/2026-05-02-rip-resolver-from-hub.md):
- The script reads hub raw data (BQD + BCCT rows) as a consumer would.
- Output goes to stdout / file / consumer-side store, NOT into hub schema.
- Destined for BCQT-System repo when BCQT migrates to consumer mode. At that
  point the algorithm should also be FIXED to distinguish NVL (import qty) vs
  TP (export qty E42) per the original `bcqt-growatt/settlement/code_map.py`.
  Current implementation is a known-incomplete port (collapses all to import qty).

Usage:
    uv run python scripts/settlement_resolver.py <client_id> [--json]

Reads:  hub.code_mappings, hub.bcct_rows
Writes: nothing to hub (stdout summary by default; --json for machine-readable)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Allow `uv run python scripts/...` to find app/ for DB connection helper
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.app.database import connect  # noqa: E402


def _load_bqd(cur, client_id: str) -> dict[str, list[str]]:
    cur.execute(
        "select internal_code, customs_code from hub.code_mappings where client_id = %s",
        (client_id,),
    )
    nb_to_hq: dict[str, list[str]] = defaultdict(list)
    for nb, hq in cur.fetchall():
        if hq not in nb_to_hq[nb]:
            nb_to_hq[nb].append(hq)
    return dict(nb_to_hq)


def _load_bcct_aggregates(cur, client_id: str) -> dict[str, dict[str, float]]:
    """Sum import quantities per (internal_code, customs_code).

    KNOWN INCOMPLETE: original Growatt algorithm distinguishes NVL (E11/E15/E13
    import) vs TP (E42 export). This collapses everything to direction='import'.
    Re-fix when porting to BCQT.
    """
    cur.execute(
        """
        select internal_code, customs_code, sum(coalesce(quantity, 0))
        from hub.bcct_rows
        where client_id = %s and direction = 'import'
          and internal_code is not null and customs_code is not null
        group by internal_code, customs_code
        """,
        (client_id,),
    )
    nb_hq_qty: dict[str, dict[str, float]] = defaultdict(dict)
    for nb, hq, qty in cur.fetchall():
        nb_hq_qty[nb][hq] = float(qty or 0)
    return dict(nb_hq_qty)


def _load_bcct_universe(cur, client_id: str) -> set[str]:
    """BCQT-side BCCT universe — distinct identifiers per row.

    mig 038 dropped the material_identity column; this query returns
    customs_code only. For Growatt imports the meaningful agency code
    lives in goods_name parens — settlement-side caller should re-run
    via the Python helper compute_internal_code() if it needs the
    parser-derived internal code. (BCQT consumer rewrite tracked in
    BACKLOG.)
    """
    cur.execute(
        "select distinct customs_code from hub.bcct_rows "
        "where client_id = %s and customs_code is not null",
        (client_id,),
    )
    return {nb for (nb,) in cur.fetchall() if nb}


def resolve(client_id: str) -> list[dict]:
    """Compute canonical resolution per NB. Returns a list of dicts (no hub writes)."""
    out: list[dict] = []
    with connect() as conn:
        with conn.cursor() as cur:
            bqd = _load_bqd(cur, client_id)
            bcct = _load_bcct_aggregates(cur, client_id)
            universe = set(bqd) | set(bcct) | _load_bcct_universe(cur, client_id)

    for nb in sorted(universe):
        bqd_hqs = bqd.get(nb, [])
        bcct_hqs = bcct.get(nb, {})
        if not bqd_hqs:
            resolved, basis = nb, "identity"
        elif len(bqd_hqs) == 1:
            resolved, basis = bqd_hqs[0], "bqd_unique"
        else:
            if bcct_hqs and any(bcct_hqs.get(h, 0) for h in bqd_hqs):
                candidates = {h: bcct_hqs.get(h, 0) for h in bqd_hqs}
                resolved = max(candidates, key=candidates.get)
                basis = "bcct_qty_pick"
            else:
                resolved, basis = bqd_hqs[0], "fallback"
        out.append({
            "internal_code": nb,
            "resolved_customs_code": resolved,
            "resolution_basis": basis,
            "bqd_hqs": bqd_hqs,
            "bcct_qty_by_hq": bcct_hqs,
        })
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("client_id", help="Client ID to resolve")
    p.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    args = p.parse_args()

    rows = resolve(args.client_id)

    if args.json:
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return

    counts = defaultdict(int)
    for r in rows:
        counts[r["resolution_basis"]] += 1
    print(f"client_id={args.client_id} total={len(rows)}")
    for basis, n in sorted(counts.items()):
        print(f"  {basis}: {n}")


if __name__ == "__main__":
    main()
