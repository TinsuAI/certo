# Project Status

## Current State
- **On branch `refactor/split-main` (NOT merged, NOT pushed).** `main`/`origin/main`/
  `tinsu/main` = `861ec57` (deployed demo unchanged). The refactor branch is 11
  commits ahead — pure code-movement, no behavior change.
- **`app/main.py` split 8017 → 167 lines (-98%)** — now a pure app factory
  (lifespan + FastAPI() + mounts + include_router + exception handlers + auth
  middleware + number filter + a re-export shim for `app.main.X` test imports).
  Logic lives in `app/web/` (templating, deps, client_context gate,
  co_case_context closure) + `app/routers/` (auth, settings, customs_fx, catalog,
  co_case, bom, bcct, co_stock, cost_allocation, pages). See
  `.ai/sessions/2026-06-02-main-monolith-split.md` for structure, method, and the
  monkeypatch-namespace tax.
- **Large stores split** (all now <1000 lines, re-export shims preserve public API):
  `source_store` 1724→912 (+`source_workbook_io` 535, `co_stock_derivation` 270);
  `source_index_store` 1394→938 (+`source_index_records` 442; the
  `PostgresSourceIndexStore` class stays); `bom_store` 1251→976 (+`bom_workbook_io`
  188, `bom_composition` 89). Remaining follow-up: **merge `refactor/split-main` →
  `main`** (20 commits, all green; demo still at `861ec57`).
- Local suite **419 passed + 8 skipped** at every refactor commit (file-store/CI mode).
- **Client feedback batch 1 — #1/#3/#5/#6 DONE + live; #2/#4 need client input.**
  Plan/tracker: `.ai/features/2026-06-01-client-feedback-batch1/brief.md`.
  - **#1 manager delete** — `manager` in `DEFAULT_CO_CASE_DELETE_ROLES`. (prior session)
  - **#3 substitute empty/error** — reads materialized CO-stock snapshot. (prior session)
  - **#5 fuzzy multi-field search** — `app/material_search.py`. (prior session)
  - **#6 bulk-delete NVL rows in BẢNG KÊ** (this session). Per-row checkbox in a
    dedicated select column + per-sheet select-all + "Chọn dòng không có tồn/BCCT"
    quick-select + bulk bar, reusing the staged-delete path (mark + `pendingOps`,
    saved via "Lưu bảng kê"). **Note:** first mis-built on the dossier list — reverted.
  - **#2 "mở" load lâu** — fixed in prior sessions; **needs client to confirm** it
    feels fast now (else capture which step + client + timing).
  - **#4 substitute "chưa phù hợp"** — CO heuristic was prototyped then **dropped**
    (path rarely fires usefully; DH covers real materials). Real lever = DH ranking →
    **needs 3-5 bad-example codes from client** to file a DH API request.

## Recent Changes (this session)

| Commit | Topic |
|---|---|
| `13d0fcd` | feat(origin): #6 bulk-delete NVL rows + sheet-order modal; fix calculate hang |
| `dee8cc3` | docs: batch1 tracker (#4b dropped, #6 done) |
| `8fe944a` | ci(deploy): drop `# syntax=docker/dockerfile:1.7` (← this is the deployed tip) |
| `e777144` | chore(ai): Data Hub feature-folder layout for screenshots (local-only) |

Beyond #6, this session also shipped (all in `13d0fcd`, deployed via `8fe944a`):
- **fix "Đang tính…" stuck (the real client bug):** a BOM norm with >6 decimals
  (e.g. `3.351351351`) failed HTML5 `step="0.000001"` (stepMismatch) → the whole
  origin form was `:invalid` → clicking "Load BOM" **never fired a request**. Changed
  all numeric inputs to `step="any"`. (Server was never the bottleneck.)
- **perf:** `/calculate` reads the materialized co_stock snapshot directly + a
  non-blocking background refresh thread, instead of a synchronous full BCCT re-pull
  (~minutes for johnson's 60k rows) on every stale snapshot.
- **fix:** sheets stuck in transient `calculating` status are recovered as `stale`.
- **UI:** select checkbox moved to its own column (separate from STT); sheet reorder
  moved from misclick-prone inline tab arrows to a dedicated confirm modal.

## Next Steps (priority order)
1. **Close batch 1 — needs client input** (email drafted at
   `C:\temp\toss\barry-co-email-update-batch1.txt`):
   - #2: ask client if "mở" is fast enough now.
   - #4: collect 3-5 wrong-substitute examples (seed code + bad suggestion +
     expected) → file `.ai/api-requests/2026-06-01-substitute-ranking-quality.md`.
2. ~~Push reorg / cleanup leftover screenshots~~ **DONE** this session: reorg +
   handoff pushed to origin+tinsu, 16 leftover PNGs untracked (`861ec57`), demo
   redeployed green.
3. **Older deferred:** origin lock TTL cleanup; customs FX historical backfill; seed
   missing CO forms; HS↔form coherence; claim-identity DB unique constraint.

## Blockers
- **#4** blocked on client supplying concrete bad-example material codes.

## Notes for Next AI Session
- **Demo runs `8fe944a`, not local HEAD.** The reorg commit is local-only.
- **Deploy gotcha:** `# syntax=docker/dockerfile:1.7` was removed because the demo
  server can't reach Docker Hub for the frontend (`registry-1.docker.io i/o timeout`),
  which fails `docker compose up --build`. Don't re-add forced Docker Hub pulls. CI
  test/build jobs pass on GitHub runners, so green tests + red "Deploy on tinsu" =
  server infra, not code. See memory `deploy-docker-hub-frontend-gotcha`.
- **The "Đang tính" bug was client-side HTML5 validation, not server slowness.** If a
  form submit silently does nothing, check `form.checkValidity()` / `:invalid` inputs
  (number `step` mismatches). Use `step="any"` for any decimal field.
- **Screenshots:** now under `.ai/features/<slug>/screenshots/<run>/` (gitignored,
  local-only). Convention in `.ai/features/README.md`. Unsorted runs stay in the
  (ignored) `.ai/screenshots/`.
- **Shell quirks:** `ls` and `grep` are aliased oddly in this zsh — `ls` can print the
  wrong directory; use `find`/`command ls`/`command grep`. `.pyc` are git-tracked.
- **Dev server:** I restarted CO on `:8001` (`nohup npm run co:serve`, log
  `/tmp/co-serve.log`), `CO_AUTH_REQUIRED=0`, DH at `127.0.0.1:8754` (running).
- **New memories this session:** `substitute-heuristic-dead-path`,
  `bangke-bulk-row-delete`, `deploy-docker-hub-frontend-gotcha`.
- `#3`/`#6` staged-delete + snapshot paths only activate in Postgres mode
  (`BARRY_DATABASE_URL`); both local and prod satisfy this.
