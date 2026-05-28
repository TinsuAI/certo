# Feature: 2-day import→export gap rule for Tồn CO eligibility

## Scope

Enforce a regulatory rule when allocating import-side stock lots to an
export shipment: an import lot is eligible **only if** its registration
date is at least N days before the case's export registration date
(default N=2, configurable per client).

### In scope
- Filter at allocation pool build time so locked sheets never claim
  ineligible lots going forward.
- Apply at the 3 stock-touching entry points: `/calculate`,
  `/substitute-candidates`, `/substitute-stock`.
- Configurable threshold via `client_config["co_stock"]["min_days_before_export"]`,
  default 2, inclusive (>=).
- Surface why a lot was filtered out in the UI (substitute modal +
  insufficient-stock callout): "Ngày nhập quá gần ngày xuất khẩu (cần
  cách N ngày)".
- Tests: unit tests on the predicate + integration tests on each entry
  point.

### Explicitly out of scope
- Re-validation of locked sheets — grandfather them. The rule applies
  to future calculate/substitute calls only. Already-locked claims
  survive untouched.
- UI threshold editor — first ship the engine + config, edit the
  threshold via DH client_config until a CO admin form is justified.
- Working-days calendar — calendar days only. Holiday awareness is
  out of scope until a customer asks.
- BCCT-side change: DH already returns `registration_date` on every
  row, no DH API request needed.

## Decisions

1. **Import date = `row.registration_date`** (BCCT row's
   `registration_date`, populated by Data Hub from `ngay_dk`/`ngay_tk`).
   Already on every stock row via `source_store.co_stock_rows_from_bcct`
   (lines 1227-1244). No schema change.

2. **Export date = the case's export BCCT registration_date** —
   looked up from `case.shipment.export_declaration_nos[0]`. If the
   case has multiple export declarations, use the **earliest**
   `registration_date` across the set (the rule passes for the
   tightest gap). When no export declaration is matched, the rule
   is a no-op (can't filter what we can't anchor).

3. **Inclusive (>=)** — `export_date - import_date >= N days`.
   `N=2` means import must be ≥2 calendar days before export.
   Example: import 2026-05-01, export 2026-05-03 → gap=2 → passes.
   Example: import 2026-05-02, export 2026-05-03 → gap=1 → fails.

4. **Calendar days, not working days.** Customs agencies count by
   calendar in the source documents we've seen.

5. **Configurable threshold per client** —
   `client_config["co_stock"]["min_days_before_export"]` with
   default 2. CO-side, doesn't require DH config change.

6. **Grandfather locked sheets** — filter is applied at
   `co_stock_allocation_pool` build time, which only runs during
   calculate / substitute. Locked sheets' `co_stock_claims` rows
   are untouched; existing material allocations on locked sheets
   are not re-validated. Two consequences:
   - Operators won't see disappearing rows on locked sheets.
   - A pre-existing locked sheet may hold a claim that the new rule
     would have rejected. Acceptable — those allocations were valid
     under the rule in force at lock time.

7. **Filter location: `co_stock_is_usable(row, *, export_date, min_gap_days)`**.
   Single predicate, consumed by `co_stock_allocation_pool` and any
   future filter site. Keeps the rule in one place.

8. **Surface the rejection reason** — when the predicate rejects a
   row, attach `eligibility_status_reason = "import_too_recent"` and
   render Vietnamese-language explanation in the substitute candidate
   panel.

## Risks

1. **No export anchor (R-anchor)**. If a case has no export declaration
   numbers entered yet, there's no `export_date` to compare against.
   Behavior: rule is a no-op (returns "eligible"). Stock will be
   allocated; lock with the regular flow. This matches today's
   behavior — we're not regressing.

2. **Multiple export declarations (R-multi)**. A single case can carry
   N export declarations. Use earliest `registration_date` so the gap
   check is conservative (the tightest constraint). Operator's
   expectation: every lot must be safely before the first export
   shipment.

3. **Mid-session shipment edit (R-edit)**. Operator picks lots,
   calculates, then changes export_declaration_nos. The new export
   date might tighten or loosen eligibility. The next /calculate
   re-runs the filter; locked sheets are grandfathered (see Decision 6).
   Operator-visible behavior: previously-eligible rows can vanish
   after a shipment edit. Audit-friendly because we already
   invalidate `_CO_CASE_SOURCE_CACHE` on shipment mutation.

4. **Backfill `registration_date` (R-backfill)**. Some legacy stock
   rows may lack `registration_date` (commits prior to
   `06f8c2f`). When the field is empty, the predicate treats the
   row as eligible (can't determine the gap → don't block). Fresh
   refresh would repopulate.

5. **Tests will flake on dates if we use today()-relative fixtures**.
   Use explicit date strings in tests, not `today() - N days`, so
   reruns don't drift.

## Open questions

None blocking. Two minor items worth touching during implementation:

- Should `client_config["co_stock"]["min_days_before_export"] = 0`
  be a supported "disable the rule" knob? **Yes** — if a client has
  agreed with customs that the rule doesn't apply, 0 cleanly disables.
  Falsy-Vietnam customs is unusual but the knob is free.
- Test fixture: do we already have a case with multiple export
  declarations? If not, add one to exercise R-multi.

## Implementation outline

1. `app/co_stock_eligibility.py` (new) — single source of truth
   `is_stock_lot_eligible(row, *, export_date, min_gap_days)`.
   Returns `(bool, reason)` where reason is one of:
   `"ok" | "ineligible_status" | "import_too_recent"`.
2. Refactor `co_stock_is_usable(row)` in `main.py:3356` to delegate.
3. Update `co_stock_allocation_pool(rows)` to accept
   `export_date` + `min_gap_days` kwargs.
4. Helper `case_export_registration_date(case, invoice_matches)`
   in `app/main.py` — returns earliest matching export date.
5. Wire into `/calculate` (`main.py:6398`) and substitute endpoints
   (`main.py:6483-6742`).
6. UI: substitute modal row hover shows `eligibility_status_reason`.
7. Tests:
   - `tests/test_co_stock_eligibility.py` — predicate unit tests
     (12 cases: status, date math, missing fields, threshold edge).
   - `tests/test_co_demo.py::test_calculate_filters_import_too_recent_lots`.
   - `tests/test_co_demo.py::test_substitute_candidates_excludes_too_recent_lots`.
   - `tests/test_co_demo.py::test_locked_sheet_not_revalidated_against_new_rule`.

Estimated effort: ~3 commits.
