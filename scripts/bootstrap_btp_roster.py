"""Bootstrap BTP roster in hub.materials from observed BOM data.

Detection rule: a code is a BTP iff it owns a `hub.bom_artifacts` row
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
-- A BTP is any code that participates as a parent in a BOM (so it has
-- a structure beneath it) but is NOT a TP root. This handles two shapes:
--
-- KNOWN LIMITATION (orphan BTPs): A code that owns its own bom_artifacts
-- row AND is never consumed as a child by any other product in this
-- client's data is classified as a TP root by this rule. For Growatt,
-- 14 codes (033.*, 100.*, B700.*, B710.*) match this profile — they
-- have own supplier files but their parent TP files weren't ingested.
-- Per agency naming convention these are still BTPs, but the rule has
-- no way to know that without prefix/regex heuristics that don't
-- generalize across clients. Staff can manually flip category from
-- whatever default landed (usually 'nvl' from BCCT, or absent) once
-- they identify the parent TPs.
--
--
-- (A) Growatt-shape: BTP has its own bom_artifacts row AND appears as
--     child_code in some BOM. Example: B700.0192500 has its own factory
--     XLSX file producing a bom_artifacts row, and is consumed by SD/PV TPs.
--
-- (B) Johnson-shape: each TP's full multi-level tree is in ONE supplier
--     file. Intermediate sub-assembly codes (level 2+) appear as
--     parent_code inside the TP's bom_edges but DON'T have their own
--     bom_artifacts row. They're still BTPs by domain meaning.
--
-- The union below catches both: any code that appears as parent_code
-- in bom_edges (including intermediate parents at level 2+) MINUS the
-- TP roots (codes that have a bom_artifacts row representing a top-level
-- product).
with
  tp_roots as (
    -- TP root = code that owns a bom_artifacts row AND is never consumed
    -- as a child by ANY other product's BOM in this client. Codes that
    -- own a bom_artifacts row but are also consumed elsewhere are BTPs
    -- (Growatt B700.* family pattern: own supplier file + used in TPs).
    select bv.product_code as code
    from hub.bom_artifacts bv
    where bv.client_id = %(client_id)s and bv.tombstoned_at is null
      and not exists (
        select 1 from hub.bom_edges e
        join hub.bom_artifacts bv2 on bv2.artifact_id = e.artifact_id
        where bv2.client_id = %(client_id)s
          and bv2.tombstoned_at is null
          and e.child_code = bv.product_code
          and bv2.product_code <> bv.product_code
      )
  ),
  parents as (
    select distinct e.parent_code as code, max(e.uom) as uom
    from hub.bom_edges e
    join hub.bom_artifacts bv using (artifact_id)
    where bv.client_id = %(client_id)s and bv.tombstoned_at is null
    group by e.parent_code
  ),
  -- Plus codes that are explicitly consumed as child somewhere AND have
  -- their own bom_artifacts (Growatt-shape sanity check; doesn't add new
  -- BTPs in Johnson-shape but harmless).
  has_bom_and_consumed as (
    select bv.product_code as code, max(coalesce(e.uom, r.uom)) as uom
    from hub.bom_artifacts bv
    left join hub.bom_edges e on e.child_code = bv.product_code
    left join hub.bom_artifact_rows r on r.material_code = bv.product_code
    where bv.client_id = %(client_id)s and bv.tombstoned_at is null
      and (e.artifact_id is not null or r.artifact_id is not null)
    group by bv.product_code
  ),
  candidates as (
    select code, uom from parents
    union
    select code, uom from has_bom_and_consumed
  )
select c.code as product_code, max(c.uom) as uom
from candidates c
where c.code not in (select code from tp_roots)
group by c.code
order by c.code
"""


CHECK_EXISTING_SQL = """
select customs_code, category
from hub.materials
where client_id = %(client_id)s and material_code = any(%(codes)s)
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
