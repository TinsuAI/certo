"""Phase 3c · Derive own raw_graph BOM artifacts for intermediate BTPs.

Closes the shallow-decomposability gap from Johnson-shape ingestion
(memory `project_growatt_bom_v1_v2_equivalence.md`): in a deep raw
tree like Johnson's SAP-indented exports, intermediate `parent_code`
values are real BTPs but the ingest writes them only as edges, not
as standalone `bom_artifacts` rows. The shallow walk then can't
materialize per-BTP shallow because there's no own-bom to anchor.

This script walks each raw_graph artifact, picks every intermediate
parent_code where `materials.category='btp_sx'` AND
`btp_sourcing != 'purchased_only'` (R3 mitigation), and mints a new
raw_graph artifact rooted at that BTP via `create_raw_artifact`.
Lineage points back to the source raw artifact.

Idempotent via `create_raw_artifact`'s normalized_hash dedup.

CLI:
    uv run python -m scripts.derive_btp_shallows <client_id> [--status draft|publish|disabled] [--commit]
"""
from __future__ import annotations

import argparse
import sys

from app.database import connect
from app.stores.bom import create_raw_artifact


def _client_policy(cur, client_id: str) -> str:
    cur.execute(
        "select auto_derive_shallow_from_raw from hub.clients where client_id=%s",
        (client_id,),
    )
    row = cur.fetchone()
    return row[0] if row else "draft_only"


def _eligible_btp_parents(cur, *, artifact_id: str, client_id: str) -> list[str]:
    """Distinct parent_code values in this artifact's edges that are
    btp_sx materials with btp_sourcing != 'purchased_only' and != the
    root product_code itself (root produces its own existing artifact)."""
    cur.execute(
        """
        select distinct e.parent_code
        from hub.bom_edges e
        join hub.materials m
          on m.client_id = %s and m.material_code = e.parent_code
        join hub.bom_artifacts a
          on a.artifact_id = e.artifact_id
        where e.artifact_id = %s
          and m.category = 'btp_sx'
          and (m.btp_sourcing is null or m.btp_sourcing != 'purchased_only')
          and e.parent_code != a.product_code
        order by e.parent_code
        """,
        (client_id, artifact_id),
    )
    return [r[0] for r in cur.fetchall()]


def _subtree_edges(cur, *, artifact_id: str, root_code: str) -> list[dict]:
    """All edges reachable from `root_code` within `artifact_id`,
    walking parent → child until leaves. Returns a fresh edge list
    with `root_code` rebound to the new subtree root."""
    cur.execute(
        """
        with recursive edges as (
            select parent_code, child_code, qty_per_parent, uom, level,
                   node_path, sheet_name, source_row_no, payload
            from hub.bom_edges where artifact_id = %s
        ),
        walk as (
            select e.*, array[e.parent_code, e.child_code] as path
            from edges e where e.parent_code = %s
            union all
            select e.parent_code, e.child_code, e.qty_per_parent, e.uom, e.level,
                   e.node_path, e.sheet_name, e.source_row_no, e.payload,
                   w.path || e.child_code
            from walk w
            join edges e on e.parent_code = w.child_code
            where not (e.child_code = any(w.path))
        )
        select parent_code, child_code, qty_per_parent, uom, level,
               node_path, sheet_name, source_row_no, payload
        from walk
        """,
        (artifact_id, root_code),
    )
    return [
        {
            "parent_code": r[0], "child_code": r[1], "qty_per_parent": r[2],
            "uom": r[3], "level": r[4], "node_path": r[5],
            "sheet_name": r[6], "source_row_no": r[7], "payload": r[8] or {},
            "root_code": root_code,
        }
        for r in cur.fetchall()
    ]


def derive_btp_shallows_for_artifact(*, artifact_id: str, client_id: str,
                                      status: str = "draft") -> list[dict]:
    """Mint own raw_graph artifacts for each eligible BTP parent.

    `status`: 'draft' | 'publish' | 'disabled'. 'disabled' returns []
    without writes. 'draft' / 'publish' mint with that status.
    Returns a list of dicts: {product_code, artifact_id, created}.
    """
    if status == "disabled":
        return []
    if status not in {"draft", "publish"}:
        raise ValueError(f"unknown status: {status!r}")

    minted: list[dict] = []
    with connect() as conn, conn.cursor() as cur:
        # Re-fetch the parent product_code so we know what to use as
        # parent_artifact_id (lineage) on minted artifacts.
        cur.execute(
            "select product_code from hub.bom_artifacts where artifact_id=%s",
            (artifact_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"artifact_id={artifact_id!r} not found")

        for btp_code in _eligible_btp_parents(
            cur, artifact_id=artifact_id, client_id=client_id,
        ):
            edges = _subtree_edges(
                cur, artifact_id=artifact_id, root_code=btp_code,
            )
            if not edges:
                continue
            # Idempotency: create_raw_artifact dedups via normalized_hash.
            # If an existing row matches, it returns its artifact_id and
            # we mark created=False.
            cur.execute(
                "select count(*) from hub.bom_artifacts where client_id=%s",
                (client_id,),
            )
            before = cur.fetchone()[0]
            new_id = create_raw_artifact(
                client_id=client_id, product_code=btp_code, edges=edges,
                actor="system", intent="derived",
                parent_artifact_id=artifact_id,
                context={"derived_from_btp": btp_code},
                source_upload_id=None,
                source_channel="agency_upload",
                lineage={"derived_from_artifact_id": artifact_id,
                         "derivation": "btp_shallow_post_ingest"},
                cursor=cur,
            )
            cur.execute(
                "select count(*) from hub.bom_artifacts where client_id=%s",
                (client_id,),
            )
            after = cur.fetchone()[0]
            created = after > before
            if created and status == "publish":
                cur.execute(
                    "update hub.bom_artifacts set status='published', "
                    "published_at=now() where artifact_id=%s",
                    (new_id,),
                )
            elif created and status == "draft":
                cur.execute(
                    "update hub.bom_artifacts set status='draft' "
                    "where artifact_id=%s",
                    (new_id,),
                )
            minted.append({
                "product_code": btp_code,
                "artifact_id": new_id,
                "created": created,
            })
    return minted


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("client_id")
    ap.add_argument("--status", choices=["draft", "publish", "disabled", "auto"],
                     default="auto",
                     help="'auto' picks per clients.auto_derive_shallow_from_raw")
    args = ap.parse_args(argv)

    with connect() as conn, conn.cursor() as cur:
        if args.status == "auto":
            policy = _client_policy(cur, args.client_id)
            status = {"disabled": "disabled", "draft_only": "draft",
                      "publish": "publish"}.get(policy, "draft")
            print(f"client policy → {policy} → status={status}")
        else:
            status = args.status

        cur.execute(
            "select artifact_id from hub.bom_artifacts "
            "where client_id=%s and source_bom_kind='technical_raw' "
            "and tombstoned_at is null",
            (args.client_id,),
        )
        raw_ids = [r[0] for r in cur.fetchall()]
        print(f"found {len(raw_ids)} raw_graph artifact(s) to walk")

    total = 0
    new = 0
    for raw_id in raw_ids:
        minted = derive_btp_shallows_for_artifact(
            artifact_id=raw_id, client_id=args.client_id, status=status,
        )
        total += len(minted)
        new += sum(1 for m in minted if m.get("created"))
    print(f"minted/saw {new}/{total} BTP shallow artifact(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
