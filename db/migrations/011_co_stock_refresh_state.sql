-- Per-client metadata for the materialized co_stock_rows snapshot. Records
-- the BCCT row count at refresh time so the /co-stock page can detect when
-- the snapshot is stale relative to current Data Hub state.
--
-- Data Hub source_summary does not expose a BCCT version/hash today, so the
-- comparator is published_row_count (heuristic but cheap). When Data Hub
-- adds a version signal we can extend this row.

create table if not exists co_stock_refresh_state (
  client_id text primary key,
  snapshot_row_count integer not null default 0,
  bcct_row_count_at_refresh integer not null default 0,
  bcct_indexed_at_at_refresh timestamptz,
  refreshed_at timestamptz not null default now()
);
