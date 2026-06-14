# Project Status

## Current State
- **Bảng kê declarability via DH `customs_relevance` — DONE + committed (`46ab586`).**
  CO reads DH (mig 078) per-material `customs_relevance` to exclude non-declarable rows from every
  C/O export (`workbook_io`, `bang_ke_renderer`, `bang_ke_xml_generator`): `excluded_non_material`
  (rác) + `declarable_unmatched` (real material, no import match → kept out of export but shown as a
  "cần đối soát" review queue). **NO client-specific heuristic** (option B) — anything DH leaves
  `null`/`review` is KEPT, so an unmapped client (growatt = 100% null) loses nothing. The earlier
  `technical_flattened` heuristic over-fit Johnson (would have dropped 94% of growatt). `customs_relevance`/
  `item_category`/`material_group` now flow through the origin material build; warning summary + web
  badges split rác vs review. New `app/origin_material_filters.py` + `tests/test_technical_noise_filter.py`.
- **Bulk row-select shell-swap fix — DONE + committed (`a9770bc`).** `wireSheetBulkDelete` was wired
  once at load (not in `refreshCaseShellInteractions`, not delegated) → select-all / "Chọn dòng không có
  tồn/BCCT" / clear / delete went dead after any in-place shell swap. Now idempotent + re-run on refresh.
- **Collapse removed/non-material rows ("gộp dòng đã xoá / phi vật tư") — DONE but UNCOMMITTED.**
  `app/templates/co_case.html` + `app/static/css/app.css` (working tree). Folds persisted-deleted rows
  + DH `excluded_non_material` (rác) into one "▸ Hiện N dòng đã loại" toggle; keeps `declarable_unmatched`
  visible (review). Visible rows renumber contiguous; folded show "–". `initOriginFoldRows` in
  `refreshCaseShellInteractions` (idempotent). Verified: headless DOM test 12/12 + live growatt demo
  (deleted 4 rows via real `/save` → folds correctly). Screenshots `.ai/screenshots/2026-06-09-declarability/`.
- **KEY FINDING — why Johnson rác doesn't auto-fold yet (DH gap, NOT a CO bug):** Johnson's rác
  (drawings/checklists/labels) are `bom_observed` codes with `customs_relevance=null`; option B (correctly)
  keeps them, so nothing folds/excludes automatically until DH classifies them. Root cause is DH-side
  (SAP Material Group dropped at BOM ingest; mig 078 re-ingest incomplete for `bom_observed`). See
  BACKLOG **DC1**; DH request sent (`.ai/api-requests/2026-06-09-johnson-bom-material-group-gap.md`).
- **Inherited, still PENDING (prior session):** the **bảng kê save-model decision** (Excel-like undo) —
  remaining Ctrl+Z/Y + undo-that-survives-a-save is gated on it. Memory [[bangke-excel-like-dirty-undo]].
  Plus D1 CO-stock refresh leftovers (transaction_key sign-off, fix C).

## Recent Changes (latest first)
- **(uncommitted)** Collapse removed/non-material rows (`app/templates/co_case.html`, `app/static/css/app.css`).
- **`b951182`** docs(backlog): M1 — Propose BOM status not syncing / re-propose.
- **`46ab586`** feat(co-origin): bảng kê declarability via DH `customs_relevance` (+ new filter module + tests + DH note).
- **`a9770bc`** fix(co-origin): re-bind bulk row-select after in-place shell swap.
- **`f4b32fd`** (prior session) docs(ai): handoff — bảng kê recalc parity + save UX. Already committed.

## Next Steps (priority order)
1. **Commit the fold feature** — `feat(co-origin): collapse removed/non-material rows` (`co_case.html` +
   `app.css`). Then (ask before) push — push auto-deploys TinsuAI/co main ~1–2min.
2. **DH-side: finish Material Group re-ingest for `bom_observed`** (BACKLOG DC1) — unblocks Johnson rác
   auto-fold/exclude. CO needs NO change once DH lands it (already reads the field); re-calculate the
   Johnson sheet afterward to bake `customs_relevance` into saved materials.
3. **DECIDE the bảng kê save-model** (still open from prior session) — blocks Excel-like undo work.
   Options: (a) manual Ctrl+S + strong undo, drop 2s auto-save [rec]; (b) auto-save on leave/idle; (c) keep 2s.
4. **BACKLOG DC2** — confirm where CO sources the technical-BOM `material_description` (DH brief flags
   `bom_artifact_rows.payload={}`). Read-only, low urgency.
4b. **BACKLOG DC3 — rác/đã-xoá behavior across Chốt/BOM/Xuất/Tính (decide + patch).** Verified 2026-06-09:
   update-BOM (`build_bom_proposal_rows:2224`) strips only `deleted`, KEEPS rác (BOM = structure — decide
   if it should strip rác too). Export + calc exclude/neutralize rác BUT only when materials carry
   `customs_relevance` — a pre-`customs_relevance` calculated sheet leaks rác into export/BOM until
   re-calculated (risk: issue a C/O with rác on old sheets). `declarable_unmatched` sums 0 → inflates LVC;
   only a visible warning exists, no hard Chốt/Xuất block (spec Edit 5). See BACKLOG DC3.
5. D1 leftovers: transaction_key stability sign-off; fix C (claim-blocked tombstone retry); parity harness.
6. BACKLOG T1 (test DB isolation), Index 4.27s N+1 (`co_case_context.py:2760-2767`), feedback backlog.

## Blockers
- Johnson rác auto-fold/exclude is blocked on DH (DC1 — Material Group re-ingest). CO side is complete.
- Excel-like undo is blocked on the save-model decision (#3).

## Notes for Next AI Session
- **Uncommitted = ONLY the fold feature** (`app/templates/co_case.html`, `app/static/css/app.css`). Everything
  else this session is committed (`a9770bc`, `46ab586`, `b951182`). Screenshots are gitignored (local only).
- **⚠ Dev-data mutation is a real trap (re-learned the hard way this session):** state lives in TWO stores —
  bulk `co_case_store.save_state` AND the per-row `co_cases` table via `_persist_case_row`. Restoring a test
  case via `save_state` ALONE does NOT revert (the per-row table keeps the change). Also: a SAVED delete on a
  calculated sheet **permanently reduces `product.materials`** (not just override-hides), and `/calculate` does
  NOT rebuild the full set. I deleted rows on growatt `co-case-e44fe2065b62 / SD00.0010600` during the fold
  demo, which dropped 128→124→122; **restored from the `cases.json` seed** (128 mat, 1 override, calculated) via
  `save_state` + `_persist_case_row`. Johnson `co-case-ec000d03522e` verified clean (overrides=0, locked).
  **Lesson: don't loop browser/`/save` tests over shared dev data; if you must, restore through BOTH stores
  (or re-seed from `cases.json`), not `save_state` alone.** (Same trap noted in prior session.)
- **Declarability data reality:** DH `customs_relevance` lives on the MATERIAL (`/v1/hub/materials`). Johnson's
  only-in-technical-BOM rác codes are NOT registered materials (bare stub, name=code) → field is `null`. The
  classification DH *can* derive (RD07/RD08/RD12) lives at BOM-row level, but the spec told CO to read
  material-level — so these rác slip through as `null`. The render of a **calculated** sheet uses SAVED
  materials (pre-`customs_relevance`), so a re-calculate is needed to refresh the field.
- **Local dev:** `npm run co:serve` → `127.0.0.1:8001` (auth OFF, `--reload`). **Start it via a harness
  background task (no trailing `&` inside the tool call) or it gets reaped.** DH dev on `:8754` (flaky — died
  a couple times this session; restart in `client/data-hub` if `customs_relevance` queries connection-refuse).
- **Verify the fold visually:** Johnson sheets are all locked + have no DH-classified rác, so nothing folds
  there. To see it: an UNLOCKED *calculated* sheet + delete rows via the real `/save` (busts cache; direct
  state injection does NOT reach the render). growatt `co-case-e44fe2065b62 / SD00.0010600` works.
- **Loose ends:** the johnson↔DH note copy is UNTRACKED in `data-hub` repo (user said copy, not commit).
- **Tests:** file-mode `PYTHONPATH=. uv run python -m pytest` (NO `.env`). The 25-code DH note + DC1/DC2 are
  the declarability follow-ups. Memory: [[technical-flattened-export-noise]], [[origin-wiring-must-survive-shell-swap]].
- **Branch/deploy:** `main` HEAD `b951182`; nothing pushed this session. `origin`+`tinsu` = TinsuAI/co; push auto-deploys.
