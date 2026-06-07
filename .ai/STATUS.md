# Project Status

## Current State
- **CO-stock state-machine detangle — Phase 1 DONE on branch `co-stock-detangle-phase1`
  (NOT pushed/merged/deployed).** Two concerns the giữ-tồn/chốt/đóng machine tangled:
  - **Removed mutex A** (`origin_calculation_lock`, per-client 60-min lock that 409-blocked
    sibling cases and never auto-released). It was **orthogonal to the Tồn CO invariant** —
    sheet-lock claim-write never held it; stock safety lives in `record_sheet_lock`'s over-claim
    check. Gone: helpers+TTL, 409 branches in `/evaluate`,`/calculate`,`/export`,
    `/origin-lock/release` endpoint, close-release, delete-block branch, all banner/button UI.
  - **Closed the over-claim TOCTOU** with `SELECT ... FOR UPDATE` on `co_stock_rows` (lot rows,
    sorted by source_row, separate stmt before the GROUP BY availability check, same txn). Race
    was latent on prod (`--workers 1`, no `await`); FOR UPDATE is correctness insurance for
    multi-worker. Also sorted the materializer's two `co_stock_rows` write batches by source_row
    to avoid a refresh↔sheet-lock deadlock (found in `/rev`).
  - Commits: `9e59711` (FOR UPDATE), `83eeedc` (remove A), `0307431` (brief), `f5da932` (audit
    correction). Tests: file-mode **483 passed / 9 skipped**; new DB concurrency test
    `tests/test_co_stock_lock_concurrency.py` + DB co_stock tests green. Dev server reloaded OK,
    0 lock-UI hits. Brief: `.ai/features/2026-06-07-co-stock-state-machine-detangle.md`.
  - **User-visible change:** no more "đang giữ phiên tính tồn" banner / "Nhả phiên" button / 409
    blocking sibling cases / 60-min stuck lock. Two operators can calculate in parallel; second to
    chốt an exhausted lot recalcs (self-healing).
- **Deployed baseline (prod `barry-co.tinsu.ai` + demo `demo-co.tinsu.ai`, all on `main`):**
  app-identity brand chrome (`1f2b6dd`, purple `--brand`), CO-case list redesign (`ee70a4b`, stat
  band + status badges + archive + create modal), UX Primer redesign (`a33eaae`), background
  dossier export (`dc1b582`), merged TKX/TKN PDF dossier, content-hash static cache-busting,
  CO→DH operator-JWT auth (no service token), #12 số tồn tổng. CI green, nightly refreshed.

## Recent Changes (latest first)
- **Phase 1 detangle** (branch `co-stock-detangle-phase1`, 2026-06-07): see Current State.
  +445/−328 across 13 files. 3-agent review (critic+2 verifiers) corrected the plan pre-code
  (advisory lock → FOR UPDATE; race latent at 1-worker; bỏ A verified safe). Memory
  `co-stock-lock-orthogonal-overclaim-race`.
- **Delete-case stock-history audit** (`f5da932`, `.ai/audits/2026-06-07-delete-case-stock-history-audit.md`):
  stock side sound; traceability partial (3 GAPs). **Corrected mid-session:** `co_stock_claims`
  has FK `ON DELETE CASCADE` to `co_cases` (mig 016) → claims pruned on case delete; only
  `co_stock_events` (no FK) survives. Earlier "claims survive" claim was wrong.

## Next Steps (priority order)
1. **Push + deploy Phase 1** when ready: branch → PR/merge to `main` (TinsuAI/co runner
   auto-deploys ~1-2min). Smoke: chốt a sheet, confirm no lock banner; chốt over-claim still 409s.
2. **Phase 2 — split "Load BOM" (structure only) from "Tính bảng kê" (allocation).** Currently the
   "Load BOM" button hits `/calculate` which does both + cascade + (was) A. Split → `bom_loaded`
   status. `prepare_case_origin_sheet` (`co_case_context.py:939`) is separable but needs refactor
   (BOM-expansion fused with allocation in `origin_material_from_bom_row`; overrides keyed by
   material row index). User asked for this. Own `/discover` first.
3. **Phase 3 — clean Tồn CO lot-history noise** (chốt+mở-chốt both logged → noisy). Keep data,
   change display (net per case / draft-vs-committed). Pair with delete-case audit R1/R2/R3.
4. **UI backlog (`.ai/BACKLOG.md`):** B1 "Đổi công ty"/"Đổi hồ sơ" → modal; B2 review workflow
   step-status display (overlaps Phase 2); B3 bảng kê column layout (select clipped, STT too wide,
   Mã NVL too wide / tên NVL too narrow); B4 full-width case UI (drop 2-side border).
5. Feedback backlog: #14 (BOM default per code), #13 (batch chốt BOM, /discover), #4 (DH substitute
   ranking via api-request).
6. Backlog audit follow-ups: delete-case GAP A/B/C (case identity on events, soft-delete/tombstone,
   case_delete event); F1 trừ-lùi import unit-guard (`.ai/audits/2026-06-07-trului-...`); DH
   regression route-guard test confirmation.

## Notes for Next AI Session
- **Branch state:** on `co-stock-detangle-phase1`, NOT merged. `main` is the last deployed state.
  Working tree clean. Deploy = push `TinsuAI/co main` (memory `deploy-remote-tinsu-co`).
- **Local dev:** `npm run co:serve` → `127.0.0.1:8001` (auth off, `--reload`). Server was restarted
  this session (it died on a reload cycle); reuse if running, else restart. PG `barry_co` via unix
  socket (`.env BARRY_DATABASE_URL`). growatt cases persist in PG; johnson-vn cases on HTTP are
  in-memory seed.
- **Tests:** `uv run pytest` file-mode (no .env) = 483 passed. **DB-backed tests need `.env`
  sourced** (`set -a; . ./.env; set +a`) — file-mode no-ops the ledger → DB tests skip/false-green
  (memory `test-env-filemode-vs-datahub`). New concurrency test uses 2 real psycopg connections +
  seeds `co_stock_rows`; skips without `BARRY_DATABASE_URL`.
- **Prod is `--workers 1`** (`Dockerfile:30`) → the over-claim race is latent there; the FOR UPDATE
  matters for any future multi-worker. `co_stock_rows` PK = `(client_id, source_row)`.
- **zsh gotcha:** quote grep `--include="*.py"` (bare `*.py` gets glob-eaten); use `command grep`.
- **Don't redo:** mutex A — decided removed (was orthogonal to stock safety, verified). E (sheet
  order) — keep, it determines allocation result. Service token — decided not to add.
