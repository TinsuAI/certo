-- 038_drop_material_identity_column.sql
--
-- Brief: .ai/features/2026-05-08-configurable-bcct-parsing/brief.md
--   (architectural follow-up — same principle as mig 035 dropping
--   internal_code: pure-derivation values are not cached.)
--
-- material_identity is a multi-stage resolver output computed from
-- (row_data, materials_catalog, code_mappings, parser_rules). The
-- dependencies are stable from a single request perspective; runtime
-- computation per response is well within budget (~1-2 ms/row × 50-row
-- page = 50-100 ms). Persisting it adds drift risk + backfill burden
-- without value gain.
--
-- bcct_material_identity_review (operator override write-data) is NOT
-- a cache — it stays.
--
-- After this migration: API endpoints + UI handlers compute
-- material_identity at read time via the resolver. No backfill ever
-- needed. Rule edits propagate instantly to next read.

begin;

alter table hub.bcct_rows drop column if exists material_identity;

commit;
