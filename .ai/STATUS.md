# Project Status

## Current State
- **CO-stock recalc/lock parity bug — FIXED, fully verified on real Johnson, NOT committed.**
  An edited origin sheet (thay/xoá/thêm NVL) could not be "Chốt" — failed with
  `không chốt được bảng kê … vì vượt tồn ở N lot` (johnson `co-case-a4e1dbbdb0f5` /
  `MFW0507-39` = 47 lot). Root cause: `recalculate_origin_sheet_edits` (the override path used
  by both "Lưu" and post-edit "Tính bảng kê") allocated tồn from `list_bcct_by_codes` → **raw
  BCCT** (`remaining_qty == quantity`, un-folded, ignores other-case claims), while
  `co_stock_ledger.record_sheet_lock` validates against the **trừ-lùi-FOLDED** snapshot − other
  claims. Every folded lot over-claimed. Regression from fold commit `66fe311` (2026-06-04);
  widened by `074e926` routing the normal "Tính bảng kê" through that raw path after an edit.
  **Fix:** recalc now sources stock from `_calculate_stock_rows_from_snapshot` (same folded+ledger
  snapshot the lock checks), raw narrow pull only on cold/empty snapshot. `app/routers/co_case.py`.
- **Bảng kê save UX reworked — in-place + debounced auto-save, NOT committed.**
  - **In-place save:** `/save` now content-negotiates — `Accept: text/html` returns the re-rendered
    `co_case.html` shell (default Accept still JSON for API/tests); the save JS routes through the
    existing `replaceCaseShellFromResponse` (same path as /calculate, /lock) → **no full reload / F5**.
  - **Auto-save (debounced 2s):** `markSheetDirty` → `scheduleAutoSave` (per-panel timer). After the
    operator pauses ~2s it auto-persists (batched: bulk delete+thay recalc ONCE), never yanks focus
    mid-edit, re-arms while a save is in flight, detects diverged ĐM inputs (norm edits land in
    pendingOps only at save-time). Manual "Lưu bảng kê" still works.
  - **Persistent edit toolbar (Excel-like, step 1):** the toolbar (status + Lùi/Tiến + Lưu + Bỏ) is now
    **server-rendered & always visible** per unlocked sheet (`data-origin-edit-toolbar` after
    `data-origin-strip`), survives shell swaps, shows **✓ Đã lưu / ● Chưa lưu · N thao tác** and no
    longer hides after save. `markSheetDirty`/`clearSheetDirty` flip state (don't create/remove);
    buttons bound by delegation; `updateSheetHistoryButtons` gates Lưu on `hasUnsavedEdits`. CSS
    `.origin-dirty-banner-clean` (calm, no amber when clean).
- **PENDING user decision (deferred via /handoff): the bảng kê save model** — needed to finish the
  Excel-like work. Conflicts with the 2s auto-save (commits too fast → kills undo window). Options:
  (a) manual Ctrl+S + strong undo, drop 2s auto-save [rec]; (b) auto-save on leave-sheet/~30s idle;
  (c) keep 2s. **Persistent toolbar is DONE**; remaining Excel work (Ctrl+Z/Y shortcuts, undo that
  SURVIVES a save [shell swap currently wipes `__sheetHistory`], unsaved-leave warning) is gated on
  this choice. Memory [[bangke-excel-like-dirty-undo]].
- **Inherited (prior session, committed + deployed):** D1 CO-stock refresh hardening (`2c856da`,
  pushed+deployed prod+demo) + backbone doc (`4f567ff`, **unpushed**). See the D1 section in Next Steps.

## Recent Changes (latest first)
- **(uncommitted)** Persistent always-visible edit toolbar (`app/templates/co_case.html`,
  `app/static/css/app.css`) — no longer hides after save; shows saved/dirty state.
- **(uncommitted)** Bảng kê save UX: `/save` HTML negotiation + in-place swap; debounced auto-save
  (`app/routers/co_case.py`, `app/templates/co_case.html`). +1 test (`/save` HTML shell).
- **(uncommitted)** Fix recalc/lock tồn parity (`app/routers/co_case.py`). +2 tests
  (`tests/test_recalc_stock_source_parity.py`, `tests/test_recalc_lock_parity_db.py` [DB-gated]).
- **`4f567ff`** docs(co-stock): backbone architecture reference. **Unpushed.**
- **`2c856da`** fix(co-stock): harden delta/full refresh (D1). Pushed + deployed prod+demo.

## Next Steps (priority order)
1. **DECIDE the bảng kê save model** (blocks the rest of the Excel-like work). I asked; user deferred.
   Options: (a) manual Ctrl+S + strong undo, drop the 2s auto-save [my rec]; (b) auto-save on
   leave-sheet / ~30s idle so undo survives; (c) keep 2s auto-save (undo ~2s). **Persistent toolbar is
   already done.** Remaining once decided: Ctrl+Z/Y; undo that SURVIVES a save (the shell swap on save
   wipes `__sheetHistory` — needs either save-without-swap or re-hydrating history after swap);
   unsaved-leave warning. Undo plumbing: `__sheetHistory` + `snapshotSheet`/`undo`/`redo` (`co_case.html`).
   Memory [[bangke-excel-like-dirty-undo]].
2. **Commit + (ask before) push this session's work.** All 3 changes (parity fix + 2 save-UX changes)
   are coherent but distinct — consider 2–3 commits: `fix(co-stock): recalc allocates from folded
   snapshot`, `feat(co-case): in-place save`, `feat(co-case): debounced auto-save`. Push auto-deploys.
3. **D1 leftover — confirm `transaction_key` stability with Data Hub** (biggest latent risk). Sign-off
   still BLANK (`.ai/api-requests/2026-05-28-bcct-incremental-since-filter.md`).
4. **D1 — fix C (claim-blocked tombstone never retried).** Fork: C1 persist+retry vs C2 full-reconcile
   backstop. + **E/F** (sync-status axis, refresh-mode UX) + delta-vs-full parity harness (needs T1).
5. **BACKLOG T1 — test DB isolation** (`/discover` brief exists). Tests with `.env` write shared dev DB.
6. **Index 4.27s johnson-vn** — N+1 `claims_summary_for_case` (`co_case_context.py:2760-2767`).
7. DH reciprocal cleanup (demo `/version` 0.0.0; prod missing `COPY CHANGELOG.md`) — needs user OK.
8. Feedback backlog: #14 (BOM default per code), #13 (batch chốt BOM), #4 (DH substitute ranking).

## Blockers
- Excel-like undo work is blocked on the save-model decision (#1).

## Notes for Next AI Session
- **NOTHING from this session is committed.** `git status`: M `app/routers/co_case.py`,
  M `app/templates/co_case.html`, M `tests/test_co_demo.py`; new tests + `.ai/scripts/*` + screenshots.
- **Verification (this session):**
  - Real-Johnson read-only before/after (edited `MFW0506-39`): PRE-FIX raw path = **37 over-claim lots**,
    POST-FIX folded path = **0** → Chốt clean. Same mechanism as the reported 47-lot case.
  - Playwright on live server + real Johnson: Chốt succeeds (HTTP 200, "Đã chốt", no "vượt tồn");
    in-place save (no reload, status calculated); auto-save (no reload, banner clears, 0 JS errors);
    persistent toolbar (visible+clean on load → dirty on edit → still visible+"Đã lưu" after save).
    Scripts: `.ai/scripts/pw_johnson_lock_repro.py`, `pw_save_inplace.py`, `pw_autosave.py`,
    `pw_toolbar.py` (each does full backup→test→restore of the dev case + ledger). Screenshots in
    `.ai/screenshots/2026-06-08-co-stock-recalc-folded-parity/` (1-before … 5-toolbar-persists).
  - Full file-mode suite: **560 passed / 11 skipped** (DB-gated parity tests skip without `.env`).
- **Local data reality (important):** the reported case `co-case-a4e1dbbdb0f5` is **prod-only** (not in
  local store). But johnson IS fully local — snapshot **60,173 rows** + ledger + **3 loadable cases**
  (`co-case-1643bb515a6a`, `co-case-ec000d03522e`, `co-case-4e9f5a3b1e9c`) + **25,727 usable+folded
  "trap" lots**. Reproductions used `co-case-ec000d03522e / MFW0506-39`. My raw `psql` earlier hit a
  wrong search_path (showed johnson=0); the app's `app.database.connect()` /
  `co_stock_materializer.row_count()` are authoritative.
- **⚠ Dev-data drift on `co-case-ec000d03522e`:** repeated Playwright tests (backup→restore against the
  SHARED mutable dev case) drifted its state — `MFW0506-39` got locked by a test then un-locked back to
  `calculated` (current: 7 locked + 1 calculated, overrides=0), and case claims drifted **545 → 524**
  (~21 lost across lock/reopen/failed-restore cycles). Case is SANE + usable; exact pristine state lost.
  NOT a code/tồn issue — test-data noise; this is why **T1 (test DB isolation)** exists. Lesson: don't
  loop browser tests over shared dev data; restore via `save_case_record` (NOT `save_state`, which only
  writes the top-level blob, not per-case `co_cases` rows) and WAIT for in-flight saves before restoring.
- **Save-path architecture (for the undo work):** origin tab is server-rendered; /calculate, /lock,
  /load-bom, /reopen all swap in-place via `replaceCaseShellFromResponse` (parses returned HTML, replaces
  `[data-co-case-shell]`, `refreshCaseShellInteractions()` re-binds). A shell swap REPLACES the panel →
  client undo history (`__sheetHistory`) is lost. That's the core tension with "undo thoải mái".
- **Local dev:** `npm run co:serve` → `127.0.0.1:8001` (auth OFF, `--reload` watch app/**). Server was
  running all session and has ALL uncommitted changes loaded. DH dev on `:8754`.
- **Tests:** file-mode `PYTHONPATH=. uv run python -m pytest` (NO .env). DB parity test
  `tests/test_recalc_lock_parity_db.py` needs `.env` (seeds a folded lot, asserts raw-claim rejected /
  folded-claim accepted against the real ledger). Memory [[test-env-filemode-vs-datahub]].
- **Branch/deploy unchanged:** `main` HEAD `4f567ff`; `4f567ff` (docs) committed but NOT pushed.
  `origin` + `tinsu` both = TinsuAI/co; push auto-deploys ~1-2min.
- **Memory updated:** [[co-stock-recalc-folded-parity]] (the fix), [[bangke-excel-like-dirty-undo]] (pending feature).
- **Inherited D1 mental-model notes** (still relevant): App CO OWNS tồn CO (claims+adjustments are
  unrecoverable crown jewels); lot identity = `direction‖declaration‖line‖item_code` (customs ITEM code,
  not hs_code); over-claim DB guard is SKIPPED when no snapshot → tồn correctness needs a fresh snapshot.
  See `docs/co-stock-architecture.md`.
