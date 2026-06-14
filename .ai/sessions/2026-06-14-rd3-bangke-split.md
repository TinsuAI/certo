# Session 2026-06-14 — RD3: redesign bước Bảng kê C/O (Review ⇄ Excel sheet) + UX fixes

Branch `feat/rd3-bangke-split` (pushed, no PR). Big session: design pass → implement the origin-step split →
many live UX iterations from the user → backlog grooming → commit/push/handoff. Did NOT touch BG1 (deferred).

## What Was Done

1. **Setup**: turned on dev server with live reload (`npm run co:serve` → `:8001`); added the requirement to
   `AGENTS.md` Session Start so future sessions auto-start it.

2. **Design pass** (user invited UX involvement): mapped the overloaded origin step (Explore agent), then ran
   a `critic` + `Plan` agent in parallel. Key outcome — **invert the content split**: config and the LVC result
   are coupled in a tight per-sheet loop, so config must live WITH the grid, not in Review. Chosen structure:
   **drill-in within step 3** (stepper unchanged).

3. **RD3 implementation** (`2464797`):
   - **Server** (`co_case_context.py`, `co_case.py`): `?sheet=<code>` → `origin_view` (review|sheet) +
     `active_sheet_code`, validated vs product codes; threaded via `co_case_step` GET. View-state kept OUT of
     `origin_case_revision`.
   - **Template** (`co_case.html`): `origin-step-root` wrapper with view class; **Review dashboard** (status
     matrix, drill rows) + **sheet workspace**; moved sheet tabs to the **bottom** (Excel-style, as `<button>`);
     `‹ Tổng quan` back; wrapped config controls in a `<details>`; settings modal container; merged warnings +
     quick-select into one `origin-grid-toolbar`; locked 🔒 on pills + tab class.
   - **JS** (`co_case.html`): `captureOriginView`/`applyOriginView`/`setOriginUrlSheet`; document-delegated
     drill/back/tab-click; `initOriginSettingsModal` **moves** config+cost+columns into the ⚙ modal (preserves
     listeners); shell-swap view restore (POST preserves prevView, GET step-nav uses `serverNav:true`);
     deep-link/F5 init; tab-click URL sync.
   - **CSS** (`app.css`): view toggle, Review table, bottom tabs (strong active + locked tint), full-screen
     overlay for sheet view + `body:has()` scroll lock, settings modal, aggressive chrome compaction.

4. **Live UX iterations** (driven by the user, all in `2464797` except picker):
   - **Picker fix** (`fb3267d`, base.html): "Đổi hồ sơ" died after shell swap (bound-once, in-shell) → delegated.
   - **invoice-facts** span overlap: container had chip styling but no flex layout → made it flex-wrap, spans keep chip.
   - **Maximize grid**: full-screen overlay (removes topnav/case chrome + bottom gap) + ⚙ modal (config/cost/cols
     off-grid) + hide save-bar-when-clean→**reverted** to always-visible compact icon cluster + warnings to 1 row
     + compact tabs + merged rows. Grid 16%→**63%@900 / 69%@1080**.
   - **Tab→URL** bug: tab switch didn't update `?sheet=` → fixed in the tab-click handler.
   - **Save-status**: user rejected hiding when clean → always-visible compact (✓/● + ↶ ↷ Lưu ✕) on metrics row.
   - **Warnings stacking 1/line**: `.origin-warning-item min-width:min(100%,13rem)` collapsed in narrow flex row →
     `min-width:auto` in sheet view.
   - **Locked sheets (B8)**: 🔒 + green tint on pills, tabs, body border.
   - **Toast (B5)**: root cause of "transparent" = `background:var(--surface)` (token doesn't exist) → `var(--card)`;
     moved to bottom-right, 5s, left-accent by kind.

5. **Backlog** (`a311cfd`): added **BG1** (delete-NVL data loss, full repro), **B5** (toast, DONE), **B6** (native
   currency review), **B7** (criteria datalist black bg), **B8** (locked-sheet ID, DONE). Carried over prev-session
   docs that were uncommitted.

6. **Verify**: e2e `e2e_bangke_split.cjs` **24/24** + screenshot eval each step; **137 targeted backend tests** pass.

## Decisions Made

- **Drill-in within step 3** (not 2 top-level steps, not persistent sub-tabs): matches the per-sheet iterative
  rhythm; stepper unchanged.
- **Config lives with the grid** (inverted from the first proposal) — critic showed config↔LVC coupling makes a
  Review-config split a ping-pong. Then pushed further: config/cost/columns into a ⚙ **modal** (user wanted max grid).
- **Sheet view = full-screen fixed overlay** (not sticky+dock). The grid has `overflow-x`, so it's *forced* to be
  the vertical scroller (sticky thead needs that) — the chrome above it can't share the grid's scroll, so the only
  way to enlarge the grid is to remove/shrink/relocate chrome rows. Overlay reclaims topnav + kills the bottom gap.
- **Settings-modal content is JS-moved** (DOM appendChild) rather than duplicated — preserves all existing listeners.
- **Save-status always visible** (user override) but compact icon cluster.
- **Grouped commits by file** (env has no `git add -p`; RD3 + fixes interleave in co_case.html/app.css).
- **Did NOT open a PR / merge** — branch only; main→prod auto-deploys, so hold for user.

## What Didn't Work

- **Sticky workspace + JS "dock"** (scroll chrome off): grid still cramped (~22%) because the *panel* chrome
  (~480px), not the app chrome, dominated; and sizing was fragile. Replaced by the full-screen overlay.
- **Hiding the dirty/save bar when clean**: user explicitly wants the status always present → reverted.
- **Over-compaction broke `origin-column-controls`** (flex-shrank to 1px in the flex-column panel because it has
  `overflow-x`). Fixed with `flex:0 0 auto` on chrome children (only the grid flexes).
- **CSS-only squeezing of chrome** hit diminishing returns + breakage; the real wins were structural (overlay +
  ⚙ modal + merging rows).

## Open Items

- **BG1 — delete-NVL data loss**: the agreed next task. NOT started. `/fix`.
- **PR/merge** of `feat/rd3-bangke-split` (merge = prod deploy).
- **B6** native-currency review, **B7** criteria dropdown styling.
- **Polish not done**: arrow-key tab nav doesn't sync URL (only click does); warnings detail hidden in sheet (tooltip
  only); deep-link to a not-yet-loaded johnson sheet shows empty until Load BOM (expected).
- **johnson NVL "no info"** (user-reported) was diagnosed as **DC1 data** (missing names/HS) + values 0 until Tính —
  NOT a redesign bug; no action taken.
