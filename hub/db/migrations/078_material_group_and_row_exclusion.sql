-- 078_material_group_and_row_exclusion.sql
-- Re-ingest SAP Material Group (raw provenance) + per-row non-declarable
-- ("rác") exclusion for the BOM the CO sister-app consumes.
--
-- Why: johnson-vn BOM leaf-NVL collapsed to category='nvl' because the
-- SAP `Material Group` column (RD07 drawing / RD08 document / RD12 label /
-- RD06 packaging / RD21 steel / RD02 fastener / RD09 plastic / CO01
-- welding rod ...) was parsed then discarded at ingest. CO cannot tell a
-- drawing from an unmatched steel bar. See
-- .ai/features/2026-06-08-leaf-nvl-declarability/brief.md and
-- ~/.claude/plans/curried-churning-sloth.md.
--
-- Design (per project rules):
--   * `material_group` is RAW source data → stored on materials /
--     catalog_candidates / bom_artifact_rows.payload (OK to store).
--   * `item_category` / `customs_relevance` are DERIVED → a VIEW, never a
--     column on materials (feedback_no_derived_in_source). Not a generated
--     column: the derivation crosses tables.
--   * client-specific mapping lives in a DB table, not `if client_id==`
--     (feedback_client_specific_in_adapter).
--   * row-level exclusion is `excluded_at`/`exclusion_reason` — NOT
--     "tombstone" (that word is reserved for artifact-level retraction).
--     BOM stays immutable: rows are tagged, never deleted
--     (project_bom_immutable_principle).
--
-- Additive + idempotent only. No behavior change until the serve-side
-- filter (separate change) is switched on per-client.

-- ────────────────────────────────────────────────────────────────────────
-- 1. Raw material_group provenance.
-- ────────────────────────────────────────────────────────────────────────
alter table hub.materials
  add column if not exists material_group text;
create index if not exists idx_materials_material_group
  on hub.materials (client_id, material_group);

alter table hub.catalog_candidates
  add column if not exists material_group text;

-- ────────────────────────────────────────────────────────────────────────
-- 2. Per-row non-declarable ("rác") exclusion on bom_artifact_rows.
--    Row-level soft-exclude; distinct from artifact-level tombstone.
-- ────────────────────────────────────────────────────────────────────────
alter table hub.bom_artifact_rows
  add column if not exists excluded_at timestamptz;
alter table hub.bom_artifact_rows
  add column if not exists exclusion_reason text;
create index if not exists idx_bom_rows_excluded
  on hub.bom_artifact_rows (artifact_id)
  where excluded_at is not null;

-- ────────────────────────────────────────────────────────────────────────
-- 3. Per-client (material_group → item_category, declarability) map.
--    Detail-table precedent: client_uom_overrides (mig 021/055).
-- ────────────────────────────────────────────────────────────────────────
create table if not exists hub.client_material_group_map (
  client_id      text not null references hub.clients(client_id) on delete cascade,
  material_group text not null,
  item_category  text not null,    -- physical nature: drawing|document|label|
                                    -- packaging|metal|hardware|plastic|
                                    -- consumable|assembly_set|finished|other
  is_declarable  boolean not null, -- false => rác (drawing/document/label)
  source         text not null default 'seed'
                   check (source in ('seed','staff_form','migration','co_proposal','imported')),
  notes          text,
  created_at     timestamptz not null default now(),
  primary key (client_id, material_group)
);

-- 4. Seed johnson-vn — every distinct Material Group in the 106 SAP source
--    files (verified 0-conflict per code). rác = drawing/document/label.
--    Phantom-sets are excluded via the `phantom` flag (independent axis),
--    NOT via item_category, so assembly_set stays is_declarable=true.
--    Guarded by `where exists (… hub.clients …)`: a fresh DB (CI) applies
--    migrations before clients are seeded, so the seed is skipped there and
--    applies only on installs that already have johnson-vn (matches mig 036/037).
insert into hub.client_material_group_map
  (client_id, material_group, item_category, is_declarable, source, notes)
select v.client_id, v.material_group, v.item_category, v.is_declarable, v.source, v.notes
from (values
  ('johnson-vn','RD07','drawing',      false,'seed','rác: rendering/blueprint/diagram (leaves)'),
  ('johnson-vn','RD08','document',     false,'seed','rác: checklist/manual'),
  ('johnson-vn','RD12','label',        false,'seed','rác: EN/warning/barcode/serial label, decal'),
  ('johnson-vn','RD06','packaging',    true ,'seed','kept: carton/cardboard/pallet'),
  ('johnson-vn','RD16','metal',        true ,'seed','plate (CON/fixing/support)'),
  ('johnson-vn','RD15','metal',        true ,'seed','tube (connect/support/fixing)'),
  ('johnson-vn','RD27','metal',        true ,'seed','sleeve/rod/axle/shaft'),
  ('johnson-vn','RD21','metal',        true ,'seed','round steel/tube/iron plate/plastic raw'),
  ('johnson-vn','RD24','metal',        true ,'seed','steel rope/cable'),
  ('johnson-vn','RD36','metal',        true ,'seed','side rail'),
  ('johnson-vn','RD02','hardware',     true ,'seed','screw/washer/nut/bolt'),
  ('johnson-vn','SA99','hardware',     true ,'seed','washer'),
  ('johnson-vn','RD28','hardware',     true ,'seed','bearing'),
  ('johnson-vn','RD22','hardware',     true ,'seed','bushing'),
  ('johnson-vn','RD11','hardware',     true ,'seed','spring'),
  ('johnson-vn','RD30','hardware',     true ,'seed','weight plate/fixing base/stopper ring'),
  ('johnson-vn','RD09','plastic',      true ,'seed','foot pad/rubber sleeve/cover/raw material'),
  ('johnson-vn','RD10','plastic',      true ,'seed','back/head/seat/leg pad (foam)'),
  ('johnson-vn','RD04','plastic',      true ,'seed','membrane/cable tie/foam/air stick'),
  ('johnson-vn','CO01','consumable',   true ,'seed','welding rod'),
  ('johnson-vn','CO03','consumable',   true ,'seed','PE membrane'),
  ('johnson-vn','CO04','consumable',   true ,'seed','powder painting material'),
  ('johnson-vn','RD18','assembly_set', true ,'seed','tube/base/frame set (phantom parent)'),
  ('johnson-vn','RD19','assembly_set', true ,'seed','connecting-tube/base/frame set (phantom parent)'),
  ('johnson-vn','RD23','assembly_set', true ,'seed','hardware/adjustment/pull-pin set'),
  ('johnson-vn','RD05','assembly_set', true ,'seed','*-Extrawork sets (rework)'),
  ('johnson-vn','RD31','other',        true ,'seed','permanent magnet'),
  ('johnson-vn','RD03','finished',     true ,'seed','finished treadmill deck')
) as v(client_id, material_group, item_category, is_declarable, source, notes)
where exists (select 1 from hub.clients c where c.client_id = v.client_id)
on conflict (client_id, material_group) do nothing;

-- ────────────────────────────────────────────────────────────────────────
-- 5. Derivation view. item_category + customs_relevance are computed here,
--    never stored on materials. customs_relevance is a single
--    declarability axis; item_category carries physical nature.
--      material_group NULL          → customs_relevance NULL (not classified)
--      MG present, no map row        → 'review'  (gap; never silently rác)
--      map.is_declarable = false     → 'excluded_non_material'  (rác)
--      declarable + has BCCT import  → 'declarable'
--      declarable + no import        → 'declarable_unmatched'
-- ────────────────────────────────────────────────────────────────────────
create or replace view hub.v_material_classification as
select m.client_id,
       m.material_code,
       m.material_group,
       map.item_category,
       map.is_declarable,
       case
         when m.material_group is null then null
         when map.material_group is null then 'review'
         when map.is_declarable = false then 'excluded_non_material'
         when coalesce(vmr.has_imports, false) then 'declarable'
         else 'declarable_unmatched'
       end as customs_relevance
from hub.materials m
left join hub.client_material_group_map map
       on map.client_id = m.client_id
      and map.material_group = m.material_group
left join hub.v_material_roles vmr
       on vmr.client_id = m.client_id
      and vmr.material_code = m.material_code;
