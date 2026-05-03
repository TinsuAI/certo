# Project Status

**Date:** 2026-05-04 (late session — 5-slice unified upload sprint shipped)

## Current State

The **unified flexible upload flow** is shipped end-to-end across all
4 modules (catalog + BQD + BOM-manual_flat + BCCT). Cache-aware
2-stage flow with mapping page + LLM suggestion + skipped-row
inline-edit on preview, fully consistent UX across modules. Layout-
driven BOM adapters keep their existing direct-to-preview path;
technical_flatten preserved.

HEAD trail (newest first):

- `27aa5c1 feat(uploads): unified mapping flow — slice 4 (bcct)`
- `b278ff5 feat(uploads): unified mapping flow — slice 3 (bom manual_flat)`
- `a8126a5 feat(uploads): unified mapping flow — slice 2 (bqd)`
- `5dd49e0 feat(uploads): unified mapping flow — slice 1 (catalog + shared helpers)`
- `89794b6 chore(inventory): historical source-data inventory + .gitignore + STATUS`

Dev server expected at `http://127.0.0.1:8754` (required port).
Test suite: **401 passed, 15 skipped** (was 361 baseline + 40 new tests
across the 4 module-flow integration suites). 0 regressions on existing
tests at any slice.

## Recent Changes (this session, 2026-05-04)

- Wrote feature brief
  `.ai/features/2026-05-04-flexible-catalog-intake.md` (~330 lines)
  with the 5-slice plan; Plan B (sequential per-slice PRs) chosen
  over Plan A (single mega-PR).
- **Slice 1 (commit `5dd49e0`)** — catalog + shared helpers:
  `app/routes/_mapping_flow.py` (NEW), shared templates
  `_upload_mapping.html` + `_upload_preview.html`, parser tuple
  return, 22 tests.
- **Slice 2 (commit `a8126a5`)** — BQD migrate. Added
  `ModuleConfig.required_mapped_fields` (all-of semantics) since BQD
  needs both `internal_code` AND `customs_code` mapped. 8 tests.
- **Slice 3 (commit `b278ff5`)** — BOM-manual_flat migrate.
  `parse_with_skipped()` entry point on the manual_flat adapter;
  layout-driven adapters (`sheet_per_product`, `multi_sheet_per_root`,
  `sap_indented_walk`, `sap_exploded_levels`) keep existing flow;
  technical_flatten preserved. 6 tests.
- **Slice 4 (commit `27aa5c1`)** — BCCT migrate. Highest risk slice.
  Parser tuple return + new mapping page endpoints; cache-hit path
  preserved; the bespoke `parse-mapping/{upload_id}` endpoints
  unreachable from the new flow. 4 tests.
- **Slice 5 (this commit)** — cleanup: deleted `bcct_parse_mapping.html`
  + the 4 dead BCCT parse-mapping endpoints + `_request_llm_mapping`
  helper. `_llm_fallback.py` retained — its module-agnostic helpers
  (lookup_cached_mapping, cache_confirmed_mapping, etc.) are reused by
  `_mapping_flow.py` and by BOM's layout-driven cascade.

## Sprint outcome — what shipped

Across all 4 modules the upload flow now uses the same shape:

```
POST /clients/{c}/<m>/upload (file)
  → save blob → record_upload → compute file_signature
  ├─ cache hit (confirmed mapping) → parse → /<m>/preview/{id}
  └─ cache miss → /<m>/upload/mapping/{upload_id}

GET /<m>/upload/mapping/{upload_id}
  → raw 10-row preview + header picker + column-map grid
  → "Apply LLM suggestion" button (opt-in, no LLM call on page load)

POST /<m>/upload/mapping/{upload_id}/parse
  → validate min_identifier_fields + required_mapped_fields
  → parse with overrides → stash pending → /<m>/preview/{id}

GET /<m>/preview/{pending_id}
  → per-module summary + sample rows + skipped-rows inline-edit

POST /<m>/preview/{pending_id}/confirm
  → ingest + cache mapping (proposed_by='manual'|'llm')

POST /<m>/preview/{pending_id}/reject
  → discard pending, mark file_uploads as 'rejected'
```

Module-specific knobs:

- **catalog**: `min_identifier_fields={customs_code, internal_code}`
  (at-least-one); provenance toggle (registered vs user_added).
- **BQD**: `required_mapped_fields={internal_code, customs_code}`
  (both required); single-table upsert on (internal, customs).
- **BOM-manual_flat**: `required_mapped_fields={product_code,
  material_code}`; `extra_required_fields_default=("qty_per_unit",)`;
  layout-driven adapters bypass mapping page;
  technical_flatten → /flatten-preview unchanged.
- **BCCT**: `required_mapped_fields={declaration_no,
  registration_date, customs_code}`; mapping POST routes into existing
  `_ingest_rows` → classify + diff + /upload/preview/ → confirm-on-update +
  history-insert all preserved.

## Sprint outcome — what was NOT done

- **Manual UI screenshot run** (Playwright on the dev server walking
  the 30 manual cases). Tests pass end-to-end and prove the flow is
  correct, but visual screenshots are not captured. Deferred to a
  follow-up session — needs interactive browser automation that
  wasn't worth the session budget after 4 slices of code.
- **`_llm_fallback.py` retirement.** It's still used as the building
  blocks for `_mapping_flow.py` (lookup_cached_mapping, etc.) AND by
  BOM's layout-driven cascade and BCCT's cache-hit recovery path.
  Renaming would be churn; staying as-is.
- **Per-client `<module>.required_fields` override** (admin UI for
  per-tenant required-fields) — not implemented. Hard-coded minimums
  per module suffice for MVP. Logged as BACKLOG entry.
- **Real-data smoke** against the 21 inventory rejects in
  `data/source_inventory/feedable_candidates.csv` for catalog, plus
  the BQD/BOM/BCCT real fixtures. Tests prove correctness on
  synthetic fixtures; real-data smoke is a follow-up validation step.

## Next Steps

1. **Manual UI screenshot run** for the 30 manual cases (catalog 10 +
   BQD 5 + BOM 7 + BCCT 8). Commit screenshots under
   `.ai/features/2026-05-04-flexible-catalog-intake/screenshots/`.
2. **Real-data smoke**: walk the 21 catalog rejects through the new
   mapping page; document which now parse vs which need additional
   parser work (DKE BOM/định mức adapter, CO ToKhaiHQ7* adapter, etc.).
3. **Sister-app coordination** for CO migration cutover (deadline
   2026-05-16). Read APIs unchanged so consumers see the same shape;
   no breaking change. Optionally update `co-migrate-to-client-config`
   sister-app note with status.
4. **Ghost-code triage**: 200 unresolved Growatt BOM material codes
   from prior session.

## Blockers

None.

## Notes for Next AI Session

- Respond in Vietnamese with full accents when the user writes
  Vietnamese.
- Dev port **8754 is non-negotiable**.
- `app/routes/_mapping_flow.py` `ModuleConfig` has 4 reference
  configs (CATALOG_CFG in catalog.py, BQD_CFG in bqd.py,
  BOM_MAPPING_CFG in bom.py, BCCT_MAPPING_CFG in bcct.py). Use
  whichever matches your need as the template.
- The mapping page form uses `col_<idx>__field` + `col_<idx>__header`
  hidden input pattern. Reuse verbatim for any 5th-module config.
- `hub.file_uploads.result.mapping_state` JSONB carries
  mapping-pending state; don't introduce a new table.
- BOM has 5 adapters total. Only `manual_flat` participates in the
  mapping flow. The other 4 (`sheet_per_product`,
  `multi_sheet_per_root`, `sap_indented_walk`,
  `sap_exploded_levels`) are layout-driven (`supports_mapping_override
  =False`) and stay on the inline rigid+LLM cascade.
- BCCT cache-hit path still goes through inline `parse_bcct_workbook`
  + `_ingest_rows`; only cache miss routes through the new mapping
  page. This keeps friction-free repeat uploads + preserves all
  confirm-on-update + history semantics.
- Layout-driven BOM adapters and BCCT cache-hit paths keep using
  `_llm_fallback.py` helpers. Don't delete that module.
- Per-client required-fields override is a known BACKLOG item —
  needs a new column on `hub.client_config` (currently fixed-schema)
  or a new generic `hub.client_module_settings(client_id, module,
  key, value JSONB)` table.
