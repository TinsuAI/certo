-- CO-owned config fingerprint for the co_stock refresh dispatch (#14). A delta
-- refresh only rewrites rows whose SOURCE BCCT data changed on Data Hub, so a
-- change to a CO-owned config section (allocation_code strategy / regex /
-- fallback, or co_stock lot_policy) — which alters derivation but touches no
-- source row — never rewrites the existing snapshot. The dispatch compares this
-- stored fingerprint against co_config_fingerprint(current_config) and forces
-- one full re-derivation on mismatch. Default '' = pre-fingerprint snapshot ->
-- first refresh after deploy goes full and re-derives once (self-healing).
alter table co_stock_refresh_state
  add column if not exists co_config_fingerprint text not null default '';
