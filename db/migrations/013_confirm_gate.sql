-- 013: BCCT confirm-on-update gate (Phase 1+2) + audit log via trigger.
--
-- See .ai/features/2026-05-04-bcct-overhaul-and-llm-parsing.md (Stage C1).
-- User requirement: any UPDATE on existing BCCT rows must require staff
-- confirm; default reject. Plus audit log of every change.
--
-- Audit trigger reads `current_setting('app.user_id', true)` for changed_by.
-- App contract: every connection used for write paths calls
--    SET LOCAL app.user_id = '<user_id>'
-- at txn start (see app/database.py:connect(user_id=...)). When unset,
-- the trigger writes 'system' as a sentinel.

-- ────────────────────────────────────────────────────────────────────────
-- Pending uploads — parsed rows + diff summary held here between the
-- pre-flight diff page and the staff-confirm page. TTL 24h.
-- ────────────────────────────────────────────────────────────────────────
create table if not exists hub.upload_pending (
  pending_id text primary key,
  client_id text not null references hub.clients(client_id) on delete cascade,
  module text not null check (module in ('bcct','catalog','bqd','bom')),
  upload_id text references hub.file_uploads(upload_id) on delete cascade,
  parsed_rows jsonb not null,           -- list of parsed row dicts
  diff_summary jsonb not null default '{}'::jsonb,  -- {new: N, diff: [...], orphan: [...]}
  created_by text references hub.users(user_id) on delete set null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '24 hours')
);

create index if not exists idx_upload_pending_expires
  on hub.upload_pending(expires_at);

-- ────────────────────────────────────────────────────────────────────────
-- BCCT row history. Append-only audit log fed by AFTER UPDATE/DELETE
-- trigger. Inserts not tracked (whole row is recoverable from upload_id).
-- ────────────────────────────────────────────────────────────────────────
create table if not exists hub.bcct_row_history (
  history_id bigserial primary key,
  client_id text not null,
  year integer not null,
  transaction_key text not null,
  line_no text not null,
  action text not null check (action in ('update','delete')),
  old_row jsonb not null,
  new_row jsonb,                        -- null on delete
  changed_by text not null default 'system',
  changed_at timestamptz not null default now(),
  upload_id text                        -- if change came via an upload, snapshot it
);

create index if not exists idx_bcct_row_history_pk
  on hub.bcct_row_history(client_id, transaction_key, line_no, changed_at desc);

-- ────────────────────────────────────────────────────────────────────────
-- Trigger: capture every UPDATE / DELETE on hub.bcct_rows.
-- Uses current_setting('app.user_id', true) to identify the actor; when
-- unset (e.g. ad-hoc psql session) writes the sentinel 'system'.
-- ────────────────────────────────────────────────────────────────────────
create or replace function hub.bcct_row_history_trigger()
  returns trigger
  language plpgsql
  as $$
declare
  actor text;
  old_jsonb jsonb;
  new_jsonb jsonb;
begin
  actor := coalesce(nullif(current_setting('app.user_id', true), ''), 'system');
  old_jsonb := to_jsonb(old);
  if (tg_op = 'UPDATE') then
    new_jsonb := to_jsonb(new);
    -- Skip if no fields actually changed (ON CONFLICT DO UPDATE on identical
    -- data fires UPDATE; not worth auditing).
    if old_jsonb = new_jsonb then
      return null;
    end if;
    insert into hub.bcct_row_history
      (client_id, year, transaction_key, line_no, action, old_row, new_row,
       changed_by, upload_id)
    values
      (old.client_id, old.year, old.transaction_key, old.line_no,
       'update', old_jsonb, new_jsonb, actor, new.upload_id);
  elsif (tg_op = 'DELETE') then
    insert into hub.bcct_row_history
      (client_id, year, transaction_key, line_no, action, old_row, new_row,
       changed_by, upload_id)
    values
      (old.client_id, old.year, old.transaction_key, old.line_no,
       'delete', old_jsonb, null, actor, old.upload_id);
  end if;
  return null;
end;
$$;

drop trigger if exists trg_bcct_row_history on hub.bcct_rows;
create trigger trg_bcct_row_history
  after update or delete on hub.bcct_rows
  for each row execute function hub.bcct_row_history_trigger();

-- ────────────────────────────────────────────────────────────────────────
-- Helper SQL function for cron-style purge of expired pending uploads.
-- Cron itself is application-side (lifespan loop or systemd timer); the
-- function makes it a one-liner from the caller.
-- ────────────────────────────────────────────────────────────────────────
create or replace function hub.purge_expired_pending_uploads()
  returns integer
  language sql
  as $$
    with deleted as (
      delete from hub.upload_pending where expires_at < now()
      returning pending_id
    )
    select count(*)::integer from deleted;
  $$;
