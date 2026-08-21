-- 043_catalog_derive_configs.sql
--
-- Brief: .ai/features/2026-05-08-catalog-multi-source/brief.md (rev 4)
--
-- Phase 5 — backend for catalog-derive tool. Single table holds regex
-- + non-regex filter knobs per critic round 2 (avoid splitting across
-- `client_parser_rules` + a separate metadata table).
--
-- Use case: staff configure a rule once per client (e.g. "extract
-- agency NVL codes from BCCT goods_name parens, codes appearing ≥3
-- times in import rows"). Tool runs the rule, anti-joins materials,
-- previews missing codes, and bulk-adds them as `bcct_observed/under_review`.
--
-- ReDoS safety: same `google-re2` validator as `client_parser_rules`
-- (see brief D3). Pattern compile + reject backreferences at save time.

begin;

create table if not exists hub.catalog_derive_configs (
  config_id bigserial primary key,
  client_id text not null references hub.clients(client_id) on delete cascade,
  name text not null,
  source_table text not null
    check (source_table in ('bcct_rows', 'bom_edges')),
  -- Regex extraction
  pattern text not null,
  source_field text not null default 'goods_name',
  match_group int not null default 1,
  -- Non-regex filters
  direction_filter text[],   -- e.g. {'import'}; null = all directions
  min_observed_count int not null default 1,
  date_from date,
  date_to date,
  -- Defaults applied to derived materials rows
  default_status text not null default 'under_review'
    check (default_status in ('under_review','active')),
  default_category text
    check (default_category is null
           or default_category in ('nvl','tp','btp_sx','btp_nm','ccdc')),
  -- Workflow
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  created_by text not null,
  updated_at timestamptz not null default now(),
  updated_by text
);

create index if not exists idx_catalog_derive_configs_client
  on hub.catalog_derive_configs (client_id, enabled);

comment on table hub.catalog_derive_configs is
  'Per-client filter rules for the catalog-derive tool. Each config '
  'extracts codes from BCCT goods_name parens (or BOM edges) using a '
  're2 regex + non-regex filters, then bulk-adds missing codes to '
  'hub.materials with source=bcct_observed/bom_observed.';

commit;
