-- 049_catalog_candidates_richness.sql
--
-- Brief: .ai/features/2026-05-09-ma-cho-duyet/brief.md (Phase 3 enrichment)
--
-- Add hs_code / uom / origin / production_source fields to candidates so
-- staff Accept doesn't drop sparse materials into catalog. These are
-- inferred at refresh time from BCCT + BOM, used to prefill the Accept
-- form. hs_alternates_count > 1 surfaces an inconsistency badge.

begin;

alter table hub.catalog_candidates
  add column if not exists hs_code text,
  add column if not exists hs_alternates_count int not null default 0,
  add column if not exists uom text,
  add column if not exists origin text,
  add column if not exists inferred_production_source text;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'catalog_candidates_inferred_production_check'
  ) then
    alter table hub.catalog_candidates
      add constraint catalog_candidates_inferred_production_check
      check (inferred_production_source is null
             or inferred_production_source in ('nk','sx','mixed','unknown'));
  end if;
end$$;

commit;
