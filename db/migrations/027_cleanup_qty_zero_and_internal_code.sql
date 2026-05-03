-- 027: Cleanup the 5 qty=0 BOM rows and 3 NULL-internal_code BCCT-derived
-- materials surfaced by the audit. Then VALIDATE the constraint added
-- NOT VALID in migration 026.
--
-- Affected BOM versions (qty=0 in alive versions):
--   bv_X2IqFkPAdXdtjiOV (B700.0087101-1, 9 good + 2 bad rows)
--   bv_zASZIOkJwi_IztHy (B700.0236502-1, 1 good + 1 bad)
--   bv_WE8kGvntAttO0R-n (B700.0236502-1, 2 good + 2 bad)
--
-- Strategy: tombstone the affected versions (preserves audit trail,
-- excludes from `latest` reads), DELETE the qty=0 child rows so
-- VALIDATE CONSTRAINT can pass. Staff re-uploads corrected workbooks
-- → new clean versions land via the normal flow.
--
-- The 3 NULL internal_code rows (MAT-A/B/C in growatt-vn) are test
-- pollution from earlier test runs; backfill with internal_code =
-- customs_code (mirrors the new derive_from_bcct default) so future
-- BQD lookups work.

-- ────────────────────────────────────────────────────────────────────────
-- 1. Tombstone the 3 affected BOM versions with audit reason.
-- ────────────────────────────────────────────────────────────────────────
update hub.bom_versions
set tombstoned_at = now(),
    tombstone_reason = 'data_quality_qty_zero (migration 027)'
where tombstoned_at is null
  and version_id in (
    select distinct bv.version_id
    from hub.bom_version_rows bvr
    join hub.bom_versions bv on bv.version_id = bvr.version_id
    where bvr.qty_per_unit is null or bvr.qty_per_unit = 0
  );

-- ────────────────────────────────────────────────────────────────────────
-- 2. Delete the qty=0 rows themselves so the CHECK constraint can VALIDATE.
-- ────────────────────────────────────────────────────────────────────────
delete from hub.bom_version_rows
where qty_per_unit is null or qty_per_unit = 0;

-- ────────────────────────────────────────────────────────────────────────
-- 3. Backfill internal_code on BCCT-derived rows that pre-date the
-- derive_from_bcct fix (Sprint A). Match: BCCT-seen, NOT HQ-registered,
-- internal_code IS NULL → set to customs_code.
-- ────────────────────────────────────────────────────────────────────────
update hub.materials
set internal_code = customs_code,
    updated_at = now()
where internal_code is null
  and provenance ? 'seen_in_bcct'
  and not (provenance ? 'registered_with_hq');

-- ────────────────────────────────────────────────────────────────────────
-- 4. Validate the CHECK now that all rows comply.
-- ────────────────────────────────────────────────────────────────────────
alter table hub.bom_version_rows
  validate constraint chk_qty_per_unit_positive;
