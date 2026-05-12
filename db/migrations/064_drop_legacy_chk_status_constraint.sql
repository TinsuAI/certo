-- 064 — drop stale `chk_status` constraint left over from mig 026.
--
-- Migration 042 line 122 wrote `drop constraint if exists materials_status_check`,
-- which silently no-ops on a fresh DB because the actual existing constraint
-- (created by mig 002 then re-added by mig 026) is named `chk_status`. Mig 042
-- then adds a NEW constraint named `materials_status_check` with the expanded
-- allowed values (`active`, `under_review`, `deprecated`, `tombstoned`, `inactive`).
--
-- Net effect on a fresh DB: TWO constraints coexist. The new one allows
-- `under_review`; the old one still requires `(active, pending, discontinued)`,
-- so any INSERT/UPDATE with `status='under_review'` fails with CheckViolation
-- chk_status. Manifested in CI on tests/test_catalog_candidates_accept.py
-- and tests/test_catalog_material_edit.py.
--
-- Older dev DBs already had `chk_status` dropped manually (or via a now-
-- superseded mig 042). This migration brings fresh DBs to parity.
--
-- Idempotent: `if exists` makes it a no-op on DBs that already lack the constraint.

alter table hub.materials drop constraint if exists chk_status;
