-- 022_bom_idempotent_v2.sql
-- /rev follow-up to migration 021. The original uq_bom_idempotent
-- constraint (from migration 006) is row-content-only via normalized_hash;
-- it doesn't include bom_variant_id or flatten_strategy. With technical
-- flattening shipped, that's wrong:
--   - Two versions with identical row content but different bom_variant_id
--     (spec §3 graph identity) are legitimately distinct.
--   - Two dual-source variants with the same TP key but different
--     flatten_strategy (spec §7) are also legitimately distinct — though
--     in practice their normalized_hash differs because their rows differ.
-- Without this fix, multi-variant uploads can fail with constraint violation.
--
-- PostgreSQL forbids COALESCE in UNIQUE constraints, so we use a unique
-- INDEX on the expression instead.

do $$
begin
  if exists (select 1 from pg_constraint where conname = 'uq_bom_idempotent') then
    alter table hub.bom_versions drop constraint uq_bom_idempotent;
  end if;
end$$;

create unique index if not exists uq_bom_idempotent_v2
  on hub.bom_versions
  (client_id, product_code, actor, intent, parent_norm,
   coalesce(bom_variant_id, 'default'), flatten_strategy, normalized_hash);
