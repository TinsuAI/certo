-- 048_catalog_candidates_extra_stats.sql
--
-- Brief: .ai/features/2026-05-09-ma-cho-duyet/brief.md
--
-- Add richer per-candidate stats so the feed UI can show direction
-- breakdown, declaration count, BOM tree role, and co-occurrence
-- signal — instead of just code+kind+sources. User feedback after
-- v1: "code with kind, sources alone — what can staff do with that?"

begin;

alter table hub.catalog_candidates
  add column if not exists import_count int not null default 0,
  add column if not exists export_count int not null default 0,
  add column if not exists decl_count int not null default 0,
  add column if not exists bom_role text,
  add column if not exists bom_sample text,
  add column if not exists co_occurrence_count int not null default 0;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'catalog_candidates_bom_role_check'
  ) then
    alter table hub.catalog_candidates
      add constraint catalog_candidates_bom_role_check
      check (bom_role is null
             or bom_role in ('tp_root','btp_sx','nvl_leaf'));
  end if;
end$$;

commit;
