# RD1 — Step-1 form decision: drop vs bind

Date: 2026-07-30
Status: Decision doc (design only, no app-code changes)
Scope: resolve the "lưng chừng" residual left after `09509ae` — case-level `co_form_type`
is set but not bound to calc or export.

## 1. Current-state analysis (re-verified against HEAD)

Verdict: the backlog claim holds. `co_form_type` is a **market-derived display label**.
It never enters bảng kê calc and never selects the HQ export template. Two stronger facts
beyond the backlog note:

- The step-1 "form" is **already not an independent user input** — the picker was removed
  in `09509ae`. What is stored is a shadow of the per-market recommendation.
- `co_form_type` has **zero** consumers in calc, renderer, export, or PDF code paths
  (verified by grep across `app/`).

### 1a. Step-1 form is derived from market, not chosen
- Create modal hidden input: `app/templates/co_case.html:461`
  `<input type="hidden" name="co_form_type" value="{{ recommended_form_lane.display_name if case.destination_market != 'Chưa nhập' else '' }}">`
- Evaluate form hidden input: `app/templates/co_case.html:1031`
  `<input type="hidden" name="co_form_type" value="{{ recommended_form_lane.display_name or case.co_form_type }}">`
- JS keeps it in sync from the market picker, explicitly commented:
  `app/templates/co_case.html:2890-2892` — "Form is derived from market (no step-1 picker)".
- `recommended_form_lane` is computed from `destination_market` (+ HS codes), not from any
  stored form: `app/web/co_case_context.py:217-219` and `:254-255`
  (`recommended_form_lane(prioritized_form_lanes(destination_market, hs_codes))`).
- Store-side, `co_form_type` is re-derived from market too:
  `app/co_case_store.py:426-444` (`apply_form_defaults` → `form_defaults_for_market` →
  `co_form_type = candidate["display_name"]`).

### 1b. Calc reads the per-sheet effective form, which ignores `co_form_type`
- `app/web/co_case_context.py:1260` `recommendation = sheet_form_recommendation(market, product.get("finished_hs", ""))`
- `app/web/co_case_context.py:1271` `effective_form = form_override or recommendation.get("form_code", "")`
- `sheet_form_recommendation` (`app/web/co_case_context.py:1438-1457`) reads only `market`
  and `finished_hs`. It never reads `co_form_type`.

So the per-sheet precedence is: **`form_override` (step-3 config bar) → market+HS recommendation**.
`co_form_type` is not in this chain.

### 1c. Export template branches on the per-sheet effective form, not `co_form_type`
- `app/workbook_io.py:442` `form = str(product.get("origin_sheet_effective_form_code") or "").upper()`
  → EUR.1 routes to PSR/Phụ lục VII; otherwise the criterion tokens (LVC/RVC/CTH/CTSH)
  select the sheet. `co_form_type` is absent from this function.

### 1d. Where `co_form_type` actually lives (the full consumer set)
Storage / round-trip only:
- DB column: `db/migrations/005_workflow_state.sql:178` `co_form_type text not null default ''`
- Upsert SQL: `app/workflow_state_store.py:412,451` (write), `:816` (read into dict)
- Case store read/write: `app/co_case_store.py:120,166-172,403`
- Internal input-workbook round-trip: `app/workbook_io.py:113,188`
  (this is `create_input_workbook` / `parse_input_workbook`, a dev/import path — NOT the
  HQ customs export)
- Seeds/registry: `app/demo_data.py:319,461,560`, `app/client_registry.py:42`,
  `app/web/client_context.py:122`

Display / search only:
- Case-list small text: `app/templates/co_case.html:400` (`dossier.co_form_type or 'Chưa chọn form'`)
- Origin page-strip: `app/templates/co_case.html:880`
  (`recommended_form_lane.display_name or case.co_form_type` — live recommendation wins)
- Search haystack: `app/templates/co_case.html:382` (`data-case-search`)
- Dangling attribute: `app/templates/co_case.html:385` `data-case-form=...` — **set but never
  read.** The list filter JS reads only `caseSearch` / `caseStatus` / `caseMarket`
  (`app/templates/co_case.html:3220-3222`, `:3237-3240`). `data-case-form` is dead markup.

### 1e. The real "lưng chừng" residual
It is not the UI picker (already removed). It is two smaller things:
1. `co_form_type` is a **stored derived value** — a cache of `form_defaults_for_market(market)`.
   Storing a derived value creates a staleness surface: if `destination_market` changes but
   the stored `co_form_type` is not re-derived, the list cell (`:400`, which reads the stored
   value directly) can disagree with the page-strip (`:880`, which prefers the live
   recommendation). The two display spots already resolve the label differently.
2. `data-case-form` is dead markup left over from the removed filter.

Both display spots and calc/export already behave as if `co_form_type` does not exist; only
the list cell at `:400` still trusts the stored value as authoritative.

Assumption: no external system (customs portal, DH) reads `co_form_type` back. It is not in
any `/v1/hub` request and not in the HQ export workbook. Verified only within this repo.

## 2. Option (a) — DROP the step-1 form as an independent concept

Framing: the picker is already gone. "Drop" here means stop treating `co_form_type` as an
authoritative stored input and let the form label surface purely as a live per-market
recommendation (step-1 display) and a per-sheet recommendation/override (step-3, unchanged).

Two depths:

### a1 — Minimal (recommended sub-option): keep the column, unify the display source
Changes:
- Case-list cell `:400`: render the same way as the page-strip —
  `recommended_form_lane.display_name or dossier.co_form_type` — so the label always reflects
  the live market recommendation and can never go stale against `:880`.
- Remove the dead `data-case-form` attribute (`:385`).
- Keep the `co_form_type` column, store writes, workbook round-trip, and `data-case-search`
  inclusion untouched — it stays as a passive cache / searchable token.

What UI/label stays: the "Thị trường / Form" cell and the page-strip "Form" chip both stay;
they just always read from the live recommendation. The market picker stays as the one real
step-1 input.

Migration for existing cases: **none required.** Existing `co_form_type` values remain in the
DB and stay searchable; they are simply no longer authoritative for display. No column change,
no workbook schema bump.

Risk: minimal. The only reader that changes behavior is the list cell, and it moves to the
same resolution the page-strip already uses. No calc/export/renderer path touches
`co_form_type`, so outcome parity is guaranteed by construction.

### a2 — Fuller cleanup (optional, later): remove the stored field
Changes: drop the `co_form_type` DB column, remove store read/write, remove the input-workbook
round-trip (`workbook_io.py:113,188`), remove `data-case-form`, and compute the display label
on the fly from the recommendation. `data-case-search` would lose the form token (market +
agreement remain in the haystack, so cases stay findable).

Migration: a forward migration to `DROP COLUMN co_form_type` on the workflow-state table, plus
an input-workbook schema-version bump so old workbooks with a `co_form_type` row still parse
(the parser already tolerates missing keys via `.get`, so read-side is safe; the concern is
only the DDL and any test fixtures that set the field).

Risk: churn touches the DB schema, the workbook I/O contract, seeds, and four test fixtures
(`tests/test_co_demo.py:2103,3046,5001,6183`). Higher blast radius for no functional gain over
a1. Recommend deferring a2 unless the field is later found to cause confusion.

Does anything read it that would break: no calc/export. The only breakage from a2 would be
fixtures/seeds that set `co_form_type` and the DB DDL — all in-repo and enumerable. a1 breaks
nothing.

## 3. Option (b) — BIND the step-1 form as the per-sheet default

Mechanism required:
1. Re-introduce a step-1 form picker (or elevate the current derived value to an editable
   default), producing an authoritative case-level `co_form_type` / form_code.
2. Feed it into the per-sheet resolver so it becomes the default when no per-sheet
   `form_override` is set. Concretely, change `app/web/co_case_context.py:1271` from
   `effective_form = form_override or recommendation.get("form_code", "")`
   to something like
   `effective_form = form_override or case_form_default or recommendation.get("form_code", "")`.

Interaction with `sheet_form_recommendation`: this **inserts a case-level default ahead of the
per-sheet market+HS recommendation.** Today the recommendation is computed per product from its
own `finished_hs` (`:1260`). A case-level default would override that per-sheet computation for
every sheet that has no explicit override.

Risk (the core problem with (b)): a wrong global default silently overrides a correct
per-sheet recommendation. A multi-product dossier can legitimately land different products on
different form lanes when their `finished_hs` differ (the recommendation is HS-sensitive). A
single case-level form flattens them all to one form and forces staff to add a per-sheet
`form_override` on every product that should have differed — inverting the sensible default.
It also silently changes the export template (`workbook_io.py:442` reads
`origin_sheet_effective_form_code`) and the calc criterion for those sheets. This is exactly
the class of "changing a case-level flag silently changes a sheet's form/RVC" that per-sheet
resolution was built to avoid.

When (b) would actually help: only when the per-sheet recommendation is systematically wrong
for a whole dossier. The correct fixes for that are (i) fix `sheet_form_recommendation` /
`prioritized_form_lanes`, or (ii) use the existing per-sheet `form_override`. Neither needs a
case-level binding.

## 4. Recommendation

**Adopt option (a), sub-option a1.** Keep `destination_market` as the only meaningful step-1
input; treat the form as a live recommendation at step-1 (display) and a
recommendation/override at step-3 (calc/export, unchanged). Unify the list-cell display to the
live recommendation and delete the dead `data-case-form` attribute. Keep the stored
`co_form_type` column as a passive searchable cache; no migration.

Reasoning:
- The step-1 form is already derived, not chosen — (b) would re-add a picker and a case-level
  binding to solve a problem the per-sheet resolver already solves correctly.
- (b)'s case-level default can override a correct per-sheet, HS-sensitive recommendation,
  silently changing the export template and calc criterion of individual sheets. That is a
  regression risk, not a fix.
- a1 removes the only real residual (the stale-label surface at `:400` and dead markup at
  `:385`) with zero migration and guaranteed outcome parity, since no calc/export path reads
  `co_form_type`.
- a2 (drop the column) is a defensible later tidy-up but adds DB + workbook + fixture churn for
  no functional gain; defer it.

Assumption behind the recommendation: the team wants the form to remain a per-sheet concern
(consistent with `09509ae` and the ADR that put form resolution per-sheet). If instead the team
decides a dossier must always be a single form (one C/O = one form, like the column-9 mode
decision at `co_case_context.py:1467-1474`), revisit (b) — but implement it as a case-level
default that still yields to per-sheet `form_override`, and add a mismatch warning like
`column9_mode_mismatches` rather than a silent override.

## Test list (for the recommended a1)

1. Calc/export parity under an arbitrary stored `co_form_type`: build a case whose stored
   `co_form_type` is deliberately wrong (e.g. "Form B") while market+HS recommend EUR.1; assert
   `origin_sheet_effective_form_code`, the calc criterion, and the export template selection
   (`workbook_io` template branch) are unchanged — i.e. driven only by market+HS/override.
2. List-cell display source: a case whose `destination_market` recommends form X but whose
   stored `co_form_type` is stale/empty renders X in the list cell (`:400`) and the page-strip
   (`:880`) identically — no divergence.
3. Empty `co_form_type`: a case with `co_form_type = ""` still shows a market-derived form label
   in both display spots (falls back to `recommended_form_lane.display_name`).
4. Search still finds by form: searching the case list by the form label still matches (form
   token remains in `data-case-search`); and searching by market/agreement also matches.
5. Filter regression after removing `data-case-form`: the status/market/search filters
   (`:3237-3240`) still work; the removed attribute is inert.
6. Load/round-trip regression: an existing persisted case carrying an old `co_form_type` loads
   and renders without error; no migration is applied.
