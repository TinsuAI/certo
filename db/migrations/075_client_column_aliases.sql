-- 075_client_column_aliases.sql
-- Per-client column-alias overrides for the upload mapping flow (Phase 3
-- mapping overhaul). Resolution at match time: code-level ALIASES (parser
-- modules) with the ENABLED rows here layered on top. An empty table ⇒
-- behaviour identical to the code defaults, so this is purely additive.
create table if not exists hub.client_column_aliases (
    id          bigint generated always as identity primary key,
    client_id   text not null references hub.clients(client_id) on delete cascade,
    module      text not null check (module in ('bcct', 'catalog', 'bqd', 'bom')),
    field       text not null,
    alias       text not null,
    enabled     boolean not null default true,
    created_by  text,
    created_at  timestamptz not null default now(),
    unique (client_id, module, field, alias)
);

create index if not exists idx_client_column_aliases_lookup
    on hub.client_column_aliases (client_id, module)
    where enabled;
