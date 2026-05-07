-- 033_v_material_roles.sql
--
-- Catalog roles refactor (multi-role first-class).
-- Brief: .ai/features/2026-05-07-catalog-roles-refactor/brief.md (rev 5)
--
-- Derives observed-role signals from data graph (BCCT direction patterns +
-- BOM membership). The view is plain (not materialized) — recomputed each
-- query. Perf measured at ~100-150ms per client on Growatt+Johnson scale,
-- well under the 500ms escalation threshold.
--
-- Atomic signals (booleans):
--   has_imports         — appears in BCCT direction='import'
--   has_exports         — appears in BCCT direction='export'
--   is_consumed_in_bom  — appears as child_code in alive bom_edges
--   has_own_bom         — owns ≥1 alive bom_artifact (META-signal, NOT a role)
--
-- Derivation rules (D4 rev 3):
--   'tp'      ⟸ has_exports
--   'btp_sx'  ⟸ is_consumed_in_bom AND has_own_bom
--   'nvl'     ⟸ has_imports AND is_consumed_in_bom AND NOT has_own_bom
--
-- Conflict detection (D8):
--   declared_observed_conflict =
--     len(observed_roles) > 0
--     AND declared IN {tp,btp_sx,nvl,ccdc}
--     AND (declared = 'ccdc' OR declared NOT IN observed_roles)
--
-- Notes:
-- - is_consumed_in_bom JOINs bom_artifacts to filter tombstoned. Edges
--   of tombstoned artifacts are logically gone.
-- - has_own_bom uses materials.customs_code as the canonical key (matches
--   how bom_artifacts.product_code is keyed in this codebase).
-- - Aggregate-LEFT-JOIN form (vs correlated EXISTS) chosen after measuring
--   1.09s vs 144ms — planner pushes the per-client WHERE filter into CTEs
--   so view-form preserves the speedup.

begin;

create or replace view hub.v_material_roles as
with bcct_signals as (
  select client_id,
         customs_code,
         bool_or(direction = 'import') as has_imports,
         bool_or(direction = 'export') as has_exports
  from hub.bcct_rows
  where customs_code is not null
  group by client_id, customs_code
),
bom_consumed as (
  select a.client_id,
         e.child_code as customs_code
  from hub.bom_edges e
  join hub.bom_artifacts a on a.artifact_id = e.artifact_id
  where a.tombstoned_at is null
  group by a.client_id, e.child_code
),
bom_owned as (
  select client_id,
         product_code as customs_code
  from hub.bom_artifacts
  where tombstoned_at is null
  group by client_id, product_code
),
atoms as (
  select m.client_id,
         m.customs_code,
         coalesce(m.category_override, m.category) as declared_kind,
         coalesce(bs.has_imports, false) as has_imports,
         coalesce(bs.has_exports, false) as has_exports,
         (bc.customs_code is not null) as is_consumed_in_bom,
         (bo.customs_code is not null) as has_own_bom
  from hub.materials m
  left join bcct_signals bs on bs.client_id = m.client_id and bs.customs_code = m.customs_code
  left join bom_consumed bc on bc.client_id = m.client_id and bc.customs_code = m.customs_code
  left join bom_owned bo on bo.client_id = m.client_id and bo.customs_code = m.customs_code
)
select a.client_id,
       a.customs_code,
       a.declared_kind,
       a.has_imports,
       a.has_exports,
       a.is_consumed_in_bom,
       a.has_own_bom,
       -- observed_roles[] per D4 rules.
       array_remove(array[
         case when a.has_exports then 'tp' end,
         case when a.is_consumed_in_bom and a.has_own_bom then 'btp_sx' end,
         case when a.has_imports and a.is_consumed_in_bom and not a.has_own_bom then 'nvl' end
       ], null) as observed_roles,
       -- is_multi_role per D7: ≥2 observed roles.
       (
         (case when a.has_exports then 1 else 0 end)
         + (case when a.is_consumed_in_bom and a.has_own_bom then 1 else 0 end)
         + (case when a.has_imports and a.is_consumed_in_bom and not a.has_own_bom then 1 else 0 end)
       ) >= 2 as is_multi_role,
       -- declared_observed_conflict per D8 (rev 4 simplified).
       (
         (case when a.has_exports then 1 else 0 end)
         + (case when a.is_consumed_in_bom and a.has_own_bom then 1 else 0 end)
         + (case when a.has_imports and a.is_consumed_in_bom and not a.has_own_bom then 1 else 0 end)
       ) > 0
       and a.declared_kind in ('tp','btp_sx','nvl','ccdc')
       and (
         a.declared_kind = 'ccdc'
         or not (
           (a.has_exports and a.declared_kind = 'tp')
           or (a.is_consumed_in_bom and a.has_own_bom and a.declared_kind = 'btp_sx')
           or (a.has_imports and a.is_consumed_in_bom and not a.has_own_bom and a.declared_kind = 'nvl')
         )
       ) as declared_observed_conflict
from atoms a;

comment on view hub.v_material_roles is
  'Per (client_id, customs_code): atomic data-graph signals + derived '
  'observed_roles[] + is_multi_role + declared_observed_conflict. Plain view '
  '— recomputed each query (realtime). Brief: '
  '.ai/features/2026-05-07-catalog-roles-refactor/brief.md (rev 5).';

commit;
