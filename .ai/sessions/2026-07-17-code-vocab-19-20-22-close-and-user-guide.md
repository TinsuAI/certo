# Session 2026-07-17 (PM3) — code-vocab batch #18–#22 close + user guide

Started from `/ask-matt "tiếp tục xem còn việc gì"`. Surveyed remaining work, then
closed out the entire 2026-07-16 code-vocabulary batch and shipped a client-facing
user guide. End state: `origin/main = prod = nightly = dacb70d` (CI green, `/version`
verified both hosts), **`TinsuAI/co` = 0 open issues**, full suite **932 pass / 14 skip**.

## What Was Done

Four commits, all pushed + deployed + `/version`-verified (prod `barry-co`, nightly `demo-co`):

1. **`c1d8d9c` — user guide.** `docs/huong-dan-su-dung/` (VI operator guide: `README.md` +
   `Huong-dan-su-dung-CO-DataHub.pdf` + 22 screenshots) covering CO + Data Hub end-to-end,
   illustrated with the fictional `Demo Furniture Co.` (no agency data → committable).
   Reproduction tooling committed under `.ai/features/2026-06-20-co-datahub-user-guide/`
   (`seed_demo_furniture.py` + puppeteer `shoot_*.cjs`). Was fully built but untracked from a
   2026-06-20 session; this session just reviewed + committed it.

2. **`acb135d` — #19 (task 1 only).** Renamed the module-private `resolved_code`/`review_code`
   → `_resolved_allocation`/`_review_allocation` in `app/client_config_store.py` (resolves the
   3-owner token collision with DH `material_identity.resolved_code` and the `status=='resolved'`
   value). All callers are in-file; no persisted names; no behavior change. **NARROW-CLOSED** —
   tasks 2 and 3 deliberately not done (see Decisions).

3. **`daf1732` — #20.** `tests/test_code_identity_invariants.py` (4 file-mode tests) pinning
   INV-1 (a claim's `customs_code` == source lot's `customs_item_code`, via
   `stock_allocation_line` → lock route → `co_stock_claims`) and INV-2 (`co_stock_rows.material_code`
   holds the derived `allocation_code`, not the catalog code). Adapter/overload comments added at
   the 4 live sites: `co_case_context.py stock_allocation_line`, `routers/co_case.py` lock route,
   `co_stock_derivation.py`, `co_stock_workbook.py`. **Issue's line numbers had drifted** — annotated
   the current sites.

4. **`dacb70d` — #22 (investigation → decision + code).** Verified against the **live local DH DB**
   (`data_hub`, `hub.*` schema) that none of the three DH→CO normalization fallbacks erases a real
   distinction. Removed two dead links + added 10 contract tests
   (`tests/test_dh_normalization_fallbacks.py`). Zero behavior change → **no re-derivation** (corrects
   the issue's #14-S3 hedge).

**Issues closed on GitHub (six):** #14, #18, #19, #20, #21, #22. (#21's code `5838d2c` was already on
origin from before this session — only the issue was closed here. #15/#16/#17 were already closed.)

## Decisions Made

- **#19 tasks 2 & 3 dropped, not deferred-in-code.** Task 2 (push `allocation_code_*` prefixes into
  the `resolve_allocation_code` return shape) would rewrite the value-set that **#21 (`5838d2c`)
  canonicalized one day earlier** (`tests/test_allocation_code_provenance.py`) for marginal dedup —
  undoing just-merged deliberate work. Task 3 (rename `bom_product_code` locals → `product_code`) is
  **unsafe**: at `co_case_context.py:839,911,987` both values coexist as distinct BOM-match fallback
  keys (`bom_rows_by_product.get(product_code) or bom_rows_by_product.get(bom_product_code)`); the
  rename collapses two lookups into one — a silent behavior change in a high-risk area. `bom_product_code`
  is a real distinct concept there, not a stale alias. User chose narrow-close.

- **#22: keep all three fallbacks; remove two DEAD links; pin the contract.** The distinction-erasures
  the audit feared need row shapes the **DH schema cannot produce**:
  - `hub.materials` has `material_code` (NOT NULL, 0/13,588 blank) and **no** `customs_code`/`internal_code`
    column → case-1 `or customs_code` is dead; all fields correctly alias to `material_code`.
  - `hub.bcct_rows` has `customs_code` (declared) + DH-enriched `material_identity`, **no** `internal_code`
    column → case-3 `or internal_code` is dead AND mis-ordered (would prefer internal over the declared lot
    identity if a future contract added it). Removed it. Removed case-1 `or customs_code` too.
  - Empirical proof both clients: growatt-vn (declared ≠ internal) 33,748/38,287 stock rows have
    `customs_item_code` = the DECLARED code (`TUDIEN`), `allocation_code` = internal (`005.0001300`) — the
    fallback resolved to declared, not internal. johnson-vn (declared == internal) 60,173/60,173 collapse
    (null control). Guarantee is **schema-level, client-independent**; Growatt is the discriminating case,
    Johnson the null control (user pushed back on "why all Growatt" — answered in the tests: 3 layers).

- **Direct-to-main commits, push on explicit approval.** Matched the repo's recent history (all recent
  commits are direct on `main`). Asked before each push (prod CD). No AI co-author trailers (user rule).

## What Didn't Work / Gotchas

- **`ls -t .ai/sessions/` resolved to the project root** at session start (shell alias/profile quirk in
  this zsh). Use `command ls` with an absolute glob, or Glob, to list session files reliably.
- **`advisor` tool disabled** this conversation ("temporarily disabled") — made the #19 scope call solo.
- **Issue line numbers drift.** #20 and #22 both cited `data_hub_client.py`/`co_case.py` line numbers from
  2026-07-16 that no longer pointed at the right code. Grep for the symbol, don't trust the line number.
- **Foreground `sleep` is blocked** (harness) — poll background tasks via the completion notification or
  `gh run watch --run_in_background`, not `sleep && tail`.

## Open Items (all user-manual, no code)

1. **growatt-vn prod regex seed** — run `scripts/seed_growatt_vn_allocation.py` (`b98156a`) on prod
   `co-app-1` + nightly `nightly-co-app-1` (`docker exec -i {c} /app/.venv/bin/python - < scripts/...py`
   via `ssh tinsu`; vet container names + locked cases first). Applied LOCALLY only; prod/nightly still
   carry the broad regex → same blanked lots (`012.0001400`-style double-paren).
2. **Flag 2 NCC on growatt-vn** — `CONG TY TNHH MINGJIE VIET NAM` + `CONG TY TNHH MINGHUI VIET NAM` on
   `/clients/growatt-vn/suppliers` (verify spelling vs live BCCT; NEVER the HK namesake). Johnson = 0 flag.

Older backlog (unchanged, see STATUS Next Steps 0b–5): batch-flow F cold-start overclaim (D2), #12 total-tồn
SUM column, DC3a/DC3c rác, ranking #4 (DH-side), phase-2 in-bloc (deferred).

## Notes for continuity

- Local DH data is real and queryable: `psql data_hub` → `hub.materials`/`hub.bcct_rows`/`hub.clients`
  (johnson-vn, growatt-vn, demo-furniture). CO's own DB: `psql barry_co` → `set search_path=co;`
  (`co_stock_rows` has `customs_item_code`/`allocation_code`; `material_code` is NOT a persisted column —
  it lives in the derived in-memory dict / payload).
- `uv.lock` stays modified + uncommitted (local-only, per convention).
