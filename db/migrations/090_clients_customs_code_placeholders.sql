-- 090_clients_customs_code_placeholders.sql
-- Per-client placeholder strings for the BCCT customs_code field (#30,
-- catalog phase 0). A placeholder (Growatt/Johnson write '.') means "no
-- HQ code on this line" — those lines are fixed-asset rows (E13
-- forklifts, racks), not materials. See
-- docs/adr/0002-customs-code-semantics.md and
-- .ai/features/2026-07-10-catalog-candidates-merge/brief.md.
--
-- One predicate reads this config (`_is_missing_hq`,
-- app/parsers/catalog_candidates.py); no placeholder literal stays in
-- shared code. Client-specific behavior lives in config, not
-- `if client_id ==` branches.

alter table hub.clients
    add column if not exists customs_code_placeholders text[]
        not null default '{}';

-- Seed the two known placeholder clients. No-op on a fresh DB where
-- clients don't exist yet (CI) — app/seed.py mirrors this for the demo
-- seed, same pattern as parser rules (migs 036/037).
update hub.clients
   set customs_code_placeholders = '{"."}'
 where client_id in ('growatt-vn', 'johnson-vn')
   and customs_code_placeholders = '{}';

-- Delete the junk materials `derive_from_bcct` created from placeholder
-- lines before the skip existed (one '.' row each for growatt-vn +
-- johnson-vn, both status='active' source='bcct_observed'; nothing
-- references hub.materials by FK). Unreplayable columns: none — both
-- rows are pure derivations from bcct_rows, never staff-edited.
delete from hub.materials m
 using hub.clients c
 where c.client_id = m.client_id
   and m.material_code = any(c.customs_code_placeholders);
