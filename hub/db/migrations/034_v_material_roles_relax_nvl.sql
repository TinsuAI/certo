-- 034_v_material_roles_relax_nvl.sql
--
-- Relax 'nvl' rule per user feedback:
--   "Có nhập BCCT, có mã loại hình nhất định là có thể tự tin là NVL rồi."
--
-- Authority: QĐ 1357/QĐ-TCHQ (2021).
-- Reference: ~/workspace/client/BCQT-System/docs/knowledge/CUSTOMS_CODES.md
--
-- Old rule (mig 033, too strict):
--   'nvl' ⟸ has_imports AND is_consumed_in_bom AND NOT has_own_bom
--
-- New rule:
--   'nvl' ⟸ has_nvl_import AND NOT has_own_bom
--
-- where has_nvl_import = at least one BCCT row with direction='import'
--       AND declaration_type IN canonical NVL set:
--         E11 — Nhập NVL của DNCX từ nước ngoài
--         E15 — Nhập NVL của DNCX từ nội địa
--         E21 — Nhập NVL gia công cho NN
--         E23 — Nhập NVL gia công từ HĐ khác
--         E31 — Nhập NVL sản xuất xuất khẩu
--         E33 — Nhập NVL vào kho bảo thuế
--
-- Excluded from auto-NVL (require operator confirm):
--   E13: Nhập hàng hóa khác vào DNCX — mixed (NVL + máy móc + CCDC)
--   E41: Nhập SP thuê gia công NN — TP, not NVL
--   A-series: commercial / domestic SX — could be NVL or finished goods (per-client decision)
--   G-series: tạm nhập — temporary, will be re-exported
--   H/C: special cases (gift / bonded warehouse / non-tariff zone)
--
-- A new atomic signal `has_nvl_import` is added alongside the existing
-- `has_imports` boolean. Catalog UI continues to show `has_imports` for
-- the broad "↓ nhập" hint; the role-observation rule uses the narrower
-- NVL-canonical filter.

begin;

-- Postgres CREATE OR REPLACE VIEW cannot reorder/insert columns;
-- adding a new atomic signal `has_nvl_import` requires a full DROP+CREATE.
drop view if exists hub.v_material_roles;

create view hub.v_material_roles as
with bcct_signals as (
  select client_id,
         customs_code,
         bool_or(direction = 'import') as has_imports,
         bool_or(direction = 'export') as has_exports,
         bool_or(
           direction = 'import'
           and declaration_type in ('E11','E15','E21','E23','E31','E33')
         ) as has_nvl_import
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
         coalesce(bs.has_nvl_import, false) as has_nvl_import,
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
       a.has_nvl_import,
       a.is_consumed_in_bom,
       a.has_own_bom,
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
       ) as declared_observed_conflict
from atoms a;

commit;
