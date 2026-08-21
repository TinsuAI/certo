-- 4-role hierarchy + per-client ACL.
-- See .ai/features/2026-05-02-auth-rbac-acl.md

alter table hub.users drop constraint if exists users_role_check;
alter table hub.users add constraint users_role_check
  check (role in ('dev', 'admin', 'manager', 'staff'));

create unique index if not exists uq_users_single_dev
  on hub.users ((1)) where role = 'dev';

create table if not exists hub.user_managed_clients (
  user_id text not null references hub.users(user_id) on delete cascade,
  client_id text not null references hub.clients(client_id) on delete cascade,
  granted_by text not null references hub.users(user_id),
  granted_at timestamptz not null default now(),
  primary key (user_id, client_id)
);

create index if not exists idx_managed_clients_client on hub.user_managed_clients(client_id);

create table if not exists hub.user_client_access (
  user_id text not null references hub.users(user_id) on delete cascade,
  client_id text not null references hub.clients(client_id) on delete cascade,
  scope text not null check (scope in ('read', 'edit')),
  granted_by text not null references hub.users(user_id),
  granted_at timestamptz not null default now(),
  primary key (user_id, client_id)
);

create index if not exists idx_client_access_client on hub.user_client_access(client_id);

update hub.users set role = 'dev' where email = 'admin@data-hub.local' and role = 'admin';
