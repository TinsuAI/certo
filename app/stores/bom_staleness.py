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
            converted.append({**r, "qty_per_unit": raw_qty, "uom": raw_uom,
                              "source_uom": raw_uom,
                              "applied_uom_factor": None,
                              "applied_uom_source": None})
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
            converted.append({**r, "qty_per_unit": raw_qty, "uom": raw_uom,
                              "source_uom": raw_uom,
                              "applied_uom_factor": None,
                              "applied_uom_source": None})
            drifts.append({
                "material_code": code, "dim": "factor_missing",
                "from_uom": raw_uom, "to_uom": target_uom, "source": None,
            })
            continue

        if conv_err == "canonical_uom_missing":
            # convert_qty signals this when target_uom is empty/None,
            # but we already gated above. Defensive fall-through.
            converted.append({**r, "qty_per_unit": raw_qty, "uom": raw_uom,
                              "source_uom": raw_uom,
                              "applied_uom_factor": None,
                              "applied_uom_source": None})
            drifts.append({
                "material_code": code, "dim": "catalog_uom_missing",
                "from_uom": raw_uom, "to_uom": target_uom, "source": None,
            })
            continue

        # Successful conversion (alias, global, client_specific,
        # client_wide, or unconfirmed_default). Capture audit fields
        # for forensics (mig 056).
        out_qty = float(new_qty) if new_qty is not None else raw_qty
        converted.append({
            **r,
            "qty_per_unit": out_qty,
            "uom": target_uom,
            "source_uom": raw_uom,
            "applied_uom_factor": (float(conv_match.factor)
                                   if conv_match else None),
            "applied_uom_source": (conv_match.source
                                   if conv_match else None),
        })

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
    """Append drift signals to a newly-minted artifact.

    Auto-routes between is_stale (derived artifacts) and has_uom_drift
    (source artifacts: manual_flat / raw_graph) per the artifact's own
    flatten_strategy. Mig-054 + mig-057 helpers handle dedup via @>
    JSONB containment so re-application doesn't duplicate."""
    if not drifts:
        return
    cur.execute(
        "select flatten_strategy from hub.bom_artifacts "
        "where artifact_id=%s",
        (artifact_id,),
    )
    row = cur.fetchone()
    strategy = row[0] if row else None
    is_source = strategy in ("manual_flat_as_provided", "no_strategy")

    seen: set[tuple[str, str]] = set()
    for d in drifts:
        sig = (d["dim"], d.get("material_code") or "")
        if sig in seen:
            continue
        seen.add(sig)
        if is_source:
            cur.execute(
                "select hub.bom_mark_uom_drift(%s::text[], %s, %s, %s, %s)",
                ([artifact_id], d["dim"], "hub.client_uom_overrides",
                 d.get("material_code") or "",
                 d.get("material_code")),
            )
        else:
            cur.execute(
                "select hub.bom_mark_stale(%s::text[], %s, %s, %s)",
                ([artifact_id], d["dim"], "hub.client_uom_overrides",
                 d.get("material_code") or ""),
            )


def _reconstruct_originals_from_artifact(
    cur, artifact_id: str,
) -> list[dict]:
    """Phase 2 round 3 — manual_flat refresh path.

    Read back the as-uploaded rows (pre-conversion) from a manual_flat
    artifact's audit columns:
    - source_uom holds the original raw UoM.
    - applied_uom_factor + applied_uom_source describe what was applied
      at last ingest/refresh.

    Reconstruction rule:
    - factor and factor>0 and source != 'alias' → original_qty = qty / factor
    - else (factor missing OR alias-only) → original_qty = qty
    - original_uom = source_uom (always; falls back to current uom only
      when source_uom is null e.g. pre-Phase-2 rows).

    This is the inverse of _convert_rows_to_catalog_uom.
    """
    from decimal import Decimal
    cur.execute(
        "select material_code, bom_code, bom_variant_id, "
        "       qty_per_unit::text, uom, "
        "       source_uom, applied_uom_factor::text, applied_uom_source "
        "from hub.bom_artifact_rows where artifact_id=%s "
        "order by row_index",
        (artifact_id,),
    )
    out: list[dict] = []
    for r in cur.fetchall():
        (mc, bc, bvid, qty_s, uom, src_uom, factor_s, source) = r
        qty = Decimal(qty_s)
        if (factor_s and Decimal(factor_s) > 0
                and source not in (None, "alias")):
            orig_qty = qty / Decimal(factor_s)
        else:
            orig_qty = qty
        orig_uom = src_uom if src_uom else uom
        out.append({
            "material_code": mc,
            "bom_code": bc,
            "bom_variant_id": bvid,
            "qty_per_unit": float(orig_qty),
            "uom": orig_uom,
        })
    return out


def _rederive_manual_flat(
    client_id: str, artifact_id: str, product_code: str,
    *, actor: str = "agency_staff",
    triggered_by_user_id: str | None = None,
) -> tuple[str | None, list[dict]]:
    """Re-apply UoM conversion to a manual_flat artifact's rows.

    Reconstructs originals from audit columns, runs convert with current
    catalog + client_uom_overrides state, mints a new manual_flat
    artifact via create_artifact (idempotent on hash). Returns the
    new artifact id (or existing on hash dedup) + drift list.
    """
    from app.stores.bom import create_artifact

    with connect() as conn, conn.cursor() as cur:
        original_rows = _reconstruct_originals_from_artifact(cur, artifact_id)
    if not original_rows:
        return None, []

    converted_rows, drifts = _convert_rows_to_catalog_uom(
        client_id, original_rows,
    )

    ctx = {"channel": "agency_upload", "profile": "manual_flat",
           "derived_from_artifact_id": artifact_id,
           "ingest_script": "bom_staleness.refresh_manual_flat"}
    if triggered_by_user_id:
        ctx["triggered_by_user_id"] = triggered_by_user_id

    # parent_artifact_id stays None for manual_flat refresh: same-hash
    # idempotency dedups against the original (which also had
    # parent=None). Lineage is preserved via tombstone_reason link
    # (`superseded_by_refresh:<new_id>`) set by refresh_artifact when
    # the hash diff produces a new artifact.
    new_id = create_artifact(
        client_id=client_id, product_code=product_code,
        rows=converted_rows,
        actor=actor, intent="asserted_technical",
        parent_artifact_id=None,
        context=ctx,
        source_upload_id=None,
        source_bom_kind="technical_flattened",
        flatten_status="not_applicable",
        flatten_strategy="manual_flat_as_provided",
        source_channel="migration",
        flatten_method="manual_flat_with_uom_conversion",
        flatten_method_version="2",
    )
    return new_id, drifts


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
    """Clear both is_stale (mig 053) and has_uom_drift (mig 057)
    flags + reasons + set resolved_at on these artifact_ids. Idempotent
    on already-clean artifacts."""
    if not artifact_ids:
        return 0
    cur.execute(
        "update hub.bom_artifacts set "
        "  is_stale=false, "
        "  stale_reasons='[]'::jsonb, "
        "  stale_resolved_at=now(), "
        "  has_uom_drift=false, "
        "  uom_drift_reasons='[]'::jsonb, "
        "  uom_drift_resolved_at=now() "
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
    superseded = False
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
                    _apply_drift_to_artifact(cur, new_id, drifts)
                    if new_id != artifact_id:
                        cur.execute(
                            "update hub.bom_artifacts "
                            "set tombstoned_at=now(), "
                            "    tombstone_reason=%s "
                            "where artifact_id=%s "
                            "  and tombstoned_at is null",
                            (f"superseded_by_refresh:{new_id}", artifact_id),
                        )
                        superseded = True
                else:
                    skipped = "derive_empty"
        elif a["flatten_strategy"] == "manual_flat_as_provided":
            # Phase 2 round 3: manual_flat refresh re-applies conversion
            # to existing rows using current catalog + override state.
            # Reconstructs originals from source_uom audit columns.
            new_id, drifts = _rederive_manual_flat(
                client_id, artifact_id, a["product_code"],
                triggered_by_user_id=triggered_by_user_id,
            )
            if new_id:
                new_ids.append(new_id)
                _apply_drift_to_artifact(cur, new_id, drifts)
                if new_id != artifact_id:
                    cur.execute(
                        "update hub.bom_artifacts "
                        "set tombstoned_at=now(), "
                        "    tombstone_reason=%s "
                        "where artifact_id=%s "
                        "  and tombstoned_at is null",
                        (f"superseded_by_refresh:{new_id}", artifact_id),
                    )
                    superseded = True
            else:
                skipped = "reconstruct_empty"
        else:
            skipped = "source_artifact"

        # Clear flag rules (Phase 2 round 3, refined for manual_flat
        # same-hash case):
        # - Tombstoned (superseded) artifacts: skip clear, they're dead.
        # - Artifacts that just received drift via _apply_drift_to_artifact:
        #   skip clear, keep their warning.
        # - Otherwise (refresh action taken, no remaining drift): clear.
        ids_just_got_drift: set[str] = set()
        if drifts:
            ids_just_got_drift.update(new_ids)
        clearables: list[str] = []
        if not superseded and artifact_id not in ids_just_got_drift:
            clearables.append(artifact_id)
        for nid in new_ids:
            if nid != artifact_id and nid not in ids_just_got_drift:
                clearables.append(nid)
        cleared_n = _clear_stale(cur, clearables) if clearables else 0

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
