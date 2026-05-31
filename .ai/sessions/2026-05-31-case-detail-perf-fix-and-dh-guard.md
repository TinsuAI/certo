# Session: Case detail perf fix (shipment) + no-silent-local-fallback guard

2026-05-30 → 2026-05-31

Picks up from `.ai/sessions/2026-05-30-case-detail-perf-root-cause.md` (which
diagnosed the ~21s load and proposed Option A but did not implement it).

## What was done

### 1. Case-detail load perf — `skip_heavy_context` (Option A), DONE + prod-verified
The ~21s case-detail load came from `co_case_source_context` paginating the full
`list_materials` + `list_bcct` catalogs (12.5k + 66k rows for Johnson) on EVERY
step, including the default-landing shipment tab which only renders
`source_summary` + `invoice_matches`.

- Added `skip_heavy_context: bool = False` to
  `DataHubPortfolioService.co_case_source_context` (`app/data_hub_client.py`).
  When set AND the case has no `export_declaration_nos`, it returns
  `invoice_matches` from the lightweight `/v1/hub/bcct/invoice-matches` endpoint
  with empty `material_rows`/`stock_rows`, skipping the heavy pagination.
  Export-declaration cases fall through to the heavy path (they need the full
  BCCT pull for `match_case_bcct_exports`).
- Threaded the flag through the module wrapper + `co_case_light_context`
  (`app/main.py`) and the local `PortfolioService` (`app/portfolio.py`, no-op
  there). `co_case_light_context` passes `skip_heavy_context=(current_step != "origin")`.
- Tests: `tests/test_co_case_skip_heavy_context.py` (3) + updated 2 in-test
  `FakePortfolioService` fakes in `test_co_demo.py`.
- **E2E on local DH (johnson-vn real data):** heavy 39.7s → light 0.03s,
  82 → 2-3 round trips, invoice_matches parity preserved.
- **Prod-verified after deploy (Bearer JWT for `claude-check@local`):** shipment
  tab ~1.5–3.6s vs ~21s baseline (~7–10x).
- Commit `d28e237`.

### 2. No-silent-local-fallback guard — DONE (both failure branches)
User directive: when Data Hub (the source of truth) is unavailable, CO must
error, never silently serve the local file-store backup (`PortfolioService`),
which looked like success and is dangerous for a CO dossier app. User chose
"Cả hai" — cover both DH-off and DH-on-but-unreachable.

- **DH off + no escape hatch:** new `SourceBackendUnavailable` raised at the
  single chokepoint `get_portfolio_service()` (`app/portfolio.py`); handler in
  `app/main.py` → 503. New setting `allow_local_source` (env
  `CO_ALLOW_LOCAL_SOURCE`) is the escape hatch; `conftest.py` sets it "1" autouse
  so the whole suite still runs on the local backend.
- **DH on but unreachable:** app-level handlers in `app/main.py` —
  `httpx.TransportError` → 503, unhandled `httpx.HTTPStatusError` → 502. Fire
  only for UNHANDLED exceptions, so routes that intentionally catch DH 404s
  (fallbacks) are unaffected.
- Tests: `tests/test_source_backend_guard.py` (6).
- Commits `d28e237` (DH-off branch) + `dbb9315` (DH-unreachable branch).

### 3. Local dev `.env`
Pointed CO at the local Data Hub on :8754 (`DATA_HUB_ENABLED=1`,
`DATA_HUB_SERVICE_TOKEN=co-service`, `CO_AUTH_REQUIRED=0`). `.env` is gitignored.
`.env.example` documents the new `CO_ALLOW_LOCAL_SOURCE` flag.

## Decisions made
- **Option A (targeted flag) over Option B (split context into two phases).**
  Lower-risk; the heavy path is preserved verbatim for origin.
- **Guard at `get_portfolio_service()` chokepoint, not per-route.** Every
  source-touching route reaches it via the `PortfolioServiceProxy`, so one guard
  covers the whole app.
- **Keep local `PortfolioService`** behind the `CO_ALLOW_LOCAL_SOURCE` flag
  rather than deleting it — deleting would have rewritten hundreds of
  `test_co_demo.py` tests that run on the local backend. User agreed.
- Verified on real Johnson data in the local DH (12.5k materials / 66k BCCT)
  rather than synthetic stubs, because the magnitude only shows at scale.

## What didn't work / mistakes made (so next session doesn't repeat)
- **Split-commit churn.** Tried to land perf and guard as two separate commits
  via manual strip-and-restore of the interleaved `main.py`/`portfolio.py`; the
  edits failed mid-way (output truncation) and produced a broken commit
  (handler present, import missing → NameError). Recovered by `git reset --soft`
  to base and committing cleanly. Lesson: when two features interleave in one
  file, either commit together or use a worktree — don't hand-strip.
- **Shell `grep` is aliased** (`--include=*.py`); bare `grep` errors with
  "no matches found". Use `command grep` or the Grep tool. Also `__pycache__`
  `.pyc` files are git-tracked here.
- **Wrong case-id path on first prod benchmark** — used
  `co-case-0605189d5eea` minus the `co-case-` prefix → all 500. Real path needs
  the full `co-case-0605189d5eea` segment.
- A synthetic SQL seed attempt against DH failed (wrong schema; the table is not
  `hub.bcct` over the unix socket) — nothing was written; turned out DH already
  had a real export invoice (`VNG26050007`) so no seed was needed.

## Open items
1. **Origin tab is the new dominant bottleneck (HIGH).** Same prod case `/origin`
   = 34.5s / 140s / one 503 timeout. Profiled: `list_bcct` full 66k = 36.15s,
   BOM workspace ~22s. Origin only needs stock for the case's BOM materials
   (via `case_allocation_pool` / `material_catalog_index`), not all 66k — the
   substitute modal already uses `list_bcct_by_codes` for exactly this. Plan
   (narrow BCCT fetch), 2 risk points (RVC/LVC parity, `origin_build_signature`
   cache key), and the benchmark harness are all written up in STATUS Next
   Steps #2. Do `/discover` → `/tdd`, not a quick fix.
2. Items 3–7 in STATUS Next Steps unchanged (origin lock TTL, customs FX
   backfill, seed missing CO forms, HS↔form coherence, can_view_client non-bug).

## State at handoff
- Branch `main` synced with `tinsu/main` at `aab0957` (6 session commits:
  `d28e237` → `aab0957`). CI/CD auto-deployed; prod healthy (`/healthz` 200).
- Local suite: 389 passed, 7 skipped.
- Memory added: `no-silent-local-fallback.md`, `co-case-source-context-shapes.md`,
  `shell-grep-alias-gotcha.md` (+ MEMORY.md index entries).
- Local dev server on :8754 DH; CO dev server may need a restart next session
  (`npm run co:serve`, log `/tmp/barry-co-8001.log`).
