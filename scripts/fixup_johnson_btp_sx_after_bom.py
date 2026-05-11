"""Post-BOM-ingest catalog fixup for Johnson (Phase 4).

After ingesting raw_graph BOMs, three catalog gaps exist:

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

3. **Leaf codes only seen in BOM** — codes appearing as `child_code`
   in `hub.bom_edges` but never in `bcct_rows`, never as parent of any
   edge. Insert as `materials` with `category='nvl'` (default for BOM
   leaves) and `source='bom_observed'`. Without this rescue, BOM-only
   codes would dangle as references with no catalog row, and Phase 2
   engine would skip them on `make_catalog_lookup`.

All three paths capture `uom` from `hub.bom_edges` (mode value) so
post-ingest catalog has canonical UoM populated end-to-end — invariant
enforced via `tests/test_fixup_johnson_btp_uom.py`. Idempotent. Only
writes when something changes.

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

    # Leaf orphans: child_codes in bom_edges that have no materials row AND
    # are not the parent of any edge (true leaves; per case (3) above).
    # Default category 'nvl' — staff can re-categorize via catalog UI.
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            with bom_codes as (
              select distinct be.child_code as code
                from hub.bom_edges be
                join hub.bom_artifacts ba on ba.artifact_id = be.artifact_id
               where ba.client_id = %s and ba.tombstoned_at is null
            ),
            parents as (
              select distinct be.parent_code as code
                from hub.bom_edges be
                join hub.bom_artifacts ba on ba.artifact_id = be.artifact_id
               where ba.client_id = %s and ba.tombstoned_at is null
            )
            select b.code
              from bom_codes b
              left join hub.materials m
                     on m.client_id = %s and m.material_code = b.code
             where m.material_code is null
               and b.code not in (select code from parents)
            """,
            (cid, cid, cid),
        )
        leaf_orphans = [r[0] for r in cur.fetchall()]

    print(f"client_id              = {cid}")
    print(f"missing BTP intermediates = {len(missing_btp)}")
    print(f"nvl → btp_sx reclassify  = {len(nvl_to_promote)}")
    print(f"leaf orphans (BOM-only NVL) = {len(leaf_orphans)}")
    if not args.commit:
        print("\n(dry-run) re-run with --commit to apply.")
        return 0

    if not missing_btp and not nvl_to_promote and not leaf_orphans:
        print("\nNothing to do.")
        return 0

    with connect() as conn, conn.cursor() as cur:
        if missing_btp:
            # Capture uom per code from the mode (most-frequent) value of
            # `bom_edges.uom` where the BTP appears as parent. Without this,
            # bom_observed BTPs would land with uom=NULL even though the BOM
            # source carries the UoM per edge — causing engine to drift on
            # `catalog_uom_missing` despite source data being available
            # (pipeline bug, not data gap; fixed at the ingest seam per
            # mig 063 consolidation).
            cur.execute(
                """
                insert into hub.materials
                  (client_id, material_code, name, category, status, source,
                   code_kind, uom, provenance)
                select %s, code, code, 'btp_sx', 'active', 'bom_observed',
                       'unified',
                       (select e.uom
                          from hub.bom_edges e
                          join hub.bom_artifacts a
                               on a.artifact_id = e.artifact_id
                         where a.client_id = %s
                           and e.parent_code = code
                           and a.tombstoned_at is null
                           and e.uom is not null and trim(e.uom) <> ''
                         group by e.uom
                         order by count(*) desc, e.uom
                         limit 1) as uom,
                       '{"seen_in_bom_only": true}'::jsonb
                  from unnest(%s::text[]) as code
                on conflict (client_id, material_code) do update set
                  uom = coalesce(hub.materials.uom, excluded.uom),
                  updated_at = now()
                """,
                (cid, cid, list(missing_btp)),
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
        if leaf_orphans:
            # Insert as default nvl. Capture uom from mode of bom_edges.uom
            # where this code appears as child — same UoM-capture pattern as
            # case (1). Staff can re-categorize (e.g., to btp_nm) later.
            cur.execute(
                """
                insert into hub.materials
                  (client_id, material_code, name, category, status, source,
                   code_kind, uom, provenance)
                select %s, code, code, 'nvl', 'active', 'bom_observed',
                       'unified',
                       (select e.uom
                          from hub.bom_edges e
                          join hub.bom_artifacts a
                               on a.artifact_id = e.artifact_id
                         where a.client_id = %s
                           and e.child_code = code
                           and a.tombstoned_at is null
                           and e.uom is not null and trim(e.uom) <> ''
                         group by e.uom
                         order by count(*) desc, e.uom
                         limit 1) as uom,
                       '{"seen_in_bom_only": true}'::jsonb
                  from unnest(%s::text[]) as code
                on conflict (client_id, material_code) do update set
                  uom = coalesce(hub.materials.uom, excluded.uom),
                  updated_at = now()
                """,
                (cid, cid, list(leaf_orphans)),
            )
            print(f"  inserted {len(leaf_orphans)} nvl (leaf orphans, bom_observed)")
        conn.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
