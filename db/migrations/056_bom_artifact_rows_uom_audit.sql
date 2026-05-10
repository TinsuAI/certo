-- 056 — Track D Phase 2 step 4: UoM conversion audit columns on
-- `hub.bom_artifact_rows`.
--
-- Forensics for "which factor did this derived row use". Populated by
-- _convert_rows_to_catalog_uom (mig-2026-05-12) when the refresh path
-- mints a new artifact. Existing pre-Phase-2 rows have NULLs (no
-- backfill — the data wasn't tracked at write time).
--
--   source_uom         — the raw UoM the row started with (from
--                        bom_edges.uom for refresh; from upload row
--                        for ingest path).
--   applied_uom_factor — numeric factor that was multiplied (1.0 for
--                        alias / unconfirmed_default; otherwise per
--                        client_uom_overrides or uom_canonical).
--   applied_uom_source — ConversionMatch.source: 'alias', 'global',
--                        'client_specific', 'client_wide',
--                        'unconfirmed_default'. Null when raw was
--                        kept (factor_missing or catalog_uom_missing).
--
-- Spec: `.ai/features/2026-05-12-bom-uom-conversion-phase-2/brief.md`
-- step 4 + decision 6 (3-tier policy traceability).

alter table hub.bom_artifact_rows
  add column if not exists source_uom text,
  add column if not exists applied_uom_factor numeric(20,9),
  add column if not exists applied_uom_source text;

comment on column hub.bom_artifact_rows.source_uom is
  'Raw UoM the row started with before conversion (mig 056). '
  'NULL on pre-Phase-2 rows.';

comment on column hub.bom_artifact_rows.applied_uom_factor is
  'Numeric factor multiplied to convert source_uom -> uom (mig 056). '
  'NULL when no conversion happened or raw was kept (factor_missing).';

comment on column hub.bom_artifact_rows.applied_uom_source is
  'ConversionMatch source: alias | global | client_specific | '
  'client_wide | unconfirmed_default (mig 056). NULL when raw kept.';

-- Constrain enum to known sources to catch typos.
alter table hub.bom_artifact_rows
  drop constraint if exists chk_bom_row_uom_source;
alter table hub.bom_artifact_rows
  add constraint chk_bom_row_uom_source check (
    applied_uom_source is null or applied_uom_source in (
      'alias', 'global', 'client_specific', 'client_wide',
      'unconfirmed_default'
    )
  );
