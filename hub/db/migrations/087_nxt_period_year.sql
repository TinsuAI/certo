-- 087_nxt_period_year.sql
-- The NXT settlement period is annual (kỳ quyết toán theo năm). Make the year a
-- first-class, required key instead of an arbitrary period_to date: artifacts
-- are now keyed and superseded by (client_id, period_year), and the upload flow
-- requires a year for every new artifact.
--
-- Additive + backfill. The column stays nullable at the DB level so the
-- migration is deploy-safe on any legacy row that has no period at all; the
-- application layer enforces "required" on every new upload, and the store
-- derives period_year from period_to when a caller omits it.
alter table hub.nxt_artifacts add column if not exists period_year smallint;

update hub.nxt_artifacts
   set period_year = extract(year from period_to)::smallint
 where period_year is null and period_to is not null;

create index if not exists idx_nxt_artifacts_client_year
    on hub.nxt_artifacts (client_id, period_year)
    where superseded_by is null;
