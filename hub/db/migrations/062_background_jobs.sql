-- 062 — Background job tracking for long-running operations.
--
-- Operations like "phân tích AI vật tư" (re-embed catalog) and "tìm lại
-- gợi ý vật tư thay thế" (refresh substitutes) take 2-5 minutes per
-- client — too long for a synchronous HTTP request. Buttons spawn
-- subprocesses; this table lets staff see what's running, what
-- finished, and what failed without tailing /tmp logs.
--
-- One row per click. The wrapper `scripts/_job_runner.py` updates
-- status as the work proceeds.

create table hub.background_jobs (
    id              bigserial primary key,
    client_id       text references hub.clients(client_id) on delete cascade,
    kind            text not null check (kind in (
        'embedding_refresh',
        'substitute_refresh',
        'other'
    )),
    label           text not null,
    status          text not null check (status in (
        'pending', 'running', 'done', 'error', 'cancelled'
    )) default 'pending',
    started_at      timestamptz not null default now(),
    running_at      timestamptz,
    finished_at     timestamptz,
    pid             integer,
    log_path        text,
    summary         text,
    error_message   text,
    started_by      text
);

create index ix_jobs_client_recent
    on hub.background_jobs (client_id, started_at desc);
create index ix_jobs_running
    on hub.background_jobs (status)
    where status in ('pending', 'running');

comment on table hub.background_jobs is
  'Tracks long-running ops kicked off from the web UI (re-embed, '
  'refresh substitutes, etc). Wrapper script updates status; UI polls.';
