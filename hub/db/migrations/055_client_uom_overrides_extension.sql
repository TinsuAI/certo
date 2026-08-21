-- 055 — Track D Phase 2 step 1: extend `hub.client_uom_overrides`.
--
-- Adds:
--   • `is_cross_family` boolean — auto-computed via trigger from
--     `from_uom` + `to_uom` canonical family lookup. Staff cannot
--     set it manually; trigger always overwrites. Used by Phase 2
--     flatten engine to decide tier-A (count↔assembly/packaging,
--     1:1 default OK) vs tier-B (count↔mass/length/volume, no
--     default, hard-block).
--   • `notes` text nullable — staff annotation (provenance, batch
--     range, supplier reference, etc).
--   • `source` enum extended with: `supplier_data`,
--     `packaging_spec`, `derived_average`, `imported`. Mig 021
--     shipped {`staff_form`, `migration`, `seed`, `co_proposal`};
--     Phase 2 admin UI + CSV import need richer provenance.
--
-- Spec: `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md`
-- decision 1 + decision 6 (3-tier policy).

alter table hub.client_uom_overrides
  add column if not exists is_cross_family boolean not null default false,
  add column if not exists notes text;

comment on column hub.client_uom_overrides.is_cross_family is
  'Auto-computed via trigger from from_uom + to_uom canonical family. '
  'true => factor must be supplied manually (no canonical fallback). '
  'Staff cannot override; trigger recomputes on insert/update of '
  'from_uom or to_uom.';

comment on column hub.client_uom_overrides.notes is
  'Staff annotation: provenance, batch range, supplier reference, '
  'agency confirmation date, etc.';

-- Replace check constraint to extend source enum.
alter table hub.client_uom_overrides
  drop constraint if exists chk_uom_override_source;
alter table hub.client_uom_overrides
  add constraint chk_uom_override_source check (source in (
    'staff_form', 'migration', 'seed', 'co_proposal',
    'supplier_data', 'packaging_spec', 'derived_average', 'imported'
  ));

-- Trigger function: compute is_cross_family from canonical lookup.
-- Resolves alias -> canonical via hub.uom_aliases; if from/to is
-- already a canonical code (matches hub.uom_canonical.uom_code),
-- short-circuit. If either side cannot resolve, default to false
-- (staff edits will fix once aliases are added).
create or replace function hub.compute_uom_override_is_cross_family()
  returns trigger as $$
declare
  from_canon text;
  to_canon text;
  from_fam text;
  to_fam text;
  norm_from text;
  norm_to text;
begin
  norm_from := lower(btrim(NEW.from_uom));
  norm_to := lower(btrim(NEW.to_uom));

  -- Resolve from_uom: alias first, then direct canonical match.
  select uom_code into from_canon from hub.uom_aliases
    where alias_norm = norm_from;
  if from_canon is null then
    select uom_code into from_canon from hub.uom_canonical
      where uom_code = norm_from;
  end if;

  -- Resolve to_uom.
  select uom_code into to_canon from hub.uom_aliases
    where alias_norm = norm_to;
  if to_canon is null then
    select uom_code into to_canon from hub.uom_canonical
      where uom_code = norm_to;
  end if;

  -- Either side unknown => leave false (defensive default; staff
  -- edits the override or extends uom_aliases later).
  if from_canon is null or to_canon is null then
    NEW.is_cross_family := false;
    return NEW;
  end if;

  select family into from_fam from hub.uom_canonical where uom_code = from_canon;
  select family into to_fam from hub.uom_canonical where uom_code = to_canon;

  NEW.is_cross_family := (from_fam is distinct from to_fam);
  return NEW;
end;
$$ language plpgsql;

comment on function hub.compute_uom_override_is_cross_family is
  'Auto-compute is_cross_family from from_uom + to_uom canonical '
  'family (mig 055). Same family => false; different family => true; '
  'unknown alias on either side => false (staff fixes via uom_aliases).';

drop trigger if exists trg_uom_override_compute_xfamily
  on hub.client_uom_overrides;
create trigger trg_uom_override_compute_xfamily
  before insert or update of from_uom, to_uom
  on hub.client_uom_overrides
  for each row execute function hub.compute_uom_override_is_cross_family();

-- Backfill existing rows. mig 021 shipped 0 rows in client_uom_overrides
-- in fresh installs; this is safety for any environments that already
-- accumulated overrides via staff_form. Trigger fires on UPDATE OF
-- from_uom; the no-op self-update is the cleanest way to invoke it.
update hub.client_uom_overrides set from_uom = from_uom;
