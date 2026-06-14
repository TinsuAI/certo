# Project Status

## Current State
- **On `main`, deployed to PROD.** `main` = `origin/main` = **`79edb05`**; prod `barry-co.tinsu.ai/version`
  confirms `0.14.0` / git_sha `79edb05` / source `build`. CI/CD run `27493638101` = success (Deploy on
  tinsu + demo + nightly). Tree clean. Branch `feat/rd3-bangke-split` is **fully merged** into main (can delete).
- **Released 0.14.0** — bundles the prior session's **RD3 "Bảng kê C/O" drill-in redesign** with this
  session's **BG1 data-loss fix + bảng kê edit-flow UX**. CHANGELOG + `pyproject`/`uv.lock` bumped;
  `/whats-new` (auth-gated in prod) renders it.
- **BG1 (xoá NVL mất dòng) FIXED** via soft-delete: deleted rows stay in `materials` (flagged), index
  stays stable, excluded from VNM/LVC. See [[bangke-soft-delete-index-model]].
- **Dev server** running locally on `:8001` (`.env` loaded → local `/version` shows 0.13.0 because `.env`
  sets `CO_VERSION`; prod bakes from `pyproject` 0.14.0 — not a bug).
- **Mid-flight: nothing.** All committed, merged, pushed, deployed.

## Recent Changes (this session, latest first)
- **`79edb05`** docs(backlog): XX1 (NVL có xuất xứ/phụ lục X → LVC/RVC) + LK1 (review logic "Chốt" lock-able).
- **`97dca73`** chore(release): 0.14.0 — CHANGELOG (Vietnamese, single-line bullets) + pyproject/uv.lock bump.
- **`cad2890`** docs(backlog): CS1 (tồn lot-history modal confusing) + CS2 (trừ-lùi review/convert/**DECOUPLE**).
- **`1e089e9`** feat(co-case): **P1-P3** — unify delete UX (single delete no confirm, bulk confirms),
  contextual "Tính bảng kê" (label "Tính lại" when stale, disabled when calculated), Load BOM overwrite warning.
- **`60e55a1`** fix(co-case): **P0** — soft-delete bảng kê NVL rows to stop data loss (BG1).

## Next Steps (priority order)
1. **CS2 — trừ-lùi DECOUPLE (user-chosen strategy).** Big: turn trừ-lùi into one-time data convert
   (`scripts/convert_co_stock.py` already exists) and **remove the embedded fold** (`fold_baseline` +
   re-fold across materializer/ledger/context/recalc/import). `/discover` + write parity tests first
   (risk: SAI TỒN). Enumerated dependency surface is in BACKLOG › CS2.
2. **XX1 — NVL có xuất xứ (phụ lục X).** Input origin for imported lots → `origin_status='origin'` →
   excluded from VNM → affects LVC/RVC. Check Data Hub for an origin field first (DH guardrail); else CO override.
3. **LK1 — review "Chốt" lock-able logic** (analogous to the contextual-Tính work): only allow lock when
   truly lock-able; consider blocking lock on unsaved edits / `declarable_unmatched` ([[DC3]]).
4. **CS1** — tồn lot-history modal redesign + investigate suspected duplicate system rows.
5. **B6** (native currency only-VND), **B7** (criteria datalist dark dropdown) — small UX.
6. Older: M1 (propose-BOM status sync), D1 (delta refresh audit — overlaps CS2), DC1/DC3, P1 index N+1, T1 test-DB isolation.

## Notes for Next AI Session
- **Old corrupted data won't auto-heal.** Cases that were deleted-from under the OLD buggy code have a
  shrunken `materials` (e.g. repro case `growatt-vn/co-case-e44fe2065b62` showed 116 active, not 122).
  Fix is fix-forward: re-**Load BOM** or re-**Tính** rebuilds full materials. No migration written.
- **⚠ DEV-FLOW (user mandate):** every feature/fix → Playwright e2e + screenshot + **EVALUATE the images**.
  New reusable e2e this session: `.ai/scripts/e2e_bangke_bg1_fix.cjs` (soft-delete fold, Load BOM confirm,
  contextual Tính, single-delete-no-confirm). Plus existing `e2e_bangke_split.cjs` (24/24).
  Run: `PWDIR=$(dirname "$(ls -d ~/.npm/_npx/*/node_modules/playwright|head -1)"); NODE_PATH="$PWDIR" node <script>`.
- **Test split:** file-mode (NO `.env`) `PYTHONPATH=. uv run python -m pytest` = 576 pass; **DB tests need
  `.env`** (`set -a; . ./.env; set +a`) — recalc/fold/parity 45 pass [[test-env-filemode-vs-datahub]].
- **Soft-delete invariants (don't regress):** never shrink `product.materials`; all calc must filter
  `deleted` (VNM/LVC, allocation, export, `build_bom_proposal_rows`). [[bangke-soft-delete-index-model]].
- **Bảng kê edit auto-recalcs** via `/save` → `recalculate_origin_sheet_edits` (allocate=True); that's why
  "Tính bảng kê" is contextual now. Any new origin control must survive shell-swap
  [[origin-wiring-must-survive-shell-swap]].
- **Deploy:** push `origin main` (= TinsuAI/co) → runner `tinsu-co` auto-deploys ~2min (prod+demo+nightly).
  Watch: `gh run watch <id> --exit-status`. Prod check: `curl -s https://barry-co.tinsu.ai/version`.
  Version is baked from `pyproject` at build; bump both CHANGELOG + pyproject for a release. **CHANGELOG
  parser (`app/changelog.py`) does NOT join wrapped bullets → write each bullet on ONE line.**
