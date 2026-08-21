-- 054 — bom_mark_stale: dedup (dim, source_pk) entries.
--
-- Mig 053 helper appended a new entry to stale_reasons on every
-- trigger fire. Repeated edits of the same (dim, source_pk) caused
-- JSONB array bloat (verified 2026-05-11: PIECES→KG→PIECES yielded
-- 2 identical-key entries). Per /rev finding #3.
--
-- Fix: use `@>` containment check before append. If an entry with
-- same (dim, source_pk) already exists, skip — keep first
-- observed_at as "first time we noticed this dependency moved".
--
-- Multi-dim still accumulates correctly: catalog_category +
-- materials_uom for same source_pk are 2 entries (different dim).

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
         stale_reasons = case
           when stale_reasons @> jsonb_build_array(
             jsonb_build_object('dim', dim, 'source_pk', source_pk)
           ) then stale_reasons
           else stale_reasons || jsonb_build_array(
             jsonb_build_object(
               'dim', dim,
               'source_table', source_table,
               'source_pk', source_pk,
               'observed_at', to_char(now() at time zone 'utc',
                                      'YYYY-MM-DD"T"HH24:MI:SS"Z"')
             )
           )
         end,
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
