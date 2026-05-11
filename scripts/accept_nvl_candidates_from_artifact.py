"""Bulk-accept NVL candidates whose code appears in a target BOM artifact.

Use case (2026-05-11): MPL0109-39 (ba_Vvkg7JQ2eSQ6XZe8) has 97 NVL
codes that exist in the BOM but not in catalog and not in BCCT
(VN-domestic supply or free-supplied parts). User confirmed bulk accept
into catalog as category='nvl', name from candidate sample_text
(= SAP "Object description" backfilled by A.7).

Filter:
- candidate.client_id matches
- candidate.code in target_artifact's distinct material_code set
- candidate.status='pending'
- candidate.bom_role='nvl_leaf'
- candidate.code NOT already in materials (defensive; refresh anti-joins
  but a race-condition or stale view could mismatch)

Usage:
  uv run python scripts/accept_nvl_candidates_from_artifact.py \\
    --client johnson-vn --artifact-id ba_Vvkg7JQ2eSQ6XZe8 [--commit]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from app.database import connect
from app.stores.catalog_candidates import accept_candidate


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--artifact-id", required=True)
    ap.add_argument("--commit", action="store_true",
                    help="actually write (default: dry-run)")
    ap.add_argument(
        "--actor", default="bulk_nvl_accept",
        help="user_id for audit trail (default: bulk_nvl_accept)",
    )
    ap.add_argument(
        "--status", default="active",
        choices=["under_review", "active"],
        help="materials.status after accept (default: active)",
    )
    args = ap.parse_args()

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select 1 from hub.bom_artifacts where artifact_id=%s "
            "  and client_id=%s and tombstoned_at is null",
            (args.artifact_id, args.client),
        )
        if not cur.fetchone():
            print(f"FAIL artifact {args.artifact_id} not alive for "
                  f"client {args.client}", file=sys.stderr)
            return 2

        cur.execute(
            """
            with codes_in_artifact as (
              select distinct material_code from hub.bom_artifact_rows
              where artifact_id=%s
            )
            select cc.candidate_id, cc.code, cc.bom_role,
                   cc.sample_text, cc.uom, cc.inferred_production_source,
                   cc.observed_count
            from codes_in_artifact c
            join hub.catalog_candidates cc
              on cc.client_id=%s and cc.code=c.material_code
             and cc.status='pending'
            left join hub.materials m
              on m.client_id=cc.client_id and m.material_code=cc.code
            where m.material_code is null
              and cc.bom_role='nvl_leaf'
            order by cc.observed_count desc
            """,
            (args.artifact_id, args.client),
        )
        rows = cur.fetchall()

    print(f"Eligible NVL candidates: {len(rows)}")
    if not rows:
        print("Nothing to accept.")
        return 0

    # Show sample
    for r in rows[:5]:
        cid, code, role, sample, uom, prod, obs = r
        print(f"  cid={cid} code={code} obs={obs} uom={uom or '-'} "
              f"prod={prod or '-'} sample={(sample or '')[:60]!r}")

    if not args.commit:
        print(f"\nDry-run only. {len(rows)} candidates would be accepted "
              f"as category=nvl, status={args.status}, "
              f"name=sample_text (fallback to code).")
        return 0

    accepted = 0
    name_from_code = 0
    failed: list[tuple[int, str, str]] = []
    for r in rows:
        cid, code, role, sample, uom, prod, obs = r
        name = (sample or "").strip()
        if not name:
            name = code  # fallback when description missing
            name_from_code += 1
        # Cap to 300 chars (matches sample_text truncate convention)
        name = name[:300]
        try:
            accept_candidate(
                candidate_id=cid,
                actor=args.actor,
                name=name,
                category="nvl",
                status=args.status,
                uom=uom,
                production_source=prod,
                supplier_hint=None,
            )
            accepted += 1
        except Exception as exc:  # noqa: BLE001
            failed.append((cid, code, str(exc)))

    print(f"\nCOMMITTED: accepted {accepted} / {len(rows)} candidates.")
    print(f"  name fallback to code (empty sample): {name_from_code}")
    if failed:
        print(f"  failed: {len(failed)}")
        for cid, code, err in failed[:5]:
            print(f"    candidate {cid} ({code}): {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
