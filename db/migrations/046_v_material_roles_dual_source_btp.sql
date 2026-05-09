-- 046_v_material_roles_dual_source_btp.sql
--
-- Surface dual-source BTP pattern via observed_roles[].
--
-- User feedback 2026-05-09 (final design): code observed BOTH as
-- self-produced (has own BOM + consumed) AND purchased (imported)
-- should emit BOTH `btp_sx` AND `btp_nm` in observed_roles[].
-- Conclusion derived: is_multi_role=true → UI surfaces "Đa nguồn (BTP)"
-- badge automatically.
--
-- Rules added (additive — existing rules preserved):
--   'tp'     ⟸ has_exports                                          (existing)
--   'btp_sx' ⟸ is_consumed_in_bom AND has_own_bom                  (existing)
--   'btp_nm' ⟸ has_imports AND is_consumed_in_bom AND has_own_bom  (NEW)
--   'nvl'    ⟸ has_nvl_import AND NOT has_own_bom                   (existing)
--
-- The btp_nm rule fires alongside btp_sx (both require has_own_bom).
-- This is intentional — the dual-source pattern IS exactly when both
-- fire. Without has_own_bom, the import looks like NVL leaf (data graph
-- alone can't distinguish leaf-NVL from external-btp_nm; staff catalog
-- declared_kind disambiguates).
--
-- declared_observed_conflict in_list keeps ('tp','btp_sx','nvl','ccdc')
-- — `btp_nm` declared never conflicts (D8 last-row preserved).
--
-- Sourcing-confirmation conflict: derived in app code (catalog.py)
-- by comparing materials.btp_sourcing (staff confirm) vs observed
-- pattern in observed_roles[]. Surface as "Conflict" badge in catalog
-- list when staff confirms a sourcing that contradicts observation.

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
         coalesce(m.category_override, m.category) as declared_kind,
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
  'Brief: .ai/features/2026-05-08-catalog-multi-source/brief.md.';

commit;
