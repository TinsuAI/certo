-- 069 — Conditional D7/D9 triggers: skip flag when alias-aligned.
--
-- Audit 2026-05-27: Johnson `1000430256` catalog uom G→EA fix (a bug
-- correction where new value aligns with BOM raw uom) flagged 1,206
-- raw_graph BOMs as drift. The triggers in mig 057/058 fire on every
-- materials.uom UPDATE without checking whether NEW.uom actually
-- creates drift against BOM rows. Result: false positives accumulate
-- after every catalog correction.
--
-- Fix: introduce `hub.is_uom_aligned(a, b)` that resolves both
-- arguments through `hub.uom_aliases` and returns true if they map
-- to the same canonical UoM. D7/D9 triggers then narrow `affected`
-- arrays to only rows whose actual BOM uom does NOT alias-align with
-- NEW.uom.
--
-- The check is conservative on unknown aliases (returns false →
-- preserves existing flag-everything behavior for codes the alias
-- table doesn't know). Phased rollout: this mig only changes the
-- materials_uom dim path. Other dims (catalog_category, btp_sourcing,
-- catalog_inserted, btp_bom_*) fire as before — no alignment notion
-- applies to those.
--
-- Spec: audit 2026-05-27. Brief
-- `.ai/features/2026-05-27-stale-rebuild/brief.md` (forthcoming).

-- ─── Helper: alias-aligned check ─────────────────────────────────────

create or replace function hub.is_uom_aligned(uom_a text, uom_b text)
  returns boolean as $$
declare
  norm_a text;
  norm_b text;
  code_a text;
  code_b text;
begin
  -- NULL / empty → not aligned (conservative).
  if uom_a is null or uom_b is null then return false; end if;
  norm_a := lower(trim(uom_a));
  norm_b := lower(trim(uom_b));
  if norm_a = '' or norm_b = '' then return false; end if;
  if norm_a = norm_b then return true; end if;
  select uom_code into code_a from hub.uom_aliases
    where alias_norm = norm_a;
  select uom_code into code_b from hub.uom_aliases
    where alias_norm = norm_b;
  -- Either side unknown → conservative false (caller still flags).
  if code_a is null or code_b is null then return false; end if;
  return code_a = code_b;
end;
$$ language plpgsql immutable;

comment on function hub.is_uom_aligned is
  'Mig 069: returns true iff both uoms map to the same canonical via '
  'hub.uom_aliases (or are case-insensitive equal). Used by D7/D9 '
  'triggers to skip flagging when catalog uom change is benign '
  '(e.g., G→Grams alias, or fix-aligns-with-BOM-uom case).';

-- ─── D7 trigger refactor: skip when aligned ──────────────────────────

create or replace function hub.materials_propagate_staleness()
returns trigger as $$
declare
  affected_derived text[];
  affected_source text[];
  do_category    boolean := NEW.category is distinct from OLD.category;
  do_uom         boolean := NEW.uom is distinct from OLD.uom;
  do_sourcing    boolean := NEW.btp_sourcing is distinct from OLD.btp_sourcing;
begin
  -- category / btp_sourcing fire as before (no alignment notion).
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

  -- materials_uom: conditional on actual misalignment.
  if do_uom then
    -- Derived: bom_artifact_rows.uom vs NEW.uom (per row).
    select array_agg(distinct ba.artifact_id)
      into affected_derived
      from hub.bom_artifacts ba
      join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
     where ba.client_id = NEW.client_id
       and bar.material_code = NEW.material_code
       and ba.tombstoned_at is null
       and not hub.is_uom_aligned(bar.uom, NEW.uom)
       and ba.flatten_strategy in (
         'technical_exploded', 'purchased_btp_as_leaf',
         'self_produced_btp_exploded', 'mixed_confirmed'
       );
    -- Source: union of manual_flat (rows) + raw_graph (edges).
    select array_agg(distinct artifact_id) into affected_source
      from (
        select ba.artifact_id
          from hub.bom_artifacts ba
          join hub.bom_artifact_rows bar on bar.artifact_id = ba.artifact_id
         where ba.client_id = NEW.client_id
           and bar.material_code = NEW.material_code
           and ba.tombstoned_at is null
           and not hub.is_uom_aligned(bar.uom, NEW.uom)
           and ba.flatten_strategy = 'manual_flat_as_provided'
        union
        select ba.artifact_id
          from hub.bom_artifacts ba
          join hub.bom_edges be on be.artifact_id = ba.artifact_id
         where ba.client_id = NEW.client_id
           and be.child_code = NEW.material_code
           and ba.tombstoned_at is null
           and not hub.is_uom_aligned(be.uom, NEW.uom)
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

-- ─── D9 trigger refactor: skip when aligned ──────────────────────────
-- catalog-row INSERT: bind BOM rows that referenced this code
-- pre-catalog-insertion. Only flag if NEW.uom is set AND doesn't
-- alias-align with the BOM row's stored uom.

create or replace function hub.materials_propagate_on_insert()
returns trigger as $$
declare
  affected_derived text[];
  affected_source text[];
begin
  -- Trigger only acts when NEW.uom is set; without target uom no
  -- drift comparison is possible.
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
     and not hub.is_uom_aligned(bar.uom, NEW.uom)
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
         and not hub.is_uom_aligned(bar.uom, NEW.uom)
         and ba.flatten_strategy = 'manual_flat_as_provided'
      union
      select ba.artifact_id
        from hub.bom_artifacts ba
        join hub.bom_edges be on be.artifact_id = ba.artifact_id
       where ba.client_id = NEW.client_id
         and be.child_code = NEW.material_code
         and ba.tombstoned_at is null
         and not hub.is_uom_aligned(be.uom, NEW.uom)
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
