-- Phase 2.1: per-case optimistic concurrency.
--
-- `co_cases` is being promoted from a derived shadow index of
-- co_case_states.payload.cases to the source of truth for case state.
-- The `revision` counter is the optimistic-lock token: save_case_record
-- will UPDATE ... WHERE revision = $expected and bump revision + 1.
-- Conflicts trigger a load-and-retry in the caller instead of clobbering.
--
-- Existing rows backfill to revision = 0 so the first save sees an
-- expected_revision of 0 and the new contract is monotonically forward.

alter table co_cases
  add column if not exists revision integer not null default 0;

create index if not exists co_cases_client_revision_idx
  on co_cases (client_id, case_id, revision);
