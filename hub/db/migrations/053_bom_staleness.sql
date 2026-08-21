-- 053 — Track D Phase 1: BOM dependency staleness flag + 4 triggers.
--
-- Adds is_stale + stale_reasons (JSONB list) + first/resolved
-- timestamps to hub.bom_artifacts. Triggers cover 4 staleness
-- dimensions (D1, D2, D7, D8). D3/D4/D5/D6 are deferred to Phase 2
-- per spec at .ai/features/2026-05-11-bom-staleness-track-d/brief.md.
--
-- Triggers mark only DERIVED artifacts (technical_exploded /
-- purchased_btp_as_leaf / self_produced_btp_exploded / mixed_confirmed)
-- — source raw_graph + manual_flat are immutable per BOM principle.
--
-- All triggers scope by client_id to prevent cross-tenant ripple.

alter table hub.bom_artifacts
  add column if not exists is_stale boolean not null default false,
  add column if not exists stale_reasons jsonb not null default '[]'::jsonb,
  add column if not exists stale_first_at timestamptz,
  add column if not exists stale_resolved_at timestamptz;

comment on column hub.bom_artifacts.is_stale is
  'Invalidation cache: true when a tracked dependency mutated since '
  'this artifact was materialized. Carve-out from no-derived-in-source '
  'principle (recompute via JOIN to audit log on every read would '
  'thrash). Cleared by manual refresh.';

comment on column hub.bom_artifacts.stale_reasons is
  'JSONB array of {dim, source_table, source_pk, observed_at} entries. '
  'Multi-dim accumulates. Cleared on refresh.';

create index if not exists idx_bom_artifacts_is_stale
  on hub.bom_artifacts (client_id, is_stale)
  where is_stale = true;

-- Helper: append a stale reason atomically. Marks artifact stale +
-- sets stale_first_at on first hit + appends to stale_reasons.
create or replace function hub.bom_mark_stale(
  artifact_ids text[],
  dim text,
  source_table text,
  source_pk text
) returns void as $$
begin
  if artifact_ids is null or array_length(artifact_ids, 1) is null then
    return;
  end if;
  update hub.bom_artifacts
     set is_stale = true,
         stale_reasons = stale_reasons || jsonb_build_array(
           jsonb_build_object(
             'dim', dim,
             'source_table', source_table,
             'source_pk', source_pk,
             'observed_at', to_char(now() at time zone 'utc',
                                    'YYYY-MM-DD"T"HH24:MI:SS"Z"')
           )
         ),
         stale_first_at = coalesce(stale_first_at, now()),
         stale_resolved_at = null
   where artifact_id = any(artifact_ids)
     and tombstoned_at is null
     and flatten_strategy in (
       'technical_exploded', 'purchased_btp_as_leaf',
       'self_produced_btp_exploded', 'mixed_confirmed'
     );
end;
$$ language plpgsql;

-- ─────────────────────────────────────────────────────────────────
-- Trigger D1/D7/D8: materials.{category,uom,btp_sourcing} UPDATE.
-- One trigger function, dim derived from which column changed.
-- ─────────────────────────────────────────────────────────────────

create or replace function hub.materials_propagate_staleness()
returns trigger as $$
declare
  affected text[];
begin
  -- Find derived artifacts for THIS client that reference the changed
  -- material via bom_artifact_rows.material_code.
  select array_agg(distinct ba.artifact_id)
    into affected
    from hub.bom_artifacts ba
    join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
   where ba.client_id = NEW.client_id
     and bar.material_code = NEW.material_code
     and ba.tombstoned_at is null
     and ba.flatten_strategy in (
       'technical_exploded', 'purchased_btp_as_leaf',
       'self_produced_btp_exploded', 'mixed_confirmed'
     );

  if NEW.category is distinct from OLD.category then
    perform hub.bom_mark_stale(
      affected, 'catalog_category', 'hub.materials',
      NEW.client_id || '/' || NEW.material_code
    );
  end if;
  if NEW.uom is distinct from OLD.uom then
    perform hub.bom_mark_stale(
      affected, 'materials_uom', 'hub.materials',
      NEW.client_id || '/' || NEW.material_code
    );
  end if;
  if NEW.btp_sourcing is distinct from OLD.btp_sourcing then
    perform hub.bom_mark_stale(
      affected, 'btp_sourcing', 'hub.materials',
      NEW.client_id || '/' || NEW.material_code
    );
  end if;
  return NEW;
end;
$$ language plpgsql;

drop trigger if exists trg_materials_propagate_staleness on hub.materials;
create trigger trg_materials_propagate_staleness
  after update on hub.materials
  for each row
  when (
    NEW.category is distinct from OLD.category
    or NEW.uom is distinct from OLD.uom
    or NEW.btp_sourcing is distinct from OLD.btp_sourcing
  )
  execute function hub.materials_propagate_staleness();

-- ─────────────────────────────────────────────────────────────────
-- Trigger D2: BTP raw_graph BOM ingest → parents stale.
-- Fires when a NEW raw_graph artifact lands for a product that is
-- referenced by other artifacts' bom_artifact_rows.
-- ─────────────────────────────────────────────────────────────────

create or replace function hub.bom_artifact_propagate_btp_added()
returns trigger as $$
declare
  affected text[];
begin
  if NEW.source_bom_kind <> 'technical_raw' then
    return NEW;
  end if;
  if NEW.tombstoned_at is not null then
    return NEW;
  end if;

  select array_agg(distinct ba.artifact_id)
    into affected
    from hub.bom_artifacts ba
    join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
   where ba.client_id = NEW.client_id
     and bar.material_code = NEW.product_code
     and ba.artifact_id <> NEW.artifact_id
     and ba.tombstoned_at is null
     and ba.flatten_strategy in (
       'technical_exploded', 'purchased_btp_as_leaf',
       'self_produced_btp_exploded', 'mixed_confirmed'
     );

  perform hub.bom_mark_stale(
    affected, 'btp_bom_added', 'hub.bom_artifacts', NEW.artifact_id
  );
  return NEW;
end;
$$ language plpgsql;

drop trigger if exists trg_bom_propagate_btp_added on hub.bom_artifacts;
create trigger trg_bom_propagate_btp_added
  after insert on hub.bom_artifacts
  for each row
  execute function hub.bom_artifact_propagate_btp_added();

-- ─────────────────────────────────────────────────────────────────
-- Trigger D2-symmetric: tombstoning a raw_graph BOM → parents stale.
-- ─────────────────────────────────────────────────────────────────

create or replace function hub.bom_artifact_propagate_btp_tombstoned()
returns trigger as $$
declare
  affected text[];
begin
  if NEW.source_bom_kind <> 'technical_raw' then
    return NEW;
  end if;

  select array_agg(distinct ba.artifact_id)
    into affected
    from hub.bom_artifacts ba
    join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
   where ba.client_id = NEW.client_id
     and bar.material_code = NEW.product_code
     and ba.artifact_id <> NEW.artifact_id
     and ba.tombstoned_at is null
     and ba.flatten_strategy in (
       'technical_exploded', 'purchased_btp_as_leaf',
       'self_produced_btp_exploded', 'mixed_confirmed'
     );

  perform hub.bom_mark_stale(
    affected, 'btp_bom_tombstoned', 'hub.bom_artifacts', NEW.artifact_id
  );
  return NEW;
end;
$$ language plpgsql;

drop trigger if exists trg_bom_propagate_btp_tombstoned on hub.bom_artifacts;
create trigger trg_bom_propagate_btp_tombstoned
  after update of tombstoned_at on hub.bom_artifacts
  for each row
  when (NEW.tombstoned_at is not null and OLD.tombstoned_at is null)
  execute function hub.bom_artifact_propagate_btp_tombstoned();
