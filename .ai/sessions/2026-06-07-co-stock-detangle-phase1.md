# Session 2026-06-07 — CO-stock state-machine detangle (Phase 1) + delete-case audit

Branch `co-stock-detangle-phase1` (4 commits, NOT pushed, NOT merged to main).

## What Was Done

Started from "what's important next" → user steered into the giữ-tồn/chốt-sheet/đóng-hồ-sơ
state machine, which they designed and now find confusing. Mapped it, found the real problem,
and shipped Phase 1.

**Discovery (brief `.ai/features/2026-06-07-co-stock-state-machine-detangle.md`):** the machine
has 5 tangled dimensions — A `origin_calculation_lock` (per-client mutex), B `origin_sheet_status`,
C `co_stock_claims` (locked/released), D case open/completed, E sheet-lock ordering. Key finding:
**mutex A is orthogonal to the Tồn CO invariant** — the sheet-lock claim-write (`record_sheet_lock`)
never acquired A; A only 409-blocked sibling cases during calculate/export and had a 60-min TTL
that was never released (stuck-lock bug). The actual invariant (Σ locked claims ≤ remaining) lives
in `record_sheet_lock`'s over-claim check, which had a **real TOCTOU race** (no FOR UPDATE, READ
COMMITTED) — latent only because prod runs `--workers 1` and the check→INSERT has no `await`.

**3-agent review (critic + 2 verifiers)** corrected the plan before coding: advisory-lock-on-claims
was insufficient (materializer rewrites `remaining_qty` in a separate txn); use `SELECT ... FOR
UPDATE` on `co_stock_rows` instead (PK `(client_id, source_row)`, same rows the materializer locks).

**Phase 1 implementation (TDD):**
- `fix(co-stock)` `9e59711`: `record_sheet_lock` locks lot rows `... order by source_row for update`
  (separate stmt — availability query uses GROUP BY) before the check, same txn. Sorted to match.
  Also sorted the materializer's two `co_stock_rows` write batches (`_upsert_records` upsert + delta
  UPDATE) by source_row so a refresh + a concurrent sheet-lock can't deadlock on overlapping lots
  (deadlock vector found in /rev). New DB test `tests/test_co_stock_lock_concurrency.py` (2 psycopg
  connections) proves serialization.
- `refactor(co-case)` `83eeedc`: removed mutex A entirely — helpers + TTL (`co_case_store.py`), the
  409 branches in `/evaluate`,`/calculate`,`/export`, the `/origin-lock/release` endpoint, close-time
  release, delete-block branch, context flags, all banner/release-form/button-guard UI
  (`co_case.html`). Kept `mark_origin_sheets_stale`. Updated `tests/test_co_demo.py` (dropped the
  mutex test, fixed the delete-block test). Removed orphaned imports (`co_auth`,`Request`,`timedelta`).
- Docs `0307431` (brief) + `f5da932` (audit correction, see below).

**Delete-case stock-history audit (`f5da932`, doc `.ai/audits/2026-06-07-delete-case-stock-history-audit.md`):**
Done earlier in the session, then corrected after the FOR UPDATE test exposed the FK. Verdict:
stock-correctness side is sound (no leak, guard, release-before-delete order). Traceability is
partial — 3 GAPs (A: events carry only `case_id` not `case_code`; B: no "deleted cases" view /
`deleted_at`; C: a 0-claim case delete leaves no footprint).

## Decisions Made

- **Remove mutex A entirely** (not just fix its release bug). Verified safe on prod: PG per-case
  store (no cross-case lost-update), ledger has its own DB over-claim guard, refresh has its own
  in-process lock. Accepted tradeoff: two operators can calculate concurrently; the second to chốt
  an exhausted lot recalcs/substitutes (self-healing via live claim overlay + over-claim check).
- **Keep E (sheet ordering)** — user pushback was correct: greedy sequential allocation from a
  shared pool is order-dependent (the calc reads live cross-case claims via `apply_used_qty`), so E
  determines the actual allocation RESULT, not just UX. Not relaxed.
- **FOR UPDATE on `co_stock_rows`, not advisory lock** — advisory-on-claims misses the
  materializer's `remaining_qty` rewrite; FOR UPDATE on the lot rows serializes both claim-vs-claim
  and claim-vs-refresh.
- **Phase split:** Phase 1 = remove A + FOR UPDATE (shipped). Phase 2 = split "Load BOM" (structure
  only) from "Tính bảng kê" (allocation). Phase 3 = clean Tồn CO history display noise. Both deferred.

## What Didn't Work / Corrected Mid-Session

- First plan said advisory xact lock per lot — **wrong** (doesn't cover the materializer txn). Fixed
  to FOR UPDATE after the critic flagged it.
- First plan named `record_sheet_replace` (doesn't exist) and missed `release_all_claims_for_case`.
- The delete-case audit's first conclusion (claims survive case delete) was **wrong**: FK
  `ON DELETE CASCADE` (mig 016) prunes them; only `co_stock_events` survives. Audit doc corrected.
- Local dev server (8001) died during a `--reload` cycle mid-session; restarted via `npm run co:serve`.

## Open Items

- **Push + deploy Phase 1** when ready (branch `co-stock-detangle-phase1` → PR/merge to main →
  TinsuAI/co runner auto-deploys). Not pushed this session.
- **Phase 2** — split Load BOM / Tính bảng kê. `prepare_case_origin_sheet` (`co_case_context.py:939`)
  is separable but needs refactor (BOM-expansion fused with allocation in `origin_material_from_bom_row`;
  overrides keyed by material row index so Load BOM must still expand to `product.materials`; add a
  `bom_loaded` status). Own discovery.
- **Phase 3** — Tồn CO lot-history shows both chốt (`claim_lock`) and mở-chốt (`claim_release`) →
  noisy. Keep full data, change display (net per case / draft-vs-committed toggle). Pair with the
  delete-case audit's R1/R2/R3 (snapshot case identity onto events; soft-delete/tombstone; emit
  case_delete event).
- Other backlog unchanged: feedback #14 (BOM default per code), #13 (batch chốt BOM), #4 (DH
  substitute ranking).
