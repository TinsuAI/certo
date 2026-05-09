-- 042_catalog_material_code_rename_and_provenance.sql
--
-- Brief: .ai/features/2026-05-08-catalog-multi-source/brief.md (rev 4)
--
-- Phase 1 of catalog multi-source feature. This migration:
--
-- 1. RENAMES `materials.customs_code` → `materials.material_code` (PK).
--    Same for the audit table `material_audit_events.customs_code →
--    material_code`. The column in `materials` is mode-agnostic
--    primary code (HQ bucket OR DNCX client ERP code OR parser-extracted
--    code, depending on row source). Old name `customs_code` encoded
--    one accidental case as universal. Per user principle: semantic
--    correctness > touch-site convenience (memory
--    `feedback_naming_discipline.md`).
--
--    KEEPS unchanged:
--    - `bcct_rows.customs_code` — what's filed on customs declaration line
--    - `code_mappings.customs_code` — HQ-side code in NB↔HQ translation
--      table (paired with `code_mappings.internal_code`)
--    Both names accurate in their respective contexts.
--
-- 2. DROPS `materials.internal_code` — vestigial (100% = customs_code in
--    current data: 451/451 Growatt + 11129/11129 Johnson).
--
-- 3. ADDS provenance + state + manual columns on `materials`:
--    - `source` enum: client_declared / bcct_observed / bom_observed / system
--      Note: `client_declared` (NOT `agency_declared`). "agency" =
--      customs broker; "client" = DNCX manufacturer per memory
--      `reference_terminology_client.md`.
--    - `status` enum: active / under_review / deprecated / tombstoned
--    - `hq_registered` boolean
--    - `promoted_to_declared_at` timestamptz
--    - `promoted_by` text
--
--    Deliberately NOT added (would violate source-data principle, memory
--    `feedback_no_derived_in_source.md`):
--    - observed_count / observed_first_at / observed_last_at /
--      observed_directions[] — these derive from `bcct_rows`. Live via
--      `v_material_roles` view extension below.
--    - roles[] (multi-role) — Phase 2.
--    - production_source / hq_registration_no / hq_registration_date /
--      supplier_hint / name_source / uom — Phase 2.
--
-- 4. BACKFILLS source enum from existing provenance jsonb:
--    - rows with `provenance ? 'seen_in_bcct'` → source='bcct_observed'
--    - rows with `provenance ? 'registered_with_hq'` → hq_registered=true
--    - all other rows stay `source='client_declared'` (default)
--
--    Then DROPS the `seen_in_bcct` jsonb key (its decl_count + dates
--    were stale and now live via view). Keeps `btp_inferred` (Phase 3
--    audit) + `registered_with_hq` detail (audit-only sub-keys
--    `first_seen` + `source_upload_id`).
--
-- 5. DROPS + RECREATES `v_material_roles` view with:
--    - material_code instead of customs_code (column rename propagation)
--    - new observation stat columns: observed_count, observed_first_at,
--      observed_last_at, observed_directions[] computed live from
--      bcct_rows aggregation
--    Verified 0 dependents on this view (pg_depend check), safe drop.
--
-- 6. RENAMES indexes for consistency.
--
-- This migration is atomic (single BEGIN/COMMIT). After it applies, app
-- code on the same release MUST also be updated (see brief Phase 3).
-- The mig itself only touches schema; downstream `materials.customs_code`
-- references in app/scripts/templates/tests will fail until refactor lands.
--
-- Idempotent guards:
-- - Column rename: `if exists` check on old name to skip on re-run.
-- - Column drops: `if exists` check.
-- - Column adds: `if not exists`.
-- - View drop: `if exists`.

begin;

-- ── 1. Drop view that references columns we're about to rename ────────

drop view if exists hub.v_material_roles cascade;

-- ── 2. Rename PK column on materials ──────────────────────────────────

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema='hub' and table_name='materials' and column_name='customs_code'
  ) then
    alter table hub.materials rename column customs_code to material_code;
  end if;
end $$;

-- materials_pkey index stays — name doesn't encode column

-- ── 3. Rename audit table column ──────────────────────────────────────

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema='hub' and table_name='material_audit_events' and column_name='customs_code'
  ) then
    alter table hub.material_audit_events rename column customs_code to material_code;
  end if;
end $$;

-- idx_material_audit name doesn't encode column; no rename needed

-- ── 4. Drop vestigial internal_code column on materials ───────────────

drop index if exists hub.idx_materials_internal_code;

alter table hub.materials drop column if exists internal_code;

-- ── 5. Add provenance + state + manual columns ────────────────────────

alter table hub.materials
  add column if not exists source text not null default 'client_declared'
    check (source in ('client_declared','bcct_observed','bom_observed','system'));

-- materials.status existed pre-mig-042 with check ('active','inactive','tombstoned').
-- Drop old check + add new one accepting `under_review` + `deprecated`.
alter table hub.materials drop constraint if exists materials_status_check;
alter table hub.materials add constraint materials_status_check
  check (status in ('active','under_review','deprecated','tombstoned','inactive'));

alter table hub.materials
  add column if not exists hq_registered boolean;

alter table hub.materials
  add column if not exists promoted_to_declared_at timestamptz;

alter table hub.materials
  add column if not exists promoted_by text;

-- Indexes for new query patterns
create index if not exists idx_materials_source
  on hub.materials (client_id, source);
create index if not exists idx_materials_status
  on hub.materials (client_id, status) where status <> 'active';

-- ── 6. Backfill from existing provenance jsonb ────────────────────────

-- 6a. Codes seen in BCCT → source='bcct_observed' (provenance fact still
--     valid even though cached counts were stale; counts now live via view)
update hub.materials
   set source = 'bcct_observed'
 where provenance ? 'seen_in_bcct'
   and source = 'client_declared';

-- 6b. Codes registered with HQ → hq_registered=true (boolean column for
--     queries; audit detail keys stay in jsonb)
update hub.materials
   set hq_registered = true
 where provenance ? 'registered_with_hq';

-- 6c. Drop now-redundant jsonb key. Counts/dates were stale; observation
--     stats now derive live via v_material_roles. Keep btp_inferred +
--     registered_with_hq sub-keys for audit detail.
update hub.materials
   set provenance = provenance - 'seen_in_bcct'
 where provenance ? 'seen_in_bcct';

-- ── 7. Recreate v_material_roles with material_code + observation stats

-- View includes mig 034's relaxed NVL rule (`has_nvl_import`) — drop+create
-- inherits both mig 033 + 034 logic, then adds observation stats.
create view hub.v_material_roles as
with bcct_signals as (
  select client_id,
         customs_code as material_code,
         bool_or(direction = 'import') as has_imports,
         bool_or(direction = 'export') as has_exports,
         bool_or(
           direction = 'import'
           and declaration_type in ('E11','E15','E21','E23','E31','E33')
         ) as has_nvl_import,
         count(distinct declaration_no) as observed_count,
         min(registration_date) as observed_first_at,
         max(registration_date) as observed_last_at,
         array_agg(distinct direction)
           filter (where direction is not null)
           as observed_directions
  from hub.bcct_rows
  where customs_code is not null
  group by client_id, customs_code
),
bom_consumed as (
  select a.client_id,
         e.child_code as material_code
  from hub.bom_edges e
  join hub.bom_artifacts a on a.artifact_id = e.artifact_id
  where a.tombstoned_at is null
  group by a.client_id, e.child_code
),
bom_owned as (
  select client_id,
         product_code as material_code
  from hub.bom_artifacts
  where tombstoned_at is null
  group by client_id, product_code
),
atoms as (
  select m.client_id,
         m.material_code,
         coalesce(m.category_override, m.category) as declared_kind,
         coalesce(bs.has_imports, false) as has_imports,
         coalesce(bs.has_exports, false) as has_exports,
         coalesce(bs.has_nvl_import, false) as has_nvl_import,
         (bc.material_code is not null) as is_consumed_in_bom,
         (bo.material_code is not null) as has_own_bom,
         coalesce(bs.observed_count, 0) as observed_count,
         bs.observed_first_at,
         bs.observed_last_at,
         coalesce(bs.observed_directions, '{}'::text[]) as observed_directions
  from hub.materials m
  left join bcct_signals bs on bs.client_id = m.client_id and bs.material_code = m.material_code
  left join bom_consumed bc on bc.client_id = m.client_id and bc.material_code = m.material_code
  left join bom_owned bo on bo.client_id = m.client_id and bo.material_code = m.material_code
)
select a.client_id,
       a.material_code,
       a.declared_kind,
       a.has_imports,
       a.has_exports,
       a.has_nvl_import,
       a.is_consumed_in_bom,
       a.has_own_bom,
       -- observed_roles[] per mig 034 relaxed NVL rule.
       array_remove(array[
         case when a.has_exports then 'tp' end,
         case when a.is_consumed_in_bom and a.has_own_bom then 'btp_sx' end,
         case when a.has_nvl_import and not a.has_own_bom then 'nvl' end
       ], null) as observed_roles,
       (
         (case when a.has_exports then 1 else 0 end)
         + (case when a.is_consumed_in_bom and a.has_own_bom then 1 else 0 end)
         + (case when a.has_nvl_import and not a.has_own_bom then 1 else 0 end)
       ) >= 2 as is_multi_role,
       (
         (case when a.has_exports then 1 else 0 end)
         + (case when a.is_consumed_in_bom and a.has_own_bom then 1 else 0 end)
         + (case when a.has_nvl_import and not a.has_own_bom then 1 else 0 end)
       ) > 0
       and a.declared_kind in ('tp','btp_sx','nvl','ccdc')
       and (
         a.declared_kind = 'ccdc'
         or not (
           (a.has_exports and a.declared_kind = 'tp')
           or (a.is_consumed_in_bom and a.has_own_bom and a.declared_kind = 'btp_sx')
           or (a.has_nvl_import and not a.has_own_bom and a.declared_kind = 'nvl')
         )
       ) as declared_observed_conflict,
       -- Observation stats (derived live from bcct_rows; never stored, never stale)
       a.observed_count,
       a.observed_first_at,
       a.observed_last_at,
       a.observed_directions
from atoms a;

comment on view hub.v_material_roles is
  'Per (client_id, material_code): atomic data-graph signals + derived '
  'observed_roles[] + is_multi_role + declared_observed_conflict + live '
  'observation stats from bcct_rows. Plain view — recomputed each query '
  '(realtime). Brief: '
  '.ai/features/2026-05-08-catalog-multi-source/brief.md (rev 4); '
  'predecessor brief: 2026-05-07-catalog-roles-refactor/brief.md.';

commit;
