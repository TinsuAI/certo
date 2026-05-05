-- 030_btp_sourcing_and_resolution_profiles.sql
--
-- Adds 3 things needed for the v3 resolver+profiles work:
--
-- 1. materials.btp_sourcing — per-BTP sourcing classification. Drives the
--    resolver "stop set" decision (purchased_only stops at the BTP;
--    self_produced_only must explode; dual_source allows both branches).
--    Nullable, with NULL = "not yet classified" (semantically 'unknown').
--    Population by scripts/detect_dual_source_btps.py per client.
--
-- 2. clients.auto_derive_shallow_from_raw — per-client policy gate for
--    Phase 2's auto-derive step. Default 'draft_only' so we never publish
--    a system-derived BOM as canonical without staff confirm.
--
-- 3. bom_resolution_profiles — Phase 4 table. Schema only here; CRUD
--    endpoints land in a later migration. Created now so Phase 3 resolver
--    can reference profile_id when it ships.
--
-- We deliberately do NOT add bom_shape as a column. The 3-shape concept
-- (raw_graph / shallow / full_flat) is a Python helper deriving from the
-- existing flatten_status + flatten_strategy values. Schema redundancy
-- avoided; 170 caller references untouched.

begin;

-- 1. materials.btp_sourcing -----------------------------------------

alter table hub.materials
  add column if not exists btp_sourcing text;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'chk_btp_sourcing') then
    alter table hub.materials add constraint chk_btp_sourcing
      check (btp_sourcing is null or btp_sourcing in (
        'purchased_only', 'self_produced_only', 'dual_source', 'unknown'
      ));
  end if;
end $$;

create index if not exists idx_materials_btp_sourcing
  on hub.materials(client_id, btp_sourcing)
  where btp_sourcing is not null;


-- 2. clients.auto_derive_shallow_from_raw ---------------------------

alter table hub.clients
  add column if not exists auto_derive_shallow_from_raw text
    not null default 'draft_only';

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'chk_auto_derive_shallow_from_raw') then
    alter table hub.clients add constraint chk_auto_derive_shallow_from_raw
      check (auto_derive_shallow_from_raw in ('disabled', 'draft_only', 'publish'));
  end if;
end $$;


-- 3. bom_resolution_profiles ----------------------------------------
-- A profile is a NAMED interpretation of a BOM under specific sourcing
-- choices. CO certificates and BCQT settlement reference (version_id,
-- profile_id) instead of cloning the version per case. See A1 from the
-- v3 design discussion.

create table if not exists hub.bom_resolution_profiles (
  profile_id        text primary key,
  client_id         text not null
                       references hub.clients(client_id) on delete cascade,
  product_code      text not null,
  bom_version_id    text not null
                       references hub.bom_versions(version_id) on delete restrict,
  name              text not null,
  sourcing_choices  jsonb not null default '{}'::jsonb,
  notes             text,
  created_by        text references hub.users(user_id) on delete set null,
  created_at        timestamptz not null default now(),
  tombstoned_at     timestamptz,
  tombstone_reason  text
);

-- Profile lookup: alive profiles per (client, product).
create index if not exists idx_bom_resolution_profiles_alive
  on hub.bom_resolution_profiles(client_id, product_code)
  where tombstoned_at is null;

-- Profile resolution requires version_id lookup quickly.
create index if not exists idx_bom_resolution_profiles_by_version
  on hub.bom_resolution_profiles(bom_version_id)
  where tombstoned_at is null;

-- Name uniqueness per (client, product) among live profiles. Tombstoned
-- profiles can collide so retract+rename is a valid operation.
create unique index if not exists uq_bom_resolution_profiles_name
  on hub.bom_resolution_profiles(client_id, product_code, name)
  where tombstoned_at is null;

-- on_delete restrict on bom_version_id is intentional: per the project's
-- BOM-immutability principle (memory: project_bom_immutable_principle.md),
-- a version a profile points at must never be physically deleted. To
-- retract a version, set tombstoned_at; profiles referencing it remain
-- queryable for historical certificate reproduction.

commit;
