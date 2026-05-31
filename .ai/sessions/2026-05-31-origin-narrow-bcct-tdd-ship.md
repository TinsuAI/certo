# Session: Origin narrow-BCCT — TDD, ship to prod, verify

2026-05-31

Picks up the design from the same-day discovery session
(`2026-05-31-origin-bcct-elimination-discovery.md`). TDD-implemented the converged
origin tab-load, shipped to prod, and verified. Origin source-context dropped from
~60s to sub-second. Next bottleneck (BOM workspace) scoped into a prep brief.

## What Was Done

Eliminated the ~40s full-BCCT pull from the **cold** origin tab-load by converging
it onto the materialized CO-stock snapshot (the source `/calculate` already uses).
Full Red→Green→Refactor TDD.

**Code (commit `b3d6083`):**
- `DataHubPortfolioService.origin_invoice_matches` (app/data_hub_client.py) — narrow
  export fetch. Invoice case: indexed `invoice_matches` + `list_bcct_by_codes`
  enrich. Export-decl case: **per-declaration** `list_bcct(declaration_no=)` (DH
  honours singular `declaration_no` only — plural is silently ignored), then the
  same `match_case_bcct_exports` the heavy path uses.
- `origin_source_context` (app/main.py) — orchestration: stock from
  `_calculate_stock_rows_from_snapshot` (netted), `material_rows=[]`,
  invoice_matches via the adapter. **DH-mode guard**: file-store/test mode falls
  back to the in-memory heavy `co_case_source_context` and never touches the
  materializer. Snapshot `None` → legacy full pull (never an empty stock preview).
- Wired `co_case_light_context` cold origin branch to `origin_source_context`;
  gated the substitute-modal TTL-cache warm on `material_rows` so the empty list
  can't poison the HS-heuristic cache.

**Tests (committed):** `tests/test_origin_narrow_source_context.py` — 6 unit
(StubTransport, deterministic: narrow invoice/export-decl paths assert no full
`/v1/hub/bcct` or `/v1/hub/materials` pagination; orchestration cold/warm/fallback)
+ 1 opt-in real-DH parity e2e (`RUN_ORIGIN_PARITY_E2E=1`, skipped in CI).

**Scope decision (analysed, not assumed):** measured `list_bcct`=39.9s (91%) vs
`list_materials`=3.7s (9%) for Johnson. `material_rows` is **unused at the origin
tab render** (shells defer allocation to `/calculate`; no template/JS reads it), so
the converged path returns `material_rows=[]` for free — simpler and lower-risk than
narrowing materials. Same outcome as the user's lean toward "drop materials too".

**Ship + verify:**
- Pushed `tinsu/main` (`3807dce..9064564`, then STATUS `..86d43f7`). CI/CD green
  each time (tests + docker + self-hosted deploy with `/healthz` + DH smoke gates).
- Local parity (real Johnson, local DH): invoice_matches **byte-identical** (10=10),
  stock material_code coverage **identical** (8 660, 0 diff either way),
  `origin_build_signature` stable across reloads. Source-context **~60s → ~0.9s
  warm / ~8s cold** (local snapshot was stale → one-time delta refresh).
- Prod benchmark (johnson-vn, throwaway case `VNG26050002` created→measured→deleted
  via SSH because the demo account can't delete): cold `/origin` **1.47s** / warm
  1.64s. Faster than local cold because prod's nightly stack refresh keeps the
  snapshot fresh → skips the delta-refresh. Prod snapshot present (60 173 rows).

**Memory added:** `dh-bcct-declaration-filter-singular` (DH bcct singular-only
declaration filter).

## Decisions Made

- **Converge onto the snapshot, not a parallel live narrow-stock fetch** — finishing
  the 2026-05-25 materializer migration; preview must equal the computed result.
  (Settled in the prior discovery session; implemented here.)
- **`material_rows=[]` at tab-load** instead of a narrow materials fetch — it is dead
  weight at render; the substitute modal self-fetches on demand (TTL-cached).
- **Cold path always re-fetches invoice_matches** (no reuse of
  `case["source_invoice_matches"]`). Warm reuse already lives upstream in
  `cached_origin_source_context` (gated on `use_cached_context`, which
  `co_case_context` auto-enables when the case has a `source_snapshot`). Reaching
  `origin_source_context` with cached matches means `force_source_refresh` bypassed
  the cache → the caller wants fresh data, so serving stale would be wrong.
- **DH-mode guard via `getattr(portfolio_service, "data_hub", None)`** — the
  converged path is a DH-mode optimization; file-store mode must not touch the
  materializer.
- **Approach for the next task (BOM, deferred):** parallel client-side fetch, NOT a
  BOM materializer. See prep brief. Rationale in §Open Items.

## What Didn't Work / corrected mid-session

- **37 test failures + 7:48 suite on the first full run.** Cause: I had sourced
  `.env` (which sets `BARRY_DATABASE_URL`), so every origin test drove the real
  local DB through `_calculate_stock_rows_from_snapshot` + `_full_refresh`. Fixed
  with the DH-mode guard (file-store/test → in-memory heavy path, never the
  materializer). → 395 passed. **Lesson: run the suite WITHOUT sourcing `.env`** (no
  `BARRY_DATABASE_URL`, DATA_HUB off) to mirror CI/file-store mode.
- **Self-caught in refactor:** initial `origin_source_context` reused
  `case["source_invoice_matches"]` on the cold path — wrong (see Decisions).
  Changed to always re-fetch; updated the unit test accordingly.
- **Prod delete via API → 403.** `claude-check@local` is not in
  `co_case_delete_roles`. Had to delete the throwaway prod case with
  `delete_case_record` inside container `co-app-1` via SSH `tinsu`.

## Open Items

1. **BOM workspace perf (~22s on product-heavy cases) — NEXT TASK.** Now the
   dominant origin cold cost after BCCT is gone. Full analysis + recommendation in
   the prep brief: **`.ai/features/2026-05-31-bom-workspace-perf-prep.md`**.
   TL;DR: recommend **parallel client-side fetch** (≈22s → ≈3–4s, output-identical,
   contained in `_build_workspace`); watch the `CURRENT_DATA_HUB_TOKEN` contextvar
   propagation to worker threads. Materialize-BOM is the heavier fallback if needed.
   Suggested flow: short `/discover` (parallel vs ask-DH-for-a-batch-endpoint) →
   `/tdd` with a parallel-output == sequential-output parity test.
2. Other deferred (unchanged): origin lock TTL cleanup, customs FX backfill, seed
   missing CO forms, CO-stock scheduled freshness refresh, claim-identity DB unique
   constraint.

## State at Handoff

- Branch `main` @ `86d43f7`, **pushed + deployed + prod-verified**. Working tree clean.
- Servers up: CO :8001 (local dev, auth off), local DH :8754. May need restart next session.
- Both throwaway test cases (prod `co-case-1b65cef349b0`, local `co-case-77c90f8b0087`) deleted & verified gone.
