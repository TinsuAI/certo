-- Phase 3.1: FK co_stock_claims.case_id → co_cases(case_id) ON DELETE CASCADE.
--
-- Defense in depth on top of the application-level HIGH #2 fix
-- (delete_case_record → release_all_claims_for_case before deleting the
-- case row). With this FK, any code path that bypasses the app — direct
-- DB delete, future endpoint that forgets to release first — still has
-- the orphan-claim hazard caught by Postgres.
--
-- CASCADE is the correct disposition: released claims keep historical
-- value via co_stock_events (claim_release events carry case_id +
-- sheet_product_code + qty), so dropping the claim row when its case is
-- gone is a clean prune, not a loss. Locked claims should never survive
-- to this point because the app blocks delete-with-claims, but if any
-- did slip through, dropping them is safer than leaving them ghost-pinned.
--
-- Backfill first: remove any pre-existing orphans so the FK can be added.

delete from co_stock_claims
 where (client_id, case_id) not in (select client_id, case_id from co_cases);

alter table co_stock_claims
  add constraint co_stock_claims_case_fk
  foreign key (client_id, case_id)
  references co_cases (client_id, case_id)
  on delete cascade;
