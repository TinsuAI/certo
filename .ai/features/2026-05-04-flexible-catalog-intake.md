# Feature: Flexible Upload Intake — Unified Across 4 Modules

**Status:** discovery brief, no code yet.
**Module scope:** **all 4 upload modules** — catalog + BQD + BOM (manual_flat adapter) + BCCT.
**Rollout:** sequential PRs within one sprint (Plan B): catalog → BQD → BOM-manual_flat → BCCT. Layout-driven BOM adapters (`sheet_per_product`, `multi_sheet_per_root`, `sap_indented_walk`, `sap_exploded_levels`) keep their existing flow; only `manual_flat` is unified.

## Why

**Catalog is the trigger, but the inconsistency is system-wide.** `parse_materials_workbook()` (app/parsers/materials.py:79) rejects 21 real client workbooks today with `"No material rows recognized; need at least one identifier column (Mã HQ / Mã NB)"` — see `data/source_inventory/feedable_candidates.csv`, filter `kind=catalog_materials, feedability=needs_parser_or_mapping`. The rejects span Growatt (`DANH MUC TP - BTP 2025.xlsx`), DKE (`BẢNG MÃ NVL-SP - Update *.xls`, `DS SP KHAI BÁO.xls`), Johnson (`DS_SP.xlsx`, `DS_NPL.xlsx`), and BCQT-System fixtures.

Beyond catalog: the codebase currently has **3 different upload UX shapes** for what is conceptually the same task ("upload Excel → confirm → ingest"):
- BCCT: bespoke older two-stage UI (`bcct_parse_mapping.html`).
- BQD + BOM-manual_flat: newer `_llm_fallback.py` shared helpers, but lazy mapping page (only on parse fail).
- Catalog: single-stage, no mapping page at all, fails hard on column-name mismatch.

A comment in `_llm_fallback.py` already calls out: *"BCCT … will be unified in a later refactor."* This is that refactor, plus catalog joins the unified flow as the design driver.

Goal: **one unified flexible upload flow** across all 4 modules, with shared route helpers + shared mapping/preview templates, where staff drives the column mapping with LLM suggestion as fallback. Same preview-confirm safety net as today.

## Scope

In (across all 4 modules):
- New 2-stage upload flow: **(a) raw-sheet preview + column mapping page** → **(b) parsed preview + confirm**. Replaces single-stage catalog flow, replaces lazy mapping in BQD + BOM-manual_flat, replaces bespoke BCCT 2-stage UI.
- Shared route module `app/routes/_mapping_flow.py`: module-agnostic helpers for cache lookup, mapping page render, parse-with-override, pending stash, preview render, confirm.
- Shared templates `clients/_upload_mapping.html` + `clients/_upload_preview.html` parameterised by module name (Jinja `{% include %}` from per-module wrappers).
- All 4 module parsers expose: `parse(blob, *, mapping_override=None, header_row_override=None) -> (rows, skipped_rows)` (signatures aligned).
- LLM column mapping via existing `propose_header_mapping` (module-aware; already works for BCCT/BQD/BOM).
- Per-client persistent mapping profile via existing `hub.parser_mappings` cache — confirmed mapping auto-applied on next upload with same file signature.
- Empty-required-cell handling: skip-with-reason, staff inline-edit + per-row include, reject-whole-upload. Source blob never mutated.
- Required-column policy: hard-coded minimum per module (catalog: `internal_code` OR `customs_code`; BCCT: `declaration_no` + `customs_code` + `direction`; BQD: `internal_code`; BOM-manual_flat: `parent_code` + `child_code` + `qty`). Per-client extras via `hub.client_config[<module>.required_fields]`.

Out (in this sprint):
- BOM layout-driven adapters (`sheet_per_product`, `multi_sheet_per_root`, `sap_indented_walk`, `sap_exploded_levels`): they already have `supports_mapping_override=False` and there is no column to map. These keep the existing direct-to-preview flow. Only `manual_flat` joins the unified flow.
- File-blob mutation (we never edit the source XLSX; "skip" / "delete" act on parsed-row set, blob stays in storage).
- "Parse different file format / wrong module" — file format detection stays as-is.
- BCCT confirm-on-update + diff-on-update history logic stays as-is (it triggers between preview-confirm and ingest, not in the upload→mapping→preview path; we just feed it the new shared preview output).

## Existing infra we reuse

| Piece | Status | Notes |
|---|---|---|
| `hub.parser_mappings(client_id, module, file_signature)` | exists (mig 012) | CHECK includes all 4 module values already |
| `compute_file_signature` (`app/parsers/_excel.py:216`) | exists | Stable hash over normalized headers per sheet |
| `app/llm.py:propose_header_mapping` | exists | Module-aware; works for all 4 modules |
| `app/routes/_llm_fallback.py` | exists | Module-agnostic helpers; absorbed by new `_mapping_flow.py` (which calls these underneath) |
| `mapping_override` parser knob | exists in BCCT + BQD + BOM-manual_flat parsers | Catalog parser gets it added; signatures aligned |
| `hub.upload_pending.parsed_rows / diff_summary` JSONB | exists | Skipped-rows + chosen mapping ride along in `diff_summary` |
| `hub.client_config(client_id, key, value)` | exists (mig 019) | Already used for per-client knobs; new keys `<module>.required_fields` |
| `clients/bcct_parse_mapping.html` | exists | Reference for what BCCT does today; replaced by shared `_upload_mapping.html` in slice 4 |

New code:
- `app/routes/_mapping_flow.py` — module-agnostic helper module (slice 1).
- `clients/_upload_mapping.html` + `clients/_upload_preview.html` — shared templates (slice 1).
- `header_row_override` knob added to all 4 parsers (slices 1-4).
- `parse(...)` signatures aligned to return `(rows, skipped_rows)` tuple in all 4 (slices 1-4).
- Module-specific wrappers in catalog/bqd/bom/bcct route files that delegate to `_mapping_flow`.

## State machine (module-agnostic; `<m>` = catalog | bqd | bom | bcct)

```
POST /clients/{c}/<m>/upload (file)
  ↓ save blob → record_upload → compute file_signature
  ├─ cache hit (confirmed mapping) →
  │     try parse with cached mapping_override →
  │     ├─ ok      → stash pending → /<m>/preview/{id}        (skip mapping page)
  │     └─ fail    → fall through to mapping page
  └─ cache miss / cached-failed →
        → render /<m>/upload/mapping/{upload_id}

GET /clients/{c}/<m>/upload/mapping/{upload_id}
  - show first 10 rows of first sheet (raw, pre-parse)
  - header row picker (<select> over rows 1-15; default = current header_row() heuristic)
  - column → field map (<select> per column, options = module's logical-fields enum + "ignore")
  - default mapping = rigid match attempt + LLM suggestion (if rigid <2 fields AND LLM enabled)
  - "Apply LLM suggestion" button → re-renders prefilled
  - submit → POST mapping

POST /clients/{c}/<m>/upload/mapping/{upload_id}/parse
  - re-parse with mapping_override + header_row_override (no DB write yet)
  - stash to upload_pending; chosen mapping goes into diff_summary.mapping
  - record into parser_mappings with proposed_by ∈ ('manual', 'llm')
  - 303 → /<m>/preview/{pending_id}

GET /clients/{c}/<m>/preview/{pending_id}
  - parsed-rows summary (existing per-module _summarize_*) + sample (20 rows)
  - NEW section: skipped_rows[] table — row_index, raw cells, reason, [include] checkbox + per-required-cell inline-edit input
  - NEW: "Reject upload" button alongside existing Confirm
  - For BCCT only: existing diff-on-update view stays (rendered after the mapping/skipped section)

POST /clients/{c}/<m>/preview/{pending_id}/confirm
  - merge user-included edits back into parsed_rows
  - existing per-module ingest path (insert/update target table, mark file_uploads done,
    mark mapping confirmed_at=now())
  - 303 → /<m>?ingested=N&skipped=M
```

### Module-specific tweaks

- **catalog:** delete-and-replace not applicable; just ingest. Provenance = registered/user_added (existing form field).
- **bqd:** confirm-on-update + history already present; preview integrates.
- **bom-manual_flat:** uses BOM proposal modes (manual/hybrid/auto) — preview adds proposal mode selector AFTER mapping confirm. Layout-driven adapters bypass the mapping page entirely (route detects adapter, skips to direct preview).
- **bcct:** confirm-on-update diff lives BELOW the skipped-rows section in preview. BCCT's existing per-typed-column logic preserved in parser; mapping just drives header→logical-field, parser handles typed-column coercion as today.

## Decisions

1. **All 4 modules unified, sequential PRs within one sprint.** Plan B chosen over plan A (single mega-PR). Each slice merges and tests green before next starts. Ordering: catalog (greenfield, lowest risk, design driver) → BQD (already on `_llm_fallback.py`, smallest port) → BOM-manual_flat (carry proposal-mode selector) → BCCT (highest risk, has confirm-on-update + history, last to ride proven pattern).

2. **Layout-driven BOM adapters stay on existing flow.** `sheet_per_product`, `multi_sheet_per_root`, `sap_indented_walk`, `sap_exploded_levels` have `supports_mapping_override=False` because their structure is layout-driven, not column-driven. Mapping page doesn't apply to them. Route branches on adapter capability: layout-driven → direct-to-preview (today's flow); manual_flat → unified flow.

3. **Persistent per-client mapping, not per-upload.** Storage: existing `hub.parser_mappings` (no new table). Cache hit → skip mapping page entirely → parse straight to preview. Cache key includes `client_id+module+file_signature`; signature ignores column order within a sheet so cosmetic reorder doesn't re-prompt. "Reset to default" = button on mapping page that soft-deletes the cache row.

4. **LLM is suggestion, not authority.** Mapping page always renders editable; LLM output (when enabled) only pre-fills the form. Staff click Save = confirmed. LLM disabled/down → page still renders with rigid auto-match + blanks. Sync call (~1-3 s), same pattern as today's BCCT.

5. **Required-column rule per module:**
    - catalog: `internal_code` OR `customs_code` (current implicit rule, made explicit).
    - bqd: `internal_code` (the join key).
    - bom-manual_flat: `parent_code` AND `child_code` AND `qty`.
    - bcct: `declaration_no` AND `customs_code` AND `direction`.

   Per-client extras via `client_config[<module>.required_fields]` JSON array. Defer per-module admin UI; ops sets via existing `client_config_ui`.

6. **Empty-required cell → skip-on-UI, NOT deny-whole-file.** Rows missing a required cell go into `skipped_rows[]` with `reason="missing_required:<field>"` + full raw snapshot. Preview UI:
    - default: NOT included on confirm
    - per-row "Include this row" checkbox
    - per-required-field inline `<input>` for staff to fill missing values
    - "Reject upload" button discards everything, logs reason
    - Source blob never mutated; everything in `upload_pending.parsed_rows` / `diff_summary.skipped_rows`.

7. **`skipped_rows[]` is provenance, not just UX.** Staff-promoted rows carry the original-skip-reason + filled-by + filled-value into the target table's `provenance` JSONB (catalog has `materials.provenance`; BCCT/BQD/BOM get per-table audit trail). Pure-skip rows logged in `hub.file_uploads` audit JSONB only.

8. **Aligned parser signatures.** All 4 parsers expose `parse_<module>_workbook(blob, *, mapping_override=None, header_row_override=None) -> tuple[list[dict], list[dict]]` returning `(rows, skipped_rows)`. BCCT/BQD/BOM-manual_flat parsers today already accept `mapping_override`; this sprint adds `header_row_override` everywhere and unifies the return shape (today they return only `rows`). Backwards-compat layer = if old caller imports the function and assigns to one variable, raises clean `TypeError` (caught in route, surfaces as 500 in dev). Migration: every existing caller updated in the slice that touches its module.

9. **Shared route helpers in `app/routes/_mapping_flow.py`.** Module-agnostic functions: `cache_lookup_or_render_mapping`, `render_mapping_page`, `parse_with_overrides_and_stash`, `render_preview_with_skipped`, `confirm_pending`. Each takes a `ModuleConfig` dataclass: `(name, parser_fn, summarize_fn, ingest_fn, required_fields_default, logical_fields_enum, preview_template, mapping_template_extras)`. Per-module routes are thin wrappers ~30 lines.

10. **Shared templates with per-module slot.** `_upload_mapping.html` + `_upload_preview.html` define the chrome (chrome = sheet preview, header picker, column-map grid, skipped rows, confirm/reject buttons). Per-module wrappers (`catalog_preview.html` etc.) `{% extends %}` shared and override the `{% block module_summary %}` slot for their domain-specific summary panel.

11. **BCCT diff-on-update preserved.** Today BCCT has a unique confirm-on-update flow that diffs new rows vs existing and shows added/changed/deleted/noop. This logic stays in `app/routes/bcct.py`'s confirm helper, called BETWEEN preview-confirm POST and ingest. The shared preview template gets a `{% block diff_view %}` slot that BCCT's wrapper fills; other modules leave empty.

## Risks

- **Cross-module regression during slice 4 (BCCT).** Highest risk in the sprint. Mitigation: BCCT goes last, reuses pattern proven on 3 modules; full BCCT regression suite (current ~150 BCCT tests) must stay green before merge; CO migration cutover (2026-05-16) coordinated AFTER slice 4 lands. If BCCT slice slips past 2026-05-14, ship slices 1-3 alone and defer BCCT to next sprint to protect cutover.
- **Helper API design hardens too early.** If catalog-only design misses something BQD/BOM/BCCT need, slices 2-4 force `_mapping_flow.py` rewrite. Mitigation: in slice 1, write the helper signature with all 4 modules in mind even though only catalog wires up; add a `pytest -m "needs_mapping_flow_signature_review"` marker on a stub test for each of bqd/bom/bcct so we know upfront if a missing knob blocks them.
- **Mapping cache poisoning across clients.** Mitigated: signature already includes `client_id+module`; cache row scoped per-client.
- **Inline edit corrupts data.** Edits restricted to required-field cells only, validated server-side, recorded in provenance. Not a free-form spreadsheet editor.
- **LLM bill blowout.** Existing per-client per-day budget (`llm_max_calls_per_day_per_client`, default 50) covers all modules combined; a single workbook = 1 LLM call regardless of module.
- **Multi-sheet workbook with mixed shapes.** Mapping applies to all sheets uniformly (today's behaviour). Per-sheet override deferred — not seen in the reject corpus.
- **Header-row pick wrong.** Mitigated: mapping page shows first 10 rows raw with row numbers; staff overrides. Default = current `header_row()` heuristic.
- **Cached mapping stale.** Cache-hit parse failure falls through to mapping page — staff re-confirms, row gets overwritten. Self-healing.
- **BOM proposal mode interplay.** BOM-manual_flat has the proposal-mode selector (manual / hybrid / auto). It must move from upload page to AFTER mapping confirm, BEFORE preview. Verify that mode change + cached mapping co-exist (cache stores mapping, not mode). Test in slice 3.
- **BCCT typed-column coercion + mapping override.** BCCT's `parse_bcct_workbook` already accepts `mapping_override`. Verify the typed-column path (declaration_date / quantity / value coercion) still runs after mapping override — should, but this is the most complex parser of the four. Slice 4 includes a real-data smoke against all known BCCT rejects and confirms typed columns survive.

## Manual test plan

### Slice 1 (catalog) — 10 cases

1. Growatt `DANH MUC TP - BTP 2025.xlsx` — cache miss → mapping page → LLM suggestion → confirm → preview → ingest.
2. DKE `BẢNG MÃ NVL-SP - Update Dec 31.xls` — `.xls` legacy + DKE column names; same flow.
3. Johnson `DS_NPL.xlsx` with `client_config[johnson-vn][catalog.required_fields]=["unit"]` → rows missing `unit` go to skipped_rows[]; staff inline-edit one row, include it, confirm → mixed ingest.
4. Re-upload Growatt (same blob) → cache HIT → skip mapping page → direct preview → confirm.
5. Re-upload Growatt with column renamed → cache MISS (signature changes) → mapping page re-prompts → new `parser_mappings` row.
6. Reject path — upload → preview → "Reject upload" → no `materials` change, `file_uploads.parse_status='rejected'`.
7. LLM disabled → mapping page renders with rigid-only + blanks → manual fill → confirm.
8. LLM unreachable (timeout) → mapping page falls back gracefully; no 5xx.
9. Synthetic file with no identifier column → mapping page renders → form validates "must map at least one of internal_code/customs_code" → block submit.
10. Mapping page edge: pick row 5 as header when heuristic picked row 3 → re-parse uses override → preview reflects.

### Slice 2 (BQD) — 5 cases

1. Growatt `BANG QUY DOI NVL.xlsx` — already parses today, run through unified flow; cache miss → mapping page → confirm → existing BQD ingest semantics preserved.
2. Growatt `BANG QUY DOI THANH PHAM.xlsx` — same.
3. Re-upload BQD (cache hit) → skip mapping → preview.
4. BQD file with one row missing `internal_code` → skipped_rows; staff inline-edit; mixed ingest.
5. BQD reject path.

### Slice 3 (BOM-manual_flat) — 7 cases

1. Manual flat BOM, well-formed → mapping page → confirm → proposal-mode selector page → manual mode → preview → ingest.
2. Same workbook, hybrid mode end-to-end.
3. Re-upload (cache hit) → skip mapping → proposal-mode → preview.
4. Layout-driven adapter (`sheet_per_product` Growatt PV file) → route detects `supports_mapping_override=False` → bypasses mapping page → direct preview as today (regression check).
5. BOM with rows missing `qty` → skipped_rows; staff fills qty=1 inline, includes; mixed ingest.
6. BOM reject path.
7. Cache hit + adapter capability change (force layout-driven for a manual_flat fixture via debug knob, if testable) — confirm route correctly bypasses mapping. If not testable safely, leave a note in BACKLOG.

### Slice 4 (BCCT) — 8 cases

1. Growatt BCCT — cache miss → mapping page → confirm → preview with diff_view (all NEW since first upload of the year) → confirm → ingest.
2. Re-upload modified Growatt BCCT (1 row changed, 1 deleted, 1 added) → cache hit → skip mapping → preview shows diff_view with NEW/UPDATED/DELETED counts → confirm → BCCT history row written.
3. DKE BCCT (`.xls`) → mapping page → confirm → preview → ingest.
4. Do Thanh BCCT E31 + E62 → both files; same flow each.
5. BCCT row missing `customs_code` → skipped_rows; staff fills; mixed ingest; verify typed-column coercion still ran on the filled row.
6. BCCT reject path.
7. BCCT with cached mapping that became stale (column dropped) → cache hit fails → falls through to mapping page → re-confirm → cache row updated.
8. Confirm-on-update DELETE detection: 03b file removes a row vs 03a → preview shows it under DELETED with confirm gate; confirm → tombstone written.

### Cross-cutting (after slice 4)

- All 4 modules accessible from same `/clients/{c}/<m>/upload` URL shape; navigation consistent.
- No unrelated module regressions (run full suite: `uv run pytest -q`).
- Real-data smoke: `DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run pytest -q -m real_data` green.

## Done criteria (sprint-level)

- All 4 modules use the unified flow end-to-end on `localhost:8754`.
- Catalog: all 21 currently-rejected catalog files parse via new flow (or are explicitly logged as "not catalog" / out-of-MVP-scope). Acceptable to leave 1-2 in the latter bucket; track in BACKLOG.
- BQD: existing real-data fixtures still parse (regression-clean) plus run through the new mapping page.
- BOM-manual_flat: existing fixtures still parse; layout-driven adapters bypass mapping page (regression check).
- BCCT: all existing BCCT tests pass; confirm-on-update + history flows preserved; real-data smoke green for Growatt + DKE + Do Thanh.
- Tests: `uv run pytest -q` green at end of each slice. `DATA_HUB_REAL_DATA_DIR=/tmp/dh_real_data uv run pytest -q` green at end of slice 4.
- UI smoke: `scripts/demo_confirm_gate.py` extended to walk all 4 modules through the unified flow; screenshots committed under `.ai/features/2026-05-04-flexible-catalog-intake/screenshots/`.
- `.ai/STATUS.md` updated; "DS SP / TP-BTP catalog rejects" struck from Next Steps; new entry "BCCT/BOM/BQD/catalog upload UX unified".
- `.ai/BACKLOG.md` deferred items logged (multi-sheet shape divergence, per-client required-fields admin UI, etc.).
- `.ai/sister-app-notes/` updated only if any consumer-facing contract changed (none expected — read APIs unchanged; consumers see same data shape).

## Open questions

- **`proposed_by='llm'` vs `'manual'` detection.** When staff loads LLM suggestion + clicks Save with 0 edits → `proposed_by='llm'`. Any edit → `'manual'`. Detect via form-state diff client-side. Trivial; deferred to implementation.
- **Per-client required-fields admin UI.** For MVP, ops sets via existing `client_config_ui`. Dedicated editor deferred.
- **Audit trail for staff inline-edited values.** Provenance-only JSONB for MVP; add real audit table when settlement reviewers ask.
- **Mapping page if no LLM and no rigid match** — staff sees blank form. Acceptable? Or better: show "LLM is off; here's a button to enable it"? Lean toward keeping page minimal; surface enable-LLM hint in admin docs only.

## Slice plan

Each slice = one PR. Each slice is independently shippable: if a later slice slips, earlier slices still deliver value. Each slice ends with `pytest -q` green and a commit on `main`.

### Slice 1 — catalog + shared helpers (greenfield, design driver)

**Goal:** ship catalog on the new flow + extract `_mapping_flow.py` + shared templates.

- `app/parsers/materials.py`: add `mapping_override` + `header_row_override`; return `(rows, skipped_rows)`.
- `app/routes/_mapping_flow.py`: new helper module (cache lookup, render mapping, parse-with-overrides, render preview, confirm). Module-agnostic via `ModuleConfig` dataclass.
- `app/templates/clients/_upload_mapping.html` + `_upload_preview.html` shared chrome.
- `app/routes/catalog.py`: rewrite to use shared helpers.
- `client_config[catalog.required_fields]` reader.
- ~14-18 tests covering catalog: parser overrides, skipped_rows, cache hit/miss/stale, LLM disabled/unavailable, required-field rule, header-row override.
- UI smoke: catalog through Playwright on Growatt + DKE + Johnson fixtures.
- Real-data smoke: `scripts/smoke_real_uploads.py` extended for catalog.
- Manual test plan items 1-10 walked.
- Commit message: `feat(uploads): unified mapping flow — slice 1 (catalog + shared helpers)`.

### Slice 2 — BQD migrate to shared flow

**Goal:** port BQD from `_llm_fallback.py` to `_mapping_flow.py` without behaviour change.

- `app/parsers/code_mappings.py`: align signature `(rows, skipped_rows)`; `header_row_override`.
- `app/routes/bqd.py`: use shared helpers; thin wrapper.
- `app/templates/clients/bqd_preview.html`: extend shared template; module-specific summary slot.
- ~6-8 tests (parser overrides, skipped_rows for BQD, regression on existing BQD test suite).
- Manual test plan slice 2 cases walked.
- Commit message: `feat(uploads): unified mapping flow — slice 2 (bqd)`.

### Slice 3 — BOM-manual_flat migrate; layout-driven adapters branch

**Goal:** unified flow for manual_flat; layout-driven adapters keep existing direct-to-preview path.

- `app/parsers/bom_adapters/manual_flat.py`: align signature; `header_row_override`.
- `app/parsers/bom.py` `parse_with_fallback`: route layout-driven vs column-driven adapters into different downstream paths.
- `app/routes/bom.py`: branch on adapter capability; manual_flat → `_mapping_flow`; layout-driven → existing flow.
- Proposal-mode selector page: insert AFTER mapping confirm, BEFORE preview, only for manual_flat.
- `bom_preview.html`: extend shared; preserve proposal-mode selector + BOM-specific summary.
- ~8-10 tests (manual_flat through new flow, layout-driven adapters bypass regression, proposal mode + cached mapping interaction).
- Manual test plan slice 3 cases walked.
- Commit message: `feat(uploads): unified mapping flow — slice 3 (bom manual_flat)`.

### Slice 4 — BCCT migrate; remove bespoke `bcct_parse_mapping.html`

**Goal:** BCCT joins unified flow; confirm-on-update + history preserved.

- `app/parsers/bcct.py`: align signature `(rows, skipped_rows)`; `header_row_override` (today only `mapping_override`).
- `app/routes/bcct.py`: replace bespoke 2-stage UI with `_mapping_flow.py` calls; preserve confirm-on-update + diff-on-update + history insert in confirm helper.
- `bcct_preview.html`: extend shared template; fill `{% block diff_view %}` with existing diff table.
- Delete `bcct_parse_mapping.html` after route is fully migrated.
- ~10-14 tests including diff-on-update + history regression + typed-column coercion under mapping override.
- Manual test plan slice 4 cases walked.
- Real-data smoke: full BCCT walk on Growatt + DKE + Do Thanh.
- Commit message: `feat(uploads): unified mapping flow — slice 4 (bcct, removes bespoke ui)`.

### Slice 5 — cleanup + sprint handoff

- Delete `app/routes/_llm_fallback.py` (its callers all migrated; functionality absorbed into `_mapping_flow.py`).
- Update `AGENTS.md` / `CLAUDE.md` if upload patterns changed enough to warrant docs.
- Run full real-data smoke; commit screenshots; write session summary; update STATUS + BACKLOG.
- Optional: `/rev` two-stage review on the cumulative diff before sprint closes.
- Commit message: `chore(uploads): sprint cleanup + retire _llm_fallback.py`.

## Suggested next step

Start `/tdd` slice 1.
