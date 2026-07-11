-- Derivation-schema stamp for the co_stock refresh dispatch. A delta refresh
-- only rewrites rows whose SOURCE BCCT data changed on Data Hub, so when a CO
-- release adds new derived payload fields (e.g. consignee_name/origin_country
-- for VN-origin, ticket #6) the existing snapshot rows never gain them through
-- the UI "Refresh tồn" button. The dispatch compares this stored stamp against
-- the code's DERIVATION_SCHEMA_VERSION and forces one full re-derivation on
-- mismatch. Default 0 = pre-stamp snapshot -> first refresh after deploy goes
-- full and backfills.
alter table co_stock_refresh_state
  add column if not exists derivation_schema_version integer not null default 0;
