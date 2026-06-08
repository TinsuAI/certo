# Session: bảng kê recalc/lock tồn parity fix + save UX (in-place, auto-save)

Date: 2026-06-08
Status at end: all changes **uncommitted**; verified on real Johnson; one feature decision pending.

## What Was Done

### 1. Fixed the "không chốt được … vượt tồn ở N lot" bug (the headline)
Reported: johnson `co-case-a4e1dbbdb0f5` / sheet `MFW0507-39` — operator saw 41 NVL không tồn,
deleted 39 (not in BCCT), substituted 2, then **couldn't Chốt** ("vượt tồn ở 47 lot").

Root cause (data-source parity gap, not the 2 substituted NVL):
- An edited sheet recalculates via `recalculate_origin_sheet_edits` (used by BOTH "Lưu"/save AND
  post-edit "Tính bảng kê" since `074e926`). It pulled tồn from `portfolio_service.list_bcct_by_codes`
  → `co_stock_rows_from_bcct`, which returns **RAW BCCT** (`remaining_qty = quantity`, NOT trừ-lùi
  folded, blind to other-case claims).
- `co_stock_ledger.record_sheet_lock` (Chốt) validates each claim against the **trừ-lùi-FOLDED**
  `co_stock_rows.remaining_qty` − other-case claims.
- Raw > folded on every lot with a trừ-lùi baseline → over-claim on dozens of lots. Unedited sheets
  lock fine because the normal `/calculate` reads the folded snapshot via
  `_calculate_stock_rows_from_snapshot`.
- Regression introduced by `66fe311` (2026-06-04, fold trừ-lùi into snapshot remaining); before it,
  snapshot remaining == raw qty so the two paths agreed. `074e926` widened exposure.

Fix (`app/routers/co_case.py`, `recalculate_origin_sheet_edits`): source stock from
`_calculate_stock_rows_from_snapshot(client)` (the same folded+ledger snapshot the lock validates),
falling back to the raw narrow pull only when the snapshot is empty (cold start). One function; fixes
both the "Lưu" and "Tính bảng kê" call sites.

Tests: `tests/test_recalc_stock_source_parity.py` (recalc sources folded snapshot, not raw; +cold-start
fallback) and `tests/test_recalc_lock_parity_db.py` (DB-gated: against the real ledger, a raw-sized
claim is rejected and a folded-sized claim is accepted on the same folded lot).

### 2. In-place save (no full reload / F5)
`/save` previously returned JSON and the JS did `window.location.assign` (full reload). Now `/save`
content-negotiates: `Accept: text/html` returns the re-rendered `co_case.html` shell; default Accept
still returns the JSON contract (4 existing tests). The save JS sends `Accept: text/html` and routes
the success through the existing `replaceCaseShellFromResponse` (same in-place swap path /calculate,
/lock, /load-bom, /reopen already use). +1 test (`test_origin_sheet_save_returns_swappable_shell_for_html_accept`).

### 3. Debounced auto-save
Hooked into the single dirty chokepoint `markSheetDirty` → `scheduleAutoSave(panel)` (per-panel 2s
timer). `maybeAutoSave` fires only when there are unsaved edits (staged ops OR a diverged ĐM input),
NOT while an input in the panel is focused (no focus-yank), and re-arms while a save is in flight.
Manual "Lưu bảng kê" still works (`triggerSave(panel, {auto:true})` just suppresses the in-flight toast).
Banner message → "…tự lưu khi ngừng…".

### 4. Persistent edit toolbar (Excel-like, step 1)
User: "banner save + Lùi/Tiến lúc nào cũng hiện đi, sao saved rồi lại ẩn?" The dirty banner was
JS-created on dirty and removed on save. Made it **server-rendered & always visible** per unlocked sheet
(`<div data-origin-edit-toolbar data-origin-dirty-banner …>` inserted after `data-origin-strip` in
`co_case.html`, gated `{% if product.origin_sheet_status != 'locked' %}`). It survives shell swaps for
free. `markSheetDirty`/`clearSheetDirty` now FLIP its state (dirty ↔ `origin-dirty-banner-clean` +
"● Chưa lưu · N thao tác" ↔ "✓ Đã lưu") instead of creating/removing. Buttons bound by **delegation**
(one `document` click listener scoping `[data-origin-edit-toolbar] button`) so they work after every
swap. `updateSheetHistoryButtons` now gates the Lưu button on `hasUnsavedEdits` (so a ĐM edit — which
only lands in pendingOps at save-time — still enables Lưu). New CSS `.origin-dirty-banner-clean` (calm
neutral/success, no amber when clean). Verified: toolbar visible+"✓ Đã lưu" on load → "● Chưa lưu" on
edit (Lưu enabled) → still visible + "✓ Đã lưu" after auto-save. `snapshotSheet` only clones the table
`tbody`, so the toolbar's placement doesn't interfere with undo/redo.

### Verification (real data + browser)
- Read-only before/after on real Johnson (`co-case-ec000d03522e` / `MFW0506-39`, after deleting 1 NVL):
  PRE-FIX raw path = **37 over-claim lots**, POST-FIX folded path = **0**. Same mechanism as the
  reported 47-lot case.
- Playwright on the live local server + real Johnson snapshot/ledger: Chốt succeeds (HTTP 200,
  "Đã chốt", no "vượt tồn"); save updates in-place (no reload); auto-save persists on its own
  (no reload, dirty banner clears, 0 JS console errors). Scripts under `.ai/scripts/pw_*.py`, each does
  full backup→test→restore of the dev case + ledger.
- Full file-mode suite: 560 passed / 11 skipped.

## Decisions Made
- **Stock source must be unified:** any path that allocates tồn reads the folded snapshot
  (`_calculate_stock_rows_from_snapshot`), never raw `list_bcct_by_codes`, except cold-start. This is
  the invariant the bug violated. Saved to memory [[co-stock-recalc-folded-parity]].
- **In-place save via content negotiation** (not a new endpoint): reuse `replaceCaseShellFromResponse`;
  keep JSON default so API/tests are untouched.
- **Auto-save is debounced + batched on purpose** (2s): the operator's real workflow is bulk edits
  (delete 39 + thay 2); per-edit save would do 41 recalcs. Focus-guard + in-flight re-arm avoid
  disruption. User explicitly asked for auto-save earlier in the session.
- **Did NOT touch prod.** Reproduced + verified entirely on the local Johnson dataset (it has the full
  snapshot + ledger + trap lots). Per [[test-local-by-default]].

## What Didn't Work / Gotchas
- **`store.save_state` does NOT restore a per-case record.** `PostgresCoCaseStateStore` hydrates
  `cases[]` from per-case `co_cases` rows; restoring a case requires `save_case_record(payload, revision)`
  or a direct `co_cases.payload` UPDATE. A first restore attempt used `save_state` → left the dev case
  dirty; cleaned up via `save_case_record` + `/load-bom` + `/calculate`.
- **Restore race:** a Playwright run that closed the browser while an auto-save was still in flight let a
  late `/save` write land AFTER restore (dev case ended with a stray override). Fix: wait for the dirty
  banner to DETACH (auto-save done) before asserting/closing; harden restore with a verify+retry. The
  first `banner_gone=False` was Johnson's slow recalc (~seconds), not a re-dirty loop.
- **Raw `psql client_id='johnson-vn'` returned 0 rows** (wrong schema/search_path); the app connection
  (`app.database.connect` / `co_stock_materializer.row_count`) shows the real 60,173. Always trust the app.
- Growatt local has a folded snapshot too but NO usable+folded "trap" lots (its folded lots have empty
  material_code) → could not reproduce on growatt; Johnson has 25,727 trap lots.
- **Dev-data drift from looping browser tests on a SHARED case.** Running several Playwright tests in a
  row against `co-case-ec000d03522e` (each backup→test→restore) cumulatively drifted its state: an early
  test left it locked (and a `save_state`-based restore failed), later runs then backed up the
  contaminated baseline, and case claims drifted **545 → 524**. End state is SANE (7 locked + MFW0506-39
  re-set to `calculated`, overrides=0) but not pristine. Takeaways: (1) `save_state` does NOT restore a
  per-case record — use `save_case_record(payload, revision)` or a direct `co_cases.payload` UPDATE;
  (2) wait for the in-flight auto-save to finish (banner detaches) before restoring, or a late write
  lands after restore; (3) this is the case for **T1 test DB isolation** — don't loop tests over shared
  mutable dev data.

## Open Items
- **Excel-like bảng kê — partially done.** ✅ Persistent always-visible toolbar + saved/dirty state
  (this session). ⏳ Still pending, **gated on the save-model decision** (user deferred twice via
  /handoff): Ctrl+Z/Y shortcuts; undo that SURVIVES a save (the shell swap on save wipes `__sheetHistory`
  — needs save-without-swap or re-hydrating history post-swap); unsaved-leave warning. Core tension: the
  2s auto-save kills the undo window. Save-model options: (a) manual Ctrl+S + drop auto-save [rec],
  (b) auto-save on leave-sheet/~30s idle, (c) keep 2s. Undo plumbing: `__sheetHistory` +
  `snapshotSheet`/`undoSheetEdit`/`redoSheetEdit` (`co_case.html`). Memory [[bangke-excel-like-dirty-undo]].
- **Commit + push this session.** Nothing committed yet. Suggest 2–3 focused commits (parity fix /
  in-place save / auto-save). Push auto-deploys to prod+demo (~1-2min) — ask first.
- **`.ai/scripts/pw_*.py`** are dev repro artifacts (mutate the local Johnson case but back up + restore).
  Keep or delete per preference; they're not test-suite tests.
- Inherited D1 backlog unchanged (transaction_key sign-off, fix C, T1 DB isolation, parity harness).
