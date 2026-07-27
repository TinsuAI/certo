# 2026-07-27 — CO 524 timeouts on case-open + substitute modal (narrow-fetch fixes)

Prod barry-co = nightly demo-co = **`8556ee1`** (3 commits this session, CI/CD green; behavior verified live).
Full suite **935 pass / 14 skip**.

## Context (client feedback, 2 items)
1. **Data Hub** — importing new BCCT for Johnson VN: "Xác nhận thay đổi BCCT" screen, yellow/green "đơn vị
   tính khác họ (604)" unclear, and **"Apply confirmed changes" stays disabled** despite ticking "51 dòng đã đổi".
   → This is the `data-hub` repo (guardrail: CO does not touch DH). **Handed to the user as a ready-to-paste
   `/diagnosing-bugs` prompt** to run a parallel session in `data-hub`. NOT fixed here. Hypothesis relayed:
   the 604 unit-family rows are a separate confirm gate — yellow (no conversion factor) block Apply until
   "+hệ số" is set; the "51 dòng" checkbox only covers the 51 changed rows.
2. **CO** — opening a case (`/clients/johnson-vn/co-case/co-case-1919b9cf8fbf`) → **Cloudflare 524**
   (origin timeout >100s), intermittent, F5 sometimes works. **This is what we fixed.**

## What Was Done
Two independent root causes, both = the shipment/substitute paths doing the full Data Hub catalog pull
(65k BCCT + 12k materials, sequential paginated HTTP) synchronously on the async event loop, which scaled
past Cloudflare's 100s limit as Johnson grew to ~73k BCCT rows.

### Fix 1 — shipment landing tab 524 (`544840e`, deployed + verified live)
- **Root cause:** `DataHubPortfolioService.co_case_source_context` skip-heavy branch (`data_hub_client.py:886`)
  had `if skip_heavy_context and not export_declaration_nos:`. Cases with an export declaration number (how
  Johnson always creates dossiers) were EXCLUDED → fell through to the full `list_materials` + `list_bcct`
  pull. `co_case_detail` (`co_case.py:1076`) is `async def` calling sync `co_case_context` → blocks the loop.
- **Fix:** route export-declaration cases in the light path through `origin_invoice_matches` (narrow
  per-declaration `list_bcct(declaration_no=)` + `match_case_bcct_exports`) — the SAME fetch the origin tab
  has used in prod since 2026-05-31 (proven byte-identical, 43/43 on Johnson). Invoice-only cases unchanged.
- **Measured on prod (case co-case-1919b9cf8fbf):** **124.88s → 0.31s**, same 2 invoice_matches
  (TK 308336942340, MFW0507-39 + MFW0504-39). 90 HTTP calls → 3.
- Test: rewrote `test_skip_heavy_context_still_paginates_for_export_declaration_cases` →
  `test_skip_heavy_context_export_declaration_uses_narrow_declaration_fetch` (asserts narrow declaration
  fetch, no materials pull, no full-catalog bcct pull). Red→green confirmed.

### Fix 2 — substitute modal 524 (`c104615`, deployed + verified live)
- **Root cause (found by the fable review of fix 1):** `co_case_origin_sheet_substitute_candidates`
  (`co_case.py:2384, 2423`) calls `co_case_source_context_cached` = the full ~125s heavy pull, **but only
  reads `material_rows`** from it (BCCT/stock fetched then discarded). Cold cache (90s TTL rarely covered) →
  full pull → 524 on the origin step. Fix 1 removed the incidental cache-warm that used to come from the
  slow landing request, so this became the primary remaining 524.
- **Fix:** new `DataHubPortfolioService.material_catalog` (materials-only, filters `category != "tp"`,
  identical to the heavy path's material_rows logic) + `co_case_material_catalog_cached` in
  `co_case_context.py` (client-wide TTL 300s cache; file-store/test mode falls back to the cheap in-memory
  source-context path). Both call sites swapped to it.
- **Measured on prod:** substitute cold path **~125s → 15.69s** (materials-only, 14 calls, **0 bcct calls**),
  12943 rows (= same count the heavy path produced); repeat opens hit the client-wide cache.
- Tests: `tests/test_substitute_modal_no_full_pull.py` — (a) `material_catalog` materials-only/no-bcct/tp
  filter; (b) `co_case_material_catalog_cached` uses catalog + caches, never heavy; (c) endpoint heuristic
  path never calls the heavy source context (drives the async endpoint via `asyncio.run` + spies, red→green).

### Fix 2 correctness lock (`8556ee1`, test-only)
- `test_material_catalog_equals_heavy_path_material_rows` — parity test: `material_catalog()` ==
  `co_case_source_context()["material_rows"]` byte-for-byte. Guards the two paths from drifting.
- Added after the user asked to verify the "chỉ list_materials" change can't break downstream calc.

## Decisions Made
- **Reuse the existing narrow paths, don't invent new DH endpoints** (CO-consumer guardrail): fix 1 uses
  `origin_invoice_matches` (already in prod); fix 2's `material_catalog` wraps `list_materials` (already used
  by the heavy path). No new Data Hub contract.
- **Deploy both fixes to prod immediately** (user: "commit và deploy luôn"). Committed only the fix files
  (never the pre-existing `.ai/BACKLOG.md` / `uv.lock` working-tree changes). Pushed main → prod CD.
- **Substitute fix caches client-wide (300s)**, not per case+shipment/90s like the old path — the material
  catalog is client-wide, so this is more correct (shared across cases) and the only visible effect is
  suggestion-list freshness (≤5 min), never a calculation number.
- **Deferred H2 (async-offload):** `co_case_detail`/`co_case_step` are `async def` calling sync
  `co_case_context`, so the ~15s materials pull (fix 2) and any sync work still block the event loop — but
  15s < 100s so no 524. Making these handlers non-blocking is a separate robustness follow-up, not urgent.

## What Didn't Work / dead ends avoided
- Could not run the FIXED `co_case_source_context` on prod before deploy (container ran old code) — measured
  the constituent narrow calls (`origin_invoice_matches`, `material_catalog`) instead as read-only proxies,
  then verified the full path live after each CD.
- The substitute endpoint has `try/except` around the catalog fetch, so a RED test could not rely on raising
  from a monkeypatched heavy call (it gets swallowed) — used call-count spies (heavy vs narrow) instead.
- fable flagged two NON-blocking parity nuances (both accepted, ticketed as follow-ups, see Open Items):
  narrow fetch omits `include_material_identity` (item_code display code vs raw on non-origin cold window,
  no calc impact); declaration_no exact-match vs the heavy path's `[^A-Z0-9]` strip (VN declarations are
  pure digits → equal in practice, no parity test).

## Open Items
- **data-hub feedback #1** (yellow/green + Apply disabled): user running a parallel `/diagnosing-bugs`
  session in the `data-hub` repo with the prompt provided. Answer for the client + any bug fix land there.
- **Follow-up A (low):** shipment/substitute narrow fetch omits `include_material_identity="true"` →
  `item_code`/`material_identity` may show raw customs code instead of display code on non-origin tabs in the
  cold window. Display-only, no calc impact. Fixing means adding the flag in `origin_invoice_matches`
  (`data_hub_client.py:962-966`) which is shared with the origin tab — needs its own test (could shift
  origin behavior), so ticket, don't hot-patch.
- **Follow-up B (H2, medium):** make `co_case_detail`/`co_case_step` (and the substitute endpoint) not block
  the event loop on the sync catalog pull (offload to a thread / precompute). Removes the residual ~15s
  first-open stall and stops one slow request from stalling others.
- **DH-side (info):** BCCT pagination is ~1.4s/1000-row page — fine now that CO doesn't pull the full corpus,
  but a per-page slowness worth noting if any full-pull path resurfaces.

## Verify / how it was proven
- Prod read-only harnesses (scratchpad, gitignored temp): timed the cold path before (124.88s) and after
  (0.31s shipment; 15.69s substitute materials-only, 0 bcct) via `ssh tinsu` → `docker exec -i co-app-1
  python -` using `data_hub_client_from_env()` (service token from the prod config file).
- CI/CD green on all three commits (`gh run watch --exit-status` = 0); ✓ Deploy on tinsu + ✓ Refresh nightly.
