# Session 2026-06-08 — P1: origin cold-load perf (drop full co_stock snapshot read at tab-render)

## What Was Done

### 1. Session start + backlog review
- Reused the already-running CO dev server on `127.0.0.1:8001` (live-reload,
  PID 1312874 family, from prior session). A duplicate `npm run co:serve` failed
  to bind ("Address already in use") and exited — no cleanup needed. DH on `:8754`.
  - Note: initial detection missed it — `pgrep` pattern used `\|` (wrong escape in
    this shell) and `ss` lacked root for process names. Confirm via `/proc` cmdline.
- Reviewed `.ai/BACKLOG.md`; flagged D1 (delta-vs-full refresh, SAI TỒN) as highest
  risk; rest UI (B1–B4) + feedback (#14/#13/#4).

### 2. New backlog item P1 — "tạo hồ sơ chạy lâu"
- Measured create flow (local, johnson-vn): POST create 0.13s, shipment landing
  0.3s — both fast. The slow part is the FIRST open of "Bảng kê C/O" (origin).
- Created 3 throwaway test cases to measure, **all deleted** (verified 0 left).

### 3. /discover P1 → brief (`.ai/features/2026-06-08-origin-cold-load-perf.md`)
- **Corrected the initial diagnosis.** Profiled `origin_source_context` components
  (johnson-vn, 1 declaration):
  - `read_co_stock_rows_cached` (60173 lô): **2595 ms** ← dominant
  - copy 60k dict + `apply_used_qty`: ~540 ms (every load)
  - `origin_invoice_matches` (narrow DH): **11 ms** — NOT the problem
  - `source_summary` 58ms, `declaration_file_counts` 11ms
- Root cause: cold origin tab-render read the **entire per-client 60k-row co_stock
  snapshot**, but the render only builds shells — `prepare_case_origin_product_shells`
  takes no `stock_rows`; the template never reads `source_context.stock_rows`; the
  one consumer `case_tkx_tkn_summary` accepts but **ignores** the param. The warm
  path (`cached_origin_source_context`) already returned `stock_rows: []` and renders
  in 0.27s — proof the read is wasted. Tàn dư sau refactor Phase 2 (allocation moved
  to `/calculate`). "Full BCCT pull ~40s" was only the empty-snapshot fallback (D1).

### 4. /tdd → fix (commit `a1ac2ed`, deployed)
- **`app/web/co_case_context.py` `origin_source_context`:** return `stock_rows: []`
  (like the warm path); dropped the `_calculate_stock_rows_from_snapshot` read AND
  the empty-snapshot fallback to the ~40s full pull. File-store-mode early return
  (`data_hub is None`) unchanged. `/calculate` untouched — it reads tồn independently
  via `_calculate_stock_rows_from_snapshot` (co_case.py:1564), which is now its sole
  remaining caller.
- **Tests (`tests/test_origin_narrow_source_context.py`):** RED test
  `test_..._skips_full_snapshot_read_at_tab_render` (asserts no snapshot read, no heavy
  pull, stock_rows=[], narrow matches still fetched) → watched it fail at the snapshot
  read → GREEN. Updated old-contract tests: removed `cold_reads_snapshot`, fixed
  `cold_always_refetches` (stock→[]), replaced `falls_back_to_heavy` with
  `no_full_pull_even_when_snapshot_empty` (regression guard for the D1 condition),
  updated e2e parity (invoice_matches still byte-identical; stock_rows==[]) + docstring.

### 5. /rev + commit + push + deploy
- Review: 0 critical, 0 blockers. One behavior change flagged for awareness (below).
- Committed `a1ac2ed` (4 files: fix, tests, brief, BACKLOG). No AI trailers.
- Pushed `899c544..a1ac2ed` → TinsuAI/co main (fast-forward). CI green (tests 47s,
  build 16s, deploy 1m5s). **Prod + demo `/version` → `a1ac2ed / source=build`.**

## Decisions Made
- **Surgical scope (user chose):** only tab-render; do NOT also scope `/calculate`
  stock to per-product lots (bigger, touches `case_allocation_pool`) — left as a
  separate backlog note. Decoupled from D1.
- **Drop the empty-snapshot → 40s fallback entirely at tab-render.** Render shows no
  tồn, so an empty stock preview is fine; `/calculate` keeps its own fallback. This
  also eliminates the worst-case 40s on fresh/never-materialized clients.
- **Verification depth (tồn is high-risk):** full file-mode suite (521 passed) +
  opt-in real-Johnson parity e2e (RUN_ORIGIN_PARITY_E2E=1, invoice_matches
  byte-identical) + 46 co_stock DB tests + live measurement.

## What Didn't Work / Gotchas
- **Initial diagnosis was wrong.** Assumed "full BCCT pull ~40s"; profiling proved
  it's the 60k-row snapshot read. Lesson: profile before writing the brief, don't
  trust the code's own "~40s" comments for the current default path.
- **Behavior change (intentional, flagged in /rev):** the snapshot-staleness
  background refresh (`_schedule_background_co_stock_refresh`) was incidentally
  triggered on every origin tab-view/preload via the snapshot read. It now fires
  **only from `/calculate`**. Not a correctness issue (live ledger overlay + age
  surfaced; `/calculate` still triggers it). Net: less refresh churn (favorable for D1).
- zsh: `pgrep -f "a\|b"` mis-escapes; `ss` needs root for `-p` names; `ls -t <dir>`
  misbehaves → use `/proc/<pid>/cmdline`, `/bin/ls`, `command grep`.

## Open Items
- **Optional follow-up (noted in brief/backlog, NOT done):** scope `/calculate` stock
  to the product's own material lots instead of copy+apply over all 60k (~540ms/calc).
  Bigger, touches allocation. Separate item.
- **Index page (case list) 4.27s** for johnson-vn — N+1 `claims_summary_for_case`
  (`co_case_context.py:2760-2767`). Separate perf item, not P1.
- **Backlog unchanged otherwise:** D1 (highest risk), UI B1–B4, feedback #14/#13/#4,
  DH reciprocal cleanup (DH demo /version 0.0.0, DH /whats-new prod empty).
- **Uncommitted:** `.ai/sessions/2026-06-08-co-app-versioning-changelog.md` (prior
  session's untracked handoff) — left as-is, unrelated to P1.
