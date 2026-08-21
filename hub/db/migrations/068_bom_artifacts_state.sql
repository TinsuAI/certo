-- 068 — `state` column on bom_artifacts: single UI-facing summary.
--
-- Audit 2026-05-27 identified a UX problem: /bom/stale page shows
-- both is_stale + has_uom_drift, in 8 dims, 3 categories. Staff sees
-- 1,336 rows and 99% are not actionable. The conceptual mismatch:
-- engineers see two flags (derived re-derivable vs source immutable);
-- staff see "is this trustworthy now / what do I do".
--
-- This mig adds `state` — a stored GENERATED column that exposes one
-- of 4 values driven by existing flags + reasons. No trigger needed:
-- Postgres maintains the generated column automatically whenever
-- source columns change. Aligns with `feedback_no_derived_in_source`
-- (no separate cache to drift from truth).
--
-- States:
-- - `clean`     — no flag; artifact aligned with current catalog.
-- - `needs_refresh` — auto-fixable by Refresh action (re-derive or
--                     manual_flat re-apply convert). Staff: 1 click.
-- - `needs_input`   — requires staff decision: factor missing, catalog
--                     uom missing, unconfirmed 1:1 default, raw_graph
--                     drift (no auto-fix path).
-- - `broken`        — reserved for future (corrupt lineage, missing
--                     raw ancestor). Not yet emitted.
--
-- Sister-app contract: API (/api/v1/bom/artifact/{id}) gains a `state`
-- field additively. is_stale + has_uom_drift retained for BC.
--
-- Spec: audit notes 2026-05-27 (this session). Brief at
-- .ai/features/2026-05-27-stale-rebuild/brief.md (forthcoming).

-- Drop generated column first if rerun (mig is idempotent).
alter table hub.bom_artifacts drop column if exists state;

-- Stored generated. Postgres maintains on every UPDATE of source cols.
-- Order of branches matters: needs_input wins over needs_refresh when
-- both apply (some artifacts have multi-dim reasons mixing both).
alter table hub.bom_artifacts add column state text
  generated always as (
    case
      -- Clean: no flag set. Tombstoned mig 067 ensures dead artifacts
      -- are clean by construction (flags cleared on tombstone).
      when not is_stale and not has_uom_drift then 'clean'
      -- needs_input: at least one dim requires staff action that
      -- Refresh alone cannot resolve. Tested via JSONB containment.
      when stale_reasons @> '[{"dim":"factor_missing"}]'::jsonb
        or stale_reasons @> '[{"dim":"catalog_uom_missing"}]'::jsonb
        or stale_reasons @> '[{"dim":"unconfirmed_default_1to1"}]'::jsonb
        or uom_drift_reasons @> '[{"dim":"factor_missing"}]'::jsonb
        or uom_drift_reasons @> '[{"dim":"catalog_uom_missing"}]'::jsonb
        or uom_drift_reasons @> '[{"dim":"unconfirmed_default_1to1"}]'::jsonb
        then 'needs_input'
      -- raw_graph with has_uom_drift: edges immutable, Refresh path
      -- skips with reason='source_artifact'. Re-upload only → input.
      when has_uom_drift
        and source_bom_kind = 'technical_raw'
        then 'needs_input'
      -- Everything else with a flag: Refresh can clear it.
      -- Covers: catalog_category, materials_uom (derived), btp_sourcing,
      --         btp_bom_added, btp_bom_tombstoned, catalog_inserted,
      --         derive_hook_failed, manual_flat materials_uom.
      else 'needs_refresh'
    end
  ) stored;

alter table hub.bom_artifacts drop constraint if exists chk_bom_state;
alter table hub.bom_artifacts add constraint chk_bom_state
  check (state in ('clean', 'needs_refresh', 'needs_input', 'broken'));

comment on column hub.bom_artifacts.state is
  'Mig 068: UI-facing 4-state summary derived from is_stale + '
  'has_uom_drift + reasons. Stored generated column auto-maintained '
  'by Postgres. UI binds to this single field instead of multi-flag '
  'union. Values: clean / needs_refresh / needs_input / broken.';

-- Partial index for the action queue. Most artifacts are clean,
-- so a partial index on the unhappy paths is cheap.
create index if not exists idx_bom_artifacts_state_action
  on hub.bom_artifacts (client_id, state)
  where state <> 'clean';
