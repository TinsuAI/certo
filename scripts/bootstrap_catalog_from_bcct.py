"""Fill catalog gaps using BCCT declarations as ground truth.

For each client, scan hub.bcct_rows. Codes appearing as direction='import'
that are not yet in hub.materials → insert as nvl (or btp_sx if a
bom_artifacts row already exists for that code = code is a sub-assembly).
Codes appearing as direction='export' not in catalog → insert as tp.

Existing materials rows are NEVER overwritten. Only the seen_in_bcct
provenance jsonb key is merged in (uses the existing helper from
app/stores/provenance.py via raw SQL).

Usage:
    uv run python scripts/bootstrap_catalog_from_bcct.py --client growatt-vn
    uv run python scripts/bootstrap_catalog_from_bcct.py --client growatt-vn --commit
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from app.database import connect


DETECT_SQL = """
with
  bcct_codes as (
    select customs_code, direction,
           min(goods_name) as goods_name,
           min(unit) as unit,
           min(hs_code) as hs_code,
           count(*) as decl_count
    from hub.bcct_rows
    where client_id = %(client_id)s
      and customs_code is not null
      and direction in ('import','export')
    group by customs_code, direction
  ),
  has_bom as (
    select distinct product_code
    from hub.bom_artifacts
    where client_id = %(client_id)s and tombstoned_at is null
  ),
  in_catalog as (
    select material_code, category from hub.materials where client_id = %(client_id)s
  )
select b.customs_code, b.direction, b.goods_name, b.unit, b.hs_code, b.decl_count,
       (b.customs_code in (select product_code from has_bom)) as has_bom,
       coalesce(c.category, '<none>') as existing_category
from bcct_codes b
left join in_catalog c on c.material_code = b.customs_code
order by b.direction, b.customs_code
"""


INSERT_SQL = """
insert into hub.materials
  (client_id, material_code, name, category, status, uom, hs_code,
   source, provenance)
values (%(client_id)s, %(code)s, %(name)s, %(category)s, 'active',
        %(unit)s, %(hs_code)s, 'bcct_observed',
        jsonb_build_object('seen_in_bcct',
          jsonb_build_object('first_seen', to_char(now(),'YYYY-MM-DD'),
                              'decl_count', %(decl_count)s::int,
                              'directions', %(directions)s::jsonb)))
on conflict (client_id, material_code) do update set
  -- Backfill uom if missing (legacy rows from before mig 063 had unit-only).
  uom = coalesce(hub.materials.uom, excluded.uom),
  provenance = hub.materials.provenance ||
    jsonb_build_object('seen_in_bcct',
      jsonb_build_object(
        'first_seen', coalesce(
          hub.materials.provenance->'seen_in_bcct'->>'first_seen',
          to_char(now(),'YYYY-MM-DD')),
        'last_seen', to_char(now(),'YYYY-MM-DD'),
        'decl_count', excluded.provenance->'seen_in_bcct'->'decl_count',
        'directions', excluded.provenance->'seen_in_bcct'->'directions')),
  updated_at = now()
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--client", required=True)
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(DETECT_SQL, {"client_id": args.client})
            rows = cur.fetchall()

    if not rows:
        print(f"No BCCT rows for client_id={args.client}")
        return 0

    # Aggregate by customs_code: a single code may appear in BOTH directions
    by_code: dict[str, dict] = {}
    for code, direction, goods_name, unit, hs_code, decl_count, has_bom, existing_category in rows:
        e = by_code.setdefault(code, {
            "code": code, "name": goods_name, "unit": unit, "hs_code": hs_code,
            "directions": [], "decl_count": 0, "has_bom": has_bom,
            "existing_category": existing_category,
        })
        e["directions"].append(direction)
        e["decl_count"] += int(decl_count or 0)
        # prefer non-null name/unit/hs from any direction
        e["name"] = e["name"] or goods_name
        e["unit"] = e["unit"] or unit
        e["hs_code"] = e["hs_code"] or hs_code

    # Classify
    new_inserts: list[dict] = []
    updates: list[dict] = []
    skip_have: list[dict] = []
    for e in by_code.values():
        if e["existing_category"] != "<none>":
            updates.append(e)  # provenance merge only
            continue
        # Decide category from directions + has_bom
        directions = set(e["directions"])
        if e["has_bom"]:
            cat = "btp_sx" if "import" in directions else "tp"
        else:
            cat = "nvl" if directions == {"import"} else (
                "tp" if directions == {"export"} else "nvl"  # mixed → default nvl
            )
        e["category"] = cat
        new_inserts.append(e)

    print(f"client_id        = {args.client}")
    print(f"BCCT codes found = {len(by_code)}")
    print(f"  already in catalog (provenance merge): {len(updates)}")
    print(f"  new inserts: {len(new_inserts)}")
    by_cat: dict[str, int] = {}
    for e in new_inserts:
        by_cat[e["category"]] = by_cat.get(e["category"], 0) + 1
    for cat, n in sorted(by_cat.items()):
        print(f"    {cat}: {n}")

    if not args.commit:
        print("\n(dry-run) no rows written. Re-run with --commit to apply.")
        return 0

    with connect() as conn:
        with conn.cursor() as cur:
            n_ins = 0
            for e in new_inserts + updates:
                cur.execute(INSERT_SQL, {
                    "client_id": args.client,
                    "code": e["code"],
                    "name": e["name"] or e["code"],
                    "category": e.get("category") or e["existing_category"],
                    "unit": e["unit"],
                    "hs_code": e["hs_code"],
                    "decl_count": e["decl_count"],
                    "directions": __import__("json").dumps(sorted(set(e["directions"]))),
                })
                n_ins += cur.rowcount
        conn.commit()
    print(f"\nInserted/updated {n_ins} materials rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
