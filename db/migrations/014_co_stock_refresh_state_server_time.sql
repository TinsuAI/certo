-- Track Data Hub's high-water mark from the last successful BCCT pull so the
-- next refresh can use `GET /v1/hub/bcct?since=<ts>&include_tombstones=true`
-- to fetch only changed/removed rows.
--
-- See `.ai/api-requests/2026-05-28-bcct-incremental-since-filter.md` and the
-- Data Hub note `2026-05-28-bcct-incremental-since-available.md` for the
-- contract this column drives.

alter table co_stock_refresh_state
  add column if not exists last_bcct_server_time text not null default '';
