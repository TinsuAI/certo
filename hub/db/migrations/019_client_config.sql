-- 019_client_config.sql
-- Per-client master config (Hướng B from 2026-05-02 architectural discussion).
-- See .ai/features/2026-05-02-client-config-refactor-and-contract-versioning.md
--
-- Three new tables:
-- 1. hub.declaration_type_catalog — list of HQ declaration type codes.
--    Seeded from data/seeds/declaration_types.yaml on first install.
--    Editable / addable / disable-able via /admin/declaration-types.
-- 2. hub.client_type_presets — named profiles for DNCX activity types.
--    Seeded from data/seeds/client_type_presets.yaml. System presets
--    cannot be deleted (is_system=true), only edited or disabled.
-- 3. hub.client_config — per-client master config:
--    eligible/relevant declaration types + fiscal year start month +
--    versioning (config_version, config_hash) for sister-app cache
--    invalidation.
--
-- Seed data is loaded by app.seed_master_data on startup, NOT inline in
-- this migration. The migration is pure schema; seeding is idempotent
-- and only touches empty tables.

create table if not exists hub.declaration_type_catalog (
  code text primary key,
  direction text not null check (direction in ('import', 'export')),
  description text not null default '',
  notes text not null default '',
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_declaration_type_catalog_direction
  on hub.declaration_type_catalog(direction)
  where is_active = true;

create table if not exists hub.client_type_presets (
  preset_key text primary key,
  display_name text not null,
  default_eligible_import text[] not null default '{}',
  default_relevant_export text[] not null default '{}',
  is_system boolean not null default false,
  is_active boolean not null default true,
  notes text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists hub.client_config (
  client_id text primary key references hub.clients(client_id) on delete cascade,
  preset_key text references hub.client_type_presets(preset_key) on delete set null,
  eligible_import_declaration_types text[] not null default '{}',
  relevant_export_declaration_types text[] not null default '{}',
  fiscal_year_start_month smallint not null default 1
    check (fiscal_year_start_month between 1 and 12),
  config_version integer not null default 1,
  config_hash text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  updated_by text references hub.users(user_id) on delete set null
);

create index if not exists idx_client_config_preset
  on hub.client_config(preset_key);
