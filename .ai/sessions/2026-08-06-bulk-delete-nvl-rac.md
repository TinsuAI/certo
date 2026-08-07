# 2026-08-06 — Bulk-delete "NVL rác" (aggregate + per-sheet, 2 kinds by customs_relevance)

Prod `barry-co` = nightly = `origin/main` = **`27980bb`** (merge of PR #23 `review/clean-fixes`; feature commit **`d6bdebb`**). CI/CD green (Docker build + Python tests + Deploy demo all success, run `31116327808`). Full suite **1030 pass / 17 skip**.

PR #23 was the review-batch integration (my feature + ~15 already-reviewed agent branches: LK1/DC3b force re-Tính, cold-start overclaim block, calculate lot-scoping, duplicate-BOM-propose guards, secure cookies, N+1 claim batching, CO-stock refresh reason, test/harness hardening). This summary covers the new feature only.

## Context (client request, evolved over the session)
"Sheet Tổng hợp NVL sau khi chạy tồn CO xong: thêm nút chọn hết NVL rác → xoá hàng loạt (giống per-sheet), có toggle bật/tắt theo doanh nghiệp. Mặc định 'thay hết', hiện tại 'thay phần thiếu'." Then, testing on Johnson: "tách 2 nhóm riêng, modal cuộn được, sửa lại 'chọn dòng lỗi' cho đúng bản chất" and "sửa lại logic cho đúng."

## What Was Done
Per-company opt-in feature `features.bulk_delete_junk_rows` (default **off**) to bulk-delete folded rác NVL, split into two kinds by `customs_relevance`, on **both** the "Tổng hợp NVL" aggregate sheet and each per-sheet grid.

### The reframe (this is the crux — "sửa logic cho đúng")
The first build mirrored the per-sheet "⊘ Lọc dòng lỗi" = `allocation_count == 0`. Testing on real Johnson data (clone of `co-case-e0b390ead3b0` with deletions reverted) proved that signal **wrong**: a cross-tab over 267 rows showed `customs_relevance` deterministically encodes BCCT-lot presence —
- `declarable` ⟺ **has ≥1 BCCT lot** (180 rows). Short = genuine **thiếu tồn** → substitute, NOT delete.
- `declarable_unmatched` ⟺ **candidate == 0**, real NVL = "**không có trong BCCT**" (chưa khớp tờ khai) (63 rows).
- `excluded_non_material` ⟺ candidate == 0, **phi vật tư** (24 rows).

All 29 Johnson "no-stock" (allocation_count==0) rows were `declarable` in-BCCT (lots exhausted/date-excluded) = thiếu tồn, i.e. the old logic would have deleted genuine shortfalls. There is NO "declarable + candidate==0" row, so the intermediate `not_in_bcct` group was empty by construction and dropped.

### Final shape (commit `d6bdebb`)
- **Rollup** (`case_shortfall_rollup`, co_case_context.py): returns `folded_rac` (grouped by material_code + kind, non-locked, each `{material_code, name, kind, products, count}`); pure-rác materials (all-noise occurrences) kept OUT of the thiếu-tồn/substitute list. Dropped the transient `bcct_candidate_count`/`not_in_bcct` fields.
- **Route**: `POST .../origin/bulk-delete-rac` — payload `{kind, material_codes, product_code?, expected_revision?}`. `kind` ∈ {declarable_unmatched, excluded_non_material}; filters rows by `customs_relevance` server-side (never trusts client); optional `product_code` scopes to one sheet (per-sheet uses this, aggregate omits = all non-locked sheets). Soft-delete override, recalc, persist, return fresh rollup; locked sheets skipped + reported.
- **Aggregate UI** (`renderRunStockSummary`): two buttons `⊘ NVL không có trong BCCT (N)` + `⊘ NVL phi vật tư (M)` from `rollup.folded_rac`, each → shared scrollable confirm modal.
- **Per-sheet UI**: replaced the mis-targeted `⊘ Lọc dòng lỗi` with the same two buttons (`data-sheet-rac-kind`, counts filled by `initSheetRacButtons` from `data-origin-fold-kind` rows), same modal, route scoped by `product_code`. Manual row-checkbox delete (`wireSheetBulkDelete`) kept unchanged.
- **Modal** (`openRacDeleteModal`): reusable, scrollable checkbox list (pre-checked, Chọn hết/Bỏ chọn), "Xoá khỏi bảng kê (N)". Each row: code + kind tag + which sheets.
- **Config plumbing**: `features` section in `default_config`/`migrate_config` (client_config_store.py); DH-mode `save_client_config` `to_save` whitelist extended (else the toggle is silently dropped in prod DH source-mode); checkbox parse in `pages.py`; checkbox in `client_config.html`; flag threaded into co_case context (`bulk_delete_junk_enabled`, guarded `hasattr` for test doubles).
- **Aggregate substitute scope default flipped** `only_short` → `everywhere` ("thay hết"), aggregate UI only; server fallback stays `only_short`.

## Decisions Made
- **Rác = `customs_relevance` folded kinds, not allocation_count==0.** Two groups, disjoint: `declarable_unmatched` ("không có trong BCCT") + `excluded_non_material` ("phi vật tư"). Thiếu tồn (declarable, có lô) stays substitute-only. (User picked "tách 2 nhóm"; Nhóm-1 name "NVL không có trong BCCT" chosen from options.)
- **Per-sheet made consistent with aggregate** (user: "làm consistent voi sheet tong hop di") — same 2 buttons + modal; per-sheet deletes via the same route scoped to its `product_code`.
- **Toggle default OFF** (opt-in per company) — accepted that this hides the always-on per-sheet bulk-delete until a company enables it.
- **`declarable_unmatched` included in the delete bucket** per user grouping, even though it's a real NVL pending đối soát (recoverable via Ctrl+Z; modal tags each row's kind). Flagged as a possible future split (see Open Items).
- **Commit only the feature files**; never the pre-existing `.ai/BACKLOG.md`/`uv.lock` working-tree changes or the untracked `app/static/docs/`, `.ai/features/…`, `_gate_tmp.cjs`. No AI co-author trailer (repo rule).
- **Merge the whole review batch to main + deploy** (user: push → open PR → merge → watch) after CI green.

## What Didn't Work / dead ends
- **First implementation (no-stock / allocation_count==0) was wrong** — deleted genuine thiếu-tồn. Reworked to customs_relevance after the Johnson cross-tab. The transient `bcct_candidate_count` stamp + `not_in_bcct` rollup group were added then removed (empty by construction).
- **Modal item CSS fought the `display:grid` `.confirm-modal`.** Codes rendered but were invisible: a flex row with `margin-left:auto` made the list size to min-content and shove content off-screen (proved via live DOM dump: `.rac-item-code` was `visible`, dark, width 96px, but at `x=697` past the item edge). Tried single-line flex + `min-width:0` (still blanked), 2-line flex body (blanked). **Fix that worked:** each modal row = its own CSS grid `auto 1fr auto` (checkbox spans 2 rows, code+tag on line 1, sheets on line 2). Folded into `d6bdebb` via `--amend` before push.
- The aggregate delete initially no-op'd because the delete URL was only on the aggregate run button; the `btn` passed through render is the **review-toolbar** run button — added `data-bulk-delete-url` to both.

## Open Items
- **`declarable_unmatched` grouping (low, product call):** currently in the delete bucket as "không có trong BCCT". If the client wants "chờ đối soát" separated from true rác/phi-vật-tư with a stronger warning (not one-click delete), split Nhóm 1 further. Not requested yet; noted at hand-off.
- **Long confirm lists:** modal is scrollable (handles Johnson's 48). Fine as-is.
- **Repo hygiene (pre-existing, not this session):** `app/static/docs/`, `.ai/features/2026-07-28-…`, `_gate_tmp.cjs`, `.claude/worktrees/` are untracked; `.ai/BACKLOG.md` + `uv.lock` carry unrelated working-tree edits. Left untouched.

## Verify / how it was proven
- **Tests:** full suite **1030 pass / 17 skip**. New: `test_shortfall_rollup.py` folded_rac split-by-kind (locked excluded, pure-rác out of substitute list); `test_bulk_delete_rac_route.py` (6 — kind isolation, `product_code` scope, locked-skip, bad-kind 400, empty 400); `test_bulk_delete_junk_flag.py` (4 — default off, migrate backfill, file + DH round-trip); `test_config_route_co_owned.py` checkbox parse.
- **Browser e2e** (puppeteer, `.ai/scripts/e2e_bulk_delete_junk.cjs` + `e2e_johnson_rac_seed.py`, screenshots `.ai/screenshots/2026-08-06-bulk-delete-rac/`): on the Johnson clone (48 `declarable_unmatched` + 23 `excluded_non_material` codes) — ON: 2 group buttons + 8 per-sheet buttons; modal lists 48 pre-checked; delete removed 63 rows, folded_rac 71→23, "không có trong BCCT" group cleared, "phi vật tư" remained (kind isolation); no console errors. OFF: no rác buttons anywhere though the case still has 71 rác (UI gated, not data). JS `node --check` clean.
- **Deploy:** merged PR #23 → CD run `31116327808` all jobs success (build, tests, Deploy demo). Flags reset OFF and the Johnson e2e clone removed after testing.

## Files
Server: `app/client_config_store.py`, `app/data_hub_client.py`, `app/routers/pages.py`, `app/web/co_case_context.py`, `app/routers/co_case.py`. UI: `app/templates/client_config.html`, `app/templates/co_case.html`, `app/static/css/app.css`. Tests: 2 new + 2 edited. Harness: `.ai/scripts/e2e_bulk_delete_junk.cjs`, `.ai/scripts/e2e_johnson_rac_seed.py`. Memory: `customs-relevance-encodes-bcct-match`, `client-config-dh-mode-to-save-whitelist`.
