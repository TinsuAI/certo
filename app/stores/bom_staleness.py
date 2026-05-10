"""Track D Phase C — refresh helpers for stale BOM artifacts.

Refresh semantics:
- Re-run the materializer derive for the artifact's product (single
  shape per per-artifact, all derived shapes per per-product).
- create_artifact is idempotent via normalized_hash. Same input rows
  return the existing artifact_id; different rows mint a new artifact
  and the old one is left in place (immutability).
- Whether or not new shapes were minted, the requested artifact's
  is_stale flag is cleared and stale_resolved_at is set. Staff can
  re-trigger if they want to mark fresh again after edits.

Spec: `.ai/features/2026-05-11-bom-staleness-track-d/brief.md`,
"Refresh flow" section.
"""
from __future__ import annotations

from typing import TypedDict

from app.database import connect


class RefreshResult(TypedDict):
    artifact_id: str
    cleared: bool
    new_artifact_ids: list[str]
    skipped_reason: str | None


_DERIVED_STRATEGIES = (
    "technical_exploded",
    "purchased_btp_as_leaf",
    "self_produced_btp_exploded",
    "mixed_confirmed",
)


def _load_artifact(cur, artifact_id: str) -> dict | None:
    cur.execute(
        "select artifact_id, client_id, product_code, source_bom_kind, "
        "flatten_strategy, parent_artifact_id, lineage_root_id, "
        "tombstoned_at, is_stale "
        "from hub.bom_artifacts where artifact_id=%s",
        (artifact_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "artifact_id": row[0], "client_id": row[1], "product_code": row[2],
        "source_bom_kind": row[3], "flatten_strategy": row[4],
        "parent_artifact_id": row[5], "lineage_root_id": row[6],
        "tombstoned_at": row[7], "is_stale": row[8],
    }


def _find_raw_ancestor_for_product(cur, client_id: str,
                                    product_code: str) -> str | None:
    """Latest published technical_raw artifact for product."""
    cur.execute(
        "select artifact_id from hub.bom_artifacts "
        "where client_id=%s and product_code=%s "
        "  and source_bom_kind='technical_raw' "
        "  and tombstoned_at is null and status='published' "
        "order by created_at desc limit 1",
        (client_id, product_code),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _rederive_shape(client_id: str, raw_artifact_id: str,
                    product_code: str, strategy: str) -> str | None:
    """Re-run the materializer for one shape; return the resulting
    artifact_id (existing on dedup, new on hash-change). None if the
    derive produced zero rows."""
    from scripts.materialize_shallow_and_full_flat import (
        SHALLOW_WALK_SQL, FULL_FLAT_WALK_SQL, derive,
    )
    from app.stores.bom import create_artifact

    if strategy == "purchased_btp_as_leaf":
        sql = SHALLOW_WALK_SQL
    elif strategy == "technical_exploded":
        sql = FULL_FLAT_WALK_SQL
    else:
        return None
    rows = derive(raw_artifact_id, product_code, client_id, sql)
    if not rows:
        return None
    return create_artifact(
        client_id=client_id, product_code=product_code, rows=rows,
        actor="erp_pipeline", intent="derived",
        parent_artifact_id=raw_artifact_id,
        context={"channel": "auto_derived", "profile": strategy,
                 "derived_from_artifact_id": raw_artifact_id,
                 "ingest_script": "bom_staleness.refresh"},
        source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy=strategy,
        source_channel="migration",
        flatten_method="recursive_sql",
        flatten_method_version="1",
    )


def _clear_stale(cur, artifact_ids: list[str]) -> int:
    if not artifact_ids:
        return 0
    cur.execute(
        "update hub.bom_artifacts set is_stale=false, "
        "stale_reasons='[]'::jsonb, stale_resolved_at=now() "
        "where artifact_id = any(%s) returning artifact_id",
        (artifact_ids,),
    )
    return len(cur.fetchall())


def refresh_artifact(client_id: str, artifact_id: str) -> RefreshResult:
    """Refresh one artifact.
    For derived artifacts, attempts to re-derive its shape from the raw
    ancestor (best-effort; skips if no raw is available — e.g. test
    fixtures or manual_flat-only products).
    Always clears the stale flag if the artifact belongs to client_id.
    Raises LookupError if not found.
    """
    new_ids: list[str] = []
    skipped: str | None = None
    with connect() as conn, conn.cursor() as cur:
        a = _load_artifact(cur, artifact_id)
        if a is None:
            raise LookupError(f"artifact {artifact_id!r} not found")
        if a["client_id"] != client_id:
            raise LookupError(
                f"artifact {artifact_id!r} not in client {client_id!r}"
            )
        if a["tombstoned_at"] is not None:
            skipped = "tombstoned"
        elif a["flatten_strategy"] in _DERIVED_STRATEGIES:
            raw_id = _find_raw_ancestor_for_product(
                cur, client_id, a["product_code"],
            )
            if raw_id is None:
                skipped = "no_raw_ancestor"
            else:
                new_id = _rederive_shape(
                    client_id, raw_id, a["product_code"],
                    a["flatten_strategy"],
                )
                if new_id:
                    new_ids.append(new_id)
                else:
                    skipped = "derive_empty"
        else:
            skipped = "source_artifact"

        cleared_n = _clear_stale(cur, [artifact_id, *new_ids])

    return {
        "artifact_id": artifact_id,
        "cleared": cleared_n > 0,
        "new_artifact_ids": new_ids,
        "skipped_reason": skipped,
    }


def refresh_product(client_id: str, product_code: str) -> list[RefreshResult]:
    """Refresh every derived artifact for a product (latest phiên bản)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select artifact_id from hub.bom_artifacts "
            "where client_id=%s and product_code=%s "
            "  and tombstoned_at is null "
            "  and flatten_strategy = any(%s)",
            (client_id, product_code, list(_DERIVED_STRATEGIES)),
        )
        artifact_ids = [r[0] for r in cur.fetchall()]
    return [refresh_artifact(client_id, aid) for aid in artifact_ids]
