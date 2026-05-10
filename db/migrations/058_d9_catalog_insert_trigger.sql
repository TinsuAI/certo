-- 058 — Track D Phase 2 step 8: D9 catalog-insert trigger.
--
-- Order-independence invariant (memory `project_ingest_order_invariance.md`):
-- BOM uploaded before catalog has the code → ingest as raw, defer
-- derived shapes (no catalog UoM to convert to). When catalog later
-- gains the code with a UoM, this trigger marks affected derived
-- artifacts stale → refresh re-derives with conversion.
--
-- Without D9, the same source data would produce different end states
-- depending on upload order:
--   - BCCT → Catalog → BOM: derived shapes ingested converted.
--   - BOM → BCCT → Catalog: derived shapes ingested with raw uom (no
--     catalog UoM at that time), and STAY raw forever.
-- D9 closes the gap: catalog INSERT fires same staleness path as
-- catalog UPDATE (D7).
--
-- Spec: `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md`
-- step 8 + scope item 7 (order-independence safeguards).

create or replace function hub.materials_propagate_on_insert()
returns trigger as $$
declare
  affected_derived text[];
  affected_source text[];
begin
  -- Same join logic as D7 (mig 057) but driven by INSERT.
  -- Find any existing artifacts that reference NEW.material_code
  -- (BOM-before-catalog ingest case).
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

  -- D9 dim: 'catalog_inserted'. Distinct from D1 (catalog_category
  -- update) so refresh UI can surface it as "BOM was uploaded before
  -- this code existed in catalog — refresh to apply UoM conversion".
  if affected_derived is not null
     and array_length(affected_derived, 1) > 0 then
    perform hub.bom_mark_stale(
      affected_derived, 'catalog_inserted', 'hub.materials',
      NEW.client_id || '/' || NEW.material_code
    );
  end if;
  -- Source artifacts only get drift marked if NEW.uom is set
  -- (otherwise there's nothing to convert against yet).
  if NEW.uom is not null and NEW.uom <> ''
     and affected_source is not null
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

comment on function hub.materials_propagate_on_insert is
  'D9 trigger (mig 058): when a catalog row is inserted matching '
  'codes that BOM artifacts already reference, mark them stale + '
  'drift. Closes order-independence gap (BOM-before-catalog ingest).';

drop trigger if exists trg_materials_propagate_on_insert on hub.materials;
create trigger trg_materials_propagate_on_insert
  after insert on hub.materials
  for each row
  execute function hub.materials_propagate_on_insert();
