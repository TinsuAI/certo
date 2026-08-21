# Project Status

## Current State

**2026-08-21 — technical-debt pass. Both suites green, and the test suite no longer writes into
the live app data directory.**

| | Result |
|---|---|
| `uv run pytest` | 1182 passed, 19 skipped · **0 files under `data/local` modified** (was 39 per run) |
| `npm test` | 57 passed, 0 failed (was 54 passed / 3 failed) |
| Open GitHub issues on `TinsuAI/co` | none — all 17 closed |
| `TODO`/`FIXME`/`HACK` in `app/`, `tests/`, `scripts/` | none |

The 2026-08-20 redesign and bảng kê fixes remain merged and live: CO `0.18.0` / `e9875e5`
(`co-app-1`, `nightly-co-app-1`), Data Hub `0.22.0` / `0783ebf`. `version` did not move that
round — identify a build by `git_sha`.

## Recent Changes

- **`npm test` was red on three tests** (`tests/legal-lookup-server.test.mjs`). The fixtures
  carried an absolute `/home/vp/workspace/client/barry-CO/...` path — the pre-consolidation repo
  — so `isLocalAppPath` (a `startsWith(process.cwd())` check) stopped emitting the raw-binary
  compare-source link. One fixture also ran `mkdir -p` on that dead path, recreating the sibling
  directory `AGENTS.md` warns about on every run. Fixtures are now rooted at `process.cwd()`; the
  test that writes real files uses `mkdtemp` under the gitignored `temp/` instead of `data/`.
  `isLocalAppPath` now compares on a path boundary, so `barry-CO` is not treated as inside
  `barry-CO-main`. `7b36ffd`
- **The suite mutated live data on every run.** `data/` is a symlink to the live app data
  directory and every file-mode store root defaults inside it: a plain `uv run pytest` appended
  BCCT and BOM uploads plus snapshots to the shared `growatt` store, rewrote its 93 MB
  `bcct/state.json`, and rewrote `co-cases/clients/growatt/cases.json` and `do-thanh/config.json`
  — 39 files, measured. A session fixture now hardlink-mirrors `SOURCE_STORE_ROOT`,
  `BOM_STORE_ROOT`, `CLIENT_CONFIG_ROOT` and `CO_CASE_STORE_ROOT` into
  `temp/pytest-store-<worker>`. Reads still see the real corpus at no disk cost; writes land on a
  fresh directory entry because the stores write with `mkstemp` + `os.replace`. `49da24e`
- **Backlog reconciled against HEAD** — ten of the fourteen items the 2026-07-17 table left open
  are closed, most of them by the redesign round without this file being updated: T1, D1 parity
  harness, the B6 rate nit, LK1 dirty-before-lock, DC3b, ST1, P1-resid, Fix F (D2), M1 sub-bug 2.
  Each verdict cites the `file:line` that decides it. `2935090`
- **Fifteen `agent/*` branches from a 2026-07-30 parallel run had never reached `main`**, and
  that date has no session summary. The thirteen doc commits (~3,500 lines) are now cherry-picked
  onto `main`: three `.ai/reference/` subsystem maps, an operator runbook, a cold-open perf
  audit, a test-gap analysis, and six design/discovery briefs.
- **Operator guide site tracked** — `app/static/docs/huong-dan/` (76 KB page + 29 annotated
  screenshots) plus its brief and `shoot_guide.cjs`, untracked since 2026-07-28. `a0cf424`
- 30 agent worktrees removed from `.claude/worktrees/` (1.4 GB → 4 KB); all 30 branches survive.
  The directory is now gitignored.
- Last `datetime.utcnow()` replaced (`co_stock_materializer.py:193`) — the run's warning count
  went from 26 to 1.

## Next Steps

1. **Look at the live apps with real eyes.** Still not done. The redesign shipped reviewed only
   through screenshots. `/design` on each app shows the whole component system in one page.
2. **The guide screenshots predate the redesign** — all 29 show the old top-nav shell. Re-run
   `.ai/features/2026-07-28-co-datahub-guide-site/shoot_guide.cjs` (`NOLOCK=1` stops before Chốt,
   so a re-run consumes no tồn) against local CO `:8001` and Data Hub `:8754`.
3. **Both unmerged code branches were reviewed 2026-08-21. One landed, one is rejected.**
   - `agent/co524-async-offload` → **LANDED** as `03220aa`. Rebased onto current `main` (one
     conflict: `limit=min(limit,50)` → `search_limit`, resolved keeping `main`'s). Suite green
     at 1183 passed / 19 skipped. Its test is a real regression test — red on `main` with
     `assert 'MainThread' != 'MainThread'`.
   - `agent/fx1-form-x-scaffold` → **REJECT.** It encodes Form X as the Vietnam→Cambodia
     bilateral form under `17/2011/TT-BCT`; the agency's workbook shows their Form X is
     VCCI-certified under `05/2018/TT-BCT` (Form B's circular), used on a domestic on-the-spot
     delivery. Evidence and the correct entry are in `.ai/BACKLOG.md` under FX1. The branch can
     be deleted; FX1 itself is low priority and stays open.
4. **Architecture review of the CO case request path — user directive 2026-08-21**, captured as
   **P2** in `.ai/BACKLOG.md` with the full measurement. Short version: prod runs
   `uvicorn --workers 1`, so one event loop per container, and ten `async def` handlers still
   call the synchronous `co_case_context` (a blocking Data Hub pull, up to ~104s on Johnson)
   with no `await` — Nạp BOM, Tính, Chốt, Mở chốt, lưu, export, upload, delete, case list and
   calculation-payload. `03220aa` fixed the three hottest (case open, workflow step, thay-thế
   modal). A lone operator is unaffected; two on one container are not. **Do not patch these
   handler-by-handler before the architecture call is made** — the user's words were that the
   path is "loằng ngoằng và tạo độ trễ nhiều quá".
5. **Backlog items still open** (see the 2026-08-21 table in `.ai/BACKLOG.md`): M1 sub-bug 1
   (`get_bom_proposal` has 0 callers — CO-side wiring, no DH request needed), FX1, D1's
   `reason`/forced-full in the refresh response, D1 tombstone retry (partial), EX1 (deferred by
   decision), #12 grand-total shortage (needs client input).
6. **Data Hub commits carry no issue references**, which its own `AGENTS.md:104` requires. The
   four PRs of the redesign round all violate it. Other repo, pushed history.
7. **5,314 lines of inline JS in `co_case.html` have zero test coverage.**
8. **CI runs only `uv run pytest`** — there is no `node --test` step, which is why three red
   JS tests survived unnoticed until 2026-08-21.

## Blockers

None.

## Notes for Next AI Session

- **Dev servers**: CO `:8001`, Data Hub `:8754`. Port 8754 is pinned — CO's JWT issuer validation
  expects exactly that origin. Start Data Hub first or every CO page 503s.
- **`data/` is a symlink to the live app data directory.** Anything that writes a default store
  path writes real data. The pytest fixture covers the four roots the suite touches; a script run
  outside pytest does not get that protection.
- **The `growatt` BCCT store still holds the accumulated cruft** — 218 uploads and 217 snapshots
  (~90 MB) from test runs before the isolation fixture. Left in place deliberately; pruning live
  data needs its own verified plan. The 788 MB in `versions/` is real data.
- **`.gitignore` excludes `.ai/features/*/screenshots/`**, which contradicts the global rule that
  committed UI proof lives exactly there. Unresolved on purpose — it may be deliberate, since
  screenshots of real cases would carry client data.
- **`attach_origin_sheet_states` rebuilds each sheet state from an explicit key list.** Anything
  added to a sheet state must be carried there or it is stripped on the next attach.
- **The invariant harness (`tests/test_case_state_invariants.py`) produced three findings and all
  three were wrong.** Treat its output as a prompt to investigate, not as evidence. Its KNOWN
  GAPS are in the module docstring; gap 2 (the world is not isolated between runs) is now closed
  by the conftest fixture.
- **Do not exercise a route with a payload the real client never sends.** Three wrong verdicts
  came from exactly that.
- The 32 e2e scripts in `.ai/scripts/` are manual, need a live server, and hardcode real client
  case IDs.
