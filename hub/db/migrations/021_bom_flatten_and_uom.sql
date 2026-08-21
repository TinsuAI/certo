-- 021_bom_flatten_and_uom.sql
-- Technical BOM flattening: structured version identity + UOM model + staff
-- decisions + non-flattened evidence. See:
--   ~/.claude/plans/hazy-cooking-parnas.md
--   .ai/features/2026-05-03-bom-flattening.md
--   ~/workspace/client/barry-CO-main/.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md
--
-- Additive only. Existing manual_flat versions backfill with
-- flatten_status='not_applicable' so the hardened /latest filter
-- continues to serve them without regression.

-- ────────────────────────────────────────────────────────────────────────
-- 1. Extend hub.bom_versions with structured identity / flatten metadata
-- ────────────────────────────────────────────────────────────────────────

alter table hub.bom_versions
  add column if not exists source_bom_kind text,
  add column if not exists flatten_status text,
  add column if not exists flatten_strategy text,
  add column if not exists source_channel text,
  add column if not exists bom_code text,
  add column if not exists bom_variant_id text,
  add column if not exists lineage jsonb not null default '{}'::jsonb,
  add column if not exists display_label text,
  add column if not exists flatten_method text,
  add column if not exists flatten_method_version text;

-- Backfill existing rows BEFORE adding NOT NULL / CHECK constraints.
-- Every existing version came from agency Excel via manual_flat-style
-- ingestion before this migration; tag accordingly. Idempotent via
-- where-clauses keyed on null.
update hub.bom_versions
set source_bom_kind = 'manual_flat'
where source_bom_kind is null;
update hub.bom_versions
set flatten_status = 'not_applicable'
where flatten_status is null;
update hub.bom_versions
set flatten_strategy = 'manual_flat_as_provided'
where flatten_strategy is null;
update hub.bom_versions
set source_channel = 'agency_upload'
where source_channel is null;
update hub.bom_versions
set bom_variant_id = 'default'
where bom_variant_id is null;
update hub.bom_versions
set flatten_method = 'none'
where flatten_method is null;
update hub.bom_versions
set flatten_method_version = '0'
where flatten_method_version is null;
-- Display label derived from structured fields; stored as a
-- denormalized cache only (NEVER used as a DB key — spec §3A).
update hub.bom_versions
set display_label = product_code
                    || ' · ' || coalesce(bom_variant_id, 'default')
                    || ' · v' || version_no::text
                    || ' · ' || source_bom_kind
                    || ' · ' || flatten_status
                    || ' · ' || flatten_strategy
where display_label is null;

-- Now lock down the enums + nullability.
alter table hub.bom_versions
  alter column source_bom_kind   set not null,
  alter column flatten_status    set not null,
  alter column flatten_strategy  set not null,
  alter column source_channel    set not null,
  alter column flatten_method    set not null,
  alter column flatten_method_version set not null;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'chk_source_bom_kind') then
    alter table hub.bom_versions add constraint chk_source_bom_kind
      check (source_bom_kind in (
        'manual_flat','technical_raw','technical_flattened',
        'technical_non_flattened','co_modified','staff_edit'
      ));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'chk_flatten_status') then
    alter table hub.bom_versions add constraint chk_flatten_status
      check (flatten_status in ('flattened','non_flattened','not_applicable'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'chk_flatten_strategy') then
    alter table hub.bom_versions add constraint chk_flatten_strategy
      check (flatten_strategy in (
        'manual_flat_as_provided','technical_exploded',
        'purchased_btp_as_leaf','self_produced_btp_exploded',
        'mixed_confirmed','no_strategy'
      ));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'chk_source_channel') then
    alter table hub.bom_versions add constraint chk_source_channel
      check (source_channel in (
        'agency_upload','staff_form','co_proposal','migration','seed'
      ));
  end if;
end$$;

-- Indexes keyed on the new fields. Generic latest-by-product is unsafe
-- without a flatten_status filter (spec §3A); this index supports the
-- safe variant.
create index if not exists idx_bom_versions_flat_status
  on hub.bom_versions(client_id, product_code, flatten_status)
  where tombstoned_at is null;
create index if not exists idx_bom_versions_variant
  on hub.bom_versions(client_id, product_code, bom_variant_id, flatten_strategy, version_no desc)
  where tombstoned_at is null;

-- (Idempotency constraint update moved to migration 022 — this migration
--  was already applied in dev when the constraint problem was noticed.)

-- ────────────────────────────────────────────────────────────────────────
-- 2. hub.bom_unresolved_nodes — preserve non_flattened evidence per row
-- ────────────────────────────────────────────────────────────────────────
create table if not exists hub.bom_unresolved_nodes (
  version_id   text not null references hub.bom_versions(version_id) on delete cascade,
  node_path    text not null,           -- e.g. 'TP-A>BTP-B>X'
  material_code text not null,
  reason       text not null,
  evidence     jsonb not null default '{}'::jsonb,
  primary key (version_id, node_path),
  constraint chk_unresolved_reason check (reason in (
    'uom_conversion_missing','uom_conversion_ambiguous','missing_child_bom',
    'cycle_detected','ambiguous_dual_source','classification_unknown',
    'canonical_uom_missing'
  ))
);
create index if not exists idx_bom_unresolved_material
  on hub.bom_unresolved_nodes(material_code);

-- ────────────────────────────────────────────────────────────────────────
-- 3. hub.bom_flatten_decisions — staff-confirm gates persisted as audit.
--    Created during preview (status='pending'), updated at confirm
--    (status='confirmed'/'rejected'), then linked to the materialized
--    version. Rows whose decision can be made automatically by the
--    flattener (alias-only UOM, catalog-clear leaf, etc.) get
--    status='auto' from the start.
-- ────────────────────────────────────────────────────────────────────────
create table if not exists hub.bom_flatten_decisions (
  decision_id text primary key,
  pending_id  text,                     -- null after materialization
  client_id   text not null references hub.clients(client_id) on delete cascade,
  product_code text not null,
  decision_type text not null,
  chosen_action text,
  alternatives jsonb not null default '[]'::jsonb,
  evidence    jsonb not null default '{}'::jsonb,
  status      text not null default 'pending',
  staff_confirmation_required boolean not null default true,
  confirmed_by text references hub.users(user_id) on delete set null,
  confirmed_at timestamptz,
  materialized_version_id text references hub.bom_versions(version_id) on delete set null,
  created_at  timestamptz not null default now(),
  constraint chk_decision_type check (decision_type in (
    'dual_source_variant','non_flattened_publish','bcct_import_vs_child_bom',
    'use_db_btp_no_same_upload','choose_btp_variant','non_alias_uom_conversion',
    'global_uom_conversion','catalog_canonical_uom_missing',
    'generic_bcct_evidence','material_change_significant','duplicate_source_rows'
  )),
  constraint chk_decision_status check (status in (
    'pending','confirmed','rejected','auto'
  ))
);
create index if not exists idx_decisions_pending
  on hub.bom_flatten_decisions(pending_id) where pending_id is not null;
create index if not exists idx_decisions_materialized
  on hub.bom_flatten_decisions(materialized_version_id)
  where materialized_version_id is not null;

-- ────────────────────────────────────────────────────────────────────────
-- 4. UOM model — canonical units + aliases + per-client overrides.
--    No prior model exists in hub; this is greenfield. UOM lookup
--    precedence (spec §9):
--      1. client_uom_overrides(client_id, material_code, from, to) exact
--      2. client_uom_overrides(client_id, NULL,          from, to)
--      3. uom_canonical family-based factor
--      4. alias normalization → same canonical → factor 1.0
--      5. unresolved → reason='uom_conversion_missing'
--    Multiple step-3 matches with the same precedence → 'uom_conversion_ambiguous'.
-- ────────────────────────────────────────────────────────────────────────
create table if not exists hub.uom_canonical (
  uom_code     text primary key,
  family       text not null,
  base_factor  numeric(20,9) not null
);

create table if not exists hub.uom_aliases (
  alias_norm  text primary key,         -- lowercased + stripped + NFC
  uom_code    text not null references hub.uom_canonical(uom_code) on delete cascade
);

-- Per-client + optional per-material conversion override.
-- material_code is nullable: NULL row applies to every material for that client.
-- material_code_key is a generated stored column so NULL participates in PK
-- as the empty string (PostgreSQL forbids function calls inside PK clauses).
create table if not exists hub.client_uom_overrides (
  client_id     text not null references hub.clients(client_id) on delete cascade,
  material_code text,
  material_code_key text generated always as (coalesce(material_code, '')) stored,
  from_uom      text not null,
  to_uom        text not null,
  factor        numeric(20,9) not null,
  source        text not null default 'staff_form',
  created_at    timestamptz not null default now(),
  primary key (client_id, material_code_key, from_uom, to_uom),
  constraint chk_uom_override_source check (source in (
    'staff_form','migration','seed','co_proposal'
  ))
);

-- Seed common units. Families: mass / length / volume / count / area /
-- volume3 / assembly. Aliases include Vietnamese / English / SAP variants.
insert into hub.uom_canonical (uom_code, family, base_factor) values
  ('kg', 'mass', 1.0),
  ('g',  'mass', 0.001),
  ('mg', 'mass', 0.000001),
  ('t',  'mass', 1000.0),
  ('m',  'length', 1.0),
  ('cm', 'length', 0.01),
  ('mm', 'length', 0.001),
  ('km', 'length', 1000.0),
  ('l',  'volume', 1.0),
  ('ml', 'volume', 0.001),
  ('m2', 'area', 1.0),
  ('cm2','area', 0.0001),
  ('m3', 'volume3', 1.0),
  ('cm3','volume3', 0.000001),
  ('pcs','count', 1.0),
  ('set','assembly', 1.0)
on conflict (uom_code) do nothing;

insert into hub.uom_aliases (alias_norm, uom_code) values
  -- mass
  ('kg', 'kg'), ('kgs', 'kg'), ('kilogram', 'kg'), ('kilograms', 'kg'),
  ('gam', 'g'), ('g', 'g'), ('gram', 'g'), ('grams', 'g'), ('gr', 'g'),
  ('mg', 'mg'), ('milligram', 'mg'),
  ('t', 't'), ('ton', 't'), ('tonne', 't'), ('tấn', 't'),
  -- length
  ('m', 'm'), ('met', 'm'), ('meter', 'm'), ('metre', 'm'), ('mét', 'm'),
  ('cm', 'cm'), ('centimet', 'cm'), ('centimeter', 'cm'),
  ('mm', 'mm'), ('milimet', 'mm'), ('millimeter', 'mm'),
  ('km', 'km'), ('kilomet', 'km'), ('kilometer', 'km'),
  -- volume
  ('l', 'l'), ('lít', 'l'), ('lit', 'l'), ('liter', 'l'), ('litre', 'l'),
  ('ml', 'ml'), ('mililit', 'ml'), ('milliliter', 'ml'), ('millilitre', 'ml'),
  -- area
  ('m2', 'm2'), ('m²', 'm2'), ('sqm', 'm2'), ('m^2', 'm2'),
  ('cm2', 'cm2'), ('cm²', 'cm2'), ('cm^2', 'cm2'),
  -- volume3
  ('m3', 'm3'), ('m³', 'm3'), ('m^3', 'm3'),
  ('cm3', 'cm3'), ('cm³', 'cm3'), ('cm^3', 'cm3'),
  -- count
  ('pcs', 'pcs'), ('pc', 'pcs'), ('piece', 'pcs'), ('pieces', 'pcs'),
  ('cái', 'pcs'), ('cai', 'pcs'), ('chiếc', 'pcs'), ('chiec', 'pcs'),
  ('ea', 'pcs'), ('each', 'pcs'), ('个', 'pcs'),
  -- assembly
  ('set', 'set'), ('bộ', 'set'), ('bo', 'set'), ('kit', 'set')
on conflict (alias_norm) do nothing;
