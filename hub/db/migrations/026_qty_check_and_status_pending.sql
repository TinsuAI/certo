-- 026: Belt-and-suspenders correctness guards (Sprint A).
--
-- Audit 2026-05-03 PM surfaced three correctness gaps that the parser
-- alone can't fix:
--
--   1. `bom_version_rows.qty_per_unit > 0` — silent qty=0 rows make
--      BCQT settlement multiply by zero, dropping the material from
--      reports. Found 5 such rows in current corpus
--      (`045.SK0003600` × 0 in B700.0236502/B700.0087101). DB
--      constraint catches *future* writes; cleanup of the existing
--      5 happens in migration 027 and validates the constraint.
--
--   2. `hub.materials.chk_status` extended with 'pending' — current
--      STATUS_MAP coerces "chờ duyệt" (waiting for HQ approval) to
--      "discontinued" which is semantically wrong: pending materials
--      are still active in the agency workflow, just not yet
--      HQ-registered. Adding 'pending' lets the parser preserve
--      intent without flipping rows out of the active set.
--
-- The `derive_from_bcct` SQL fix (set `internal_code = customs_code`
-- when auto-deriving a catalog row from BCCT) lands in
-- app/stores/provenance.py — no schema change needed there.

-- ────────────────────────────────────────────────────────────────────────
-- 1. qty_per_unit > 0  — added NOT VALID so the 5 pre-existing qty=0
--    rows don't fail the migration. Migration 027 cleans them up and
--    runs `validate constraint`.
-- ────────────────────────────────────────────────────────────────────────
alter table hub.bom_version_rows
  add constraint chk_qty_per_unit_positive
  check (qty_per_unit is not null and qty_per_unit > 0)
  not valid;

-- ────────────────────────────────────────────────────────────────────────
-- 2. Extend status enum to include 'pending'.
-- ────────────────────────────────────────────────────────────────────────
alter table hub.materials drop constraint chk_status;
alter table hub.materials
  add constraint chk_status check (status in ('active','pending','discontinued'));
