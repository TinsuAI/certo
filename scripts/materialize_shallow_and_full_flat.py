"""Auto-derive shallow + full_flat versions from raw_graph BOMs.

For each alive technical_raw version (bom_shape='raw_graph'), derive:
  - shallow: walk edges, stop at any code in materials.category in
    ('btp_sx','btp_nm','tp') OR a true leaf in this graph. Group by
    material_code. Flatten_strategy='purchased_btp_as_leaf' so bom_shape
    derives to 'shallow'.
  - full_flat: walk edges to true leaves only (codes that don't appear
    as parent_code in this raw_graph). Group by material_code.
    Flatten_strategy='technical_exploded' so bom_shape derives to 'full_flat'.

Inserts new bom_artifacts via `create_artifact` with:
  - actor='erp_pipeline'
  - intent='derived'
  - source_channel='auto_derived'
  - parent_artifact_id = the raw_graph artifact_id (lineage)
  - context = batch + adapter info copied from raw

Status policy: respects clients.auto_derive_shallow_from_raw
  - 'disabled': do nothing
  - 'draft_only' (default): insert as status='draft'
  - 'publish': insert as status='published'

Idempotent via normalized_hash. Re-runnable safely.

Usage:
    uv run python scripts/materialize_shallow_and_full_flat.py --client growatt-vn
    uv run python scripts/materialize_shallow_and_full_flat.py --client growatt-vn --commit
    uv run python scripts/materialize_shallow_and_full_flat.py --client growatt-vn --commit --force-publish
"""
from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from app.database import connect
from app.stores.bom import create_artifact


LIST_RAW_VERSIONS_SQL = """
select artifact_id, product_code, bom_variant_id, context, normalized_hash
from hub.bom_artifacts
where client_id = %(client_id)s
  and source_bom_kind = 'technical_raw'
  and tombstoned_at is null
  and status = 'published'
order by created_at
"""


SHALLOW_WALK_SQL = """
with recursive
  e as (
    select parent_code, child_code, qty_per_parent::numeric as q, uom
    from hub.bom_edges where artifact_id = %(artifact_id)s
  ),
  -- Phase 3a: btp_sx with btp_sourcing='self_produced_only' is exploded
  -- (treated like an inner node), every other btp_sx still stops the
  -- shallow walk. btp_nm and tp always stop. NULL/unknown sourcing
  -- defaults to stop (legacy behavior; staff classifies via catalog UI).
  stop_set as (
    select material_code as code from hub.materials
    where client_id = %(client_id)s
      and (
        category in ('btp_nm','tp')
        or (category = 'btp_sx'
            and (btp_sourcing is null or btp_sourcing != 'self_produced_only'))
      )
  ),
  walk as (
    select child_code, q as cum_qty, uom,
           array[parent_code, child_code] as path
    from e where parent_code = %(product_code)s
    union all
    select e.child_code, w.cum_qty * e.q, e.uom, w.path || e.child_code
    from walk w join e on e.parent_code = w.child_code
    where w.child_code not in (select code from stop_set)
      and not (e.child_code = any(w.path))
  ),
  stops as (
    select child_code, cum_qty, uom from walk w
    where w.child_code in (select code from stop_set)
       or not exists (select 1 from e where parent_code = w.child_code)
  )
select child_code, sum(cum_qty) as qty, max(uom) as uom
from stops group by child_code order by child_code
"""


FULL_FLAT_WALK_SQL = """
with recursive
  e as (
    select parent_code, child_code, qty_per_parent::numeric as q, uom
    from hub.bom_edges where artifact_id = %(artifact_id)s
  ),
  parents as (select distinct parent_code from e),
  walk as (
    select child_code, q as cum_qty, uom,
           array[parent_code, child_code] as path
    from e where parent_code = %(product_code)s
    union all
    select e.child_code, w.cum_qty * e.q, e.uom, w.path || e.child_code
    from walk w join e on e.parent_code = w.child_code
    where not (e.child_code = any(w.path))
  ),
  leaves as (
    select w.child_code, w.cum_qty, w.uom
    from walk w left join parents p on p.parent_code = w.child_code
    where p.parent_code is null
  )
select child_code, sum(cum_qty) as qty, max(uom) as uom
from leaves group by child_code order by child_code
"""


def fetch_client_policy(client_id: str) -> str:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select auto_derive_shallow_from_raw from hub.clients where client_id=%s",
                (client_id,),
            )
            r = cur.fetchone()
    return r[0] if r else "draft_only"


def derive(raw_artifact_id: str, product_code: str, client_id: str,
           sql: str) -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {
                "client_id": client_id,
                "artifact_id": raw_artifact_id,
                "product_code": product_code,
            })
            return [
                {"material_code": r[0], "qty_per_unit": float(r[1]), "uom": r[2]}
                for r in cur.fetchall()
            ]


def list_raw_artifacts_missing_shapes(client_id: str) -> list[tuple]:
    """Published technical_raw artifacts for `client_id` that don't yet
    have any derived flattened artifact (shallow / full_flat) attached.
    Used by the post-ingest hook to catch up the per-artifact
    materialization without walking everything."""
    sql = """
    select raw.artifact_id, raw.product_code, raw.bom_variant_id,
           raw.context, raw.normalized_hash
      from hub.bom_artifacts raw
     where raw.client_id = %s
       and raw.source_bom_kind = 'technical_raw'
       and raw.tombstoned_at is null
       and raw.status = 'published'
       and not exists (
         select 1 from hub.bom_artifacts d
          where d.client_id = raw.client_id
            and d.product_code = raw.product_code
            and d.parent_artifact_id = raw.artifact_id
            and d.source_bom_kind = 'technical_flattened'
            and d.tombstoned_at is null
       )
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (client_id,))
        return cur.fetchall()


def materialize_one(
    raw_id: str, product_code: str, raw_variant: str | None,
    raw_ctx: dict | None, *, client_id: str, publish: bool = True,
) -> dict:
    """Materialize shallow + full_flat for one raw_graph artifact.
    Returns counters dict. Idempotent via create_artifact's hash dedup."""
    counters = {"shallow_inserted": 0, "shallow_dedup": 0,
                "full_flat_inserted": 0, "full_flat_dedup": 0,
                "shallow_empty": 0, "full_flat_empty": 0}
    for kind, sql, strategy in [
        ("shallow", SHALLOW_WALK_SQL, "purchased_btp_as_leaf"),
        ("full_flat", FULL_FLAT_WALK_SQL, "technical_exploded"),
    ]:
        rows = derive(raw_id, product_code, client_id, sql)
        if not rows:
            counters[f"{kind}_empty"] += 1
            continue
        new_ctx = dict(raw_ctx or {})
        new_ctx.update({
            "channel": "auto_derived",
            "profile": kind,
            "derived_from_artifact_id": raw_id,
            "derived_from_variant": raw_variant,
            "ingest_script": "materialize_shallow_and_full_flat.py",
        })
        existing = create_artifact(
            client_id=client_id, product_code=product_code, rows=rows,
            actor="erp_pipeline", intent="derived",
            parent_artifact_id=raw_id, context=new_ctx,
            source_upload_id=None,
            source_bom_kind="technical_flattened",
            flatten_status="flattened",
            flatten_strategy=strategy,
            source_channel="migration",
            bom_variant_id=raw_variant,
            flatten_method="recursive_sql",
            flatten_method_version="1",
        )
        if existing:
            counters[f"{kind}_inserted"] += 1
        else:
            counters[f"{kind}_dedup"] += 1
    if not publish:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                update hub.bom_artifacts
                   set status='draft'
                 where client_id=%s and product_code=%s
                   and parent_artifact_id=%s
                   and source_channel='migration'
                   and context->>'channel'='auto_derived'
                   and status='published'
                   and created_at > now() - interval '60 seconds'
                   and not exists (
                     select 1 from hub.bom_presets p
                      where p.artifact_id = hub.bom_artifacts.artifact_id
                        and p.tombstoned_at is null
                   )
                """,
                (client_id, product_code, raw_id),
            )
    return counters


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--client", required=True)
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--force-publish", action="store_true",
                    help="ignore client policy; publish derived versions")
    args = ap.parse_args()

    policy = fetch_client_policy(args.client)
    if policy == "disabled" and not args.force_publish:
        print(f"client {args.client!r} has auto_derive_shallow_from_raw='disabled'."
              f" Nothing to do (use --force-publish to override).")
        return 0

    publish = args.force_publish or policy == "publish"
    print(f"client                = {args.client}")
    print(f"policy                = {policy}")
    print(f"will be {'PUBLISHED' if publish else 'DRAFT'}")
    print()

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(LIST_RAW_VERSIONS_SQL, {"client_id": args.client})
            raw_versions = cur.fetchall()

    print(f"raw_graph versions to derive from: {len(raw_versions)}")

    counters = {"shallow_inserted": 0, "shallow_dedup": 0,
                "full_flat_inserted": 0, "full_flat_dedup": 0,
                "shallow_empty": 0, "full_flat_empty": 0}

    for raw_id, product_code, raw_variant, raw_ctx, raw_hash in raw_versions:
        if not args.commit:
            shallow_rows = derive(raw_id, product_code, args.client, SHALLOW_WALK_SQL)
            full_rows = derive(raw_id, product_code, args.client, FULL_FLAT_WALK_SQL)
            print(f"  {product_code:25s} variant={raw_variant or 'default':28s}"
                  f" shallow={len(shallow_rows):>3}  full_flat={len(full_rows):>3}")
            continue

        for kind, sql, strategy in [
            ("shallow", SHALLOW_WALK_SQL, "purchased_btp_as_leaf"),
            ("full_flat", FULL_FLAT_WALK_SQL, "technical_exploded"),
        ]:
            rows = derive(raw_id, product_code, args.client, sql)
            if not rows:
                counters[f"{kind}_empty"] += 1
                continue
            new_ctx = dict(raw_ctx or {})
            new_ctx.update({
                "channel": "auto_derived",  # logical role (record in jsonb)
                "profile": kind,
                "derived_from_artifact_id": raw_id,
                "derived_from_variant": raw_variant,
                "ingest_script": "materialize_shallow_and_full_flat.py",
            })
            existing = create_artifact(
                client_id=args.client,
                product_code=product_code,
                rows=rows,
                actor="erp_pipeline",
                intent="derived",
                parent_artifact_id=raw_id,
                context=new_ctx,
                source_upload_id=None,
                source_bom_kind="technical_flattened",
                flatten_status="flattened",
                flatten_strategy=strategy,
                source_channel="migration",
                bom_variant_id=raw_variant,
                flatten_method="recursive_sql",
                flatten_method_version="1",
            )
            if existing:
                counters[f"{kind}_inserted"] += 1
            else:
                counters[f"{kind}_dedup"] += 1

        # If draft-only policy, demote NEWLY-created auto_derived rows to
        # 'draft'. Guard via created_at within last few seconds to avoid
        # demoting versions that were promoted by a prior --force-publish
        # run (BOM immutability: don't downgrade already-published rows).
        if not publish:
            with connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        update hub.bom_artifacts
                        set status='draft'
                        where client_id=%s and product_code=%s
                          and parent_artifact_id=%s
                          and source_channel='migration'
                          and context->>'channel'='auto_derived'
                          and status='published'
                          and created_at > now() - interval '60 seconds'
                          and not exists (
                            select 1 from hub.bom_presets p
                            where p.artifact_id = hub.bom_artifacts.artifact_id
                              and p.tombstoned_at is null
                          )
                        """,
                        (args.client, product_code, raw_id),
                    )

    if not args.commit:
        print("\n(dry-run) no rows written. Re-run with --commit to apply.")
        return 0

    print()
    for k, v in counters.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
