"""Track D refresh helpers for stale BOM artifacts.

Refresh semantics:
- Re-run the materializer derive for the artifact's product (single
  shape per per-artifact, all derived shapes per per-product).
- Phase 2 step 2b: each derived row's UoM is converted to the
  catalog's canonical via `convert_qty` + `make_uom_lookup`. Drift
  signals (tier-A unconfirmed_default, tier-B factor_missing,
  catalog_uom_missing) propagate as `stale_reasons` entries on the
  newly-minted artifact so the staleness UI surfaces them even
  before the ingest-time preview UI ships.
- create_artifact is idempotent via normalized_hash. Same input rows
  return the existing artifact_id; different rows mint a new artifact
  and the old one is left in place (immutability).
- Whether or not new shapes were minted, the requested artifact's
  is_stale flag is cleared and stale_resolved_at is set. Staff can
  re-trigger if they want to mark fresh again after edits.

Spec: `.ai/features/2026-05-11-bom-staleness-track-d/brief.md`,
"Refresh flow" section + Phase 2 brief decisions 5+6 (3-tier policy).
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import TypedDict

from app.database import connect
from app.flatten.uom import convert_qty


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


def _convert_rows_to_catalog_uom(
    client_id: str, rows: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Convert each derived row's qty/uom from raw UoM → catalog UoM.

    Returns `(converted_rows, drift_signals)`. Drift signals are
    `{material_code, dim, from_uom, to_uom, source}` records that the
    caller appends to the new artifact's `stale_reasons`.

    Tier handling (per Phase 2 brief decision 6):
    - Catalog UoM resolves + same family / alias → silent convert.
    - Tier A (cross-family count↔count_packaging↔assembly): factor
      defaults 1.0, source=`unconfirmed_default`. Row converted to
      catalog UoM; drift reason `unconfirmed_default_1to1` emitted.
    - Tier B (count↔mass etc., no override row): conversion fails
      with `uom_conversion_missing`. Row keeps RAW qty + RAW uom (no
      silent corruption); drift reason `factor_missing` emitted.
    - Catalog UoM null: row keeps raw uom; drift reason
      `catalog_uom_missing` emitted (order-independence — staff
      fills catalog later, refresh re-derives).
    """
    from app.stores.uom import make_uom_lookup

    if not rows:
        return rows, []

    # Phase 2 canonical: materials.uom (mig 050+). make_catalog_lookup
    # queries the legacy materials.unit column — different consumer.
    codes = sorted({r.get("material_code") for r in rows
                     if r.get("material_code")})
    catalog_uom: dict[str, str | None] = {}
    if codes:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "select material_code, uom from hub.materials "
                "where client_id=%s and material_code = any(%s)",
                (client_id, codes),
            )
            catalog_uom = {c: u for c, u in cur.fetchall()}

    uom_lookup = make_uom_lookup(client_id)

    converted: list[dict] = []
    drifts: list[dict] = []

    for r in rows:
        code = r.get("material_code")
        raw_qty = r.get("qty_per_unit")
        raw_uom = r.get("uom")
        target_uom = catalog_uom.get(code) if code else None

        if not target_uom:
            # Catalog has no canonical UoM — defer (order-independence).
            converted.append({**r, "qty_per_unit": raw_qty, "uom": raw_uom})
            drifts.append({
                "material_code": code, "dim": "catalog_uom_missing",
                "from_uom": raw_uom, "to_uom": None, "source": None,
            })
            continue

        new_qty, conv_match, conv_err = convert_qty(
            Decimal(str(raw_qty)) if raw_qty is not None else None,
            raw_uom, target_uom,
            material_code=code, lookup=uom_lookup,
        )

        if conv_err == "uom_conversion_missing":
            # Tier B (cross-family, no override) — keep raw, flag
            # factor_missing. Refresh will fail with stale flag retained
            # until staff populates client_uom_overrides.
            converted.append({**r, "qty_per_unit": raw_qty, "uom": raw_uom})
            drifts.append({
                "material_code": code, "dim": "factor_missing",
                "from_uom": raw_uom, "to_uom": target_uom, "source": None,
            })
            continue

        if conv_err == "canonical_uom_missing":
            # convert_qty signals this when target_uom is empty/None,
            # but we already gated above. Defensive fall-through.
            converted.append({**r, "qty_per_unit": raw_qty, "uom": raw_uom})
            drifts.append({
                "material_code": code, "dim": "catalog_uom_missing",
                "from_uom": raw_uom, "to_uom": target_uom, "source": None,
            })
            continue

        # Successful conversion (alias, global, client_specific,
        # client_wide, or unconfirmed_default).
        out_qty = float(new_qty) if new_qty is not None else raw_qty
        converted.append({**r, "qty_per_unit": out_qty, "uom": target_uom})

        if conv_match and conv_match.source == "unconfirmed_default":
            drifts.append({
                "material_code": code, "dim": "unconfirmed_default_1to1",
                "from_uom": raw_uom, "to_uom": target_uom,
                "source": "unconfirmed_default",
            })

    return converted, drifts


def _apply_drift_to_artifact(
    cur, artifact_id: str, drifts: list[dict],
) -> None:
    """Append drift signals to a newly-minted artifact's stale_reasons.

    Uses bom_mark_stale (mig 054 dedup) per dim+material_code so the
    same drift across two refresh runs doesn't duplicate. We collapse
    drifts by (dim, material_code) at call time then loop the helper."""
    if not drifts:
        return
    seen: set[tuple[str, str]] = set()
    for d in drifts:
        sig = (d["dim"], d.get("material_code") or "")
        if sig in seen:
            continue
        seen.add(sig)
        cur.execute(
            "select hub.bom_mark_stale(%s::text[], %s, %s, %s)",
            ([artifact_id], d["dim"], "hub.client_uom_overrides",
             d.get("material_code") or ""),
        )


def _rederive_shape(client_id: str, raw_artifact_id: str,
                    product_code: str, strategy: str,
                    *, actor: str = "agency_staff",
                    triggered_by_user_id: str | None = None
                    ) -> tuple[str | None, list[dict]]:
    """Re-run the materializer for one shape; return
    `(artifact_id_or_none, drift_signals)`.

    Phase 2 step 2b adds UoM conversion via `_convert_rows_to_catalog_uom`
    between SQL derive and create_artifact. Drift signals are surfaced
    so the caller can mark the resulting artifact's stale_reasons —
    same idempotency story (same hash → existing artifact id, new
    drifts get accumulated).

    `actor` defaults to 'agency_staff' (refresh is staff action, not a
    migration script). `triggered_by_user_id` goes into context jsonb
    for forensics — answers "which staff clicked refresh".
    """
    from scripts.materialize_shallow_and_full_flat import (
        SHALLOW_WALK_SQL, FULL_FLAT_WALK_SQL, derive,
    )
    from app.stores.bom import create_artifact

    if strategy == "purchased_btp_as_leaf":
        sql = SHALLOW_WALK_SQL
    elif strategy == "technical_exploded":
        sql = FULL_FLAT_WALK_SQL
    else:
        return None, []
    raw_rows = derive(raw_artifact_id, product_code, client_id, sql)
    if not raw_rows:
        return None, []

    converted_rows, drifts = _convert_rows_to_catalog_uom(client_id, raw_rows)

    ctx = {"channel": "auto_derived", "profile": strategy,
           "derived_from_artifact_id": raw_artifact_id,
           "ingest_script": "bom_staleness.refresh"}
    if triggered_by_user_id:
        ctx["triggered_by_user_id"] = triggered_by_user_id
    artifact_id = create_artifact(
        client_id=client_id, product_code=product_code, rows=converted_rows,
        actor=actor, intent="derived",
        parent_artifact_id=raw_artifact_id,
        context=ctx,
        source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="flattened",
        flatten_strategy=strategy,
        source_channel="migration",
        flatten_method="recursive_sql_with_uom_conversion",
        flatten_method_version="2",
    )
    return artifact_id, drifts


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


def refresh_artifact(client_id: str, artifact_id: str,
                     *, triggered_by_user_id: str | None = None) -> RefreshResult:
    """Refresh one artifact.
    For derived artifacts, attempts to re-derive its shape from the raw
    ancestor (best-effort; skips if no raw is available — e.g. test
    fixtures or manual_flat-only products).
    Always clears the stale flag if the artifact belongs to client_id.
    Raises LookupError if not found.

    `triggered_by_user_id` propagates staff identity into the
    re-derived artifact's context jsonb + connection's app.user_id
    (for any future audit triggers on hub.bom_artifacts).
    """
    new_ids: list[str] = []
    skipped: str | None = None
    drifts: list[dict] = []
    with connect(user_id=triggered_by_user_id) as conn, conn.cursor() as cur:
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
                new_id, drifts = _rederive_shape(
                    client_id, raw_id, a["product_code"],
                    a["flatten_strategy"],
                    triggered_by_user_id=triggered_by_user_id,
                )
                if new_id:
                    new_ids.append(new_id)
                    # Phase 2 step 2b: surface UoM drift on the new
                    # artifact via stale_reasons. Helper deduplicates
                    # by (dim, material_code) via mig 054 @> check.
                    _apply_drift_to_artifact(cur, new_id, drifts)
                else:
                    skipped = "derive_empty"
        else:
            skipped = "source_artifact"

        # Always clear the originally-targeted artifact (refresh action
        # taken). Clear newly-minted artifact only if no drift signals
        # — drift means the new artifact ships warning, must stay stale
        # until staff populates client_uom_overrides.
        clearables = [artifact_id]
        if new_ids and not drifts:
            clearables.extend(new_ids)
        cleared_n = _clear_stale(cur, clearables)

    return {
        "artifact_id": artifact_id,
        "cleared": cleared_n > 0,
        "new_artifact_ids": new_ids,
        "skipped_reason": skipped,
    }


def refresh_product(client_id: str, product_code: str,
                    *, triggered_by_user_id: str | None = None
                    ) -> list[RefreshResult]:
    """Refresh every derived artifact for a product (latest phiên bản)."""
    with connect(user_id=triggered_by_user_id) as conn, conn.cursor() as cur:
        cur.execute(
            "select artifact_id from hub.bom_artifacts "
            "where client_id=%s and product_code=%s "
            "  and tombstoned_at is null "
            "  and flatten_strategy = any(%s)",
            (client_id, product_code, list(_DERIVED_STRATEGIES)),
        )
        artifact_ids = [r[0] for r in cur.fetchall()]
    return [
        refresh_artifact(client_id, aid,
                         triggered_by_user_id=triggered_by_user_id)
        for aid in artifact_ids
    ]
