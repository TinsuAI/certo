-- 079_declarability_import_aware_and_rd07.sql
-- Fixes from the /rev of mig 078 (see .ai/features/2026-06-08-leaf-nvl-declarability/brief.md):
--
-- 1. CRITICAL — import-blind override. The rác classification marked a material
--    excluded_non_material whenever its Material Group is non-declarable, IGNORING
--    import evidence. For johnson that dropped 205 materials that have an HS code +
--    a BCCT import line (142 labels, 55 + 8 mislabeled "drawings"/"docs" that are
--    actually steel weight-plates/grips). Fix: a real import wins over the MG
--    heuristic — has_imports => declarable, always.
--
-- 2. IMPORTANT — RD07 is overloaded. It is the SAP "Set / Semi-Assy" grouping
--    (Packaging set, Pad set, Frame set, Screw set, ...), NOT "drawing". Mapping
--    it drawing/rác wrongly excluded ~753 real sets (vs 238 genuine drawings).
--    Remap RD07 -> assembly_set (declarable). Genuine drawings in RD07 then
--    surface as declarable_unmatched (kept + flagged for review), never silently
--    dropped. Reliable drawing auto-hide needs name-level classification and is
--    a follow-up (catalog_candidates lacks a name for ~704 of these codes).
--
-- Additive/idempotent: a map UPDATE + create-or-replace view.

-- 1. RD07: drawing -> assembly_set (declarable).
update hub.client_material_group_map
   set item_category = 'assembly_set',
       is_declarable = true,
       source = 'migration',
       notes = 'mig079: SAP Set/Semi-Assy grouping (NOT drawing). Drawings are '
               'name-level + mixed in; do not blanket-exclude or real sets drop.'
 where client_id = 'johnson-vn' and material_group = 'RD07';

-- 2. View: import evidence wins over the MG rác heuristic.
--    Order matters — the has_imports branch precedes the is_declarable=false
--    branch so an imported material in a rác MG resolves to 'declarable'.
create or replace view hub.v_material_classification as
select m.client_id,
       m.material_code,
       m.material_group,
       map.item_category,
       map.is_declarable,
       case
         when m.material_group is null then null
         when coalesce(vmr.has_imports, false) then 'declarable'
         when map.material_group is null then 'review'
         when map.is_declarable = false then 'excluded_non_material'
         else 'declarable_unmatched'
       end as customs_relevance
from hub.materials m
left join hub.client_material_group_map map
       on map.client_id = m.client_id
      and map.material_group = m.material_group
left join hub.v_material_roles vmr
       on vmr.client_id = m.client_id
      and vmr.material_code = m.material_code;
