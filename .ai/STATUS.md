# Project Status

**Date:** 2026-05-21 — Catalog detail per-material BCCT time-series shipped + pushed to origin. Ad-hoc UoM drift Excel report tool created (untracked).

## Current State

**Branch:** `main` at `58587ca`, **in sync with `origin/main`** (10 commits pushed in this session block).

Recent commits on `origin/main`:
- `58587ca` — **NEW:** per-material BCCT time-series on catalog detail page (RLE + quarterly aggregate)
- `6d45f77` — handoff notes (declaration file status + A.2 conflicts session log)
- `21f3620` — declaration file status API + bulk ZIP download for CO
- `d4ea2d7` — catalog conflicts review queue (A.2)
- `b315eba` — UoM evidence audit
- `b4665f6` / `10c2084` / `bb0faf1` / `3baea87` / `69b9da0` — M16 + UoM work

**Tests:** 1143 passed, 15 skipped (+13 this session for the time-series store).

**Migrations:** at mig 066. No new mig.

**Working tree:** dirty with pre-existing `demo-company-feed/*` PNG/xlsx drift (unrelated, predates this session block). Untracked: `scripts/uom_drift_report.py` (ad-hoc tool built this session — NOT committed; reusable for future analyst questions, keep or commit standalone next session if desired), `scripts/generate_training_input_scenarios.py`, `docs/training/`, two prior session notes.

**Dev server:** `:8754` workers=4. Restarted via `setsid` mid-session after the template edit; PID rolled — verify with `lsof -i :8754 -P -n` next session.

**Demo box (`100.84.189.87:8754`):** still NOT updated. Backlog now includes the time-series feature on top of the prior bundle (mig 065/066 + M16 ingest + UoM overrides + A.2 conflicts + declaration API + ZIP route + time-series).

**Local Johnson BOM state:** unchanged this session. Sample timeline rendering verified on `1000469833` — 6 SETS↔PIECES runs across 2025-06 to 2026-05; declaration_type drift E13→E11→E15→E11; 5 quarters of data, no price jumps.

## Recent Changes

Two deliverables this session block:

### 1. UoM drift Excel report tool (uncommitted)

- `scripts/uom_drift_report.py` (untracked). Argparse CLI: `--client`, `--year-from`, `--year-to`, `--nvl-imports-only`, `--out`. Renders 2-sheet XLSX with summary + per-(code, unit) detail. Cross-year flags: "Bất nhất 2025/2026" (intra-year), "Bất nhất giữa 2 năm" (set-comparison: tập ĐVT khác nhau giữa 2 năm — broader than mode-drift), "Đổi ĐVT chính" (mode-drift only — narrow signal). Highlight vàng dòng có mode-drift.
- Generated 2 files for user, both delivered to Windows side: `C:\Users\sys\Downloads\johnson_uom_drift_2025_2026.xlsx` (all rows, 188 codes) + `C:\temp\toss\johnson_uom_drift_NVL_nhap_2025_2026.xlsx` (NVL imports only, 171 codes).
- **Lesson surfaced** (caught by user): semantic of "drift between years" must compare the full unit *set*, not just the mode — comparing modes alone can falsely report "stable" when 2025 has units {SETS, PIECES} (mode SETS) and 2026 has {SETS, METRES} (mode SETS). Set-comparison surfaces 118 cases vs 85 mode-only; the 33-case gap is exactly the misleading subset.

### 2. Catalog detail per-material BCCT time-series (commit `58587ca`)

Closes BACKLOG A.4 phase 2 (the snapshot panel shipped 2026-05-10 was phase 1).

- New store `app/stores/catalog_bcct_timeseries.py::analyze_material_timeline` — 1 SQL query per material aggregating by `(declaration_no, direction, registration_date, declaration_type)` with `mode() within group` for multi-line collapse. Python-side RLE + calendar-quarter bucketing.
- Categorical timelines for `unit / hs_code / origin / declaration_type` (declaration_type is new; snapshot panel covers `goods_name` instead — by design per brief). Critical fields expand by default.
- Per-quarter numeric panel with price min/median/max + qty total/mean + currency mode + 2× median-jump flag (boundary inclusive: ratio == 2.0 or == 0.5 fires).
- Direction breakdown chip per run (`↓ NK N`, `↑ XK M`). Combined NK+XK timeline per MVP decision.
- Inline "Xem biến động →" anchor link from snapshot drift rows to matching timeline sections.
- +13 provider tests (10 base + 3 from review bundle: same-day-different-values, 2.0×/0.5× boundary, direction-split-by-value-change).
- 3 committed screenshots verify on Johnson `1000469833`.
- Review bundle applied: `prev_median > 0` guard comment, `sorted(set(currencies))` for deterministic currency tie-break, 3 extra tests.

### 3. Push to origin

10 commits pushed `fd793fc..58587ca` in one go (first push since 2026-05-15 multi-session work).

## Next Steps

Priority order:

1. **Wait for CO consumer PR** on the declaration file status endpoint
   (`/v1/hub/clients/{cid}/declarations` + ZIP download). Data Hub
   provider tests + changelog + sister-app note shipped; CO `CLAUDE.md`
   rule satisfied. Nothing to do until CO pings back.

2. **Deploy bundle to demo box** (`100.84.189.87:8754`). Now includes:
   mig 065/066, M16 ingest, UoM overrides, A.2 conflicts page,
   declaration file status API + ZIP route, time-series feature.
   Single deploy picks all of them up.

3. **Ask Johnson confirm factor for 58 unverified M16 codes** (list in
   `.ai/features/2026-05-15-m16-uom-analysis/unverified_codes.txt`).

4. **CO repo dropdown logic for dual_source 409**. Data Hub side
   ready; CO repo at `~/workspace/client/barry-CO-main` needs the
   consumer.

5. **Verify `1000454182` factor=2.0** with Johnson (n=2/3 small sample).

6. **70 sản phẩm XK 2026 thiếu BOM** — get from Johnson or document.

7. **Decide what to do with `scripts/uom_drift_report.py`.** Options:
   - Commit standalone (keeps the analyst tool reusable + tested).
   - Promote to a route / admin page if user wants it on-screen.
   - Leave untracked (current state — useful for ad-hoc but not
     versioned).

8. **Next backlog item if bandwidth.**
   - F.1 Growatt programmatic bulk re-ingest (~0.5-1d, mirror Johnson).
   - A.4.2 Substitute XLSX bulk upload (~0.5d).
   - A.4.3 Smarter goods_name similarity — gated on pg_trgm.
   - Future phase 3 SVG timeline visualization on top of the time-
     series store shipped today (defer unless staff request).

## Blockers

- Johnson contact / customs broker for UoM factor confirmation
  (carry-over).
- CO repo dev availability for declaration consumer PR + dual_source
  dropdown logic (carry-over).

## Notes for Next AI Session

- **`scripts/uom_drift_report.py` untracked but useful.** Argparse-
  driven; tested manually against Johnson 2025-2026 (188 codes all,
  171 NVL-only with `--nvl-imports-only`). Per-code (unit) breakdown
  + 4 boolean drift flags. Re-runs idempotently.

- **"Bất nhất" semantic clarification baked in.** The script offers
  two cross-year flags now: `Bất nhất giữa 2 năm` (set-comparison —
  broader, surfaces ANY change in distinct unit sets between years)
  and `Đổi ĐVT chính` (mode-only — narrower, only when mode flipped).
  Cross-year set-drift was 118 codes for Johnson NVL; mode-drift
  only 85. The 33-code gap matters because it captures cases where
  2025 + 2026 share the same mode but one year has additional units
  the other doesn't — a real signal staff would miss with mode-only.

- **`hub.bcct_rows.year` is a NOT NULL generated column** derived from
  `registration_date`. Means you CANNOT insert a row with null
  `registration_date` in tests. Discovered while writing
  `tests/test_catalog_bcct_timeseries.py` — dropped the null-date
  test. The `where registration_date is not null` clause in the
  store stays as defensive coding but the case is schema-impossible.

- **Time-series store has a paren-extract limitation.** Same as the
  snapshot panel — SQL uses `customs_code = %s`, doesn't match NB
  codes hidden in `goods_name` parens (Growatt-shape). BACKLOG A.5
  tracks the eventual fix; not in scope here.

- **`_FIELDS` is duplicated** between `catalog_bcct_analysis.py`
  (snapshot, includes `goods_name`) and `catalog_bcct_timeseries.py`
  (time-series, replaces `goods_name` with `declaration_type`). By
  design — snapshot focuses on name drift, time-series doesn't track
  name until BACKLOG A.4.3 lands. Worth flagging when a 3rd
  consumer needs the field set; until then live with it.

- **Multi-section screenshot trick:** when capturing the new section
  with `page.screenshot(full_page=True)`, the resulting PNG was
  34kx6k pixels (the catalog detail page is enormous). Fix in
  `scripts/screenshot_catalog_timeline.py`: capture per-element
  with `locator.screenshot()` against the specific
  `#timeline-<field>` and the quarterly block. Each output ≤ 350px
  tall. Pattern reusable for other detail-page sections.

- **`set` iteration is not deterministic** (Python 3.12 reorders
  small int sets via hash). Code review flagged this in the
  currency-mode tie-break path. Replacement: `sorted(set(values))`
  before iterating. Worth keeping in mind for any "pick a mode"
  helper.

- **Dev server detached via setsid stays alive across Bash-tool
  shell churn.** Verified twice this session — survived. Default
  start command for new sessions:
  `setsid nohup uv run uvicorn app.main:app --host 127.0.0.1 --port 8754 --workers 4 > /tmp/dh_dev.log 2>&1 < /dev/null &`
  Confirm PID + PGID via
  `ps -o pid,pgid,sid -p $(pgrep -f "uvicorn app.main" | head -1)`
  — if PGID != session shell PGID, it's detached.

- **Push gate now reset.** `main` matches `origin/main`. Future
  commits should be smaller per-session pushes to avoid re-piling
  10 commits at once.
