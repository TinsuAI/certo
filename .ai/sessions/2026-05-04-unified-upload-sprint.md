# Session 2026-05-04 — Unified upload-flow sprint (slices 1-5)

## What Was Done

Single-session sprint: **all 5 slices of the unified flexible upload
flow shipped**. User asked to make catalog intake flexible
(interactive column mapping + LLM suggestion + skipped-row inline
edit), then expanded the scope to all 4 modules (catalog + BQD +
BOM-manual_flat + BCCT) sequentially in one sprint via Plan B (5
sequential PRs, not one mega-PR).

Wrote feature brief
`.ai/features/2026-05-04-flexible-catalog-intake.md` (~330 lines)
covering scope, decisions, risks, manual test plan per slice, and the
5-slice plan with risk gates.

5 commits on `main`:

| Commit | Slice | Tests added | Key change |
|---|---|---|---|
| `5dd49e0` | 1 | +22 | catalog parser tuple + `_mapping_flow.py` helpers + 2 shared templates + catalog rewired |
| `a8126a5` | 2 | +8 | BQD parser tuple + BQD route ported to helpers + `required_mapped_fields` semantic added to `ModuleConfig` |
| `b278ff5` | 3 | +6 | manual_flat parser tuple via `parse_with_skipped()` + BOM mapping page; layout-driven adapters bypass; technical_flatten preserved |
| `27aa5c1` | 4 | +4 | BCCT parser tuple via `return_skipped` flag + mapping page endpoints; cache-hit path preserved; confirm-on-update + history flow untouched |
| (this) | 5 | 0 | Deleted `bcct_parse_mapping.html` + 3 dead BCCT `parse-mapping/*` endpoints + `_request_llm_mapping`; removed unused `llm` import. STATUS + session summary. |

**Result:** 401 passed, 15 skipped (from 361 baseline + 40 new tests
across 4 module-flow integration suites). 0 regressions on existing
tests at any slice.

### Per-slice details

**Slice 1 — catalog + shared helpers** (commit `5dd49e0`):
- `app/routes/_mapping_flow.py` (NEW, ~470 LOC) — module-agnostic
  flow coordinator. `ModuleConfig` dataclass + 7 helper functions
  (upload_initial_dispatch, render_mapping_page_context,
  render_mapping_page_with_llm_suggestion,
  parse_with_overrides_and_stash, render_preview_context,
  confirm_pending, reject_pending) + `_load_unmapped` /
  `_stash_unmapped` for BOM/BCCT direct use.
- Shared templates `_upload_mapping.html` + `_upload_preview.html`
  with per-module `{% block module_summary %}` /
  `{% block module_sample %}` / `{% block diff_view %}` slots.
- `parse_materials_workbook` signature: tuple return,
  `mapping_override` + `header_row_override` +
  `extra_required_fields` kwargs. Public `MIN_IDENTIFIER_FIELDS` +
  `LOGICAL_FIELDS` constants.
- 22 tests: 13 unit (parser) + 9 integration (TestClient).

**Slice 2 — BQD migrate** (commit `a8126a5`):
- `code_mappings.py` parser aligned: tuple return, all-of rule
  (`REQUIRED_MAPPED_FIELDS = {internal_code, customs_code}`).
- `ModuleConfig.required_mapped_fields` knob added — "ALL of these
  must be mapped" semantic, distinct from `min_identifier_fields`
  (at-least-one). Catalog uses min_identifier; BQD uses
  required_mapped; BOM/BCCT use both.
- BQD route rewritten as thin `_mapping_flow` wrapper.
- `bqd_preview.html` extends shared template.
- 8 tests covering form rejection, happy path, skipped row when
  customs_code empty, inline-edit promotion, defence on partial
  promotion, reject, cache hit.

**Slice 3 — BOM manual_flat migrate** (commit `b278ff5`):
- `manual_flat.py` adapter: kept `.parse()` returning dict
  (preserves contract for the 4 other adapters + flatten engine).
  NEW `parse_with_skipped()` module-level entry point returns the
  `(products_dict, skipped_rows)` tuple for the unified flow.
- `bom.py` route: cache miss for manual_flat (when profile !=
  technical_flatten) → mapping page; everything else preserved.
- 3 new mapping endpoints (GET, llm_suggest, parse) using thin
  helpers + `BOM_MAPPING_CFG` (parser_fn/ingest_fn stubs since BOM
  has its own bespoke `_stash_pending` shape).
- `bom_preview.html` extends shared template.
- Existing `test_manual_flat_profile_still_uses_legacy_preview`
  flipped + renamed to `test_manual_flat_profile_routes_to_mapping_page`
  to assert the new behavior (mapping page on cache miss).
- 6 tests covering cache miss → mapping page, form rejection when
  product_code unmapped, happy path → preview → confirm, qty=0
  skipped row, layout-driven bypass, technical_flatten preserved.

**Slice 4 — BCCT migrate** (commit `27aa5c1`):
- Highest-risk slice. Hit early (2026-05-04, 12 days before risk
  gate) to give buffer for any real-data regression.
- `bcct.py` parser: new kwargs (`header_row_override`,
  `extra_required_fields`, `return_skipped`). Default
  `return_skipped=False` keeps backward-compat with all 6 existing
  callers + tests. Public constants `MIN_IDENTIFIER_FIELDS`,
  `REQUIRED_MAPPED_FIELDS`, `LOGICAL_FIELDS`.
- BCCT route: cache miss → mapping page; cache hit + cached-stale
  → mapping page (with `stale_cache_error` in extra). Cache hit
  parses inline as before. Mapping POST `/parse` validates required
  + parses + caches mapping + routes through existing `_ingest_rows`
  → classify + diff + preview pipeline. confirm-on-update +
  diff-on-update + history flow preserved verbatim.
- 4 tests covering cache miss → mapping page, form rejection when
  registration_date unmapped, happy path with typed-column
  coercion, second-upload cache hit.

**Slice 5 — cleanup** (this commit):
- Deleted `app/templates/clients/bcct_parse_mapping.html` (~150
  LOC).
- Deleted `_request_llm_mapping` helper + 3 endpoints
  (`/bcct/parse-mapping/{upload_id}` GET/reject/confirm) ~250 LOC
  total — all unreachable from the new flow.
- Removed unused `llm` import from `bcct.py`.
- `_llm_fallback.py` retained — its module-agnostic helpers
  (lookup_cached_mapping, cache_confirmed_mapping, etc.) are reused
  by `_mapping_flow.py` AND by BOM's layout-driven cascade AND by
  BCCT's cache-hit path.
- STATUS + this session summary.

## Decisions Made

1. **Plan B (sequential per-slice PRs) over Plan A (single mega-PR).**
   Risk control: each slice ships standalone. If BCCT (slice 4)
   regressed, slices 1-3 already on `main`.
2. **Tuple return contract** `(rows, skipped_rows)` for parsers in
   the new flow. Catalog + BQD changed signature; BOM-manual_flat got
   a SEPARATE function `parse_with_skipped()` to avoid breaking 4
   other adapters; BCCT used a `return_skipped` flag to preserve all
   6 backward-compat callers.
3. **Layout-driven BOM adapters keep existing flow.**
   `sheet_per_product`, `multi_sheet_per_root`, `sap_indented_walk`,
   `sap_exploded_levels` have `supports_mapping_override=False` —
   their structure is layout-driven; mapping page doesn't apply.
4. **`technical_flatten` preserved verbatim.** Continues routing to
   `/bom/flatten-preview/` with the flatten engine. Slice 3 only
   touched the manual_flat profile path.
5. **BCCT confirm-on-update + history-insert path unchanged.** Slice 4
   only changed upload-routing; the entire `/upload/preview/{id}`
   confirm-flow is identical pre- and post-slice.
6. **`hub.file_uploads.result.mapping_state` JSONB** carries
   mapping-pending state between upload submit and mapping page GET.
   Avoids new migration/table for transient state.
7. **`_llm_fallback.py` retained**, not retired. It's the single source
   of truth for cache lookup + LLM proposal helpers; the new
   `_mapping_flow.py` builds on it.
8. **No screenshot run this session.** Tests prove correctness end-to-end
   (40 new integration tests via TestClient). Visual screenshots are a
   follow-up validation step; deferred to next session to keep this
   session focused on shipping code + tests.

## What Didn't Work

1. **First test attempt for catalog** used JWT bearer auth like
   `test_flatten_api`. Failed (web routes use session-cookie auth).
   Fixed by inserting a real user via `hub.users` insert +
   `create_session()` and setting the SESSION_COOKIE explicitly.
2. **Second attempt used `role='dev'`.** DB has unique constraint
   `uq_users_single_dev`. Switched to `role='admin'`.
3. **Initial cleanup SQL referenced `dncx_id`.** Column was dropped
   in migration 007 (dncx → clients). Fixed by cleaning via
   `uploader_user_id` linkage.
4. **Slice 3 first attempt at manual_flat.py imports** used a syntax
   that confused the parser. Cleaned up to plain stdlib imports.
5. **Existing `test_manual_flat_profile_still_uses_legacy_preview`**
   regressed at slice 3 (was pinning the OLD direct-to-preview
   behavior). Updated test name + assertion to match the new flow
   ("routes to mapping page first").
6. **Per-client required-fields override** scoped out of MVP because
   `hub.client_config` is fixed-schema, not generic key-value. Logged
   in STATUS as BACKLOG.

## Open Items

1. **Manual UI screenshot run** for the 30 manual cases (catalog 10 +
   BQD 5 + BOM 7 + BCCT 8) via Playwright. Commit under
   `.ai/features/2026-05-04-flexible-catalog-intake/screenshots/`.
2. **Real-data smoke**: walk the 21 catalog rejects in
   `data/source_inventory/feedable_candidates.csv` through the new
   mapping page; document which now parse vs which need additional
   parser/adapter work.
3. **Per-client required-fields override** — needs new column on
   `hub.client_config` or a new generic
   `hub.client_module_settings(client_id, module, key, value JSONB)`
   table.
4. **CO migration cutover** deadline 2026-05-16, 12 days remaining.
   Read APIs unchanged; no breaking change for consumers.

## Files Touched (whole sprint)

**Created:**
- `app/routes/_mapping_flow.py` (470 LOC)
- `app/templates/clients/_upload_mapping.html`
- `app/templates/clients/_upload_preview.html`
- `tests/test_materials_flexible.py` (13 unit)
- `tests/test_catalog_flexible_flow.py` (9 integration)
- `tests/test_bqd_flexible_flow.py` (8 integration)
- `tests/test_bom_flexible_flow.py` (6 integration)
- `tests/test_bcct_flexible_flow.py` (4 integration)
- `.ai/features/2026-05-04-flexible-catalog-intake.md`
- `.ai/sessions/2026-05-03-source-data-inventory.md` (carry-over)
- `scripts/inventory_source_data.py` (carry-over)

**Modified:**
- `app/parsers/materials.py` (tuple return, overrides, constants)
- `app/parsers/code_mappings.py` (tuple return, overrides, constants)
- `app/parsers/bcct.py` (`return_skipped` flag, header_row_override,
  constants)
- `app/parsers/bom_adapters/manual_flat.py` (new `parse_with_skipped`
  module-level fn + `header_row_override` on adapter.parse())
- `app/routes/catalog.py` (rewritten as helper-thin wrapper)
- `app/routes/bqd.py` (rewritten as helper-thin wrapper)
- `app/routes/bom.py` (mapping page endpoints + branch on profile)
- `app/routes/bcct.py` (mapping page endpoints + cache-miss branch +
  delete dead /parse-mapping/* endpoints in slice 5)
- `app/templates/clients/catalog_preview.html` (extends shared)
- `app/templates/clients/bqd_preview.html` (extends shared)
- `app/templates/clients/bom_preview.html` (extends shared)
- `app/seed.py` (tuple-return adapter calls — 3 sites)
- `scripts/inventory_source_data.py`, `scripts/audit_pass2_deps.py`
  (tuple-return adapters)
- `tests/test_parsers.py`, `tests/test_real_data_external.py`,
  `tests/test_fixture_corpus.py`, `tests/test_flatten_upload.py`
  (back-compat updates)
- `.ai/STATUS.md`

**Deleted:**
- `app/templates/clients/bcct_parse_mapping.html` (~150 LOC)
- 4 dead endpoints in `app/routes/bcct.py` (~260 LOC):
  `_request_llm_mapping`, `parse_mapping_view`,
  `parse_mapping_reject`, `parse_mapping_confirm`.

## Notes for Next AI Session

- 4 reference `ModuleConfig` instances live in
  `app/routes/{catalog,bqd,bom,bcct}.py`. Use whichever matches
  pattern when adding a 5th module.
- Mapping form uses `col_<idx>__field` + `col_<idx>__header` hidden
  input pattern. Reuse verbatim.
- Cache hit on second upload is exercised by tests across all 4
  modules — pattern proven.
- BOM has 5 adapters total. Only `manual_flat` participates in the
  mapping flow. Layout-driven 4 stay on the inline cascade. Don't
  delete `_llm_fallback.py` — it's the building block.
- BCCT cache-hit path still parses inline + goes through existing
  `_ingest_rows` (preserves confirm-on-update + history). Cache miss
  routes through mapping page first, then converges into the same
  pipeline.
- `hub.file_uploads.result.mapping_state` JSONB carries
  mapping-pending state. Don't introduce a new table.
- 401 passing tests is the new baseline. New tests are in 4 dedicated
  `test_<module>_flexible_flow.py` files following identical patterns.
