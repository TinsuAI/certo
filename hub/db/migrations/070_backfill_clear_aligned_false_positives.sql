-- 070 — Backfill: clear has_uom_drift / is_stale on artifacts that
--                  are alias-aligned with current catalog uom.
--
-- Mig 069 made D7/D9 triggers conditional (skip flag when alias-
-- aligned), but the 1,206 Johnson raw_graph rows + 119 manual_flat
-- + a handful of derived rows accumulated under the old eager-flag
-- behaviour are still flagged. Many of them are now false positives:
-- the BOM's uom alias-aligns with current catalog uom.
--
-- This mig sweeps existing flagged artifacts and clears the flag
-- (only the `materials_uom` / `catalog_inserted` dims; other dims
-- like factor_missing / catalog_uom_missing / unconfirmed_default
-- are kept untouched — they represent real action items).
--
-- Conservative: per-artifact decision. An artifact is "really
-- aligned" iff EVERY one of its rows (or edges, for raw_graph) maps
-- via hub.is_uom_aligned to the current catalog uom. Any unaligned
-- row → keep flag.
--
-- Forensics: reasons arrays preserved. Only the boolean + resolved_at
-- are touched. A future audit can grep for entries with
-- `uom_drift_resolved_at` set and explain "cleared by mig 070".
--
-- Idempotent: only applies the relaxation; doesn't add anything.
-- Side-effect free if no candidates qualify.

-- ─── Phase 1: technical_raw — check via bom_edges.uom ────────────────

with raw_unaligned as (
  select distinct ba.artifact_id
    from hub.bom_artifacts ba
    join hub.bom_edges be on be.artifact_id = ba.artifact_id
    join hub.materials m on m.client_id = ba.client_id
                         and m.material_code = be.child_code
   where ba.tombstoned_at is null
     and ba.has_uom_drift = true
     and ba.source_bom_kind = 'technical_raw'
     and not hub.is_uom_aligned(be.uom, m.uom)
),
raw_align_candidates as (
  select ba.artifact_id
    from hub.bom_artifacts ba
   where ba.tombstoned_at is null
     and ba.has_uom_drift = true
     and ba.source_bom_kind = 'technical_raw'
     and not exists (
       select 1 from raw_unaligned u where u.artifact_id = ba.artifact_id
     )
)
update hub.bom_artifacts ba
   set has_uom_drift = false,
       uom_drift_resolved_at = coalesce(uom_drift_resolved_at, now())
  from raw_align_candidates rac
 where ba.artifact_id = rac.artifact_id;

-- ─── Phase 2: manual_flat — check via bom_artifact_rows.uom ─────────

with mf_unaligned as (
  select distinct ba.artifact_id
    from hub.bom_artifacts ba
    join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
    join hub.materials m on m.client_id = ba.client_id
                         and m.material_code = bar.material_code
   where ba.tombstoned_at is null
     and ba.has_uom_drift = true
     and ba.flatten_strategy = 'manual_flat_as_provided'
     and not hub.is_uom_aligned(bar.uom, m.uom)
),
mf_align_candidates as (
  select ba.artifact_id
    from hub.bom_artifacts ba
   where ba.tombstoned_at is null
     and ba.has_uom_drift = true
     and ba.flatten_strategy = 'manual_flat_as_provided'
     and not exists (
       select 1 from mf_unaligned u where u.artifact_id = ba.artifact_id
     )
)
update hub.bom_artifacts ba
   set has_uom_drift = false,
       uom_drift_resolved_at = coalesce(uom_drift_resolved_at, now())
  from mf_align_candidates mac
 where ba.artifact_id = mac.artifact_id;

-- ─── Phase 3: derived technical_flattened — same logic ──────────────
-- Only clear is_stale when EVERY stale reason was materials_uom (or
-- catalog_inserted) AND every row's uom alias-aligns with its
-- material's current catalog uom. Other reason dims (factor_missing,
-- catalog_uom_missing, unconfirmed_default_1to1) require staff input
-- and must NOT be cleared by this backfill.

with derived_only_materials_uom_reasons as (
  -- Artifacts whose stale_reasons contain ONLY {materials_uom,
  -- catalog_inserted}. Any other dim disqualifies (keep stale).
  select ba.artifact_id
    from hub.bom_artifacts ba
   where ba.tombstoned_at is null
     and ba.is_stale = true
     and ba.flatten_strategy in (
       'technical_exploded', 'purchased_btp_as_leaf',
       'self_produced_btp_exploded', 'mixed_confirmed'
     )
     and not exists (
       select 1 from jsonb_array_elements(ba.stale_reasons) r
        where (r->>'dim') not in ('materials_uom', 'catalog_inserted')
     )
),
derived_unaligned as (
  select distinct ba.artifact_id
    from hub.bom_artifacts ba
    join derived_only_materials_uom_reasons o using (artifact_id)
    join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
    join hub.materials m on m.client_id = ba.client_id
                         and m.material_code = bar.material_code
   where not hub.is_uom_aligned(bar.uom, m.uom)
),
derived_align_candidates as (
  select o.artifact_id
    from derived_only_materials_uom_reasons o
   where not exists (
     select 1 from derived_unaligned u where u.artifact_id = o.artifact_id
   )
)
update hub.bom_artifacts ba
   set is_stale = false,
       stale_resolved_at = coalesce(stale_resolved_at, now())
  from derived_align_candidates dac
 where ba.artifact_id = dac.artifact_id;
