-- 093_catalog_bulk_accept.sql
-- Catalog phase 5 (#35): bulk approval.
--
-- Accepting ~2,157 discovered codes at once must NOT fire the D9
-- staleness trigger (mig 058, current body mig 071) once per row — that
-- runs the two affected-artifact subqueries (each calling
-- has_drift_remaining per BOM row) 2,157 times (brief Risk 2).
--
-- Two additions, no data change:
--   1. Guard the D9 insert trigger with a session GUC. When
--      `hub.bulk_load = 'on'`, the trigger no-ops. Bulk accept sets it
--      SET LOCAL (transaction-scoped, pool-safe — resets on commit) so
--      the inserts skip per-row propagation.
--   2. hub.materials_propagate_bulk(client, codes): the set-based
--      equivalent of the trigger's two arms, run ONCE after the inserts.
--      Same joins + same has_drift_remaining narrowing as the mig-071
--      D9 trigger, so the marked-artifact sets are identical; a parity
--      test locks that.
--
-- The trigger body below is mig 071's D9 verbatim apart from the added
-- guard. If mig 071's body ever changes, both this trigger AND
-- materials_propagate_bulk must be updated together (the parity test
-- catches divergence).

-- ── 1. Guard the mig-071 D9 trigger with hub.bulk_load ─────────────────

create or replace function hub.materials_propagate_on_insert()
returns trigger as $$
declare
  affected_derived text[];
  affected_source text[];
begin
  -- Bulk accept suppresses per-row propagation and calls
  -- hub.materials_propagate_bulk once for the whole set instead.
  if current_setting('hub.bulk_load', true) = 'on' then
    return NEW;
  end if;

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

comment on function hub.materials_propagate_on_insert is
  'D9 trigger (mig 058, body mig 071, guarded mig 093): mark BOM '
  'artifacts stale + drift when a catalog row is inserted whose UoM '
  'leaves referencing BOM rows unresolved. No-ops when hub.bulk_load='
  '''on'' — bulk accept batches via hub.materials_propagate_bulk.';

-- ── 2. Set-based propagation for bulk accept ───────────────────────────
-- Mirrors the mig-071 D9 trigger's two arms over a whole code set. Reads
-- each accepted material's UoM (already inserted) via has_drift_remaining,
-- so only codes whose UoM leaves a BOM row unresolved mark anything —
-- exactly as the per-row trigger would. Per-code attribution the trigger
-- writes in source_pk collapses to one bulk marker; the exact code list
-- lives in the catalog_bulk_accept audit event.

create or replace function hub.materials_propagate_bulk(
  p_client text, p_codes text[]
) returns void as $$
declare
  affected_derived text[];
  affected_source text[];
begin
  if p_codes is null or array_length(p_codes, 1) is null then
    return;
  end if;

  select array_agg(distinct ba.artifact_id)
    into affected_derived
    from hub.bom_artifacts ba
    join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
   where ba.client_id = p_client
     and bar.material_code = any(p_codes)
     and ba.tombstoned_at is null
     and hub.has_drift_remaining(p_client, bar.material_code, bar.uom)
     and ba.flatten_strategy in (
       'technical_exploded', 'purchased_btp_as_leaf',
       'self_produced_btp_exploded', 'mixed_confirmed'
     );

  select array_agg(distinct artifact_id) into affected_source
    from (
      select ba.artifact_id
        from hub.bom_artifacts ba
        join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
       where ba.client_id = p_client
         and bar.material_code = any(p_codes)
         and ba.tombstoned_at is null
         and hub.has_drift_remaining(p_client, bar.material_code, bar.uom)
         and ba.flatten_strategy = 'manual_flat_as_provided'
      union
      select ba.artifact_id
        from hub.bom_artifacts ba
        join hub.bom_edges be on be.artifact_id = ba.artifact_id
       where ba.client_id = p_client
         and be.child_code = any(p_codes)
         and ba.tombstoned_at is null
         and hub.has_drift_remaining(p_client, be.child_code, be.uom)
         and ba.source_bom_kind = 'technical_raw'
    ) src;

  if affected_derived is not null
     and array_length(affected_derived, 1) > 0 then
    perform hub.bom_mark_stale(
      affected_derived, 'catalog_inserted', 'hub.materials',
      p_client || '/bulk_accept'
    );
  end if;
  if affected_source is not null
     and array_length(affected_source, 1) > 0 then
    perform hub.bom_mark_uom_drift(
      affected_source, 'catalog_inserted', 'hub.materials',
      p_client || '/bulk_accept', null
    );
  end if;
end;
$$ language plpgsql;

comment on function hub.materials_propagate_bulk is
  'Set-based D9 propagation for catalog bulk accept (#35, mig 093). '
  'Run once after a bulk insert while the per-row trigger is suppressed '
  'via hub.bulk_load. Marks the same artifact sets the mig-071 trigger '
  'would row by row (parity-tested).';
