"""Phase 3a · classify materials.btp_sourcing for all btp_sx codes.

Sources of evidence (per Phase 3 brief):
- BCCT import row for the code (direction='import') → purchased signal
- code appears as bom_edges.parent_code → self_produced signal

Classification:
- both signals → 'dual_source'
- purchased only → 'purchased_only'
- self-produced only → 'self_produced_only'
- neither → 'unknown'

Usage:
    uv run python -m scripts.detect_dual_source_btps <client_id> [--dry-run]

The classifier is idempotent: re-running with the same data is a no-op.
Manual staff override on materials.btp_sourcing wins until the next
classifier run rewrites it (TODO: respect override flag once UI lands).
"""
from __future__ import annotations

import argparse
import sys

from app.database import connect


def classify_btp_sourcing_for_client(cur, client_id: str) -> dict[str, str]:
    """Return {customs_code: btp_sourcing} for all btp_sx materials of client_id.

    Pure function over (cur, client_id); does not write to DB.
    """
    # mig 035 dropped bcct_rows.internal_code; pull from material_identity.
    # declared_internal_code = parser-derived (e.g. paren-extracted PV01.x);
    # display_code = canonical resolved. Either matching the catalog code is
    # signal of "imported as this catalog item".
    cur.execute(
        """
        select m.customs_code,
               (select count(*) from hub.bcct_rows b
                where b.client_id = %s
                  and coalesce(
                        b.material_identity->>'declared_internal_code',
                        b.material_identity->>'display_code',
                        b.customs_code
                      ) = m.customs_code
                  and b.direction = 'import') as import_count,
               (select count(*) from hub.bom_edges e
                join hub.bom_artifacts a using (artifact_id)
                where a.client_id = %s
                  and e.parent_code = m.customs_code) as parent_count
        from hub.materials m
        where m.client_id = %s and m.category = 'btp_sx'
        """,
        (client_id, client_id, client_id),
    )
    out: dict[str, str] = {}
    for code, import_count, parent_count in cur.fetchall():
        if import_count and parent_count:
            out[code] = "dual_source"
        elif import_count:
            out[code] = "purchased_only"
        elif parent_count:
            out[code] = "self_produced_only"
        else:
            out[code] = "unknown"
    return out


def apply_classifications(cur, client_id: str,
                          classifications: dict[str, str]) -> int:
    """Write classifications to materials.btp_sourcing. Returns count of
    rows actually changed (idempotent — unchanged rows skipped)."""
    n = 0
    for code, value in classifications.items():
        cur.execute(
            """
            update hub.materials
               set btp_sourcing = %s
             where client_id = %s
               and customs_code = %s
               and (btp_sourcing is distinct from %s)
            """,
            (value, client_id, code, value),
        )
        n += cur.rowcount
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("client_id")
    parser.add_argument("--dry-run", action="store_true",
                        help="classify and report; do not write")
    args = parser.parse_args(argv)

    with connect() as conn, conn.cursor() as cur:
        classifications = classify_btp_sourcing_for_client(cur, args.client_id)
        if not classifications:
            print(f"no btp_sx materials for client_id={args.client_id!r}")
            return 0

        breakdown: dict[str, int] = {}
        for v in classifications.values():
            breakdown[v] = breakdown.get(v, 0) + 1
        for k in ("purchased_only", "self_produced_only",
                  "dual_source", "unknown"):
            print(f"  {k:>20s}: {breakdown.get(k, 0)}")
        print(f"  {'total':>20s}: {len(classifications)}")

        if args.dry_run:
            print("(dry-run; no writes)")
            return 0

        n = apply_classifications(cur, args.client_id, classifications)
        print(f"updated {n} row(s) in hub.materials.btp_sourcing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
