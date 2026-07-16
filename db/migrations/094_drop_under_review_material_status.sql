-- 094 — remove `under_review` from hub.materials.status (issue #49).
--
-- Mig 042 line 124 admitted `under_review` to support the catalog_derive
-- wizard, abandoned in the 2026-05-09 pivot. It became a dead end: accepting
-- a candidate landed under_review while BCCT ingest auto-inserted `active`
-- with no review at all, inverting the trust ordering. Approval is `source`
-- promotion plus the candidates queue — status was never the approval gate.
-- ADR 0001 rejected merging candidates into materials as status='under_review'.
--
-- Resulting set: active | deprecated | tombstoned | inactive.
--
-- The flip must precede the constraint or the ADD CONSTRAINT validates
-- against surviving rows and fails. Local dev DB has 1 such row.
--
-- hub.catalog_derive_configs.default_status (mig 043) also references
-- 'under_review' but has zero readers — dead table from the same abandoned
-- wizard. Its own CHECK is left alone; it does not constrain hub.materials.

update hub.materials set status = 'active', updated_at = now()
 where status = 'under_review';

alter table hub.materials drop constraint if exists materials_status_check;
alter table hub.materials add constraint materials_status_check
  check (status in ('active','deprecated','tombstoned','inactive'));
