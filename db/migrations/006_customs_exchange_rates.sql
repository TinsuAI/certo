create table if not exists customs_exchange_rate_rows (
  client_id text not null default 'global',
  currency_code text not null,
  effective_date date not null,
  currency_name text not null default '',
  rate_vnd_per_unit numeric(18, 6) not null,
  rate_text text not null default '',
  source text not null default '',
  source_endpoint text not null default '',
  payload jsonb not null default '{}'::jsonb,
  fetched_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (client_id, currency_code, effective_date)
);

create index if not exists customs_exchange_rate_rows_effective_idx
  on customs_exchange_rate_rows (client_id, effective_date desc, currency_code);

create index if not exists customs_exchange_rate_rows_currency_idx
  on customs_exchange_rate_rows (client_id, currency_code, effective_date desc);

create table if not exists customs_exchange_rate_refreshes (
  refresh_id text primary key,
  client_id text not null default 'global',
  status text not null default '',
  source text not null default '',
  fetched_row_count integer not null default 0,
  upserted_row_count integer not null default 0,
  saved_row_count integer not null default 0,
  currency_count integer not null default 0,
  latest_effective_date date,
  error text not null default '',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists customs_exchange_rate_refreshes_client_created_idx
  on customs_exchange_rate_refreshes (client_id, created_at desc);
