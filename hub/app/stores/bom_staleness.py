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

from hub.app.database import connect
from hub.app.flatten.uom import convert_qty


class RefreshResult(TypedDict):
    artifact_id: str
    cleared: bool
    new_artifact_ids: list[str]
    skipped_reason: str | None


class PlanRow(TypedDict):
    row_index: int
    material_code: str | None
    source_qty: float | None
    source_uom: str | None
    target_uom: str | None
    factor: str | None
    factor_source: str | None
    status: str  # ready | unconfirmed_default | blocked_no_factor | blocked_catalog_missing


class RefreshPlan(TypedDict):
    artifact_id: str
    flatten_strategy: str
    rows: list[PlanRow]
    drifts: list[dict]
    would_be_hash: str | None
    has_blocking: bool
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
        "tombstoned_at, is_stale, bom_variant_id "
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
        "bom_variant_id": row[9],
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
    from hub.app.stores.uom import make_uom_lookup

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
    from hub.app.stores.bom import create_artifact

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
                    triggered_by_user_id: str | None = None,
                    bom_variant_id: str | None = None,
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

    `bom_variant_id` MUST be passed through so refreshed artifacts stay
    under the same variant as their predecessor. Forgetting this lets
    refresh silently mint default-variant duplicates next to the existing
    agency-batch variant — a pre-existing latent bug surfaced by bulk
    --cleanup-stale runs on Johnson re-ingest (2026-05-13).
    """
    from hub.scripts.materialize_shallow_and_full_flat import (
        SHALLOW_WALK_SQL, FULL_FLAT_WALK_SQL, derive,
    )
    from hub.app.stores.bom import create_artifact

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
        bom_variant_id=bom_variant_id,
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


def plan_refresh(client_id: str, artifact_id: str) -> RefreshPlan:
    """Pure refresh planner. Returns what `commit_refresh` would write,
    but writes nothing.

    Used by GET /clients/{cid}/bom/artifact/{aid}/refresh/preview to
    render the conversion plan before staff confirms (Phase 3 G).

    Empty `rows` + non-null `skipped_reason` means refresh would no-op
    (tombstoned, no_raw_ancestor, source_artifact, derive_empty,
    reconstruct_empty).
    """

    def _empty(strategy: str, reason: str) -> RefreshPlan:
        return {
            "artifact_id": artifact_id,
            "flatten_strategy": strategy,
            "rows": [],
            "drifts": [],
            "would_be_hash": None,
            "has_blocking": False,
            "skipped_reason": reason,
        }

    raw_rows: list[dict]
    with connect() as conn, conn.cursor() as cur:
        a = _load_artifact(cur, artifact_id)
        if a is None:
            raise LookupError(f"artifact {artifact_id!r} not found")
        if a["client_id"] != client_id:
            raise LookupError(
                f"artifact {artifact_id!r} not in client {client_id!r}"
            )
        strategy = a["flatten_strategy"]
        if a["tombstoned_at"] is not None:
            return _empty(strategy, "tombstoned")
        if strategy in _DERIVED_STRATEGIES:
            raw_id = _find_raw_ancestor_for_product(
                cur, client_id, a["product_code"],
            )
            if raw_id is None:
                return _empty(strategy, "no_raw_ancestor")
            from hub.scripts.materialize_shallow_and_full_flat import (
                SHALLOW_WALK_SQL, FULL_FLAT_WALK_SQL, derive,
            )
            if strategy == "purchased_btp_as_leaf":
                sql = SHALLOW_WALK_SQL
            elif strategy == "technical_exploded":
                sql = FULL_FLAT_WALK_SQL
            else:
                return _empty(strategy, "unsupported_strategy")
            raw_rows = derive(raw_id, a["product_code"], client_id, sql)
            if not raw_rows:
                return _empty(strategy, "derive_empty")
        elif strategy == "manual_flat_as_provided":
            raw_rows = _reconstruct_originals_from_artifact(cur, artifact_id)
            if not raw_rows:
                return _empty(strategy, "reconstruct_empty")
        else:
            return _empty(strategy, "source_artifact")

    converted_rows, drifts = _convert_rows_to_catalog_uom(client_id, raw_rows)

    plan_rows: list[PlanRow] = []
    for idx, (raw, conv) in enumerate(zip(raw_rows, converted_rows)):
        code = conv.get("material_code")
        src_uom = conv.get("source_uom")
        post_uom = conv.get("uom")
        factor = conv.get("applied_uom_factor")
        source = conv.get("applied_uom_source")
        # Determine target_uom: when conversion happened, post_uom is
        # the catalog UoM. When it didn't, look at the matching drift
        # for catalog_uom_missing vs factor_missing distinction.
        target_uom: str | None
        if post_uom != src_uom:
            target_uom = post_uom
        else:
            drift_for_code = next(
                (d for d in drifts if d.get("material_code") == code),
                None,
            )
            if drift_for_code and drift_for_code.get("dim") == "catalog_uom_missing":
                target_uom = None
            elif drift_for_code:
                target_uom = drift_for_code.get("to_uom")
            else:
                target_uom = post_uom  # alias / silent same-uom case
        # Status mapping.
        if source == "unconfirmed_default":
            status = "unconfirmed_default"
        elif factor is not None or source == "alias":
            status = "ready"
        elif target_uom is None:
            status = "blocked_catalog_missing"
        else:
            status = "blocked_no_factor"
        plan_rows.append({
            "row_index": idx,
            "material_code": code,
            "source_qty": raw.get("qty_per_unit"),
            "source_uom": src_uom,
            "target_uom": target_uom,
            "factor": str(factor) if factor is not None else None,
            "factor_source": source,
            "status": status,
        })

    from hub.app.stores.bom import normalized_hash
    would_be_hash = normalized_hash(converted_rows) if converted_rows else None
    has_blocking = any(
        r["status"] in ("blocked_no_factor", "blocked_catalog_missing")
        for r in plan_rows
    )

    return {
        "artifact_id": artifact_id,
        "flatten_strategy": strategy,
        "rows": plan_rows,
        "drifts": drifts,
        "would_be_hash": would_be_hash,
        "has_blocking": has_blocking,
        "skipped_reason": None,
    }


def commit_refresh(client_id: str, artifact_id: str,
                   *, edits: list[dict] | None = None,
                   skip: bool = False,
                   triggered_by_user_id: str | None = None) -> RefreshResult:
    """Commit path for refresh — re-plans internally to defeat TOCTOU
    between preview render and POST commit.

    Phase 3 G additions:
    - `skip=True`: log a `refresh.skipped` event in `hub.bom_audit_events`
      and return without state change. Artifact stays stale; no new
      artifact minted; no flag cleared.
    - `edits=[{material_code, from_uom, to_uom, factor, source?}]`:
      upsert these factor rows into `hub.client_uom_overrides` BEFORE
      computing the refresh, so a previously-blocking row may become
      ready in the same round-trip.
    - `triggered_by_user_id`: propagates staff identity into context.

    `refresh_artifact()` keeps its current public signature and
    delegates here.
    """
    if skip:
        try:
            sk_plan = plan_refresh(client_id, artifact_id)
        except LookupError:
            raise
        with connect(user_id=triggered_by_user_id) as conn, conn.cursor() as cur:
            cur.execute(
                "insert into hub.bom_audit_events "
                "(client_id, product_code, artifact_id, event_type, actor, details) "
                "select client_id, product_code, artifact_id, "
                "       'refresh.skipped', %s, %s::jsonb "
                "from hub.bom_artifacts where artifact_id=%s",
                (
                    triggered_by_user_id or "agency_staff",
                    json.dumps({
                        "blocking_count": sum(
                            1 for r in sk_plan["rows"]
                            if r["status"].startswith("blocked")
                        ),
                        "row_count": len(sk_plan["rows"]),
                        "skipped_reason_from_plan": sk_plan["skipped_reason"],
                    }),
                    artifact_id,
                ),
            )
        return {
            "artifact_id": artifact_id,
            "cleared": False,
            "new_artifact_ids": [],
            "skipped_reason": "staff_skip",
        }

    if edits:
        with connect(user_id=triggered_by_user_id) as conn, conn.cursor() as cur:
            for e in edits:
                cur.execute(
                    "insert into hub.client_uom_overrides "
                    "(client_id, material_code, from_uom, to_uom, factor, source) "
                    "values (%s, %s, %s, %s, %s, %s) "
                    "on conflict (client_id, material_code_key, from_uom, to_uom) "
                    "do update set factor=excluded.factor, "
                    "              source=excluded.source",
                    (client_id, e["material_code"], e["from_uom"], e["to_uom"],
                     e["factor"], e.get("source") or "staff_form"),
                )

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
                    bom_variant_id=a["bom_variant_id"],
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


def refresh_artifact(client_id: str, artifact_id: str,
                     *, triggered_by_user_id: str | None = None) -> RefreshResult:
    """Public refresh API. Thin wrapper around `commit_refresh`.

    Existing callers (programmatic refresh, refresh_product loop, the
    direct POST route) get the same behaviour as before: re-derive the
    artifact, mint a new artifact when hash differs, tombstone the old,
    clear flag if no remaining drift.

    The new preview-aware paths (`skip`, `edits`) are exposed on
    `commit_refresh` directly.
    """
    return commit_refresh(client_id, artifact_id,
                          triggered_by_user_id=triggered_by_user_id)


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


def reconcile_for_material(client_id: str, material_code: str,
                            *, cap: int = 50,
                            triggered_by_user_id: str | None = None) -> dict:
    """Auto-reconcile after a catalog edit / override insert that touched
    this material. Walks all NON-clean artifacts referencing the material
    and:
    - Derived (technical_flattened): refresh_artifact (re-derive).
    - manual_flat: refresh_artifact too (calls _rederive_manual_flat).
    - raw_graph: re-check alignment via hub.has_drift_remaining; clear
      has_uom_drift if all edges now align (mig 071-style sweep narrowed
      to this material).

    Capped at `cap` artifacts. Returns counts {refreshed, cleared,
    deferred, errors}. UI fires this after catalog edit; if `deferred > 0`
    staff sees a notice and can hit "Refresh all" on /bom/needs-action.
    """
    counts = {"refreshed": 0, "cleared": 0, "deferred": 0, "errors": 0}
    refs_cte = """
        with refs as (
          select distinct ba.artifact_id, ba.flatten_strategy,
                          ba.source_bom_kind, ba.state
            from hub.bom_artifacts ba
            left join hub.bom_artifact_rows bar
              on bar.artifact_id = ba.artifact_id
            left join hub.bom_edges be
              on be.artifact_id = ba.artifact_id
           where ba.client_id = %s
             and ba.tombstoned_at is null
             and ba.state <> 'clean'
             and (bar.material_code = %s or be.child_code = %s)
        )
    """
    with connect(user_id=triggered_by_user_id) as conn, conn.cursor() as cur:
        # Count first so we can report `deferred` exactly when capped.
        cur.execute(
            refs_cte + " select count(*) from refs",
            (client_id, material_code, material_code),
        )
        (total,) = cur.fetchone()
        if total > cap:
            counts["deferred"] = total - cap
        cur.execute(
            refs_cte
            + " select artifact_id, flatten_strategy, source_bom_kind, "
              "        state from refs order by artifact_id limit %s",
            (client_id, material_code, material_code, cap),
        )
        affected = cur.fetchall()

    for aid, strategy, _kind, _state in affected:
        try:
            if strategy in _DERIVED_STRATEGIES \
                    or strategy == "manual_flat_as_provided":
                result = refresh_artifact(
                    client_id, aid,
                    triggered_by_user_id=triggered_by_user_id,
                )
                if result.get("cleared"):
                    counts["refreshed"] += 1
            else:
                # raw_graph: re-check alignment. If all edges align under
                # the current catalog uom + override state, clear the flag.
                with connect(user_id=triggered_by_user_id) as conn, \
                        conn.cursor() as cur:
                    cur.execute(
                        """
                        select count(*) from hub.bom_edges be
                         where be.artifact_id = %s
                           and hub.has_drift_remaining(%s, be.child_code,
                                                       be.uom)
                        """,
                        (aid, client_id),
                    )
                    (n_unresolved,) = cur.fetchone()
                    if n_unresolved == 0:
                        cur.execute(
                            "update hub.bom_artifacts "
                            "set has_uom_drift = false, "
                            "    uom_drift_resolved_at = coalesce("
                            "      uom_drift_resolved_at, now()) "
                            "where artifact_id = %s "
                            "  and has_uom_drift = true",
                            (aid,),
                        )
                        if cur.rowcount > 0:
                            counts["cleared"] += 1
        except Exception:
            counts["errors"] += 1
            continue
    return counts
