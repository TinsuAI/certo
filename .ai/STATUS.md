# Project Status

## Current State
- **On `main`, deployed to PROD.** `main` = `origin/main` = **`7874e21`**; prod `barry-co.tinsu.ai/version`
  = `0.14.0` / git_sha `7874e21` / source `build`. CI/CD run `27500543989` success (prod+demo+nightly).
  Tree clean, in sync with origin.
- **SHIPPED this session — workbook → standalone CO-stock snapshot import + converter tool page.**
  Onboarding clients (running the Excel trừ-lùi in parallel) upload `.xlsm` → convert to the standard
  template (remaining baked = workbook "Tồn" col) → **standalone import sets `co_stock_rows` directly**
  (materializer `fold=False`, full replace, allocation per `client_config`) — no fold, no BCCT overlay,
  no key-match. Tool lives on its **own page** `/clients/{id}/co-stock/workbook-tool` (off the Tồn CO
  table). [[co-stock-workbook-converter]].
- **Trục B FIXED on DEV + PROD** — `growatt-vn` allocation_code config `same_as_customs_code →
  description_regex` + re-materialize 38287 rows (allocation category→dotted, qty intact). BOM↔stock
  match **4% → 99%**; origin sheet "NVL không tồn" **101 → 0** (dev e2e). [[growatt-allocation-strategy-bom-match]].
- **Dev server** running locally on `:8001` (`npm run co:serve`, background task `b0bzczccq`).
- **Mid-flight: UNCOMMITTED local changes** — legacy CO-stock fold removal (CS2 decouple) + CS1 lot-history
  modal redesign + **mig 017** (drops `co_stock_adjustments`, applied on dev). Tests green; not committed/pushed.

## Recent Changes (this session, latest first)
- **UNCOMMITTED 2026-06-15 — legacy CO-stock FOLD removed (CS2 decouple) + CS1 lot-history modal redesign.**
  Fold path gone: deleted `app/co_stock_adjustments_store.py`, `scripts/fix_trului_unit.py`,
  `tests/test_co_stock_fold.py`; removed `fold_baseline`/`refold_*`/fold calls (materializer, co_case_context,
  co_stock.py export); removed `/co-stock/import` overlay route (co_stock.html form → `/import-snapshot`);
  **mig 017** drops `co_stock_adjustments`. CS1: `fold_lot_events` collapses system events + `readded` flag +
  template/CSS + screenshots. Full file-mode suite **591 pass**; legacy route → 404; table dropped on dev.
  [[co-stock-folded-remaining-model]] [[cs3-costock-harmonize-model]].
- **`7874e21`** feat(co-stock): workbook→standalone snapshot import + converter tool page.
  New `app/co_stock_workbook.py` (parse → `convert_to_standard_template` → `stock_rows_from_standard`
  → `import_standard_snapshot`), `+remaining_qty` template col, materializer `fold` param +
  `is_workbook_sourced` (DH-refresh guard), routes `/co-stock/convert-workbook` + `/import-snapshot` +
  `/workbook-tool`, new template `co_stock_workbook_tool.html`, `scripts/convert_co_stock.py` thinned,
  `tests/test_co_stock_workbook.py`. Backlog **CS3** + 2 discovery briefs.
- **PROD data op (not a commit):** Trục B on prod via `ssh tinsu` → `co-app-1` (config + re-materialize
  + restart). Config backup `/var/lib/barry-co/.../growatt-vn/config.json.bak-trucb-20260614`.
- **DEV data op:** Trục B on dev (`barry-CO-bom-data/.../growatt-vn/config.json.bak-2026-06-14`).

## Next Steps (priority order)
1. **growatt-vn PROD re-calc — DEFERRED (prod = test data only).** Sheets calculated BEFORE Trục B store
   the old category allocation, but no manual "Tính lại" needed: prod runs test data, so re-derive cleanly
   at the next REAL data ingest (config already correct). Not urgent. [[prod-test-data-recalc-deferred]].
2. **CS3 — LEGACY FOLD REMOVED 2026-06-15** (brief `…cs3-costock-three-sources/brief.md`): single model now —
   `tồn = opening (DH BCCT feed) − baseline_used (workbook chốt, off-app) − CO claims`, computed read-time by
   `apply_used_qty`; `co_stock_adjustments` dropped (mig 017). **PARKED** (chưa cần): re-import reconcile rule +
   relax `is_workbook_sourced` so DH adds new-lot opening on a workbook-chốt client. CS1 modal redesign DONE (local).
3. **(was: 2 P0 fold bugs) — MOOT 2026-06-15.** Fold removed entirely → aggregate double-count + sticky
   `bcct_qty` no longer exist; no DH-overlay path remains.
4. **Minor /rev findings** (folded into CS3): `stock_rows_from_standard` source_row keys (decl,line) vs
   `parse_workbook` consolidates by triplet; workbook client can't DH-refresh (by design); converter route
   broad `except`.
5. Older backlog: XX1 (NVL có xuất xứ), LK1 (Chốt lock-able), CS1 (lot history modal), B6/B7 UX, D1, M1.

## Notes for Next AI Session
- **⚠ FOLDER GOTCHA (I broke + fixed this session):** `../barry-CO` is the **git WORKTREE PARENT** of
  this repo (`.git` points there). Do NOT move/archive it — git breaks. `data/` → symlink to
  `../barry-CO-bom-data` (LIVE app data, incl. agency trừ-lùi workbooks). `../barry-CO-data` = 3.5G no-git
  agency source. See AGENTS.md "Related sibling folders" + `../_archive/README.md`. Real trừ-lùi files:
  Growatt `barry-CO-data/extracted/Growatt-20260421/Growatt/tru lui CO final…xlsm`; Johnson
  `barry-CO-bom-data/local/hq-templates/tru-lui-co-template.xlsm`.
- **Trục B is config+DATA, NOT in git** (lives in barry-CO-bom-data on dev, /var/lib/barry-co on prod).
  Backups noted above. Reversible (restore .bak + re-run with old config). The CODE deploy (7874e21) ≠
  the Trục B data fix — both done now.
- **CO-stock key model (the "loạn" resolved):** lot identity = `(declaration_no, line_no)` (verified
  unique); `customs_item_code` = BCCT item_code = the goods-name `"<code>#&…"` PREFIX (Johnson unified;
  Growatt category like "DIOT"); `allocation_code` (BOM key) resolved per client_config — that's the ONE
  place per-company code logic belongs. Converter keys `customs_code` on the prefix (NOT Mã NPL/SP).
- **Standalone vs overlay import:** new `/co-stock/import-snapshot` (standalone, workbook=truth, fold=False)
  vs legacy `/co-stock/import` (adjustment overlay on BCCT + fold). Don't conflate.
- **Prod access:** `ssh tinsu` → `co-app-1` (prod app, port 8755), `co-db-1` (prod PG). Run prod scripts:
  `ssh tinsu 'docker exec -i co-app-1 python -' < script.py`. [[demo-server-ssh]].
- **Test split:** file-mode (NO `.env`) `PYTHONPATH=. uv run python -m pytest` = 596 pass; DB tests need
  `.env` ([[test-env-filemode-vs-datahub]]); test_co_demo FAILS with .env (spurious — run file-mode).
- **DEV-FLOW mandate:** every feature/fix → Playwright e2e + screenshot + **EVALUATE images**. New e2e:
  `.ai/scripts/e2e_costock_workbook_snapshot.cjs` (12/12), `e2e_growatt_origin_stock.cjs`, fixture gen
  `gen_costock_wb_fixture.py`. Recipe: `PWDIR=$(dirname "$(ls -d ~/.npm/_npx/*/node_modules/playwright|head -1)"); NODE_PATH="$PWDIR" node <script>`.
- **Deploy:** push `origin main` (= TinsuAI/co) → runner auto-deploys ~2min (prod+demo+nightly). Version
  baked from pyproject (didn't bump — this was a feature push, not a release).
