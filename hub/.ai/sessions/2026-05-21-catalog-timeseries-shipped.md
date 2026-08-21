# 2026-05-21 — Catalog detail per-material BCCT time-series (A.4 phase 2) + UoM drift Excel report

Session opened with user reading STATUS.md from prior handoff. Two
deliverables shipped:

1. Ad-hoc UoM drift Excel report tool (untracked).
2. Catalog detail time-series feature (commit `58587ca`, pushed).

Plus a 10-commit push to `origin/main` covering work back to the
M16/UoM session block.

## What Was Done

### Phase 0 — UoM drift Excel report tool

User asked: "find materials in BCCT 2025+2026 where unit changes over
time → export Excel".

- Wrote `scripts/uom_drift_report.py` (untracked, lives in workdir).
  Argparse CLI with `--client`, `--year-from`, `--year-to`,
  `--nvl-imports-only`, `--out`. Two-sheet XLSX:
  - "Tóm tắt": per-code summary with concatenated unit list, total
    rows / declarations, span, ĐVT chính per year, 4 boolean drift
    flags.
  - "Chi tiết": per-(code, unit) with row count, declaration count,
    date span, in-year flags.
- Generated 2 reports for the user:
  - All BCCT rows: 188 Johnson codes with ≥2 distinct units in 2025-
    2026 → `C:\Users\sys\Downloads\johnson_uom_drift_2025_2026.xlsx`.
  - NVL imports only: 171 codes → `C:\temp\toss\johnson_uom_drift_
    NVL_nhap_2025_2026.xlsx`.
- After user request, added 3 columns to the Tóm tắt sheet:
  - "Bất nhất 2025": intra-year drift in 2025.
  - "Bất nhất 2026": intra-year drift in 2026.
  - "Bất nhất giữa 2 năm": ĐVT chính 2025 ≠ ĐVT chính 2026
    (initially, mode comparison).
- User flagged the mode-only "Bất nhất giữa 2 năm" is misleading
  ("can wrongly report stability when modes match but sets differ").
  Updated semantic:
  - "Bất nhất giữa 2 năm" → set-comparison: `set(units 2025) !=
    set(units 2026)`.
  - "Đổi ĐVT chính" → mode-only signal (the original semantic, kept
    as a stronger flag).
- Resulting counts on Johnson NVL: 27 intra-2025, 106 intra-2026,
  **118 cross-year set-drift, 85 cross-year mode-drift**. The 33-row
  gap is exactly the misleading subset.

### Phase 1 — `/discover` time-series feature on catalog detail

User asked: "track each code's biến động over time → cho vào trang
details của từng mã → discover + plan now".

- Invoked `/discover` skill. Read existing infrastructure:
  - `app/stores/catalog_bcct_analysis.py` + `catalog_detail.html`
    panel — snapshot drift (unit / hs_code / goods_name / origin)
    shipped 2026-05-10 per BACKLOG A.4.
  - Confirmed no existing time-series brief; OK to ship as phase 2.
  - Sized Johnson BCCT distribution: 9,310 codes, 91% have ≤20 rows,
    max 1,037 (`OTHERS` bucket).
- Wrote brief at
  `.ai/features/2026-05-20-catalog-detail-time-series/brief.md`.
  ~140 lines covering scope, decisions, risks, open questions, 3-
  phase implementation plan.

### Phase 2 — Implementation (commit `58587ca`)

- New store `app/stores/catalog_bcct_timeseries.py`:
  - `analyze_material_timeline` entry point.
  - Dataclasses: `Run`, `FieldTimeline`, `QuarterStat`,
    `MaterialTimeline`.
  - One SQL query aggregating per `(declaration_no, direction,
    registration_date, declaration_type)` with
    `mode() within group (order by <field>)` to collapse multi-line
    declarations to their modal field value.
  - Python RLE walking rows in `(date, decl_no, direction)` order;
    each value change starts a new run.
  - Calendar-quarter bucketing with price + qty aggregates;
    `price_jump_from_prev` flag when median ratio falls outside
    `[0.5, 2.0]`.
  - `_normalize_value` treats null + empty-string the same to
    match the snapshot panel's `∅` convention.
- Wired into `app/routes/catalog.py::catalog_detail` (+5 lines).
- Template section in `app/templates/clients/catalog_detail.html`:
  - "Biến động theo thời gian" h3 with declaration count.
  - One collapsible `<details>` per field with ≥2 runs. Critical
    severity (unit) auto-expanded. Table: from-date, to-date,
    value (∅ for null), n_decl, n_lines, direction chips.
  - Per-quarter table at the bottom with price/qty aggregates +
    inline ⚠ marker on jump rows.
  - Inline anchor link "Xem biến động →" from snapshot drift rows
    jumps to matching `#timeline-<field>` section.
- 10 provider tests in `tests/test_catalog_bcct_timeseries.py`
  covering RLE collapse, RLE split, null-vs-non-null, multi-line
  modal pick, declaration_type drift, direction breakdown, quarter
  boundary span, price jump 2× increase, price jump 0.5× decrease,
  empty-timeline.
- UI smoke `scripts/screenshot_catalog_timeline.py` — Playwright
  per-element capture (not full_page because the detail-page
  section selector picks up the entire 6k-pixel `<section class="zone">`).
  3 PNGs committed.

### Phase 3 — `/rev` review + bundle fix

- Invoked `/rev` skill. Findings labeled by severity:
  - Critical: none.
  - Important: I1 boundary test (2.0× / 0.5×), I2 missing comment
    on `prev_median > 0` guard, I3 same-day different-value test,
    I4 "Số TK" column header semantic.
  - Minor: 9 items (deferred).
- User picked the default fix bundle:
  - I1 added `test_price_jump_boundaries_inclusive` (exact 2.0×
    and 0.5×).
  - I2 added explicit comments on `prev_median > 0` guard +
    "boundary inclusive" semantic on the threshold check.
  - I3 added `test_rle_same_day_different_values_produces_separate_runs`.
  - M3 changed `max(set(currencies), key=...)` to
    `max(sorted(set(currencies)), key=...)` for deterministic
    tie-break.
  - M5 added `test_rle_direction_changes_split_when_value_also_differs`.
- Final tests: 13 passing in the new file, 1143 total.

### Phase 4 — Push

- `git push origin main` → 10 commits `fd793fc..58587ca`. First
  push since the multi-day session block opened on 2026-05-15.

## Decisions Made

- **RLE over per-declaration full timeline.** Per-declaration view
  for a 1,037-row code is unreadable; RLE collapses runs of
  consecutive same-value declarations into one row. Matches the
  user's mental model from the Excel report.

- **Aggregate per `(declaration_no, direction, registration_date,
  declaration_type)` first, then RLE.** Tie-break for multi-line
  field divergence: PostgreSQL `mode() within group (order by
  <field>)`. Modal value wins; alphabetical tie-break.

- **Combined NK + XK timeline, per-run direction breakdown chip.**
  Brief option Q1 — MVP combined. Switch to split if staff feedback
  asks.

- **Calendar quarter, not fiscal.** Brief option Q2 — MVP. Per-
  client fiscal-year alignment available via `client_config.
  fiscal_year_start_month` if needed later.

- **BCCT-only timeline, no merge with `material_audit_events` or
  BOM artifacts.** Brief option Q3 — MVP. Could grow to a full
  "material biography" if staff asks.

- **No suppress mechanism on the time-series.** Mirrors A.2
  conflicts decision: derive on read, never store flags. Read
  `feedback_no_derived_in_source`.

- **`_FIELDS` differs deliberately between snapshot and time-
  series**: snapshot has `goods_name` (the noisy name-drift signal),
  time-series replaces it with `declaration_type` (where the agency
  switched import scheme). Document trade-off; defer field-set
  consolidation until 3+ consumers need the registry.

- **Per-element screenshots, not full_page.** Detail page is too
  tall for full_page screenshots (34k×6k PNG). `locator.screenshot()`
  against `#timeline-<field>` gives clean 1360×N PNGs.

- **Set-comparison vs mode-only for cross-year drift.** Surfaced by
  the user during the Excel report iteration. Set-comparison is the
  honest broader signal; mode-drift is the narrower stronger signal.
  Both shipped in the report as separate columns (118 vs 85
  Johnson NVL codes). The time-series feature on the detail page
  surfaces RLE runs directly, so the distinction is implicit there.

## What Didn't Work

- **First screenshot was 34kx6k PNG.** Playwright `page.screenshot(full_page=True)`
  captured the entire catalog detail page (BCCT references + BOM
  references + audit panel + …). Re-targeted to per-element
  `locator.screenshot()` against the specific `#timeline-*` ids.

- **First null-registration-date test failed.** Tried to insert a
  bcct_rows row with `registration_date=null` to exercise the
  `where registration_date is not null` defensive clause in the
  store. Hit `NotNullViolation: null value in column "year"` —
  `bcct_rows.year` is a NOT NULL generated column derived from
  `registration_date`. Dropped the test; kept a comment noting the
  schema rules the case out.

- **Initial "Bất nhất giữa 2 năm" semantic was mode-only.** User
  caught the misleading framing — "two years can both have mode =
  SETS but one carries PIECES + the other carries METRES; modes
  match but the sets differ". Updated to set-comparison + added
  a separate "Đổi ĐVT chính" column for the original mode-drift
  signal.

- **Dev server SIGKILL-style restart in mid-session** when the
  previous nohup process tree was rooted in the Bash tool shell.
  Same fix as 2026-05-15 session: `setsid` detach. Did not lose
  data, just had to wait for application startup again.

## Open Items

- **`scripts/uom_drift_report.py` untracked.** Decide whether to
  commit standalone, promote to a route/UI, or leave as workdir-
  only tooling. Currently sits next to `scripts/screenshot_*.py`
  helpers, consistent with the "analyst scripts" pattern.

- **CO consumer PR for `/v1/hub/clients/{c}/declarations` + ZIP**
  still pending. No further action from Data Hub.

- **Demo box deploy bundle.** Now includes the time-series feature
  on top of everything from prior sessions. Single deploy will
  pick up the lot.

- **`_FIELDS` field-set registry refactor.** Currently duplicated
  between snapshot and time-series stores. Triggered "3+ consumer"
  threshold: add catalog conflicts page as a 3rd consumer? If so,
  the registry becomes useful. Defer.

- **Future phase 3 (SVG horizontal timeline).** Brief earmarked
  ~1d effort if staff requests visual polish on top of the table
  view. No request yet — keep on the shelf.

- **A.4.3 smart goods_name similarity (pg_trgm-based)** still
  deferred. Until it ships, goods_name stays in snapshot panel
  only (not time-series).

- **A.5 paren-extract limitation** carried over. Time-series SQL
  uses `customs_code = %s` like the snapshot panel; Growatt NB
  codes hidden in `goods_name` parens don't surface.

- **Future session note housekeeping.** Two prior session notes
  (`2026-05-15-catalog-conflicts-page-ship.md`,
  `2026-05-15-m16-ingest-and-uom-evidence-audit.md`) remain
  untracked. The 2026-05-15 conflicts one was drafted earlier
  in this conversation but missed the handoff commit (the handoff
  ended up committing `2026-05-18-declaration-file-status-shipped.md`
  instead). Next session can decide whether to commit them or
  let them go.
