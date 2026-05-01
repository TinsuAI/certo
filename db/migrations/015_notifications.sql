-- 015_notifications.sql
-- In-app notifications. Surface async events + multi-step waiting work
-- (e.g. preview pending confirm, LLM mapping awaits review, catalog
-- alarm count crossed threshold) to specific users without making them
-- poll dashboards.
--
-- Per-user feed, scoped optionally to a client_id so that staff focused
-- on one DNCX don't see another's noise but still get system-wide alerts
-- (client_id IS NULL).
--
-- Lives in `hub` schema to inherit role grants. Postgres-flavored:
-- bigserial PK, tz-aware timestamps, partial index for the hot
-- 'unread by user' query.

create table if not exists hub.notifications (
  id bigserial primary key,
  user_id text not null references hub.users(user_id) on delete cascade,
  kind text not null,
  title text not null,
  body text,
  link_url text,
  status text not null default 'unread',
  client_id text references hub.clients(client_id) on delete cascade,
  related_kind text,
  related_id text,
  created_at timestamptz not null default now(),
  read_at timestamptz,
  constraint chk_notif_status check (status in ('unread','read'))
);

-- Hot path: bell endpoint reads "unread for this user, newest first".
-- Partial index keeps it small (read rows fall out of index as they age).
create index if not exists idx_notifications_user_unread
  on hub.notifications (user_id, created_at desc)
  where status = 'unread';

-- Full-list page: one query per user, all statuses.
create index if not exists idx_notifications_user_created
  on hub.notifications (user_id, created_at desc);
