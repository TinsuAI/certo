# Session 2026-07-11 (PM) — missing_price belts, prod audit, stock-refresh schema backfill, QA issues

Closed both standing non-ticket action items, root-caused and fixed the empty
suppliers screen, pushed + deployed, backfilled prod/nightly, filed 3 QA issues.
`origin/main` = prod = nightly = **`9f38afa`** (CI green, verified `/version` on both).

## What Was Done

1. **`missing_price` one-belt hole closed (`b89e187`).** `lvc_missing_price` had only
   belt 1 (`calculated_sheet_status`). Added belt 2 (`origin_sheet_action_error` re-checks
   the flag on lock, AFTER shortage — a no-lot NVL trips both flags and its remedy is the
   document, not a price) and belt 3 (`origin_sheet_export_blockers` re-checks it).
   3 tests in `tests/test_missing_price_lock_guard.py`.

2. **Prod audit of already-locked SHORTAGE sheets: NO exposure.** Read-only in-container
   script over `co_cases` payload + `co_stock_claims` (prod `co-app-1`): 16 cases,
   82 sheets, 10 locked — **0 locked sheets** carry shortage/missing-price/unmatched lines.
   Side finding: 4 johnson-vn `calculated` sheets DO carry flags (VGM0121-05: 6/143/121;
   MFW0525-39 ×2; MFW0525-571) — belts 2/3 now hard-block their lock/export until re-Tính.
   The standing "audit locked SHORTAGE sheets" item is CLOSED, nothing to remediate.

3. **Suppliers screen empty → root cause + fix (`9f38afa`).** User report: NCC curation
   screen listed nobody and "Refresh tồn" didn't help.
   - Root cause chain: the screen derives from `co_stock_rows.payload->consignee_name`;
     every pre-VN-origin snapshot lacks that field; the refresh dispatch picks the DELTA
     path (pull only BCCT rows changed since `last_bcct_server_time`), which rewrites
     nothing when source data didn't change → a CO-side derivation field addition can
     NEVER backfill through the UI.
   - Fix: migration `020` adds `co_stock_refresh_state.derivation_schema_version`
     (default 0); `record_refresh_state` stamps `DERIVATION_SCHEMA_VERSION` (=2, in
     `co_stock_materializer`); the dispatch forces ONE full re-derivation on stamp
     mismatch, then returns to delta. Tests: `tests/test_co_stock_refresh_schema_version.py`
     (+2 existing fake states gained the stamp).
   - Verified live locally on johnson-vn (the real broken case): forced `mode=full`,
     60,173 updated / 0 removed (37s), consignee 0 → 60,173/60,173, screen renders 664
     suppliers; next refresh delta again (3s).

4. **Pushed + deployed + backfilled.** Push `a5ed43d..9f38afa` → CI/CD green → prod +
   nightly `git_sha=9f38afa`, migration 020 applied at boot. Ran the route's own refresh
   logic in-container on PROD and NIGHTLY for both clients: all `mode=full`, growatt-vn
   38,287/38,287 and johnson-vn 65,945/65,945 with consignee_name, 0 removed, 0 blocked
   by claims, stamps=2. Prod suppliers screen is now populated.

5. **QA session → GitHub issues #15, #16, #17** (all `ready-for-agent`, independent):
   #15 long NCC name forces horizontal scroll; #16 suppliers search box (accent/case-
   insensitive); #17 case view suppresses client-tabs (`active == "co-case"` in
   `_client_nav.html`, since `b7e5b4d`).

## Decisions Made

- Missing-price belts mirror the shortage guard exactly, with shortage taking precedence
  in the lock gate (message names the document remedy, not a price).
- Backfill trigger = schema-version stamp on refresh state (not payload sniffing, not a
  one-off script): every future derivation field addition backfills by bumping
  `DERIVATION_SCHEMA_VERSION`.
- The 2 prod NCC flags are left to the USER via the UI so the evidence audit log records
  their identity (agent-written events would fabricate an actor).
- #14 recommendation (not yet decided): option 2 — CO-side allocation override on the
  client overlay (precedent `bang_ke_overrides`); ask the agency first whether growatt-vn
  will upload customs-coded manual BOMs anyway (option 3 would void the need).
- Issues #15-#17 filed per QA-skill format: durable, user-language, no file refs, and
  deliberately deferred to fresh `/implement` sessions (context hygiene).

## What Didn't Work / Gotchas

- **psql on local `barry_co` defaults to `public` schema, which holds a STALE legacy
  copy of the app tables** (old `co_stock_rows` with only legacy `growatt`, no
  `co_stock_refresh_state`). App uses `BARRY_DATABASE_SCHEMA=co`. Cost a diagnosis round;
  always `set search_path=co`. Memory saved: `local-barry-co-db-schema-co`.
- Chasing the wrong environment: assumed the user saw the empty screen on prod, but
  prod/nightly container logs showed the suppliers screen had NEVER been served there —
  they were on local `:8001` before the overnight tour's 14:22 full re-derivation.
  Check access logs before theorising about which deployment a report is from.
- `zsh` eats `===`/`==` in heredoc-less compound commands (`(eval):1: == not found`) —
  use `echo ---` separators.

## Open Items

- **USER: flag the 2 NCC on prod UI** (`/clients/growatt-vn/suppliers`): exact live-BCCT
  spellings `CONG TY TNHH MINGJIE VIET NAM` + `CONG TY TNHH MINGHUI VIET NAM`; NEVER
  `MINGJIE INDUSTRIAL (HK) LIMITED`. Johnson stays zero-flag.
- **Decide #14** (growatt-vn allocation strategy; recommendation = option 2, see issue).
  Note: until #14 is resolved, the flags have no effect on growatt-vn's Tính (technical
  BOMs match no on-spot lots).
- **`/implement` #15, #16, #17** — fresh context per ticket (`gh issue view <n>`).
- Local dev leftovers: dev server on `:8001` (reload); `uv.lock` modified, deliberately
  uncommitted; local growatt-vn + demo-furniture evidence flags ON from the overnight tour.
- Backlog unchanged otherwise: ST1 (readiness chip), FX1, D2, etc.
