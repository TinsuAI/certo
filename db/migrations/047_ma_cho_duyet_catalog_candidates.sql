-- 047_ma_cho_duyet_catalog_candidates.sql
--
-- Brief: .ai/features/2026-05-09-ma-cho-duyet/brief.md
--
-- Mã chờ duyệt — passive candidate feed. Replaces the catalog_derive
-- wizard (mig 043) with a state-machine table + auto-refresh from BCCT
-- + BOM + code_mappings.
--
-- This migration:
--
-- 1. DROPS hub.catalog_derive_configs (mig 043 wizard, throwaway test
--    data only — user pivoted post-shipping per BACKLOG entry).
--
-- 2. CREATES hub.catalog_candidates with state machine
--    (pending / accepted / rejected). Status sticky across refresh —
--    only observation stats rebuild from truth.
--
-- 3. ALTER hub.materials ADD code_kind enum + Phase 2 manual fields
--    (production_source, supplier_hint, uom). Backfill code_kind
--    pattern-aware via parser-rule-style regex + code_mappings lookup.
--    `roles[]` and `category` drop deferred to Phase 2 backlog.

begin;

-- 1. Drop the wizard table and its dependencies.
drop index if exists hub.idx_catalog_derive_configs_client;
drop table if exists hub.catalog_derive_configs;

-- 2. Create the candidates state-machine table.
create table if not exists hub.catalog_candidates (
  candidate_id   bigserial primary key,
  client_id      text not null
    references hub.clients(client_id) on delete cascade,
  code           text not null,
  code_kind      text not null
    check (code_kind in ('nb','hq','unified')),

  -- Live observation snapshot. Rebuilt on every refresh, not incremental.
  sources        text[] not null default '{}',
  observed_count int not null default 0,
  first_seen     date,
  last_seen      date,
  sample_text    text,
  suggested_category text,
  multi_direction boolean not null default false,

  -- State machine. Sticky across refresh.
  status text not null default 'pending'
    check (status in ('pending','accepted','rejected')),
  decided_at      timestamptz,
  decided_by      text,
  decision_reason text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists uq_catalog_candidates
  on hub.catalog_candidates (client_id, code, code_kind);

create index if not exists idx_catalog_candidates_client_status
  on hub.catalog_candidates (client_id, status, observed_count desc);

comment on table hub.catalog_candidates is
  'Mã chờ duyệt — passive candidate feed for catalog. Watches BCCT + '
  'BOM + code_mappings continuously. Status pending → accepted (insert '
  'materials + auto-mapping) | rejected. Refresh rebuilds observation '
  'stats from truth; status untouched.';

-- 3. Materials schema enrichment.
alter table hub.materials
  add column if not exists code_kind text not null default 'unified',
  add column if not exists production_source text,
  add column if not exists supplier_hint text,
  add column if not exists uom text;

-- Keep default 'unified' on materials.code_kind. Insert sites that need
-- 'nb' or 'hq' (e.g. accept_candidate flow) override explicitly. Default
-- protects existing app code paths that don't yet pass code_kind.

-- Add check constraints separately (idempotent if re-run).
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'materials_code_kind_check'
  ) then
    alter table hub.materials
      add constraint materials_code_kind_check
      check (code_kind in ('nb','hq','unified'));
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'materials_production_source_check'
  ) then
    alter table hub.materials
      add constraint materials_production_source_check
      check (production_source is null
             or production_source in ('nk','sx','mixed','unknown'));
  end if;
end$$;

-- Backfill code_kind pattern-aware. Existing materials may already mix
-- NB-style and HQ-bucket-style codes (verified on Growatt: 252 nb-pattern
-- + 129 hq-like + 70 fallback). Default 'unified' is correct for
-- single-system clients (no rules + no mappings).
with dual_clients as (
  select distinct client_id from hub.client_parser_rules
   where output_field = 'internal_code' and enabled
  union
  select distinct client_id from hub.code_mappings
)
update hub.materials m set code_kind = case
    -- (a) Match BQD's NB side → 'nb'
    when exists (select 1 from hub.code_mappings cm
                 where cm.client_id = m.client_id
                   and cm.internal_code = m.material_code) then 'nb'
    -- (b) Match BQD's HQ side → 'hq'
    when exists (select 1 from hub.code_mappings cm
                 where cm.client_id = m.client_id
                   and cm.customs_code = m.material_code) then 'hq'
    -- (c) Match parser-rule-style patterns (NB-paren style) → 'nb'
    when m.material_code ~ '^\d{3}\.[\w\-]+$'                  -- agency_nvl_paren
      or m.material_code ~ '^[A-Z]{2,}\d{2}\.[\w\-]+$'         -- agency_tp_paren
      or m.material_code ~ '^[A-Z]\d{3}\.[\w\-]+$'             -- agency_pcba_paren
      or m.material_code ~ '^\d{2}[A-Z]\.[\w\-]+$'             -- alpha_suffix_paren
      then 'nb'
    -- (d) Otherwise (dual-system but unmatched) → 'hq' (assume bucket)
    else 'hq'
  end
where m.client_id in (select client_id from dual_clients);

-- Single-system clients keep the default 'unified'. No update needed.

commit;
