-- 077 — has_drift_remaining mirrors classify_uom_relation acceptance (D.2 / A).
--
-- A.4.4 (2026-06-07) built the canonical classifier
-- `app/stores/uom.py::classify_uom_relation`: a UoM pair is acceptable
-- (no staff action) when it is equivalent OR convertible, and only
-- `incompatible` requires a factor. The read surfaces adopted it; the SQL
-- staleness check `hub.has_drift_remaining` (mig 071) did NOT — it only
-- knew alias-align + a single per-material *exact-forward* override. So it
-- still flagged as drift every pair the classifier accepts via:
--   - same-family base_factor (g↔kg, m↔cm),
--   - tier-A cross-family default (count/count_packaging/assembly ↔ 1:1),
--   - client-wide override (material_code_key = ''),
--   - reverse-direction override (row exists cat→bom, not bom→cat).
-- These four were the residual false-positives mig 070/071 chased by hand.
--
-- This mig widens `has_drift_remaining` to mirror the classifier's full
-- acceptance (Step 1-6 of `resolve_conversion` + `_TIER_A_FAMILIES`), so
-- the trigger/backfill stop over-flagging. Only `create or replace` the
-- function — the D7/D9 triggers call it by name and pick up the new body.
--
-- Pinned to the Python classifier by tests/test_has_drift_remaining_parity.py
-- (brief R1: the parity corpus is the drift guard, non-optional). Backfill
-- below re-runs the mig 070/071 "all rows resolved? → clear" pass with the
-- widened predicate to clear residual false positives.
--
-- Spec: .ai/features/2026-06-08-bom-staleness-fingerprint/brief.md (scope A).

create or replace function hub.has_drift_remaining(
  p_client_id text,
  p_material_code text,
  p_bom_uom text
) returns boolean as $$
declare
  cat_uom   text;
  bom_canon text;
  cat_canon text;
  bom_fam   text;
  cat_fam   text;
begin
  if p_bom_uom is null or trim(p_bom_uom) = '' then
    return false;  -- no source uom on BOM row → nothing to compare
  end if;
  select uom into cat_uom from hub.materials
   where client_id = p_client_id and material_code = p_material_code;
  if cat_uom is null or trim(cat_uom) = '' then
    return false;  -- no catalog uom → catalog_uom_missing handled elsewhere
  end if;

  -- (1) identity / alias: same canonical (symmetric). resolve_conversion
  -- steps 1-3 alias branch.
  if hub.is_uom_aligned(p_bom_uom, cat_uom) then
    return false;
  end if;

  -- (2) explicit override — per-material OR client-wide, EITHER direction.
  -- Mirrors resolve_conversion steps 1-2 + classify's symmetric reverse.
  if exists (
    select 1 from hub.client_uom_overrides
     where client_id = p_client_id
       and material_code_key in (p_material_code, '')
       and ( (from_uom = p_bom_uom and to_uom = cat_uom)
          or (from_uom = cat_uom and to_uom = p_bom_uom) )
  ) then
    return false;
  end if;

  -- Resolve both sides to canonical (lower+trim, matching hub.is_uom_aligned).
  select uom_code into bom_canon from hub.uom_aliases
   where alias_norm = lower(trim(p_bom_uom));
  select uom_code into cat_canon from hub.uom_aliases
   where alias_norm = lower(trim(cat_uom));
  -- Unknown token on either side → cannot prove convertible → drift remains
  -- (conservative; classifier returns incompatible / remediation=add_alias).
  if bom_canon is null or cat_canon is null then
    return true;
  end if;
  select family into bom_fam from hub.uom_canonical where uom_code = bom_canon;
  select family into cat_fam from hub.uom_canonical where uom_code = cat_canon;

  -- (3) same-family base_factor conversion (resolve_conversion step 4).
  if bom_fam = cat_fam then
    return false;
  end if;
  -- (4) tier-A cross-family default 1:1 (resolve_conversion step 5,
  -- _TIER_A_FAMILIES). count / count_packaging / assembly are mutually
  -- "convertible-by-assumption".
  if bom_fam in ('count', 'count_packaging', 'assembly')
     and cat_fam in ('count', 'count_packaging', 'assembly') then
    return false;
  end if;

  -- (5) tier-B hard block: mass↔count, mass↔length, etc. (step 6 → None).
  return true;
end;
$$ language plpgsql stable;

comment on function hub.has_drift_remaining is
  'Mig 077: true iff bom_uom vs current catalog uom is incompatible per '
  'classify_uom_relation (alias / per-material+client-wide override either '
  'direction / same-family base_factor / tier-A 1:1 all resolve → false; '
  'tier-B + unknown token → true). Pinned by test_has_drift_remaining_parity.';

-- ─── Backfill: clear residual false positives with the widened check ──────
-- Same per-artifact "every contributing row resolved? → clear" structure as
-- mig 070/071; only the predicate (has_drift_remaining) is now wider.

with raw_unresolved as (
  select distinct ba.artifact_id
    from hub.bom_artifacts ba
    join hub.bom_edges be on be.artifact_id = ba.artifact_id
   where ba.tombstoned_at is null
     and ba.has_uom_drift = true
     and ba.source_bom_kind = 'technical_raw'
     and hub.has_drift_remaining(ba.client_id, be.child_code, be.uom)
),
raw_clearable as (
  select ba.artifact_id
    from hub.bom_artifacts ba
   where ba.tombstoned_at is null
     and ba.has_uom_drift = true
     and ba.source_bom_kind = 'technical_raw'
     and not exists (
       select 1 from raw_unresolved u where u.artifact_id = ba.artifact_id
     )
)
update hub.bom_artifacts ba
   set has_uom_drift = false,
       uom_drift_resolved_at = coalesce(uom_drift_resolved_at, now())
  from raw_clearable rc
 where ba.artifact_id = rc.artifact_id;

with mf_unresolved as (
  select distinct ba.artifact_id
    from hub.bom_artifacts ba
    join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
   where ba.tombstoned_at is null
     and ba.has_uom_drift = true
     and ba.flatten_strategy = 'manual_flat_as_provided'
     and hub.has_drift_remaining(ba.client_id, bar.material_code, bar.uom)
),
mf_clearable as (
  select ba.artifact_id
    from hub.bom_artifacts ba
   where ba.tombstoned_at is null
     and ba.has_uom_drift = true
     and ba.flatten_strategy = 'manual_flat_as_provided'
     and not exists (
       select 1 from mf_unresolved u where u.artifact_id = ba.artifact_id
     )
)
update hub.bom_artifacts ba
   set has_uom_drift = false,
       uom_drift_resolved_at = coalesce(uom_drift_resolved_at, now())
  from mf_clearable mc
 where ba.artifact_id = mc.artifact_id;

with derived_only_uom_dims as (
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
derived_unresolved as (
  select distinct ba.artifact_id
    from hub.bom_artifacts ba
    join derived_only_uom_dims o using (artifact_id)
    join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
   where hub.has_drift_remaining(ba.client_id, bar.material_code, bar.uom)
),
derived_clearable as (
  select o.artifact_id
    from derived_only_uom_dims o
   where not exists (
     select 1 from derived_unresolved u where u.artifact_id = o.artifact_id
   )
)
update hub.bom_artifacts ba
   set is_stale = false,
       stale_resolved_at = coalesce(stale_resolved_at, now())
  from derived_clearable dc
 where ba.artifact_id = dc.artifact_id;
