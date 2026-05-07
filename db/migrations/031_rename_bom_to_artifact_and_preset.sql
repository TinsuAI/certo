-- 031_rename_bom_to_artifact_and_preset.sql
--
-- Vocab rename pass: align DB with the canonical 4-tier ontology
-- locked in .ai/GLOSSARY.md (commit 27a7889, 2026-05-07).
--
--   bom_versions             -> bom_artifacts            (bản lưu)
--   bom_version_rows         -> bom_artifact_rows
--   bom_resolution_profiles  -> bom_presets
--   version_id               -> artifact_id              (cross-table)
--   version_no               -> artifact_no
--   parent_version_id        -> parent_artifact_id
--   materialized_version_id  -> materialized_artifact_id
--   bom_version_id           -> artifact_id  (in presets)
--   profile_id               -> preset_id
--
-- Past migrations (005..030) still mention old names. They are immutable
-- history and are NOT edited. Future readers translate mentally; this
-- single migration is the join point.
--
-- ALTER TABLE/COLUMN RENAME in Postgres is metadata-only — fast even on
-- the largest table here (a few hundred rows in dev, < 50 on demo).
-- FK constraints carry over automatically. Generated columns referencing
-- renamed columns auto-update (parent_norm).
--
-- Forward-only ID prefix policy (D3/D8 of the rename brief):
--   bv_* rows survive as-is; new rows minted by code with ba_*.
--   bp_* fresh prefix for new presets (no historical rows).
-- ID prefix is opaque — code change in app/stores/bom.py covers minting.

begin;

-- ─────────────────────────────────────────────────────────────────────
-- 1. Tables
-- ─────────────────────────────────────────────────────────────────────

alter table hub.bom_versions             rename to bom_artifacts;
alter table hub.bom_version_rows         rename to bom_artifact_rows;
alter table hub.bom_resolution_profiles  rename to bom_presets;

-- ─────────────────────────────────────────────────────────────────────
-- 2. Columns — bom_artifacts
-- ─────────────────────────────────────────────────────────────────────
-- parent_norm is a STORED generated column on parent_version_id. Postgres
-- automatically updates the generation expression when the referenced
-- column is renamed (verified PG 12+).

alter table hub.bom_artifacts rename column version_id        to artifact_id;
alter table hub.bom_artifacts rename column version_no        to artifact_no;
alter table hub.bom_artifacts rename column parent_version_id to parent_artifact_id;

-- ─────────────────────────────────────────────────────────────────────
-- 3. Columns — bom_artifact_rows
-- ─────────────────────────────────────────────────────────────────────

alter table hub.bom_artifact_rows rename column version_id to artifact_id;

-- ─────────────────────────────────────────────────────────────────────
-- 4. Columns — bom_audit_events
-- ─────────────────────────────────────────────────────────────────────

alter table hub.bom_audit_events rename column version_id to artifact_id;

-- ─────────────────────────────────────────────────────────────────────
-- 5. Columns — bom_change_requests
-- ─────────────────────────────────────────────────────────────────────

alter table hub.bom_change_requests rename column parent_version_id        to parent_artifact_id;
alter table hub.bom_change_requests rename column materialized_version_id  to materialized_artifact_id;

-- ─────────────────────────────────────────────────────────────────────
-- 6. Columns — bom_unresolved_nodes (mig 021)
-- ─────────────────────────────────────────────────────────────────────

alter table hub.bom_unresolved_nodes rename column version_id to artifact_id;

-- ─────────────────────────────────────────────────────────────────────
-- 7. Columns — bom_flatten_decisions (mig 021)
-- ─────────────────────────────────────────────────────────────────────

alter table hub.bom_flatten_decisions rename column materialized_version_id to materialized_artifact_id;

-- ─────────────────────────────────────────────────────────────────────
-- 8. Columns — bom_edges (mig 029)
-- ─────────────────────────────────────────────────────────────────────

alter table hub.bom_edges rename column version_id to artifact_id;

-- ─────────────────────────────────────────────────────────────────────
-- 9. Columns — bom_presets (mig 030, post-table-rename)
-- ─────────────────────────────────────────────────────────────────────

alter table hub.bom_presets rename column profile_id     to preset_id;
alter table hub.bom_presets rename column bom_version_id to artifact_id;

-- ─────────────────────────────────────────────────────────────────────
-- 9b. Columns — bcct_rows (BCCT row → BOM artifact link)
-- ─────────────────────────────────────────────────────────────────────
-- Each BCCT row may carry a soft pointer to the BOM artifact that was
-- consulted during ingest. Originally `bom_version_id`; aligned with
-- the rest of the rename.

alter table hub.bcct_rows rename column bom_version_id to artifact_id;

-- ─────────────────────────────────────────────────────────────────────
-- 10. Index renames
-- ─────────────────────────────────────────────────────────────────────
-- Indexes are not auto-renamed when their table is. Do them explicitly
-- so DBA tooling + EXPLAIN output reads consistently with new names.

alter index if exists hub.idx_bom_versions_product       rename to idx_bom_artifacts_product;
alter index if exists hub.idx_bom_versions_intent        rename to idx_bom_artifacts_intent;
alter index if exists hub.idx_bom_versions_alive         rename to idx_bom_artifacts_alive;
alter index if exists hub.idx_bom_versions_flat_status   rename to idx_bom_artifacts_flat_status;
alter index if exists hub.idx_bom_versions_variant       rename to idx_bom_artifacts_variant;

alter index if exists hub.idx_bom_version_rows_material  rename to idx_bom_artifact_rows_material;

alter index if exists hub.idx_bom_resolution_profiles_alive       rename to idx_bom_presets_alive;
alter index if exists hub.idx_bom_resolution_profiles_by_version  rename to idx_bom_presets_by_artifact;
alter index if exists hub.uq_bom_resolution_profiles_name         rename to uq_bom_presets_name;

-- bom_artifacts primary key constraint is auto-named by Postgres
-- (typically "bom_versions_pkey"); rename for tidy \d output.
do $$
begin
  if exists (select 1 from pg_constraint where conname = 'bom_versions_pkey') then
    alter index hub.bom_versions_pkey rename to bom_artifacts_pkey;
  end if;
  if exists (select 1 from pg_constraint where conname = 'bom_version_rows_pkey') then
    alter index hub.bom_version_rows_pkey rename to bom_artifact_rows_pkey;
  end if;
  if exists (select 1 from pg_constraint where conname = 'bom_resolution_profiles_pkey') then
    alter index hub.bom_resolution_profiles_pkey rename to bom_presets_pkey;
  end if;
end $$;

-- ─────────────────────────────────────────────────────────────────────
-- 11. Sanity grants (belt-and-suspenders per R5)
-- ─────────────────────────────────────────────────────────────────────
-- Grants carry over RENAME automatically, but applying explicitly is
-- harmless and ensures any role added since the original GRANT picks
-- up access on the renamed objects. The pg_roles filter restricts to
-- expected app roles; missing roles are silently skipped because the
-- loop is empty. No catch-all exception handler — any failure inside
-- the loop is a real bug and should surface.

do $$
declare
  r record;
begin
  for r in
    select rolname from pg_roles
    where rolname in ('data_hub_app','bcqt_app','co_app','data_hub_ro')
  loop
    execute format('grant select, insert, update, delete on hub.bom_artifacts      to %I', r.rolname);
    execute format('grant select, insert, update, delete on hub.bom_artifact_rows  to %I', r.rolname);
    execute format('grant select, insert, update, delete on hub.bom_presets        to %I', r.rolname);
  end loop;
end $$;

commit;
