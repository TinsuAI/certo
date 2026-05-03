# Project Status

**Date:** 2026-05-04

## Current State

Data Hub MVP web app is running and broadly functional. Slice 1 of the
**unified flexible upload flow** has shipped — catalog upload now goes
through an interactive 2-stage column-mapping flow with cache-hit fast
path, LLM suggestion (opt-in), and skipped-row inline-edit on preview.
Pattern + shared helpers are proven on catalog and ready to port to
BQD / BOM-manual_flat / BCCT in slices 2-4.

HEAD: `5dd49e0 feat(uploads): unified mapping flow — slice 1 (catalog + shared helpers)`.

Dev server expected at `http://127.0.0.1:8754` (required port).
Test suite: **383 passed, 15 skipped** (was 361 baseline + 22 new tests).
0 regressions.

## Recent Changes (this session, 2026-05-04)

- Wrote feature brief
  `.ai/features/2026-05-04-flexible-catalog-intake.md` (~330 lines)
  scoping the 5-slice unified-upload-flow plan across all 4 modules.
  Plan B chosen (sequential per-slice PRs) over Plan A (single mega-PR).
- **Slice 1 shipped** (commit `5dd49e0`):
  - Materials parser: tuple return `(rows, skipped_rows)`,
    `mapping_override` + `header_row_override` + `extra_required_fields`
    kwargs, public `MIN_IDENTIFIER_FIELDS` + `LOGICAL_FIELDS` constants.
    All callers updated.
  - `app/routes/_mapping_flow.py` (NEW) — module-agnostic flow coordinator:
    `ModuleConfig` dataclass + `upload_initial_dispatch`,
    `render_mapping_page_context`, `render_mapping_page_with_llm_suggestion`,
    `parse_with_overrides_and_stash`, `render_preview_context`,
    `confirm_pending`, `reject_pending`.
  - Shared templates: `_upload_mapping.html` (raw 10-row preview +
    header picker + column-map grid + LLM-suggest button) and
    `_upload_preview.html` (skipped-rows inline-edit + confirm/reject).
    Per-module wrappers fill `{% block module_summary %}` /
    `module_sample`. `diff_view` block reserved for BCCT slice 4.
  - Catalog route rewired to use shared helpers; bespoke single-stage
    upload replaced with cache-aware 2-stage flow.
  - 22 new tests: 13 unit (parser overrides, skipped_rows shape,
    identifier rule, back-compat) + 9 integration via `TestClient`
    (cache miss/hit, mapping POST, skipped-row promotion, identifier
    defence, reject, second-upload cache hit).
- Prior-session inventory work committed separately as `89794b6`.

## Next Steps

Slices 2-5 of the sprint are pending. See
`.ai/features/2026-05-04-flexible-catalog-intake.md` for full slice plan
+ manual test cases per slice. Summary:

1. **Slice 2 — BQD migrate to shared flow.** Port `app/routes/bqd.py`
   from `_llm_fallback.py` to `_mapping_flow` helpers. Lowest-risk port
   (BQD already on the older shared helpers). ~6-8 new tests; manual
   cases 1-5.
2. **Slice 3 — BOM-manual_flat migrate; layout-driven adapter
   bypass.** Branch route on adapter capability:
   `supports_mapping_override=True` → unified flow; layout-driven
   adapters (`sap_indented_walk`, `multi_sheet_per_root`,
   `sheet_per_product`, `sap_exploded_levels`) keep direct-to-preview.
   Proposal-mode selector inserts AFTER mapping confirm. Manual cases 1-7.
3. **Slice 4 — BCCT migrate** (highest risk). Replace bespoke
   `bcct_parse_mapping.html` flow; preserve confirm-on-update +
   diff-on-update + history. Risk gate: if not done by 2026-05-14, ship
   1-3 alone and defer BCCT to next sprint to protect 2026-05-16 CO
   cutover. Manual cases 1-8.
4. **Slice 5 — cleanup + screenshots + handoff.** Delete
   `_llm_fallback.py`. Walk all 30 manual cases via Playwright;
   commit screenshots under
   `.ai/features/2026-05-04-flexible-catalog-intake/screenshots/`.
   Update STATUS, BACKLOG, sister-app notes.

Plus carryover from prior session:

5. Pick canonical intake batches from
   `data/source_inventory/feedable_candidates.csv` per client/module.
6. CO migration cutover deadline 2026-05-16.

## Blockers

None.

## Notes for Next AI Session

- Respond in Vietnamese with full accents when the user writes Vietnamese.
- Dev port **8754 is non-negotiable**.
- Read `_mapping_flow.ModuleConfig` + the `CATALOG_CFG` instance in
  `app/routes/catalog.py` as the reference template for slice 2-4
  configs. The `parse_with_overrides_and_stash` validates
  `min_identifier_fields` per module — define this carefully in each
  config (e.g., bqd needs `frozenset({"internal_code"})` since BQD
  always has internal_code as the join key).
- Test pattern: copy `tests/test_catalog_flexible_flow.py` and adjust
  CLIENT name + module path + parser-specific assertions.
- The mapping page form uses `col_<idx>__field` + `col_<idx>__header`
  hidden input pattern. Reuse verbatim across slices 2-4 for
  consistency.
- `hub.file_uploads.result.mapping_state` JSONB carries
  mapping-pending state between upload submit and mapping page GET.
  Don't introduce a new table for this.
- BACKLOG entry to add when next session opens: per-client
  `<module>.required_fields` override (deferred from slice 1 because
  `hub.client_config` is fixed-schema, not generic key-value).
