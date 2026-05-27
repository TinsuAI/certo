-- 067 — Clear is_stale + has_uom_drift when artifact is tombstoned.
--
-- Audit 2026-05-27: Johnson DB has 2,719 tombstoned technical_flattened
-- artifacts carrying is_stale=true. Tombstoned artifacts are dead — they
-- do not drive any view (UI filters via `tombstoned_at IS NULL`) and
-- cannot be refreshed (commit_refresh returns 'tombstoned'). The flag
-- is purely pollution in audit queries like `SELECT WHERE is_stale`.
--
-- Root cause: when bom_staleness.commit_refresh() supersedes an
-- artifact, it sets `tombstoned_at` + `tombstone_reason` but does NOT
-- clear the stale flag on the old (superseded) row — only on the new
-- one (via `_clear_stale` if no remaining drift). The intent was: dead
-- artifacts don't need clearing. In practice: they pollute filters.
--
-- Fix (this mig):
--   a) Backfill: clear flag on existing tombstoned artifacts.
--   b) Trigger: AFTER UPDATE OF tombstoned_at, when transitioning from
--      NULL → non-NULL, clear flag + resolved_at = now().
--
-- Idempotent: trigger uses IF EXISTS; backfill is one-shot UPDATE.

-- ─── Backfill ────────────────────────────────────────────────────────

update hub.bom_artifacts
   set is_stale = false,
       has_uom_drift = false,
       stale_resolved_at = coalesce(stale_resolved_at, now()),
       uom_drift_resolved_at = coalesce(uom_drift_resolved_at, now())
 where tombstoned_at is not null
   and (is_stale = true or has_uom_drift = true);

-- ─── Trigger: clear on tombstone ─────────────────────────────────────

create or replace function hub.bom_artifact_clear_flags_on_tombstone()
returns trigger as $$
begin
  -- Only act on NULL → non-NULL transition (tombstoning event).
  if OLD.tombstoned_at is null and NEW.tombstoned_at is not null then
    NEW.is_stale := false;
    NEW.has_uom_drift := false;
    -- Reasons arrays preserved for forensics (audit trail of why this
    -- artifact died). Only the boolean flag + resolved_at change.
    NEW.stale_resolved_at := coalesce(NEW.stale_resolved_at, now());
    NEW.uom_drift_resolved_at := coalesce(NEW.uom_drift_resolved_at, now());
  end if;
  return NEW;
end;
$$ language plpgsql;

comment on function hub.bom_artifact_clear_flags_on_tombstone is
  'Mig 067: clear is_stale + has_uom_drift when artifact is tombstoned. '
  'Tombstoned artifacts cannot be refreshed; the flag was pollution. '
  'Reasons arrays preserved for forensics.';

drop trigger if exists trg_bom_clear_flags_on_tombstone on hub.bom_artifacts;
create trigger trg_bom_clear_flags_on_tombstone
  before update of tombstoned_at on hub.bom_artifacts
  for each row
  when (OLD.tombstoned_at is null and NEW.tombstoned_at is not null)
  execute function hub.bom_artifact_clear_flags_on_tombstone();
