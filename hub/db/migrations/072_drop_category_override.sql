-- 072 — Drop unused materials.category_override + override_reason.
--
-- Background: mig 002 (2026-05-01 scaffold) added these two columns
-- under a "patch instead of edit" design — parser writes category,
-- staff overlays an override + reason rather than editing. The UI
-- for setting overrides was never built (session
-- 2026-05-01-client-restructure-i18n-redesign.md to-do #11, dropped
-- on the floor). Three later mechanisms supplanted the original
-- intent:
--   - mig 045 materials_audit_trigger: captures category edits, so
--     "preserve original parser value for audit" is no longer the
--     override's job.
--   - A.3 catalog edit form: staff edits category directly.
--   - mig 033/046 v_material_roles: observed_roles[] surfaces
--     multi-role truth at the view level; declared remains single
--     by design (see [[project_bom_code_multirole]] revision).
--
-- Data audit 2026-05-28: 0/13,589 rows across Growatt + Johnson have
-- category_override or override_reason set. Dropping is dead-weight
-- removal, not a data migration. Closes BACKLOG A.1.
--
-- This mig:
--   1. Recreates hub.v_material_roles dropping coalesce(override, category).
--      declared_kind = m.category directly.
--   2. Drops both columns from hub.materials.

begin;

drop view if exists hub.v_material_roles cascade;

create view hub.v_material_roles as
with bcct_signals as (
  select client_id, customs_code as material_code,
         bool_or(direction = 'import') as has_imports,
         bool_or(direction = 'export') as has_exports,
         bool_or(direction = 'import' and declaration_type in ('E11','E15','E21','E23','E31','E33')) as has_nvl_import,
         count(distinct declaration_no) as observed_count,
         min(registration_date) as observed_first_at,
         max(registration_date) as observed_last_at,
         array_agg(distinct direction) filter (where direction is not null) as observed_directions
  from hub.bcct_rows where customs_code is not null
  group by client_id, customs_code
),
bom_consumed as (
  select a.client_id, e.child_code as material_code from hub.bom_edges e
  join hub.bom_artifacts a on a.artifact_id=e.artifact_id where a.tombstoned_at is null
  group by a.client_id, e.child_code
),
bom_owned as (
  select client_id, product_code as material_code from hub.bom_artifacts
  where tombstoned_at is null group by client_id, product_code
),
atoms as (
  select m.client_id, m.material_code,
         m.category as declared_kind,
         coalesce(bs.has_imports, false) as has_imports,
         coalesce(bs.has_exports, false) as has_exports,
         coalesce(bs.has_nvl_import, false) as has_nvl_import,
         (bc.material_code is not null) as is_consumed_in_bom,
         (bo.material_code is not null) as has_own_bom,
         coalesce(bs.observed_count, 0) as observed_count,
         bs.observed_first_at, bs.observed_last_at,
         coalesce(bs.observed_directions, '{}'::text[]) as observed_directions
  from hub.materials m
  left join bcct_signals bs on bs.client_id=m.client_id and bs.material_code=m.material_code
  left join bom_consumed bc on bc.client_id=m.client_id and bc.material_code=m.material_code
  left join bom_owned bo on bo.client_id=m.client_id and bo.material_code=m.material_code
)
select a.client_id, a.material_code, a.declared_kind,
       a.has_imports, a.has_exports, a.has_nvl_import,
       a.is_consumed_in_bom, a.has_own_bom,
       array_remove(array[
         case when a.has_exports then 'tp' end,
         case when a.is_consumed_in_bom and a.has_own_bom then 'btp_sx' end,
         case when a.has_imports and a.is_consumed_in_bom and a.has_own_bom then 'btp_nm' end,
         case when a.has_nvl_import and not a.has_own_bom then 'nvl' end
       ], null) as observed_roles,
       (
         (case when a.has_exports then 1 else 0 end)
         + (case when a.is_consumed_in_bom and a.has_own_bom then 1 else 0 end)
         + (case when a.has_imports and a.is_consumed_in_bom and a.has_own_bom then 1 else 0 end)
         + (case when a.has_nvl_import and not a.has_own_bom then 1 else 0 end)
       ) >= 2 as is_multi_role,
       (
         (case when a.has_exports then 1 else 0 end)
         + (case when a.is_consumed_in_bom and a.has_own_bom then 1 else 0 end)
         + (case when a.has_imports and a.is_consumed_in_bom and a.has_own_bom then 1 else 0 end)
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
       a.observed_count, a.observed_first_at, a.observed_last_at, a.observed_directions
from atoms a;

comment on view hub.v_material_roles is
  'Per (client_id, material_code): observed_roles[] (4 roles: tp, btp_sx, '
  'btp_nm, nvl — dual-source emerges as btp_sx+btp_nm both fire), '
  'is_multi_role, declared_observed_conflict, observation stats. '
  'declared_kind = materials.category (mig 072 dropped unused override).';

alter table hub.materials
  drop column if exists category_override,
  drop column if exists override_reason;

commit;
