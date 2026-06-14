# Session 2026-06-09 — CO bảng kê declarability (DH customs_relevance) + collapse rows

## What Was Done

Three commits on `main` + one uncommitted feature, all on the origin bảng kê.

1. **Fix: bulk row-select dead after shell swap** (`a9770bc`). `wireSheetBulkDelete` (select-all,
   "Chọn dòng không có tồn/BCCT", clear, delete) was wired once at load — not in
   `refreshCaseShellInteractions`, not delegated — so it died after any in-place shell swap
   (Lưu/Tính/Chốt now replace the panel DOM instead of full reload). Made idempotent +
   re-run via `initSheetBulkDelete` in `refreshCaseShellInteractions`. Verified with a headless DOM
   harness (regression repro + fix).

2. **Backlog M1** (`b951182`): Propose BOM approved on DH still shows "pending" in CO; "Đã propose"
   button re-proposes. Captured with code pointers.

3. **Declarability via DH `customs_relevance`** (`46ab586`). Started from a user report that the HQ
   export carried non-declarable rows (cột M = `technical_flattened`). Investigation arc:
   - First cut: a CO heuristic (`technical_flattened` + no HS + no allocation). Wrong assumption
     (thought rows had no name); real rows DO carry technical-BOM names → matched 0 on real data.
   - User pointed to the DH spec (`data-hub/.ai/sister-app-notes/2026-06-09-co-consumer-spec-declarability.md`).
     Adopted DH's authoritative per-material `customs_relevance` (mig 078): `excluded_non_material`
     (rác) | `declarable` | `declarable_unmatched` | `review` | `null`.
   - Implemented the rich path: read `customs_relevance` across all 3 export paths (`workbook_io`,
     `bang_ke_renderer`, `bang_ke_xml_generator`); carry `customs_relevance`/`item_category`/
     `material_group` through both origin material builders; split the warning summary + web badges
     (rác "phi vật tư" vs review "⚠ cần đối soát"). New `app/origin_material_filters.py` +
     `tests/test_technical_noise_filter.py`.
   - **Overfit check (user asked "có sợ overfit cho Johnson không"):** YES — the legacy heuristic would
     have dropped **94% (4016/4286) of growatt** (growatt = 100% `null`, unmapped). **Chose option B:
     removed the heuristic entirely.** Now anything DH leaves null/review is KEPT; only DH-classified
     rác/unmatched is excluded. Added a cross-client overfit guard test.
   - Sent a DH request listing Johnson's 25 unclassified rác codes:
     `.ai/api-requests/2026-06-09-johnson-bom-material-group-gap.md` (split: ~12 rác → `excluded_non_material`,
     ~11 real physical → need `material_group`, 2 ambiguous). Copied to `data-hub/.ai/sister-app-notes/`.

4. **Collapse removed/non-material rows ("gộp dòng đã xoá / phi vật tư")** — UNCOMMITTED
   (`app/templates/co_case.html` + `app/static/css/app.css`). User picked "gộp thành 1 dòng bung được"
   earlier. Folds persisted-deleted rows + DH `excluded_non_material` into one "▸ Hiện N dòng đã loại"
   toggle; keeps `declarable_unmatched` visible (review queue, per spec). Visible rows renumber
   contiguous (JS), folded show "–". `initOriginFoldRows` (idempotent, in `refreshCaseShellInteractions`);
   `boxes()` skips hidden folded rows. Verified: headless DOM test 12/12 + live growatt demo.

## Decisions Made

- **Option B (drop the heuristic) over keeping a fallback.** CO classifies NOTHING itself; it trusts DH's
  per-client `customs_relevance` and keeps null/review (spec: "never silently drop"). Trade-off accepted:
  Johnson rác that DH currently leaves `null` (25/26 of one product) **reappears** in the export until DH
  maps it — but that's the correct ownership boundary (fix in DH's `client_material_group_map`, not a CO
  heuristic). The win: zero overfit (growatt loses nothing).
- **Rich path, not the DH server-side filter** (`exclude_non_declarable` stays default-false) so CO can show
  *why* a row dropped and surface `declarable_unmatched` for review.
- **Fold scope:** collapse deleted + `excluded_non_material`; do NOT fold `declarable_unmatched` (must stay
  visible for reconciliation, per spec).

## What Didn't Work

- **The first declarability heuristic** (no-name assumption) — matched 0 real rows; the rác rows carry
  technical-BOM names. Corrected to `customs_relevance`.
- **Injecting state to force foldable rows for a screenshot** — direct `save_state`/state-store writes do NOT
  reach the render (caching + render rebuild + the per-row `co_cases` store). Had to use the real `/save`
  flow on an unlocked sheet.
- **`/calculate` to "restore" deleted rows** — it does NOT rebuild the full BOM set; it reduced growatt
  SD00.0010600 further (124→122). Restored from the `cases.json` seed instead.
- **Restoring a mutated test case via `save_state` alone** — leaves the per-row `co_cases` table stale (the
  change persists). Must also `_persist_case_row` (or re-seed).

## Open Items

- **Commit the fold feature** (uncommitted). Then ask before push (auto-deploys).
- **DH must finish Material Group re-ingest for `bom_observed` codes** (BACKLOG DC1) — root cause of Johnson
  rác being `null`. Per DH brief `data-hub/.ai/features/2026-06-08-leaf-nvl-declarability/brief.md`, the SAP
  adapter (`sap_indented_walk.py`) dropped Material Group/Phantom/Bulk at ingest; mig 078 re-ingest is
  incomplete for the only-in-technical-BOM set. CO needs no change (already reads the field).
- **BACKLOG DC2** — confirm where CO sources the technical-BOM `material_description` (DH brief flags
  `bom_artifact_rows.payload={}` for these codes).
- **Save-model decision** still open (inherited) — gates Excel-like undo.
- **Untracked:** the DH note copy in `data-hub/.ai/sister-app-notes/` (user said copy, not commit).
- **Dev data:** growatt `co-case-e44fe2065b62 / SD00.0010600` restored from seed (128 mat). Johnson
  `co-case-ec000d03522e` verified clean. Screenshots in `.ai/screenshots/2026-06-09-declarability/` (gitignored).
