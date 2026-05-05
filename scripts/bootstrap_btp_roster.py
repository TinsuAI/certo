"""Bootstrap BTP roster in hub.materials from observed BOM data.

Detection rule: a code is a BTP iff it owns a `hub.bom_versions` row
(it has its own structure) AND appears as `child_code` in `hub.bom_edges`
of any BOM in the same client (it is consumed by another product).
Codes that own a BOM but are never consumed are TP roots; codes that
appear only as children with no BOM of their own are leaf NVL.

Usage:

    docker compose exec -T app uv run python scripts/bootstrap_btp_roster.py \\
        --client growatt-vn               # dry-run

    docker compose exec -T app uv run python scripts/bootstrap_btp_roster.py \\
        --client growatt-vn --commit      # actually insert

Behavior:
- Only INSERTs codes that do not already exist in `hub.materials`.
- Existing rows are NEVER overwritten — if a code is already present
  with another category (e.g. mistakenly `nvl`), the script reports
  the conflict but leaves the row alone for human review.
- Idempotent: re-running with --commit after a successful run is a no-op.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from app.database import connect


DETECT_BTPS_SQL = """
with
  has_bom as (
    select distinct product_code
    from hub.bom_versions
    where client_id = %(client_id)s and tombstoned_at is null
  ),
  consumed_uoms as (
    select e.child_code as code, e.uom
    from hub.bom_edges e
    join hub.bom_versions bv using (version_id)
    where bv.client_id = %(client_id)s and bv.tombstoned_at is null
    union all
    select r.material_code as code, r.uom
    from hub.bom_version_rows r
    join hub.bom_versions bv using (version_id)
    where bv.client_id = %(client_id)s and bv.tombstoned_at is null
  ),
  consumed as (
    select code, max(uom) as uom
    from consumed_uoms where uom is not null group by code
  )
select hb.product_code, c.uom
from has_bom hb
join consumed c on c.code = hb.product_code
order by hb.product_code
"""


CHECK_EXISTING_SQL = """
select customs_code, category
from hub.materials
where client_id = %(client_id)s and customs_code = any(%(codes)s)
"""


INSERT_BTP_SQL = """
insert into hub.materials
  (client_id, customs_code, internal_code, name, category, status, unit, provenance)
values
  (%(client_id)s, %(code)s, %(code)s, null, 'btp_sx', 'active', %(unit)s,
   jsonb_build_object(
     'btp_inferred', jsonb_build_object(
       'first_seen', to_char(now(), 'YYYY-MM-DD'),
       'detector', 'bootstrap_btp_roster.py',
       'rule', 'has_own_bom_and_consumed_as_child'
     )
   ))
on conflict (client_id, customs_code) do nothing
"""


def detect(conn, client_id: str):
    with conn.cursor() as cur:
        cur.execute(DETECT_BTPS_SQL, {"client_id": client_id})
        return [{"code": r[0], "unit": r[1]} for r in cur.fetchall()]


def existing(conn, client_id: str, codes: list[str]) -> dict[str, str]:
    if not codes:
        return {}
    with conn.cursor() as cur:
        cur.execute(CHECK_EXISTING_SQL, {"client_id": client_id, "codes": codes})
        return {r[0]: r[1] for r in cur.fetchall()}


def insert(conn, client_id: str, rows: list[dict]) -> int:
    n = 0
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(INSERT_BTP_SQL, {
                "client_id": client_id,
                "code": r["code"],
                "unit": r.get("unit"),
            })
            n += cur.rowcount
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--client", required=True, help="client_id (e.g. growatt-vn)")
    ap.add_argument("--commit", action="store_true",
                    help="write to DB; default is dry-run")
    args = ap.parse_args()

    with connect() as conn:
        candidates = detect(conn, args.client)
        if not candidates:
            print(f"No BTP candidates detected for client_id={args.client!r}.")
            return 0

        codes = [c["code"] for c in candidates]
        ex = existing(conn, args.client, codes)

        new_rows = [c for c in candidates if c["code"] not in ex]
        already = [c for c in candidates if ex.get(c["code"]) in ("btp_sx", "btp_nm")]
        miscat = [(c, ex[c["code"]]) for c in candidates
                  if c["code"] in ex and ex[c["code"]] not in ("btp_sx", "btp_nm")]

        print(f"client_id              = {args.client}")
        print(f"BTP candidates total   = {len(candidates)}")
        print(f"  already btp_sx/btp_nm = {len(already)}")
        print(f"  miscategorized other  = {len(miscat)}")
        print(f"  new (to insert)       = {len(new_rows)}")

        if miscat:
            print("\nConflicts (existing rows with non-BTP category — left untouched):")
            for c, cat in miscat[:10]:
                print(f"  {c['code']:25s} current={cat}")
            if len(miscat) > 10:
                print(f"  ... and {len(miscat) - 10} more")

        if new_rows:
            print("\nSample of new rows:")
            for c in new_rows[:5]:
                unit = c.get("unit") or "-"
                print(f"  {c['code']:25s} unit={unit}")
            if len(new_rows) > 5:
                print(f"  ... and {len(new_rows) - 5} more")

        if not args.commit:
            print("\n(dry-run) no rows written. Re-run with --commit to write.")
            return 0

        n = insert(conn, args.client, new_rows)
        conn.commit()
        print(f"\nInserted {n} BTP rows into hub.materials.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
