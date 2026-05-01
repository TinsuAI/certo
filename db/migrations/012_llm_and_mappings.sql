-- 012: LLM settings + parser-mapping cache + per-(date,client_id) usage budget.
--
-- See .ai/features/2026-05-04-bcct-overhaul-and-llm-parsing.md (Stage D).
-- Pattern mirrors ~/workspace/client/BCQT-System/app/settings_store.py:
-- single key-value table backed by `current_setting`-style read-through.

-- ────────────────────────────────────────────────────────────────────────
-- Admin-tunable global settings. Single-tenant trusted-admin model; LLM
-- API key lives here alongside endpoint config. Multi-tenant rewrite
-- needs a proper secrets store — out of MVP scope.
-- ────────────────────────────────────────────────────────────────────────
create table if not exists hub.app_settings (
  key text primary key,
  value text,
  updated_at timestamptz not null default now(),
  updated_by text references hub.users(user_id) on delete set null
);

-- Default LLM keys (empty values = feature disabled until admin fills them).
insert into hub.app_settings (key, value) values
  ('llm_base_url', ''),
  ('llm_model', ''),
  ('llm_api_key', ''),
  ('llm_temperature', '0.0'),
  ('llm_timeout_s', '30'),
  ('llm_max_retries', '2'),
  ('llm_max_calls_per_day_per_client', '50')
on conflict (key) do nothing;

-- ────────────────────────────────────────────────────────────────────────
-- Parser-mapping cache. Keyed by (client_id, module, file_signature).
-- file_signature includes client_id+module already (defence in depth) so
-- cross-client cache poisoning is impossible even if a malicious actor
-- crafted a colliding hash.
-- ────────────────────────────────────────────────────────────────────────
create table if not exists hub.parser_mappings (
  client_id text not null references hub.clients(client_id) on delete cascade,
  module text not null check (module in ('bcct', 'catalog', 'bqd', 'bom')),
  file_signature text not null,
  mapping jsonb not null,             -- {"Số TK": "declaration_no", ...}
  sample_headers jsonb not null,      -- the headers that produced this signature
  proposed_by text not null check (proposed_by in ('rigid', 'llm', 'manual')),
  confirmed_by text references hub.users(user_id) on delete set null,
  confirmed_at timestamptz,
  use_count integer not null default 0,
  last_used_at timestamptz,
  created_at timestamptz not null default now(),
  primary key (client_id, module, file_signature)
);

create index if not exists idx_parser_mappings_module
  on hub.parser_mappings(module, last_used_at desc);

-- ────────────────────────────────────────────────────────────────────────
-- Per-(date, client_id) usage budget for LLM calls. One rogue agency
-- shouldn't exhaust the global daily allowance.
-- ────────────────────────────────────────────────────────────────────────
create table if not exists hub.llm_usage (
  date date not null,
  client_id text not null references hub.clients(client_id) on delete cascade,
  call_count integer not null default 0,
  token_in_total bigint not null default 0,
  token_out_total bigint not null default 0,
  last_call_at timestamptz,
  primary key (date, client_id)
);
