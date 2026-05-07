"""Verify v2 (technical_raw) rolls up to v1 (manual_flat) at the BTP boundary.

For each product under a client that has BOTH a published manual_flat
version (v1) AND a published technical_raw version (v2), walk v2's edges
from the root, stopping at any code present in `hub.materials` with
category in ('btp_sx', 'btp_nm', 'tp') OR a true leaf in v2. Group the
stopped quantities by material_code and compare to v1 grouped totals.

Prints a per-product table with:
  v1_uniq   v2_rollup_uniq   overlap   only_v1   only_v2   qty_match   qty_diff   verdict

Verdict is OK when the two sets are bijective and every qty matches.

Usage:
    docker compose exec -T app uv run python scripts/verify_btp_rollup.py \\
        --client growatt-vn

    # Limit to one product:
    docker compose exec -T app uv run python scripts/verify_btp_rollup.py \\
        --client growatt-vn --product SD00.0010600

Read-only. No writes.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from app.database import connect


PAIRS_SQL = """
select v1.product_code,
       v1.artifact_id as v1_id,
       v2.artifact_id as v2_id
from (
    select distinct on (product_code) product_code, artifact_id, created_at
    from hub.bom_artifacts
    where client_id = %(client_id)s
      and tombstoned_at is null
      and status = 'published'
      and source_bom_kind = 'manual_flat'
    order by product_code, created_at desc
) v1
join (
    select distinct on (product_code) product_code, artifact_id, created_at
    from hub.bom_artifacts
    where client_id = %(client_id)s
      and tombstoned_at is null
      and status = 'published'
      and source_bom_kind = 'technical_raw'
    order by product_code, created_at desc
) v2 using (product_code)
order by v1.product_code
"""


VERIFY_SQL = """
with recursive
  e as (
    select parent_code, child_code, qty_per_parent::numeric as q
    from hub.bom_edges where artifact_id = %(v2_id)s
  ),
  stop_set as (
    select customs_code as code
    from hub.materials
    where client_id = %(client_id)s
      and category in ('btp_sx','btp_nm','tp')
  ),
  walk as (
    select child_code, q as cum_qty,
           array[parent_code, child_code] as path
    from e where parent_code = %(product_code)s
    union all
    select e.child_code, w.cum_qty * e.q, w.path || e.child_code
    from walk w join e on e.parent_code = w.child_code
    where w.child_code not in (select code from stop_set)
      and not (e.child_code = any(w.path))
  ),
  stops as (
    select child_code, cum_qty
    from walk w
    where w.child_code in (select code from stop_set)
       or not exists (select 1 from e where parent_code = w.child_code)
  ),
  v2_rollup as (
    select child_code as material_code, sum(cum_qty) as qty
    from stops group by child_code
  ),
  v1 as (
    select material_code, sum(qty_per_unit::numeric) as qty
    from hub.bom_artifact_rows where artifact_id = %(v1_id)s
    group by material_code
  ),
  joined as (
    select coalesce(v1.material_code, v2_rollup.material_code) as code,
           v1.qty as qty_v1, v2_rollup.qty as qty_v2
    from v1 full outer join v2_rollup using (material_code)
  )
select
  (select count(*) from v1) as v1_uniq,
  (select count(*) from v2_rollup) as v2_uniq,
  (select count(*) from joined where qty_v1 is not null and qty_v2 is not null) as overlap,
  (select count(*) from joined where qty_v1 is not null and qty_v2 is null) as only_v1,
  (select count(*) from joined where qty_v1 is null and qty_v2 is not null) as only_v2,
  (select count(*) from joined
     where qty_v1 is not null and qty_v2 is not null and qty_v1 = qty_v2) as qty_match,
  (select count(*) from joined
     where qty_v1 is not null and qty_v2 is not null and qty_v1 <> qty_v2) as qty_diff
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--client", required=True)
    ap.add_argument("--product", default=None,
                    help="optional: limit to one product_code")
    args = ap.parse_args()

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(PAIRS_SQL, {"client_id": args.client})
            pairs = cur.fetchall()

        if args.product:
            pairs = [p for p in pairs if p[0] == args.product]

        if not pairs:
            print(f"No (manual_flat, technical_raw) pairs for client_id={args.client!r}"
                  + (f", product={args.product!r}" if args.product else "") + ".")
            return 0

        print(f"Verifying {len(pairs)} product pair(s) for client_id={args.client}\n")
        cols = ("product_code", "v1_uniq", "v2_uniq", "overlap",
                "only_v1", "only_v2", "qty_match", "qty_diff", "verdict")
        widths = (20, 8, 8, 8, 8, 8, 10, 9, 10)
        print("  ".join(f"{c:<{w}}" for c, w in zip(cols, widths)))
        print("-" * (sum(widths) + 2 * (len(widths) - 1)))

        all_ok = True
        for product_code, v1_id, v2_id in pairs:
            with conn.cursor() as cur:
                cur.execute(VERIFY_SQL, {
                    "client_id": args.client,
                    "v1_id": v1_id,
                    "v2_id": v2_id,
                    "product_code": product_code,
                })
                row = cur.fetchone()
            v1u, v2u, ovl, o1, o2, qm, qd = row
            ok = (o1 == 0 and o2 == 0 and qd == 0 and v1u == v2u)
            if not ok:
                all_ok = False
            verdict = "OK" if ok else "MISMATCH"
            cells = (product_code, str(v1u), str(v2u), str(ovl),
                     str(o1), str(o2), str(qm), str(qd), verdict)
            print("  ".join(f"{c:<{w}}" for c, w in zip(cells, widths)))

        print()
        print("All products match." if all_ok else "Some products mismatch — see above.")
        return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
