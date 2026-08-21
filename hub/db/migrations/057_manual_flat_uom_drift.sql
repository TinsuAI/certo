-- 057 — Track D Phase 2 step 6: manual_flat UoM drift signal.
--
-- Adds a separate `has_uom_drift` signal on `hub.bom_artifacts` for
-- manual_flat_as_provided artifacts. These are source artifacts (not
-- derived), so they cannot be re-derived to resolve drift. The signal
-- tells staff "Re-upload BOM" instead of "Refresh".
--
-- Why a separate column from `is_stale`:
-- - is_stale (mig 053): clearable by Refresh action. Semantically
--   "derived data needs re-derivation".
-- - has_uom_drift (this mig): only clearable by re-upload OR catalog
--   UoM edit. Semantically "source data conflicts with catalog UoM".
--
-- D7 trigger extension: when materials.uom changes, also mark
-- manual_flat_as_provided artifacts referencing that material with
-- has_uom_drift=true (in addition to existing derived-artifact
-- staleness path).
--
-- Spec: `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md`
-- decision 7 + Phase 3 follow-up E (folded in).

alter table hub.bom_artifacts
  add column if not exists has_uom_drift boolean not null default false,
  add column if not exists uom_drift_reasons jsonb not null
    default '[]'::jsonb,
  add column if not exists uom_drift_first_at timestamptz,
  add column if not exists uom_drift_resolved_at timestamptz;

comment on column hub.bom_artifacts.has_uom_drift is
  'Source-artifact UoM conflict signal (mig 057). Distinct from '
  'is_stale: cannot be cleared by Refresh, requires re-upload or '
  'catalog UoM edit. Applies to manual_flat_as_provided + raw_graph.';

comment on column hub.bom_artifacts.uom_drift_reasons is
  'JSONB array of {dim, source_table, source_pk, observed_at, '
  'material_code} for UoM drift events.';

create index if not exists idx_bom_artifacts_has_uom_drift
  on hub.bom_artifacts (client_id, has_uom_drift)
  where has_uom_drift = true;

-- Helper: mark UoM drift on artifacts. Uses @> dedup like
-- bom_mark_stale (mig 054). Filter to source artifacts only.
create or replace function hub.bom_mark_uom_drift(
  artifact_ids text[],
  dim text,
  source_table text,
  source_pk text,
  material_code text default null
) returns void as $$
declare
  new_reason jsonb;
begin
  if artifact_ids is null or array_length(artifact_ids, 1) is null then
    return;
  end if;
  new_reason := jsonb_build_object(
    'dim', dim,
    'source_table', source_table,
    'source_pk', source_pk,
    'material_code', material_code,
    'observed_at', to_char(now() at time zone 'utc',
                           'YYYY-MM-DD"T"HH24:MI:SS"Z"')
  );
  update hub.bom_artifacts
     set has_uom_drift = true,
         uom_drift_reasons = case
           when uom_drift_reasons @> jsonb_build_array(
             jsonb_build_object(
               'dim', dim,
               'source_table', source_table,
               'source_pk', source_pk,
               'material_code', material_code
             )
           ) then uom_drift_reasons
           else uom_drift_reasons || jsonb_build_array(new_reason)
         end,
         uom_drift_first_at = coalesce(uom_drift_first_at, now()),
         uom_drift_resolved_at = null
   where artifact_id = any(artifact_ids)
     and tombstoned_at is null
     and flatten_strategy in (
       'manual_flat_as_provided', 'no_strategy'
     );
end;
$$ language plpgsql;

comment on function hub.bom_mark_uom_drift is
  'Marks source artifacts (manual_flat / raw_graph) with UoM drift. '
  'Filter excludes derived artifacts which use is_stale instead.';

-- ─────────────────────────────────────────────────────────────────
-- Extend D7 trigger: when materials.uom changes, also fire on
-- source artifacts (manual_flat + raw_graph). Existing trigger
-- function appends a separate path for the source side.
-- ─────────────────────────────────────────────────────────────────

create or replace function hub.materials_propagate_staleness()
returns trigger as $$
declare
  affected_derived text[];
  affected_source text[];
begin
  -- Derived artifacts (existing Phase 1 behaviour).
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

  -- Source artifacts (Phase 2 mig 057): manual_flat + raw_graph
  -- referencing this material. raw_graph has rows in bom_edges
  -- (child_code), manual_flat in bom_artifact_rows (material_code).
  select array_agg(distinct artifact_id)
    into affected_source
    from (
      select ba.artifact_id
        from hub.bom_artifacts ba
        join hub.bom_artifact_rows bar
          on bar.artifact_id = ba.artifact_id
       where ba.client_id = NEW.client_id
         and bar.material_code = NEW.material_code
         and ba.tombstoned_at is null
         and ba.flatten_strategy = 'manual_flat_as_provided'
      union
      select ba.artifact_id
        from hub.bom_artifacts ba
        join hub.bom_edges be on be.artifact_id = ba.artifact_id
       where ba.client_id = NEW.client_id
         and be.child_code = NEW.material_code
         and ba.tombstoned_at is null
         and ba.source_bom_kind = 'technical_raw'
    ) src;

  if NEW.category is distinct from OLD.category then
    perform hub.bom_mark_stale(
      affected_derived, 'catalog_category', 'hub.materials',
      NEW.client_id || '/' || NEW.material_code
    );
  end if;
  if NEW.uom is distinct from OLD.uom then
    perform hub.bom_mark_stale(
      affected_derived, 'materials_uom', 'hub.materials',
      NEW.client_id || '/' || NEW.material_code
    );
    -- Phase 2: also surface drift on source artifacts. Trigger filter
    -- in bom_mark_uom_drift narrows to manual_flat + no_strategy
    -- (raw_graph kind). The two sets above cover both.
    perform hub.bom_mark_uom_drift(
      affected_source, 'materials_uom', 'hub.materials',
      NEW.client_id || '/' || NEW.material_code,
      NEW.material_code
    );
  end if;
  if NEW.btp_sourcing is distinct from OLD.btp_sourcing then
    perform hub.bom_mark_stale(
      affected_derived, 'btp_sourcing', 'hub.materials',
      NEW.client_id || '/' || NEW.material_code
    );
  end if;
  return NEW;
end;
$$ language plpgsql;
