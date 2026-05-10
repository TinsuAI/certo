"""Post-BOM-ingest catalog fixup for Johnson (Phase 4).

After ingesting raw_graph BOMs, two catalog gaps exist:

1. **Intermediate parent codes never in BCCT** — Johnson BTP_SX without
   NP/XK (memory `project_reingest_pending`). These appear ONLY as
   `parent_code` in `hub.bom_edges`, never in `bcct_rows`. Insert as
   `materials` with `category='btp_sx'` and `source='bom_observed'`.

2. **NVL materials that turned out to be sub-assemblies** — codes
   classified `nvl` by `bootstrap_catalog_from_bcct.py` (because they
   only appear as imports in BCCT) but BOM later reveals them as
   intermediate parents. Reclassify to `btp_sx`. Memory
   `project_bom_code_multirole` notes the proper fix is multi-role
   columns; for MVP we use the single-value column.

Idempotent. Re-runnable. Only writes when something changes.

Usage:
    uv run python scripts/fixup_johnson_btp_sx_after_bom.py [--commit]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from app.database import connect


CLIENT_ID = "johnson-vn"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--client", default=CLIENT_ID)
    args = ap.parse_args()

    cid = args.client

    with connect() as conn, conn.cursor() as cur:
        # 1) Find intermediate parent codes (parent in BOM that aren't
        # the root_code of any bom_artifact).
        cur.execute(
            """
            with edges as (
                select distinct be.parent_code
                  from hub.bom_edges be
                  join hub.bom_artifacts ba on ba.artifact_id = be.artifact_id
                 where ba.client_id = %s and ba.tombstoned_at is null
            ),
            roots as (
                select distinct product_code
                  from hub.bom_artifacts
                 where client_id = %s and tombstoned_at is null
            )
            select e.parent_code,
                   coalesce(m.category, '<missing>') as cat
              from edges e
              left join hub.materials m
                     on m.client_id = %s and m.material_code = e.parent_code
             where e.parent_code not in (select product_code from roots)
            """,
            (cid, cid, cid),
        )
        rows = cur.fetchall()

    missing_btp = [r[0] for r in rows if r[1] == "<missing>"]
    nvl_to_promote = [r[0] for r in rows if r[1] == "nvl"]

    print(f"client_id              = {cid}")
    print(f"missing BTP intermediates = {len(missing_btp)}")
    print(f"nvl → btp_sx reclassify  = {len(nvl_to_promote)}")
    if not args.commit:
        print("\n(dry-run) re-run with --commit to apply.")
        return 0

    if not missing_btp and not nvl_to_promote:
        print("\nNothing to do.")
        return 0

    with connect() as conn, conn.cursor() as cur:
        if missing_btp:
            cur.executemany(
                """
                insert into hub.materials
                  (client_id, material_code, name, category, status, source,
                   code_kind, provenance)
                values (%s, %s, %s, 'btp_sx', 'active', 'bom_observed',
                        'unified', '{"seen_in_bom_only": true}'::jsonb)
                on conflict (client_id, material_code) do nothing
                """,
                [(cid, code, code) for code in missing_btp],
            )
            print(f"  inserted {len(missing_btp)} btp_sx (bom_observed)")
        if nvl_to_promote:
            cur.execute(
                """
                update hub.materials
                   set category = 'btp_sx',
                       updated_at = now()
                 where client_id = %s
                   and material_code = any(%s)
                   and category = 'nvl'
                """,
                (cid, nvl_to_promote),
            )
            print(f"  reclassified {cur.rowcount} materials nvl → btp_sx")
        conn.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
