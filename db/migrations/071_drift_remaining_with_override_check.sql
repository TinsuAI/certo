-- 071 — Broader drift check: alias OR per-material override resolves it.
--
-- Mig 070 cleared alias-aligned false positives but left 919 Johnson
-- raw_graph rows flagged. Audit 2026-05-27 found the residual pattern:
-- BOM uom=EA, catalog uom=CAY/METRIC-TONS/KILO-GRAMMES/etc. — pairs
-- that ARE cross-family per uom_canonical, but staff has already
-- inserted per-material `client_uom_overrides` rows (EA→CAY=1.0,
-- EA→METRIC-TONS=0.001, etc.) confirming the synonym/conversion.
-- These artifacts are not "drifting"; the conversion is resolved.
--
-- Triggers should look at the overrides table too, not just aliases.
--
-- This mig:
-- 1. Adds `hub.has_drift_remaining(client_id, material_code, bom_uom)`
--    — true iff BOM uom can't be resolved against current catalog uom
--    via alias OR override row.
-- 2. Refactors D7/D9 triggers to use this richer check.
-- 3. Re-runs backfill (mig 070-style) using the new check.

create or replace function hub.has_drift_remaining(
  p_client_id text,
  p_material_code text,
  p_bom_uom text
) returns boolean as $$
declare
  cat_uom text;
  has_override boolean;
begin
  if p_bom_uom is null or trim(p_bom_uom) = '' then
    return false;  -- no source uom on BOM row → nothing to compare
  end if;
  select uom into cat_uom from hub.materials
   where client_id = p_client_id and material_code = p_material_code;
  if cat_uom is null or trim(cat_uom) = '' then
    return false;  -- no catalog uom → catalog_uom_missing handled elsewhere
  end if;
  if hub.is_uom_aligned(p_bom_uom, cat_uom) then
    return false;
  end if;
  -- Cross-family: check if staff already resolved via override.
  select exists (
    select 1 from hub.client_uom_overrides
     where client_id = p_client_id
       and material_code = p_material_code
       and from_uom = p_bom_uom
       and to_uom = cat_uom
       and factor is not null
  ) into has_override;
  return not has_override;
end;
$$ language plpgsql stable;

comment on function hub.has_drift_remaining is
  'Mig 071: true iff bom_uom vs current catalog uom for this material '
  'is unresolved (neither alias-aligned nor present in client_uom_overrides). '
  'Used by D7/D9 triggers + backfill. STABLE (not IMMUTABLE) because '
  'it reads materials + overrides tables.';

-- ─── D7 trigger v2: use has_drift_remaining ──────────────────────────

create or replace function hub.materials_propagate_staleness()
returns trigger as $$
declare
  affected_derived text[];
  affected_source text[];
  do_category    boolean := NEW.category is distinct from OLD.category;
  do_uom         boolean := NEW.uom is distinct from OLD.uom;
  do_sourcing    boolean := NEW.btp_sourcing is distinct from OLD.btp_sourcing;
begin
  if do_category or do_sourcing then
    select array_agg(distinct ba.artifact_id)
      into affected_derived
      from hub.bom_artifacts ba
      join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
     where ba.client_id = NEW.client_id
       and bar.material_code = NEW.material_code
       and ba.tombstoned_at is null
       and ba.flatten_strategy in (
         'technical_exploded', 'purchased_btp_as_leaf',
         'self_produced_btp_exploded', 'mixed_confirmed'
       );
    if do_category then
      perform hub.bom_mark_stale(
        affected_derived, 'catalog_category', 'hub.materials',
        NEW.client_id || '/' || NEW.material_code
      );
    end if;
    if do_sourcing then
      perform hub.bom_mark_stale(
        affected_derived, 'btp_sourcing', 'hub.materials',
        NEW.client_id || '/' || NEW.material_code
      );
    end if;
  end if;

  if do_uom then
    -- For uom changes, narrow `affected` to rows that still have
    -- unresolved drift after the change. hub.has_drift_remaining
    -- examines current catalog uom (= NEW.uom inside this BEFORE/AFTER
    -- trigger — the UPDATE has applied NEW.uom by the time AFTER fires).
    select array_agg(distinct ba.artifact_id)
      into affected_derived
      from hub.bom_artifacts ba
      join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
     where ba.client_id = NEW.client_id
       and bar.material_code = NEW.material_code
       and ba.tombstoned_at is null
       and hub.has_drift_remaining(NEW.client_id, NEW.material_code, bar.uom)
       and ba.flatten_strategy in (
         'technical_exploded', 'purchased_btp_as_leaf',
         'self_produced_btp_exploded', 'mixed_confirmed'
       );
    select array_agg(distinct artifact_id) into affected_source
      from (
        select ba.artifact_id
          from hub.bom_artifacts ba
          join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
         where ba.client_id = NEW.client_id
           and bar.material_code = NEW.material_code
           and ba.tombstoned_at is null
           and hub.has_drift_remaining(NEW.client_id, NEW.material_code, bar.uom)
           and ba.flatten_strategy = 'manual_flat_as_provided'
        union
        select ba.artifact_id
          from hub.bom_artifacts ba
          join hub.bom_edges be on be.artifact_id = ba.artifact_id
         where ba.client_id = NEW.client_id
           and be.child_code = NEW.material_code
           and ba.tombstoned_at is null
           and hub.has_drift_remaining(NEW.client_id, NEW.material_code, be.uom)
           and ba.source_bom_kind = 'technical_raw'
      ) src;
    perform hub.bom_mark_stale(
      affected_derived, 'materials_uom', 'hub.materials',
      NEW.client_id || '/' || NEW.material_code
    );
    perform hub.bom_mark_uom_drift(
      affected_source, 'materials_uom', 'hub.materials',
      NEW.client_id || '/' || NEW.material_code,
      NEW.material_code
    );
  end if;
  return NEW;
end;
$$ language plpgsql;

-- ─── D9 trigger v2: use has_drift_remaining ──────────────────────────

create or replace function hub.materials_propagate_on_insert()
returns trigger as $$
declare
  affected_derived text[];
  affected_source text[];
begin
  if NEW.uom is null or trim(NEW.uom) = '' then
    return NEW;
  end if;

  select array_agg(distinct ba.artifact_id)
    into affected_derived
    from hub.bom_artifacts ba
    join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
   where ba.client_id = NEW.client_id
     and bar.material_code = NEW.material_code
     and ba.tombstoned_at is null
     and hub.has_drift_remaining(NEW.client_id, NEW.material_code, bar.uom)
     and ba.flatten_strategy in (
       'technical_exploded', 'purchased_btp_as_leaf',
       'self_produced_btp_exploded', 'mixed_confirmed'
     );

  select array_agg(distinct artifact_id) into affected_source
    from (
      select ba.artifact_id
        from hub.bom_artifacts ba
        join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
       where ba.client_id = NEW.client_id
         and bar.material_code = NEW.material_code
         and ba.tombstoned_at is null
         and hub.has_drift_remaining(NEW.client_id, NEW.material_code, bar.uom)
         and ba.flatten_strategy = 'manual_flat_as_provided'
      union
      select ba.artifact_id
        from hub.bom_artifacts ba
        join hub.bom_edges be on be.artifact_id = ba.artifact_id
       where ba.client_id = NEW.client_id
         and be.child_code = NEW.material_code
         and ba.tombstoned_at is null
         and hub.has_drift_remaining(NEW.client_id, NEW.material_code, be.uom)
         and ba.source_bom_kind = 'technical_raw'
    ) src;

  if affected_derived is not null
     and array_length(affected_derived, 1) > 0 then
    perform hub.bom_mark_stale(
      affected_derived, 'catalog_inserted', 'hub.materials',
      NEW.client_id || '/' || NEW.material_code
    );
  end if;
  if affected_source is not null
     and array_length(affected_source, 1) > 0 then
    perform hub.bom_mark_uom_drift(
      affected_source, 'catalog_inserted', 'hub.materials',
      NEW.client_id || '/' || NEW.material_code,
      NEW.material_code
    );
  end if;
  return NEW;
end;
$$ language plpgsql;

-- ─── Backfill round 2: include override resolution ───────────────────
-- Re-uses the same per-artifact "every row resolved?" logic from mig 070
-- but with the broader has_drift_remaining helper.

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
