# RD3 — Bước 3 "Bảng kê C/O": discovery cho THAY ĐỔI LỚN (nội dung chưa chốt)

`/discover`-style brief. Purpose: map the current bảng kê step precisely, lay out a menu of
PLAUSIBLE "big changes" the user could mean, and list the decisions only the user can make.
**This brief does NOT pick one and does NOT change app code.** Assumptions are stated inline.

Grounding: `.ai/BACKLOG.md` (reconciled vs code 2026-07-17), `.ai/DECISIONS.md` (12+ bảng kê
ADRs), sessions `2026-06-14-rd3-bangke-split`, `2026-06-25-bangke-blank-export-undo-export-parity`,
`2026-07-06-auto-flow-batch-redesign`, `2026-07-11-vn-origin-*`; memories
`[[bangke-export-equals-web-invariant]]`, `[[bangke-post-save-undo-override-history]]`,
`[[bangke-soft-delete-index-model]]`, `[[co-origin-sequential-pipeline]]`,
`[[bangke-blank-names-fast-path-empty-catalog]]`. **Line numbers verified against current code**
by a three-part code-map pass over `app/web/co_case_context.py`, `app/templates/co_case.html`,
and the export renderers.

**Path map (post mid-July move):** build + calc = `app/web/co_case_context.py`; routes =
`app/routers/co_case.py`; grid + all JS = `app/templates/co_case.html` (one `<script>`,
lines 2137-6749); filters = `app/origin_material_filters.py`; export = `app/bang_ke_renderer.py`
(config/JSON path, LIVE) + `app/workbook_io.py` (orchestrator + legacy path, LIVE) +
`app/bang_ke_xml_generator.py` (from-scratch XML path, built but **not wired to any route**).

---

## 1. Current bảng kê step — precise map

### 1.1 Where it sits in the flow
5 steps: **Lô hàng → Chứng từ → Bảng kê C/O → TKX/TKN → Review & Xuất**. Bảng kê is step 3, the
heaviest. Since `2464797` (2026-06-14) step 3 is a **drill-in**, not a new stepper level: a
**Review dashboard** (`section.origin-review`, `co_case.html:875`; status matrix + drill rows
`origin-review-table` `:945-986`) ⇆ a per-sheet **Excel-like workspace** (`section.workspace-main`
`:1051`) with the grid centre-stage, config/cost/columns re-parented into a ⚙ settings modal
(`initOriginSettingsModal` `:2640`), and **sheet tabs at the bottom** (`origin-sheet-tabs-bottom`
`:1893`, Excel-style). View state (`?sheet=<code>`, `origin_view=review|sheet`) is threaded through
`co_case_step` and kept OUT of `origin_case_revision` (`co_case_context.py:61-88`).

One bảng kê **sheet per finished product (SP)**; a lô with 30 SP = 30 sheets. Sheets share one
CO-stock pool, so processing is **strictly sequential + interleaved**: `/calculate` of sheet N
requires every earlier sheet (in `origin_product_order`) to be **locked**
(`origin_sheet_action_error`, `co_case_context.py:1621-1695`, sequence gate `:1642-1645`).
"Tính tất cả rồi Chốt tất cả" is impossible by design; the correct batch primitive is a wizard that
interleaves calc→review→lock (`[[co-origin-sequential-pipeline]]`).

### 1.2 Data model

**Materials list (per sheet).** Built by `origin_product_from_invoice_match`
(`co_case_context.py:2290-2376`); one `origin_material_from_bom_row` per BOM row with
`material_sequence = enumerate(bom_rows, start=1)` (`:2311-2325`). Each material carries: identity
(`material_code`, `material_sequence`, `customs_item_code`), display (`material_name`, `hs_code`),
money (`unit_value_native`/`_vnd`, `material_value_native`/`_vnd`, `non_origin_cif_value`), origin
(`origin_status`, `origin_country`, `bang_ke_origin_text`), classification (`customs_relevance`,
`bom_technical_noise`), and allocation (`allocation_code` + `_status/_source/_confidence`,
allocation_lines to lots). `material_sequence` is a per-product positional enumeration re-derived
each recalc, unique per sheet; it equals the render index + 1.

**Active vs soft-deleted.** `BG1` (`60e55a1`+`1e089e9`, `[[bangke-soft-delete-index-model]]`) made
delete a **soft-delete**: the row stays in `materials` with a `deleted` flag; calc runs on
`active_materials = [m for m in materials if not m.get("deleted")]` (`:2328`). This keeps positional
indices stable (the old hard-remove shifted indices → 1 delete lost 2 rows). Deleted rows render
folded + struck (`origin-material_structure_only` neutral row, `:2505-2518`), contribute 0 to
VNM/LVC/allocation, and are excluded from missing-value flags. **Every consumer re-applies the
`deleted` filter** (`material_row_index` `:2027`, `case_missing_stock_summary` `:2054`,
`case_shortfall_rollup` `:2106`, `enrich_origin_product` `:3106-3135`).

**Overrides — TWO unrelated maps despite similar names:**
- **`material_overrides`** = per-material sheet edits (delete/replace/add/norm-edit). **Keyed by
  1-based `material_sequence`, NOT render index and NOT material_code** — resolved through
  `material_override_key(material, index)` (`origin_material_filters.py:25-32`). The positional-index
  fragility that caused BG1 was retired by the VN-origin re-key (#7); the key is `material_sequence`
  with a version-mismatch gate (`applied_overrides`, `co_case_context.py:1314-1326`: overrides
  written under BOM version A are kept but not applied under version B). `/save` is
  **override-delta-based** (`recalculate_origin_sheet_edits`, `co_case.py:570-693`): it merges
  `replaces/adds/deletes/norm_edits` into a cumulative map — **there is no "clear override" op**.
  `attach_origin_sheet_states` rebuilds sheet state from a **whitelist** (`:1239-1424`), so
  overrides + history must be carried explicitly or they are dropped.
- **`bang_ke_overrides`** = client-level column-9 convention (`{column9_mode, unknown_origin_label}`),
  `bang_ke_settings` `:1458-1466`, precedence `resolve_case_column9_mode` `:1467-1474`. Unrelated to
  per-material edits. A refactor of one must not conflate the other.

**Folds / rác.** A row folds when `_row_deleted or material.bom_technical_noise`
(`co_case.html:1577-1580`, JS `initOriginFoldRows` `:6528-6564`). `bom_technical_noise ==
is_bom_technical_noise(material)` (`origin_material_filters.py:12-16`), which reads
`customs_relevance` (`_EXPORT_EXCLUDE = {"excluded_non_material","declarable_unmatched"}`, `:9`).
The web ALSO folds `declarable_unmatched` ("⚠ chưa khớp · không xuất", `co_case.html:1673`).
Fold-summary: `origin_warning_summary` `:3238-3298` (rác row `:3266`, unmatched row `:3277`).

**customs_relevance.** Copied straight from the DH materials catalog at Tính
(`co_case_context.py:2482` structure-only, `:2759` allocated). CO **never manufactures it**;
unclassified is **KEPT, not dropped** (DH-trust contract, `origin_material_filters.py:3-8`). Fast
`/calculate` paths used to pass an EMPTY catalog → every material got `customs_relevance=0` → rác +
unmatched leaked to export as blank rows; fixed by pulling the materials-only catalog at the 4 build
sites (90s TTL, `763fe74`, `[[bangke-blank-names-fast-path-empty-catalog]]`). **Residual DC3b:
sheets calculated before mig-078 / before the catalog fix persisted materials with NO
`customs_relevance` → rác stays until re-Tính** (`co_case_context.py:2482/2759` are the only writers,
so a persisted-old sheet never carries the field; BACKLOG:24,35-37).

**Per-sheet form / criteria.** `effective_form = form_override or
sheet_form_recommendation(destination_market, finished_hs).form_code`
(`co_case_context.py:1260-1271`); stamped as `origin_sheet_effective_form_code` +
`origin_sheet_effective_criteria_text` (`:1307-1310`). Case-level `co_form_type` (step 1) is a
**decorative label** — it does NOT drive calc or template selection. Per-sheet form drives BOTH the
calc criteria/threshold (LVC vs RVC) AND the export template (`workbook_io.py:442-475`
`hq_sheet_codes_for_product`: EUR.1 → Phụ lục VII/PSR sheet; else LVC).

**Column-9 / VN-origin (shipped #6–#13, `51fe273`).** `_resolve_vn_origin_lines`
(`co_case_context.py:2765-2788`): a line is originating iff `origin_country`→VN (`is_vietnam_origin`,
`:2778`) **AND** its supplier is flagged (Phụ lục X evidence, `co_supplier_evidence_events`, curation
screen `/clients/{id}/suppliers`). Col (9) text is materialized at Tính as `bang_ke_origin_text`
(`_materialize_material_origin_text` `:1550-1592`, mode = client-default `country`|
`qualification_label`); renderers are pure readers. Col (12) = "Phụ lục X/<NCC>" (`bang_ke_co_doc_no`
`:2782`); **col (13) blank by user directive** (doc_no/doc_date deferred). VNM exclusion: originating
amount is subtracted (`vnm_value = material_value − origin_amount`, floored 0, `:2588-2599`); origin
rows carry `non_origin_cif_value=""` so they never enter the VNM sum.

**Stock allocation.** One shared per-material `stock_pool` (`case_allocation_pool`
`co_case_context.py:2159-2225`, built in `prepare_case_origin_products` `:862`); each SP consumes in
`origin_product_order`, lots sorted usable→remaining→value→declaration_date ASC (FIFO, sort key
`:2226-2236`). A lot aliases under `co_stock_key_candidates = {material_code, allocation_code,
customs_item_code}` (`:1989-1995`, in-memory only). Shortage (`allocation_status="shortage"`) when a
BOM line's consumed qty exceeds matched lots. `case_shortfall_rollup` (`:2083-2158`) pivots the
allocated case to a material-centric shortage view (batch "Tổng hợp NVL"). Substitute-stock overlay
(`co_case_origin_sheet_substitute_stock`, `co_case.py:2579-2671`) nets LIVE cross-case ledger claims
via `apply_used_qty` before reporting tồn (D fix).

### 1.3 The calc → lock → export invariant

**Stated rule: export == web grid; ALL logic at Tính; export is a PURE renderer**
(`[[bangke-export-equals-web-invariant]]`, user 2026-06-25 emphatic — a divergence between the file
shipped and the on-screen grid is "rất nguy hiểm"; route comment `co_case.py:1318-1320`).

**Holds for matched-row column VALUES** — the three body loops read pre-computed fields off the
material dict, no recompute (`bang_ke_renderer._write_body:239-339`, `workbook_io.write_hq_sheet_
materials:601-694`, `bang_ke_xml_generator._build_material_row:487-528`). The removed
`_enrich_materials_from_catalog` (render-time classification at the export route) is exactly the
forbidden "logic at export"; old sheets are fixed by **re-Tính**, never by patching export.
customs_relevance round-trips through the export FORM so a form-rebuilt export keeps classification.

**Qualified in practice — export STILL re-derives four things at render time** (a "big change"
target, C14 below):
1. **Footer totals + LVC%** recomputed in the renderer, not read from Tính (`_ratio_percent`/
   `_compute_ratio` `bang_ke_renderer.py:431-443`; `workbook_io.py:703-704,726-727`).
2. **FX cross-conversion** at render (`_pick_currency_value` `bang_ke_renderer.py:161-193`), incl.
   the **B6 double-apply nit at line 185/189** — when `_vnd` is missing on legacy data it falls back
   to the native value then divides by `fob_fx_rate` → converts twice. **The legacy body path
   (`workbook_io.write_hq_sheet_materials`) skips per-row FX entirely** (reads raw `:633-638`), so
   config/XML and legacy paths diverge on currency.
3. **Render-split fan-out + residual math** (`bang_ke_rows.material_render_parts`) — re-buckets
   allocation lines and computes an unallocated residual at render.
4. The **noise strip** itself (a filtering decision at export, §1.3 belts below).

**Column numbering gotcha (load-bearing).** DECISIONS/GLOSSARY cite the **legal Phụ lục VIII form**
numbers — (7)/(8) trị giá có/không xuất xứ, (9) nước xuất xứ, (12)/(13) evidence. The **export
code's internal layout indices differ**: in `_HQ_LEGACY_LAYOUT`/`HQ_HEADERS` col 7 = Đơn giá CIF,
**8 = trị giá xuất xứ, 9 = trị giá KXX, 10 = nước xuất xứ, 11(K) = tờ khai NK, 13(M)/14(N) = C/O doc
evidence** (`workbook_io.py:377-399,645-676`). Any change that talks about "column N" must translate
between the legal-form number (what the user means) and the code index (what the renderer uses).

**Lock (`Chốt`).** `origin_can_lock = status=='calculated' and not sequence_reason`
(`co_case_context.py:1402`); the endpoint (`lock_co_case_origin_sheet`, `co_case.py:2244-2313`)
re-checks via `origin_sheet_action_error` → HTTP 409 (not just a disabled button). **Three-belt
hard-blocks** (calc-status + lock 409 + export blocker), each re-derived at action time because
save/bulk routes hardcode `status="calculated"` (`co_case.py:1881,2803,2990,3042`):
- `lvc_declarable_unmatched` (DC3c) — flag `co_case_context.py:3120-3123`; lock re-check `:1657-1664`;
  export blocker `origin_sheet_export_blockers:1593-1620`; calc-status hold `co_case.py:2111`.
- `lvc_missing_price` — flag `:3106-3111`; lock re-check `:1673-1680`.
- `lvc_allocation_shortage` — flag `:3130-3135`; lock re-check `:1665-1672`.
A blocked sheet holds at `bom_loaded` → badge reads "Đã nạp BOM" even after calc (ST1 readiness-chip
imperfection, ADR-deferred).

**Two open holes on this seam, one shared root (BACKLOG cross-item finding):**
- **DC3b** — pre-mig/pre-catalog sheets lack `customs_relevance` → rác leaks to export until re-Tính.
- **LK1 dirty-before-lock** — `lock_co_case_origin_sheet` reads the **persisted** case
  (`_sheet_with_allocations` falls back to disk `co_case.py:211-232`) with no forced save/recalc, so
  a sheet with unsaved client edits or a `stale` sheet can be locked against last-saved data. Only
  re-validation is the `StockOverclaimError` pre-check.
- One "force recalc before lock/export on stale/pre-mig sheets" fix closes both.

**Save-model / undo.** Undo/redo is **server-side per-sheet override history**
(`origin_sheet_states[code].override_history`/`override_redo`, bounded 25 via `clean_override_stack`
`:1219-1237`) because client-only history cannot survive a save — every `/save` swaps the whole sheet
DOM via `replaceCaseShellFromResponse` (`co_case.html:2256`), and `/save` is delta-based with no
"clear" op (`[[bangke-post-save-undo-override-history]]`). Client has a parallel HTML-snapshot stack
(`__sheetHistory` `:5198`), falls back to server steps (`serverHistoryStep` `:5297-5318`) when empty.
Routes `/origin/sheet/{code}/undo`,`/redo` walk the stacks and recompute via
`_recompute_origin_sheet_context`. Autosave configurable (default 30s, `autoSaveDelayMs:5517`).

### 1.4 Known pain points already in the backlog (current friction)
- **BG1** — DONE (soft-delete); index fragility retired by the #7 `material_sequence` re-key.
- **DC3b** — rác leaks to export on pre-mig / pre-catalog sheets until re-Tính. OPEN.
- **DC3c / missing-price / shortage** — three-belt hard-blocks shipped; correct but produce the
  "Đã nạp BOM after calc" badge lie (ST1, readiness chip deferred by ADR 2026-07-11).
- **LK1 dirty-before-lock** — can lock stale/unsaved data. OPEN.
- **Save/undo model** — override-delta merge with no "clear" op; version-aware binding is partial
  (version-mismatch gate exists; ADR wants full `(artifact_id, material_sequence)` key).
- **XX1 col (13)** — blank by directive; doc_no/doc_date deferred.
- **B6** — native↔VND toggle works; FX-accuracy + the render-time double-apply nit (`:185/189`) +
  legacy-path per-row FX skip remain.
- **EX1** — col K = decl number only; `import_ref_format` config deferred.
- **M1** — propose-BOM status never re-read from DH; "Đã propose ✓" re-POSTs.
- **P1/P2 perf** — fast `/calculate` pulls the ~13k catalog for names + customs_relevance; residual
  first-open latency; proposal = materialize customs_relevance + name into the CO-stock snapshot.
- **Batch/wizard** — backend built (`calculate-all`, `bulk-substitute`, `bulk-lock`,
  `case_shortfall_rollup`, `substitution_plan.py`) but the two batch buttons are **gated off**;
  "Tổng hợp NVL" tab shipped; wizard start `[data-origin-wizard-start]` exists (`co_case.html:918`).

### 1.5 Invariants any "big change" MUST NOT break
1. **Export == web grid; push new logic to Tính** (classification, values, folds). The three body
   loops + two column dicts + JSON configs + XML config must move in lockstep on any column change.
2. **Sequential-interleaved pool correctness** — calc N needs 1..N-1 locked; lock order does NOT
   change allocation (fixed at Tính); the FOR-UPDATE overclaim guard at lock is the real safety net.
3. **customs_relevance is DH-owned; CO echoes, never manufactures; unclassified is KEPT.**
4. **Row identity = `material_sequence` (version-gated); `added_<n>` for manual rows.** Overrides,
   undo snapshots, propose-bom, export must all key consistently. Don't reintroduce a positional key.
5. **Locked sheets are immutable snapshots** — config/mode/flag flips never rewrite a locked sheet;
   they mark `calculated` sheets `stale` + show a mismatch chip.
6. **View state stays out of `origin_case_revision`; every mutation carries `expected_revision` and
   reconciles by re-rendering from the response** (`replaceCaseShellFromResponse` +
   `refreshCaseShellInteractions:6715`). No speculative client state.
7. **Three-belt guards** (calc-status + lock 409 + export blocker) — never a single point, because
   save/bulk routes hardcode `status="calculated"`.
8. **Wiring survives shell-swap** — new controls must be document-delegated or re-bound in
   `refreshCaseShellInteractions`. Client wire contracts: `__pendingOps
   {replaces,adds,deletes,normEdits}` (`:5183`) and `compactOriginPayload` (`:2334-2419`).

---

## 2. Candidate "big changes" (menu — do NOT pick one)

Each: what it changes · files/seams · risk · invariant it must not break. Derived from code +
backlog; not exhaustive. Several already have a decided guardrail in DECISIONS — flagged so grilling
doesn't re-litigate settled sub-decisions.

### C1 — Force re-Tính before lock/export (close DC3b + LK1 in one)
- **What:** lock/export refuses (or auto-runs) a recalc when the sheet is `stale`, has unsaved edits,
  or was calculated before the catalog/mig-078 fix (no `customs_relevance` stamp).
- **Seams:** `origin_sheet_action_error`, `origin_sheet_export_blockers`, the lock route (reads
  persisted case), a "sheet needs recalc" predicate (schema/fingerprint stamp — precedent: mig 020
  `derivation_schema_version`, #14 `co_config_fingerprint`).
- **Risk:** low-medium. Auto-recalc at lock could change allocation if upstream changed; must respect
  the sequential rule. Likely a **prerequisite** for any bigger change, not the big change itself.
- **Must not break:** invariants 1, 2, 7.

### C2 — Guided batch wizard (interleave calc→review→lock) + re-enable gated batch
- **What:** replace the impossible "Tính tất cả / Chốt tất cả" with a wizard walking SP in order,
  calc→(review shortage/LVC)→lock per sheet, plus the "Tổng hợp NVL" shortfall board driving
  bulk-substitute (only_short/everywhere). Re-enable the two gated buttons behind it.
- **Seams:** routes exist (`co_case.py` calculate-all/bulk-substitute/bulk-lock, `substitution_plan.py`,
  `case_shortfall_rollup`); gate at `co_case.html:926-936`; `renderOriginWizard:6432`; sequential gate
  `origin_sheet_action_error`. Design + prototype already done (`2026-07-06-auto-flow-batch`).
- **Risk:** medium-high. Batch multiplies DC3a/DC3c errors across the lô (Slice-0 guards done first).
  Revision-token 409 across many sheets. Cross-dossier contention (D2 cold-start hole).
- **Must not break:** invariants 2, 6, 7. **DECIDED (do not re-litigate):** auto-calc but STOP for
  review, no auto-lock (ADR 2026-07-06); gate-relax by material-overlap is UNSOUND — keep the index
  gate (R1, verified: lots alias under multiple keys so overlap-by-code under-blocks → over-claim).

### C3 — Save-model cleanup: add "clear override" op + full version-aware binding
- **What:** the override map is already keyed by `material_sequence` (shipped via #7), but the
  delta-merge model has no way to un-set an edit and the version binding is only partial. Add a
  "clear override" op; key the binding by `(bom_product_artifact_id, material_sequence)`; migrate
  legacy positional keys deterministically. (Optionally replace delta-merge with a full-snapshot
  document save — the deeper version.)
- **Seams:** `/save` merge (`recalculate_origin_sheet_edits`), `material_override_key`, the client
  `__pendingOps` shape + `compactOriginPayload`, `attach_origin_sheet_states` whitelist, propose-bom
  `build_bom_proposal_rows` (deleted skip), export, undo/redo snapshots.
- **Risk:** medium. Broad blast radius; must stay consistent across save/propose/export/undo.
- **Must not break:** invariants 4, 5. **DECIDED:** key = `material_sequence` version-aware, NO new
  UUID, NO `material_code` key (ADR 2026-07-11). The incremental version is blessed; the full-snapshot
  document model is the actual "big change" question.

### C4 — Richer inline editing + per-cell validation (true Excel-like grid)
- **What:** today only Định mức (`input.origin-norm-edit`, `co_case.html:1685`) is directly editable;
  code/substitute/add/delete go through the modal/bulk bar. Add direct cell editing with live
  validation (unit price numeric, HS format, origin picker, per-row criteria), inline errors,
  keyboard nav.
- **Seams:** grid cells + `initOriginLiveRecompute:5648`, `reallocateSheet:5087`, `__pendingOps`,
  `/save` payload, `computeFeasibility` client LVC preview, shell-swap wiring.
- **Risk:** medium. Client speculative state fights the server-authoritative re-render model
  (invariant 6). Validation must not become "grid logic" export can't reproduce.
- **Must not break:** invariants 1, 6.

### C5 — Pre-lock diff / review view (what changed vs BOM and vs last lock)
- **What:** before Chốt, show a diff — rows added/deleted/substituted/edited vs the source BOM and
  vs the previous locked snapshot; surface shortage/unmatched/missing-price/LVC delta in one confirm.
- **Seams:** the existing Review dashboard, `case_shortfall_rollup`, override history, lock route.
  Read-model only (projection over calculated state).
- **Risk:** low-medium. Must be a pure VIEW (invariant 1); diff-vs-previous-lock needs the prior
  snapshot retained.
- **Must not break:** invariants 1, 5.

### C6 — Bulk material operations beyond bulk-delete
- **What:** multi-select (the `origin-row-select` column + `origin-bulk-bar` already exist) → bulk
  edit (set price/origin/criteria), bulk substitute across sheets (partly exists via
  `plan_shortfall_substitution`), bulk classify rác/keep, bulk restore.
- **Seams:** select checkboxes + `initSheetBulkDelete`, batched override payload, `bulk-substitute`.
- **Risk:** medium. Batched edits multiply the DC3 error surface; couples to C3's override model.
- **Must not break:** invariants 4, 7.

### C7 — Better fold / rác handling UX
- **What:** a dedicated rác/unmatched panel (not just inline fold `initOriginFoldRows:6528`), a
  "hide all rác" toggle, a per-row "why folded" reason (excluded_non_material vs declarable_unmatched
  vs deleted), one-click reclassify-and-remember.
- **Seams:** fold-summary render, `is_bom_technical_noise`, `customs_relevance` (DH-owned).
- **Risk:** medium. Permanent reclassify collides with invariant 3 (customs_relevance is DH's); a
  CO-side declarability override is a new state axis + a DH-vs-CO trust question (ADR 2026-07-08
  deferred the DH-vs-stock contradiction case).
- **Must not break:** invariants 1, 3.

### C8 — Per-column provenance ("why is this cell this value")
- **What:** per-cell source — BOM row / DH catalog / matched stock lot / user override / config
  default — as hover or inspector. Name, origin, HS, value already have multi-tier fallbacks whose
  winner is invisible today (allocation `_source`/`_confidence` already computed).
- **Seams:** stamp a `_source`/`_provenance` tag per field at Tính; render-only in the grid.
- **Risk:** low (additive read-model if stamped at Tính).
- **Must not break:** invariant 1.

### C9 — Undo/redo depth + history timeline
- **What:** raise `OVERRIDE_HISTORY_MAX` (25, `co_case_context.py:1219`), add a visible timeline /
  named checkpoints, restore to any point, show what each step changed.
- **Seams:** `override_history`/`override_redo`, `/undo`,`/redo`, whitelist-carry, storage size.
- **Risk:** low-medium. Storage growth (snapshots are full override maps).
- **Must not break:** invariant 4 mechanics (whitelist carry).

### C10 — Template / form switching mid-sheet with live preview
- **What:** richer per-sheet form switching in the workspace (beyond the config-bar `form_override`
  `co_case.html:1321`), with a live preview of how criteria/threshold and the export template change
  (LVC ⇆ PL VII/PSR).
- **Seams:** `origin_sheet_effective_form_code`, `effective_criteria`,
  `hq_sheet_codes_for_product:442-475`, config bar in ⚙ modal.
- **Risk:** medium. A form change alters calc criteria → must mark `stale` + re-Tính; never rewrite a
  locked sheet.
- **Must not break:** invariants 2, 5.

### C11 — Materialize customs_relevance + name into the CO-stock snapshot (perf + DC3b)
- **What:** bake `customs_relevance`, canonical name, HS into the CO-stock snapshot so fast
  `/calculate` reads the snapshot instead of pulling the 13k catalog; re-Tính gets fast and old
  sheets stop leaking rác.
- **Seams:** `co_stock_rows` / source snapshot shape, `co_stock_materializer.py`, the 4 calc build
  sites, snapshot invalidation (fingerprint — #14 `co_config_fingerprint` precedent).
- **Risk:** medium-high. Snapshot schema + invalidation; overlaps D1 delta-vs-full and P1/P2.
- **Must not break:** invariant 3, delta/full parity (D1).

### C12 — Readiness-chip / status-model honesty
- **What:** the ADR-deferred readiness chip: render a persistent blocker chip from
  `origin_readiness_status` (shortage/missing-price/unmatched/missing_bom) beside the badge, WITHOUT
  re-keying `calculated_sheet_status`.
- **Seams:** summary table + sheet-tab pill (`origin-sheet-status-pill` `co_case.html:966,1166`);
  flags already exist on the product (`data-origin-*` attrs `:1082-1092`, `renderOriginWizard:6432`).
- **Risk:** low (render-only). The full status-enum refactor is explicitly deferred + constrained by
  ADR 2026-07-11 — do not do the enum refactor here.
- **Must not break:** never trust persisted status in gates (the save-route bypass lesson).

### C13 — Whole-case / consolidated bảng kê view (cross-SP)
- **What:** a single consolidated bảng kê across all SP of the lô (or per export form/market),
  instead of only per-sheet grids — matching how a dossier is filed and how "Tổng hợp NVL" already
  aggregates.
- **Seams:** a new read-model over all sheets' calculated rows; export already groups by per-sheet
  form. Interacts with the row-grain (one row per BOM line) and row-split ADRs.
- **Risk:** high. Big conceptual shift; must stay a projection (invariant 1) and respect per-sheet
  form/criteria; could collide with the sequential per-sheet lock model. Likely the largest reading
  of "big change".
- **Must not break:** invariants 1, 2.

### C14 — Make export truly pure: move footer totals / LVC% / FX / fan-out to Tính
- **What:** export currently re-derives footer totals, the LVC ratio, FX cross-conversion (with the
  double-apply nit + legacy-path skip), and the render-split residual. Push all of these to Tính and
  have all three renderers read pre-computed `lvc_percent`, per-row display-currency values, and a
  pre-split row list — so "export == web grid" holds literally, not just for matched-row values.
- **Seams:** `_recompute_origin_sheet_context` (Tính), `bang_ke_renderer._apply_footer:342-378` +
  `_pick_currency_value:161-193`, `workbook_io.py:703-727`, `bang_ke_rows.material_render_parts`,
  the three body loops (must move in lockstep).
- **Risk:** medium. Touches the money/ratio path; needs a parity harness (export == web totals).
  Also fixes the config-vs-legacy FX divergence.
- **Must not break:** invariant 1 (this strengthens it), no LVC/threshold numeric drift.

---

## 3. OPEN QUESTIONS FOR USER (for a follow-up `/grill-with-docs`)

Decisions only the user can make. Ordered by how much each narrows the scope.

1. **What is the "big change" actually about?** Which axis — (a) batch/wizard flow for a multi-SP lô
   (C2), (b) the in-sheet editing experience (C4/C6/C7/C8), (c) the save/override/undo model (C3/C9),
   (d) correctness hardening before lock/export (C1/C11/C12/C14), or (e) a structural rethink like a
   consolidated cross-SP bảng kê (C13)? Everything else depends on this.

2. **What is the concrete pain the client is voicing?** The last recorded client signal was "flow
   quá nhiều thao tác" (30 SP = 30 sheets) → that points at C2. Is the new "big change" the same
   complaint, or a different one (editing is clumsy / review-before-lock missing / rác handling
   manual / the exported file is hard to trust)? A one-sentence symptom picks the branch.

3. **Batch flow: build the guided wizard now, or keep per-sheet and only fix correctness?** The batch
   backend exists but is gated off; the design is done and prototyped. Re-enable + wizard (C2), or
   leave batch retired and invest in single-sheet UX instead?

4. **Save/override model: incremental cleanup (C3 — blessed `material_sequence` + a "clear" op) or a
   deeper overhaul?** Keep the delta-merge save model (re-keyed + clear op), or replace it with a
   full-snapshot document model? The former is decided-and-cheap; the latter is a real "big change".

5. **Reclassifying rác/declarability on the CO side (C7):** customs_relevance is DH-owned and CO only
   echoes it. Do you want operators to override declarability in CO (new CO-side state + a DH-vs-CO
   trust decision), or keep "fix it in Data Hub, CO re-Tính"?

6. **Consolidated cross-SP bảng kê (C13):** is the target still one grid per SP, or a single
   consolidated bảng kê per dossier/form? This reshapes the whole step and the export.

7. **Correctness prerequisites (C1/C11/C14):** should "force re-Tính before lock/export",
   "materialize customs_relevance into the snapshot", and "move export derivations to Tính" be folded
   into the big change as prerequisites, or shipped separately first so the big change starts clean?

**Top 3 to answer first:** Q1 (which axis), Q2 (the concrete client pain), Q3 (wizard vs per-sheet).
