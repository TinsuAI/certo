# Project Status

## Current State
- **Branch `feat/rd3-bangke-split` (NOT merged, pushed to origin).** This session shipped **RD3 — redesign
  the "Bảng kê C/O" (origin) step** plus a string of UX fixes. 4 commits on top of `main` HEAD `09509ae`
  (`fb3267d` picker, `2464797` RD3 redesign, `24d456c` live-reload doc, `a311cfd` backlog+carry-over).
  Pushed to `origin/feat/rd3-bangke-split` (feature branch → **no auto-deploy**; only `main`→TinsuAI/co
  deploys). **No PR opened yet.**
- **RD3 shipped (origin step split into a drill-in):**
  - **Review dashboard** (default landing of step 3): per-sheet status matrix (status pill +🔒, BOM summary,
    effective config read-only, metric chips, ⚠ count, drill chevron) + case toolbar (reorder, Xuất bảng kê HQ).
  - **Sheet view** (drill-in, `?sheet=<code>`): **full-screen `position:fixed` overlay** — covers topnav/case
    chrome, only "‹ Tổng quan" back. Grid is the single scroller (frozen thead, **bottom Excel tabs** pinned,
    strong active + 🔒 green tint for locked). **⚙ modal** holds config overrides + cost-buildup + column
    toggles (moved off-grid). Save-status = always-visible compact icon cluster (✓/● + ↶ ↷ Lưu ✕) on the
    metrics row. Warnings collapse to one inline row. Grid ≈ **63% @900px / 69% @1080px** of viewport.
  - **Routing**: `?sheet=` GET → `origin_view` (server, `co_case_context.py`); client restores view across
    shell-swaps + syncs URL on tab-click; **view-state never enters `origin_case_revision`**.
- **Live reload mandate added** to `AGENTS.md` Session Start (dev server `npm run co:serve` → `127.0.0.1:8001`,
  uvicorn `--reload`, every session).
- **Dev server running** locally on `:8001` (background task; auth OFF, .env loaded).
- **Mid-flight: nothing.** All committed + pushed. STATUS + new session log are the only uncommitted docs
  (this handoff).

## Recent Changes (this session, latest first)
- **`a311cfd`** docs: BACKLOG **BG1** (delete-NVL data loss) + **B5–B8** UX items; carry-over prev-session docs.
- **`24d456c`** docs: AGENTS.md — start dev server with live reload at session start.
- **`2464797`** feat: RD3 bảng kê redesign (co_case.html +379, app.css +304, co_case_context.py, co_case.py,
  new `.ai/scripts/e2e_bangke_split.cjs`). Includes invoice-facts overlap fix + toast redesign (B5).
- **`fb3267d`** fix: delegate case picker ("Đổi hồ sơ") so it survives shell swap.

## Next Steps (priority order)
1. **BG1 — Xoá NVL mất dòng (DATA LOSS, deferred to here).** Repro `growatt-vn/co-case-e44fe2065b62`/origin:
   delete 1 row → view drops by **2** (122→120→118), fold "đã xoá" stuck at **1** → real rows vanish (wrong
   LVC/VNM + wrong BOM on Chốt). User-confirmed next task. Soi `co_case_origin_sheet_save` + `sheet_edit_bom_rows`
   (recalc) + fold-summary render + JS `initSheetBulkDelete`/staged ops. `/fix` it. (BACKLOG › Bug — Bảng kê › BG1.)
2. **Open PR for `feat/rd3-bangke-split`** (or merge to main when user approves → that auto-deploys prod).
3. **B6** — review "nguyên tệ" (native currency): all cases show only VND, suspect `currency_mode` / FX path.
4. **B7** — "Tiêu chí" datalist dropdown has an ugly black background → elegant (Primer combobox or token).
5. Older backlog: DC1/DC3, M1, D1 parity, P1 index N+1, T1 test-DB isolation.

## Notes for Next AI Session
- **⚠ DEV-FLOW (user mandate):** every feature/fix → run **Playwright e2e + screenshot + EVALUATE the images**
  (not just code asserts) before claiming done. Memory [[dev-flow-e2e-screenshot-eval]].
- **Reusable e2e:** `.ai/scripts/e2e_bangke_split.cjs` (24/24: review→drill→sheet→⚙ modal→back→deep-link→
  multi-tab switch). Run: `PWDIR=$(dirname "$(ls -d ~/.npm/_npx/*/node_modules/playwright|head -1)"); NODE_PATH="$PWDIR" node <script>`.
  Scratch shots → `.ai/screenshots/2026-06-14-bangke-split/` (gitignored). Multi-product test case: `co-case-be691b9dceec`.
- **RD3 architecture (read before touching sheet view):**
  - Sheet view is a **full-screen fixed overlay** (`.origin-view-sheet [data-origin-sheet-workspace]` →
    `position:fixed; inset:0; z-index:50`) + `body:has(.origin-view-sheet){overflow:hidden}`. The grid
    (`.origin-table-scroll`, has `overflow-x`) is **forced** to be the vertical scroller (sticky thead needs it)
    → to enlarge the grid you must **shrink/relocate chrome rows above it**, not the page.
  - **⚙ settings modal** content is **moved by JS** (`initOriginSettingsModal`, in `refreshCaseShellInteractions`)
    from the panel into `[data-origin-settings-body]` — DOM-move preserves listeners; re-runs each shell swap.
  - View helpers in co_case.html: `captureOriginView`/`applyOriginView`/`setOriginUrlSheet`; drill/back/tab-click
    handlers are **document-delegated** (survive shell swap). `replaceCaseShellFromResponse` captures view before
    swap, restores after (POST preserves prevView; GET workflow-step nav passes `serverNav:true`).
  - **Any new origin control must be document-delegated or registered in `refreshCaseShellInteractions`** or it
    dies after a Tính/Chốt swap. [[origin-wiring-must-survive-shell-swap]].
- **Toast** now `.ui-toast` bg `var(--card)` (was broken `var(--surface)` → transparent), bottom-right, 5s.
- **CSS uses `:has()`** (modern browsers) for `body:has(.origin-view-sheet)` lock. Fine for staff browsers.
- **Local dev:** `npm run co:serve` (already running). File-mode tests: `PYTHONPATH=. uv run python -m pytest`
  (NO `.env`) [[test-env-filemode-vs-datahub]]. This session: 137 targeted backend pass.
- **Design pass** (start of session) produced the drill-in + inverted content split (config lives WITH the grid,
  not in Review) via critic + Plan agents — captured in the session log. Don't re-litigate.
- **Commit-split caveat:** co_case.html/app.css mix RD3 + fixes in interleaved hunks, env has no `git add -p`
  → grouped by file (chủ ý). base.html picker fix is its own commit.
