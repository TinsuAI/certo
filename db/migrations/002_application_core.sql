create table if not exists clients (
  id text primary key,
  name text not null,
  code text not null default '',
  status text not null default '',
  tax_code text not null default '',
  contact text not null default '',
  module_status jsonb not null default '{}'::jsonb,
  bom_source_profile jsonb not null default '{}'::jsonb,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists clients_status_idx
  on clients (status);

create table if not exists client_configs (
  client_id text primary key references clients(id) on delete cascade,
  config_version integer not null default 1,
  config_hash text not null default '',
  payload jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists client_configs_hash_idx
  on client_configs (client_id, config_hash);
