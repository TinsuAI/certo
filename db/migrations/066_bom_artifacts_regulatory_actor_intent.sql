-- 066 — extend chk_actor + chk_intent for customs/regulatory filings.
--
-- Pre-066 actor enum {agency_staff, co_system, erp_pipeline, system} did
-- not have a fitting value for "Mẫu 16/15/15a-style regulatory filings
-- nộp cơ quan hải quan". Mig 065 ingest had to mislabel them as
-- `erp_pipeline` — fixed here by adding `customs_filing`.
--
-- Similarly `intent` previously had {asserted_technical, derived,
-- modified_for_case, staff_edit} — none mean "this is the BOM declared
-- to customs". Adding `customs_declared` so filed-with-customs BOMs no
-- longer mimic asserted_technical (which carries technical-truth
-- semantic).
--
-- Idempotent: each DROP uses IF EXISTS; ADD uses IF NOT EXISTS via
-- catalog check inline.

alter table hub.bom_artifacts drop constraint if exists chk_actor;
alter table hub.bom_artifacts add constraint chk_actor
    check (actor in ('agency_staff', 'co_system', 'erp_pipeline',
                     'system', 'customs_filing'));

alter table hub.bom_artifacts drop constraint if exists chk_intent;
alter table hub.bom_artifacts add constraint chk_intent
    check (intent in ('asserted_technical', 'derived',
                      'modified_for_case', 'staff_edit',
                      'customs_declared'));
