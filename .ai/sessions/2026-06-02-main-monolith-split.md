# Session 2026-06-02 — Split the 8k-line main.py monolith

## What was done
Decomposed `app/main.py` from **8017 → 629 lines (-92%)** on branch
`refactor/split-main` (NOT merged, NOT pushed). 11 commits, **419 pytest pass +
8 skipped at every commit**; dev server `:8001` healthy throughout.

### New structure
- `app/web/` — shared layer (imported by routers; never imports `main`, so no cycle):
  - `templating.py` — `templates` Jinja instance, `theme_context`, theme consts
  - `deps.py` — `require_local_source_writes`, `large_request_form`
  - `client_context.py` — **the gate**: `resolve_client`, `client_context`,
    `_data_hub_overview_context`, `client_case`, `default_client_case`,
    `effective_min_gap_days`, `source_workspace_for_client`, `case_finished_hs_codes`
  - `co_case_context.py` (~2883 lines) — the **114-function co_case/origin/
    allocation helper closure** + workflow constants + shared mutable state
    (`_CO_CASE_SOURCE_CACHE`, `_co_stock_refresh_inflight`)
- `app/routers/` — `APIRouter` per domain, wired via `app.include_router`:
  - `auth.py`, `settings.py`, `customs_fx.py`, `catalog.py`
  - `co_case.py` (~2449 lines) — 30 co-case routes + 27 route-level helpers
  - `bom.py`, `bcct.py`, `co_stock.py`, `cost_allocation.py`
- `app/main.py` (629 lines) — app factory, middleware, exception handlers,
  lifespan, the remaining dashboard/config/evaluate/upload/export routes,
  `format_number_display`, and **re-export blocks** (`from app.web.* import (...)`)
  that keep `app.main.X` working for tests + the still-in-main routes.

## How (method)
- **Self-contained domains** (auth/settings/customs_fx/catalog) peeled directly.
- **Coupled core**: extracted the shared gate first (`client_context`), then
  the co_case closure, then routes — each via **AST scripts** that compute the
  transitive call-closure, classify external deps (imports vs constants vs
  cross-domain), generate the new module with a correct import header, strip the
  ranges from main, and convert `@app.*` → `@router.*`.
- **Re-export pattern**: main does `from app.web.<mod> import (...)` so existing
  `from app.main import X` test imports and intra-main call sites keep resolving
  without a circular import (web/routers never import main).

## The recurring tax (IMPORTANT for follow-up work)
Moving a module-global that tests swap **wholesale** (`monkeypatch.setattr(main,
"X", fake)` / `patch.object`) breaks behavior even with re-export, because the
moved code references `X` from its *own* module namespace. Fix applied: tests
that swap `portfolio_service`, `bom_service`, `co_case_source_context`,
`_calculate_stock_rows_from_snapshot`, `_refresh_co_stock_delta_or_full`,
`create_hq_bang_ke_workbook`, `_fetch_export_declaration_dates` now patch the
**new** namespace (`app.web.co_case_context.*` / `app.web.client_context.*` /
`app.routers.co_case.*`) — with the **same instance** when a singleton.
Patching an *attribute on* the singleton (`setattr(main.portfolio_service,
"method", ...)`) is fine (same object everywhere); only whole-object swaps need
the twin.

## What did NOT change
Zero behavior change — pure code movement. Route count unchanged (91). No app
logic touched. Baseline node suite still 53 pass / 3 pre-existing fails
(`legal-lookup-server.test.mjs`, unrelated).

## Open items / follow-ups (none block; all optional)
1. **Slim `main.py` to a pure factory**: move the leftover dashboard/`config`/
   `evaluate`/`upload`/`export`/`demo-input` routes into a `pages`/`misc` router.
2. **Remove dead imports in `main.py`**: ~100+ leftover imports (co_case-era) are
   now unused in the body. CAUTION: the `from app.web.* import (...)` re-export
   blocks are intentional — keep any name a test imports/patches via `app.main.X`.
   Removing the rest needs an AST pass that excludes test-required names, then
   full pytest.
3. **Split the large stores** (task 5): `source_store.py` (1724),
   `source_index_store.py` (1394), `bom_store.py` (1251).
4. Merge `refactor/split-main` → `main` (then optionally push; tinsu push
   redeploys demo).

## Pre-refactor batch-1 items (still open, unchanged this session)
#2 (mở speed) + #4 (substitute ranking) still need client input; email draft at
`C:\temp\toss\barry-co-email-update-batch1.txt`.
