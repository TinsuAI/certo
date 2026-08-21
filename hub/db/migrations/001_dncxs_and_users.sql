-- Core identity tables: agency users + the DNCXs the agency manages.

create table if not exists hub.users (
  user_id text primary key,
  email text unique not null,
  display_name text not null,
  password_hash text not null,
  role text not null default 'staff',
  status text not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_users_email on hub.users(email);

create table if not exists hub.sessions (
  session_id text primary key,
  user_id text not null references hub.users(user_id) on delete cascade,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  last_seen_at timestamptz not null default now(),
  user_agent text,
  ip_address text
);

create index if not exists idx_sessions_user on hub.sessions(user_id);
create index if not exists idx_sessions_expires on hub.sessions(expires_at);

create table if not exists hub.dncxs (
  dncx_id text primary key,
  name text not null,
  tax_code text,
  code_resolution_mode text not null default 'simple_mapping',
  bom_proposal_mode text not null default 'auto',
  bom_proposal_qty_tolerance_pct numeric(6,3) not null default 5.0,
  status text not null default 'active',
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_dncxs_status on hub.dncxs(status);

-- Deployment-level config. Single row, key 'singleton'.
create table if not exists hub.deployment_config (
  config_key text primary key default 'singleton',
  agency_name text not null default 'Agency',
  bom_proposal_mode text not null default 'auto',
  bom_proposal_qty_tolerance_pct numeric(6,3) not null default 5.0,
  updated_at timestamptz not null default now()
);

insert into hub.deployment_config (config_key) values ('singleton')
on conflict do nothing;
