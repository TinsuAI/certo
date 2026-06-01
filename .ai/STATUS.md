# Project Status

## Current State
- Local `main` at `e777144`. **Deployed commit (demo) = `8fe944a` on `tinsu/main`**
  (CI/CD green, Deploy demo OK). The `e777144` screenshot reorg is **committed
  locally only — NOT pushed/deployed** (docs-only, no app change). Working tree clean.
- Local suite **419 passed + 8 skipped** (file-store/CI mode).
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
2. **(optional) Push the reorg** `e777144` to origin+tinsu if you want the
   feature-folder layout on remotes (currently local-only).
3. **(optional) Cleanup leftover tracked screenshots:** `co-case-overview-lock` (11)
   and `data-hub-e2e` (5) PNGs are still committed under `.ai/screenshots/`; the rest
   of `.ai/screenshots/` is unsorted verification/audit (ignored).
4. **Older deferred:** origin lock TTL cleanup; customs FX historical backfill; seed
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
