# Session 2026-05-03 PM — BOM flatten engine + iterative UX + critic review

**Outcome:** Technical-BOM flattening shipped end-to-end as 9 commits. 307 tests passed (was 239 baseline). Independent critic review caught 3 Critical + 2 Important bugs; all fixed with regression tests.

## What Was Done

### Slice 1 — schema (commit `23e31dd`)

Migration `021_bom_flatten_and_uom.sql` extends `hub.bom_versions` with structured identity (`source_bom_kind`, `flatten_status`, `flatten_strategy`, `source_channel`, `bom_code`, `bom_variant_id`, `lineage`, `display_label`, `flatten_method`, `flatten_method_version`). Backfills 295 existing rows with `flatten_status='not_applicable'` so manual_flat consumers see no behaviour change. New tables: `bom_unresolved_nodes`, `bom_flatten_decisions`, `uom_canonical` (16 seed units), `uom_aliases` (66 vi/en/zh aliases), `client_uom_overrides`. Migration `022_bom_idempotent_v2.sql` replaces `uq_bom_idempotent` with a unique INDEX that includes `coalesce(bom_variant_id,'default')` + `flatten_strategy` so dual-source variants don't collide.

### Slice 2 — pure flatten engine (commit `b600d60`)

`app/flatten/` — 7 modules, no DB I/O. `engine.py` orchestrates graph traversal + cycle detection; `classify.py` implements spec §6 decision order; `uom.py` does precedence-driven conversion; `identity.py` derives `display_label`; `types.py` defines all dataclasses with English-machine-code Literal types. Quantities use `Decimal` throughout. Dual-source fan-out emits both `purchased_btp_as_leaf` and `self_produced_btp_exploded` as parallel `FlattenedVersion` drafts. Same-upload BTP lookup is auto-injected by wrapping `ctx.same_upload_btp` with a closure that consults the parsed dict first.

44 unit tests cover spec items 1-17, 21, 22, 24.

### Slice 3 — adapter registry refactor (commit `a05cd82`)

Old 3-branch dispatch in `app/parsers/bom.py` became a Protocol-based registry under `app/parsers/bom_adapters/`. Each adapter exposes `name`/`label_key`/`description_key`/`supports_mapping_override`/`emits_intermediate_btp_versions`/`parse()`. Profile names neutralized: `growatt_multi_workbook` → `sheet_per_product`, `johnson_sap_exploded` → `sap_exploded_levels` (+ legacy aliases preserved).

Two new adapters with `emits_intermediate_btp_versions=False` for single-rooted SAP/multi-sheet sources where intermediates are explosion artifacts, not standalone BTPs:
- `sap_indented_walk` — Johnson-style: filename = root, Level column drives walk
- `multi_sheet_per_root` — Growatt PV*.XLSX: one product across multiple sheets

Pre-multiplied leaf rows carry `explicit_context='do_not_explode'` so the engine treats them as terminal leaves. `parse_with_fallback(blob, root_code=...)` propagates filename hint via inspect-based kwargs.

### Slice 4 — stores (commit `994f9ca`)

`app/stores/bom.py` extended with structured fields on `create_version` (defaults preserve manual_flat). `version_no` is variant-scoped per spec §3A. New helpers:
- `create_flattened_version_set` — atomic single-connection / single-transaction materialization
- `latest_flattened_versions` — returns flattened/not_applicable ranked by (variant, strategy)
- `make_bcct_import_lookup` / `make_catalog_lookup` / `make_current_db_btp_lookup` — preload-into-memory closures for the engine context

`app/stores/uom.py` implements spec §9 UOM precedence stack (client+material → client-wide → global → alias). `app/stores/flatten_decisions.py` persists staff-confirm gate lifecycle. 13 store tests.

### Slice 5 — API hardening (commit `e1a82aa`)

`/v1/hub/products/{p}/bom/latest` filters by `flatten_status` (excludes `non_flattened`). Returns `409 Conflict` with variant list when dual-source variants are published. `get_version_with_rows()` JSON gains all new fields + sibling `unresolved[]` and `decisions[]` arrays. `docs/API_CONTRACT.md` updated with response shapes + Consumer Rules sub-section. 9 API tests.

### Slice 6 — upload UX (commit `e9b3d3a`)

New `technical_flatten` profile in `app/routes/bom.py` runs the engine after parse, stashes `FlattenResult` + decisions, redirects to `/bom/flatten-preview/{id}`. New template `bom_flatten_preview.html` redesigned dark-safe via CSS vars only:
- 4 stat cards (TP×BTP / flattened / non_flattened / unresolved)
- decision cards in grid with Vietnamese title + "Why" + evidence accordion + confirm checkbox + action select
- versions section grouped by product, BTP/TP badges from catalog category
- sticky action bar

`bom.html` list page redesigned: status badges + filter chips ("Tất cả / Sẵn sàng tính toán / Cần review · N") with in-page JS filtering. Staleness bar dark-theme fix in `app.css` (was using non-existent `--surface-2`/`--background-2` vars; switched to `--card-muted` + `--foreground`).

i18n `flatten.*` namespace (vi + en, ~50 keys) with convention `flatten.dec.<type>.{label,why}` so adding new decision_types requires only 2 i18n keys, no Python change. 9 upload tests including idempotent re-upload and Johnson + Growatt fixture coverage.

### Slice 7 — independent critic review + 5 fixes (commit `a503bcd`)

After self-review caught 2 (dual-source gate when staff doesn't confirm + uq_bom_idempotent constraint conflict), spawned an independent critic agent for a deeper review. Critic found 3 Critical + 7 Important + 5 Minor.

**Fixed in this session (3 Critical + 2 Important):**
- **C1**: `create_flattened_version_set` was not transactional — refactored to use single connection + cursor passed into `create_version`. Rolls back atomically on any failure.
- **C2**: Dual-source variants could publish without staff confirm when ALSO non_flattened (engine collapsed strategy to `no_strategy`, publish_filter then bypassed dual-source gate). Engine now preserves dual strategy under unresolved; publish_filter dropped the `flatten_status==flattened` precondition.
- **C3**: `same_upload_btp` wrapper + `make_current_db_btp_lookup` treated `default` as a wildcard — settlement-correctness bug for any non-default variant. Both now use strict equality.
- **I1**: `multi_sheet_per_root` adapter accepted single-root flat files (one TP + leaves), routing them through pre-flatten path. Now requires at least one intermediate parent; flat files defer to `manual_flat`.
- **I3**: `_explode` didn't propagate `dual_source_variant` decisions for nested dual-source occurrences. Now emits decisions at any depth (spec §7+§11).

7 regression tests in `tests/test_flatten_rev_findings.py` pin all 5 fixes.

### Slice 8 — comparison harness (commit `262f9f2`)

`scripts/compare_real_boms_vs_co.py` runs the flatten engine on every real Growatt + Johnson workbook (39 + 82) and compares leaf-by-leaf against CO's `derived/CO/bom-{flatten,aggregate}/` reference output. Findings:

| | DH BTPs/file (after refactor) | Leaf overlap | Qty divergence type |
|---|---|---|---|
| Growatt 39 files | 0 (was 6.4) | **93.3 %** | 11/24 sampled mismatches are CO undercounts |
| Johnson 82 files | 0 (was 69) | **100 %** | 388/404 sampled mismatches are CO undercounts |

DH math is correct (multiplies edge qty correctly through ancestor chains). CO's "ignore ancestor multipliers" model under-counts when ancestor edges have qty>1. Concrete example: leaf `1000445332` in `MFW0502-39` — DH=12.564 KG, CO=8.488 KG. CO under-reports by 32 % because edges `1000480127=2.0` and `1000480135=3.0` are ignored.

`scripts/screenshot_flatten.py` provides UI walkthrough (8 case demo + idempotent re-upload + Johnson + Growatt) in light + dark themes.

### Slice 9 — handoff docs (commit `2591dfe`)

`STATUS.md` refreshed, `DECISIONS.md` 2026-05-03 entry on the design choice to keep flatten metadata as a separate axis from `actor`/`intent`. Sister-app note posted at `.ai/sister-app-notes/2026-05-03-bom-flatten-shipped.md` for CO + BCQT consumer migration.

## Decisions Made

1. **Flatten metadata is a separate axis from `actor`/`intent`.** Tempting overloading (e.g. `intent='technical_flattened'`) was rejected — keeps "who/why" semantics distinct from "what artifact", prevents intent-based consumer code from breaking, lets dual-source variants coexist as distinct rows. Recorded in `.ai/DECISIONS.md`.
2. **`emits_intermediate_btp_versions: bool` per adapter.** Adapters where intermediate codes are explosion artifacts (SAP-indented Johnson, multi-sheet Growatt) set this False and pre-flatten in the parser. Eliminates ~5800 BTP versions across 121 real workbooks while preserving spec compliance for adapters where intermediates ARE standalone BTPs.
3. **Strict variant equality everywhere.** `default` is a real variant, never a wildcard. Critic flagged the wildcard fallback as a settlement-correctness bug; fix preserves spec §3A graph-identity intent.
4. **Single-tx materialization.** All writes in `create_flattened_version_set` go through one connection. Failed materialization rolls back atomically; pending row stays for staff retry. `create_version` accepts an optional `cursor` for composability.
5. **Adapter chain ordering.** Single-root adapters first (more discriminating). Strict adapters reject when preconditions don't match → falls through to generic adapters. Required adding an "intermediate-parent must exist" guard to `multi_sheet_per_root` to prevent it claiming flat manual_flat uploads.
6. **i18n key convention `flatten.dec.<type>.{label,why}`** so new decision_types require only 2 i18n keys, no Python change.
7. **Did NOT add a separate `flatten_strategy='adapter_preflattened'` enum value yet** (critic I5). Currently single-root adapters mark rows with `explicit_context='do_not_explode'` and engine writes `flatten_strategy='technical_exploded'`. Audit-trail divergence noted in BACKLOG; deferred to avoid migration churn before consumer migration confirms the schema is stable.

## What Didn't Work

1. **First attempt at `multi_sheet_per_root` accepted single-root flat files.** Manual_flat-style uploads with 1 TP + N leaves got routed through the pre-flatten path with `do_not_explode` markers, bypassing catalog/BCCT classification. Critic caught this as I1; fix added the intermediate-parent guard.
2. **First publish_filter implementation left dual-source variants open when staff didn't confirm AND version was also non_flattened.** Engine had `if has_unresolved: flatten_strategy = "no_strategy"` which collapsed dual-source variants' strategy → publish_filter's `flatten_strategy in (purchased_btp_as_leaf, self_produced_btp_exploded)` check bypassed them. Critic caught this as C2; fix preserves dual strategy under unresolved AND drops the `flatten_status==flattened` precondition.
3. **Initial graph-pure mock context for the comparison script** (`scripts/compare_real_boms_vs_co.py`) classified everything without catalog evidence as `unresolved` — produced 0 leaves on every Growatt + Johnson file. Reworked to inject a synthetic catalog that returns active-NVL for any code WITHOUT a child BOM (matches CO's behavior of "anything without children is a leaf"). After this fix, leaf-set match jumped to 93-100 %.
4. **First try at the SAP-indented walker** put leaves into `parsed[parent_code]` keyed by material code — caused `parsed['1000541366']` to receive children from BOTH ancestor instances (`1000480140`'s subtree + `1000480147`'s subtree). Engine then double-counted by recursing into '1000541366' from each ancestor. Refactored to do per-instance walk in the parser (not the engine) and emit one entry per (root → leaf-row-instance) under the single root key — preserves per-instance qty correctness without polluting the engine's "code = identity" model.
5. **Migration 021 originally tried to update the unique constraint inline.** PostgreSQL forbids COALESCE in UNIQUE constraints; first attempt failed at apply time. Pulled the constraint change into migration `022_bom_idempotent_v2.sql` as a separate `DROP CONSTRAINT` + `CREATE UNIQUE INDEX` (the index form does allow expression-based uniqueness).

## Open Items

1. **Critic findings deferred to BACKLOG** (full list in STATUS.md Next Steps section): I2 (SAP leaf detection second-pass), I4 (intent allowlist→exclusion), I5 (`flatten_strategy='adapter_preflattened'`), I6 (`recommended_variant_version_id` in 409 body), I7 (FK cascade for `bom_flatten_decisions.pending_id`), M1-M5 (evidence code, i18n fallback test, UOM connection-per-row, normalized_hash precision, recursion depth cap).
2. **2 Growatt parse errors** (`PV01.0104800.XLSX`, `PV01.0105100.XLSX`) — all 5 adapters reject. Worth a separate inspection pass.
3. **30 of 39 Growatt workbooks have no CO reference output** to compare against. CO only has reference for 9. Producing CO-style references for the other 30 would close the comparison gap.
4. **CO + BCQT consumer migration** still required before they can safely consume Data Hub BOM. Sister-app note explains the contract; migration deadlines remain 2026-05-16 (CO) and TBD (BCQT).
