# Project Status

## Current State
- **`main` = `origin/main` = prod = nightly = `dfa31d9`** (`barry-co.tinsu.ai/version` +
  `demo-co.tinsu.ai/version` both `dfa31d9`, v0.14.0). CI green. Tree clean.
- **Empty/no-BOM sheet can't be locked/exported — 2-layer fix** (the "Chốt + Chưa có BOM" anomaly: a
  sheet whose BOM resolved to 0 rows → `materials=[]`, `lvc_status="missing_bom"` could be locked
  (0 ledger claims) + exported (empty bảng kê)):
  1. **Root cause (`dfa31d9`):** `/calculate` no longer sets "calculated" unconditionally —
     `calculated_sheet_status()` keeps a `missing_bom` result at `"bom_loaded"` + surfaces an error.
  2. **Gate guard / defense-in-depth (`66d5ad7`):** `origin_sheet_action_error(...,"lock")` +
     `origin_sheet_export_blockers` block `lvc_status=="missing_bom"` (covers single+bulk lock + the
     `origin_can_lock` UI flag + any legacy "calculated"-but-empty persisted data).
  Shortage / missing-price sheets keep a BOM (lvc review/missing_value) → still lockable (Mục 6 intact).
- **Mục 6 (client-feedback batch workflow) is DONE + live + e2e-verified.** All 4 slices shipped:
  - **A (#14) BOM mặc định per-client** — pick a BOM → saved as the client default (pin version);
    later cases auto-reuse it. Store `bom_default_store` (Postgres `co_bom_product_default` + JSON
    fallback `config/bom-default/<client>.json`), write-through on pick (diff-guard: only a CHANGED
    pick writes, so editing an old case can't clobber a newer default), read-time precedence in
    `selected_bom_rows_by_product` (below per-case override, above aggregate composition default).
  - **B (#13a) Chạy tồn 1 lần** — "Chạy tồn (tất cả SP)" review-toolbar button → `preview-stock-all`
    runs stock for ALL products (preview, non-committing) → mã-thiếu summary panel.
  - **C (#13b) Thay định mức loạt** — each missing material opens the SAME rich sheet substitute
    modal (ranking/score + per-lot stock + đơn giá + đủ/thiếu) in stage-mode; "Áp thay thế (N)" →
    `bulk-substitute` (material_override at matched row) → override-aware re-preview.
  - **D (#13c) Chốt tất cả** — `bulk-lock` locks every sheet in order, commits ledger claims;
    skip-and-report not-calculated/overclaim; sequential (a skipped sheet blocks the rest).
- **DATA NOT PURGED.** prod `co-db-1` has 4 real cases (johnson-vn) + 24 Growatt cost-allocation
  ratios. **Do NOT seed/test against prod; use nightly OR the local dev DB.**
- **Cost-allocation system mature** (2026-05-27 + Mục 4a): admin `/clients/{id}/cost-allocation`,
  Excel import, Mode A→B, per-product + bulk "Áp hệ số". Engine: hệ số×FOB → 6 chi tiết.

## Recent Changes (this session — live on `dfa31d9`)
- `dfa31d9` fix: /calculate keeps an empty/no-BOM sheet at "bom_loaded" (root cause; +2 tests).
- `66d5ad7` fix: block lock/export of an empty/no-BOM sheet (audit finding; +7 tests).
- `ed8ebaa` docs(handoff) + `edc3b2d`/`1313ba0` test harnesses (in-container BOM default; substitute→export).
- `8f85e1f` feat: per-client default BOM pick (#14) — `bom_default_store`, migration 018, precedence.
- `c9f5183` feat: run stock once for all products + aggregate shortages (#13a).
- `8195ff9` feat: bulk substitute định mức with the rich sheet picker (#13b) — reuses the sheet's
  substitute modal in stage-mode; preview made override-aware.
- `bd09a87` feat: bulk-lock — Chốt tất cả (#13c).
- `198d70a` test: DB-mode e2e for bulk-lock ledger claims (`.ai/scripts/e2e_bulk_lock_ledger.py`).
- `edc3b2d` test: in-container e2e for the BOM default (`.ai/scripts/e2e_bom_default_incontainer.py`).
- `1313ba0` test: substitute→HQ-export correctness (`.ai/scripts/e2e_substitute_export.py`).
- Feature brief: `.ai/features/2026-06-18-bom-default-batch-flow.md`. Screenshots + scratch browser
  e2e (`e2e_muc6.cjs/.py`): `.ai/screenshots/2026-06-18-bom-default-batch-flow/` (gitignored).

## Next Steps (priority order)
1. **PLAY THE USER — full CO-flow walkthrough + UX/correctness review (do this FIRST next session).**
   Act as a normal agency staff member and go through the whole CO dossier flow end-to-end
   (shipment → documents → BOM/bảng kê → TKX/TKN → review & export), **especially exercising the
   features added these last sessions:** Mục 6 — BOM mặc định per-client (#14, pick → reuse), Chạy tồn
   1 lần (#13a), Thay định mức loạt + rich substitute modal (#13b), Chốt tất cả (#13c), and the
   empty/no-BOM lock-export guards. Judge **đúng/sai (correctness)** AND **trải nghiệm dùng (UX)** at
   each step, not just "does it run". Drive the REAL UI (browser e2e — local `:8001` is auth-off
   DB-mode, see [[co-local-dbmode-e2e]]); use a real-data client (`growatt-vn`) so substitutes/stock
   are populated; report friction, confusing labels, missing affordances, and any logic that looks
   wrong. Treat it like the "Chốt + Chưa có BOM" catch — assume something is subtly broken until proven.
2. **Remaining client feedback (2026-06-05 `HIỆN TRẠNG BARRY CO`):**
   - **#12** — số tồn **TỔNG** để kiểm soát (hiện chỉ theo lô/mã; add aggregate SUM). Medium.
   - **#4** — ranking mã thay thế "chưa OK" — **DH-side** (`data_hub_client.py`); needs a
     `.ai/api-requests/` artifact, not CO code.
3. **`compact` PDF profile UI toggle** — adapter supports `quality=compact`; no UI toggle; blocked on
   user confirming Ecosys legibility. Lossless `print` + 2 MB split already solves size.
4. **EX1** — column-K declaration ref configurable (số vs số/dòng).
5. **XX1** — NVL CÓ xuất xứ → fill bảng kê cột M-N (currently blanked; column L date auto-fills).
6. **(Tech-debt)** Config-page POST 409 in DH source-mode for source fields (overrides persist before
   the guard but response is 409).
7. **Correctness backlog:** B6 (currency native→VND), DC3, LK1, D1 — see BACKLOG.md.

## Notes for Next AI Session
- **Local dev is AUTH-OFF + DB-mode** (`.env`: `CO_AUTH_REQUIRED=0`, `BARRY_DATABASE_URL` → local
  `barry_co`, `DATA_HUB_ENABLED=1` → local DH `:8754`). This means **headless browser e2e works
  locally on `:8001`** (no SSO) — a correction to the old "no headless HTTP e2e" note (that applies
  to prod/nightly which DO require SSO). Dev server `npm run co:serve` = `:8001`.
- **Local DB has 0 cases** but real stock: `co_stock_rows` for `growatt-vn` (38k) + DH has
  growatt-vn materials/substitutes (7859). **Demo clients `growatt`/`johnson` HAVE a CO BOM
  workspace; the `-vn` DH clients do NOT** (0 product versions). So: use **growatt-vn** for
  run-stock/substitute/lock e2e (real stock + DH substitutes), **growatt** demo for BOM-pick.
- **Gotcha:** a hand-seeded case product shows "❗ Chưa có BOM" — the BOM picker `<select>` is only
  wired through the BCCT/invoice match flow, not a bare seed. So Slice A's browser pick isn't
  stageable from a hand-seed; verify it server-side via `e2e_bom_default_incontainer.py` instead.
- **e2e harnesses** (run with `.env` sourced, DB-mode): `e2e_bulk_lock_ledger.py` (ledger claims +
  overclaim + cross-case), `e2e_bom_default_incontainer.py` (Slice A write-through + precedence, run
  on nightly via `ssh tinsu`+`docker exec`), `e2e_substitute_export.py` (substitute → xlsx export
  reflects the swap). Scratch browser e2e: `.ai/screenshots/.../e2e_muc6.{cjs,py}` (puppeteer; no
  playwright installed). All self-clean; isolate on throwaway client/case ids.
- **DB-mode seed for e2e:** `get_co_case_state_store().save_case_record(client_id, case_dict, 0)`
  (writes `co_cases`). `co_case_store.save_state` is FILE-mode only — won't reach the DB the server
  reads. Force the recompute path with `origin_sheet_states[code].material_overrides={"0":{"norm_edit_only":True}}`.
- **Deploy:** ff-merge to `main` + push → CI deploys BOTH prod + nightly (same image) ~1-2min;
  verify `…/version` git_sha. **NEVER write the literal CI-skip token** in a commit msg →
  [[ci-skip-token-in-commit-msg]].
- **Test env:** full file-mode (NO `.env`) = **656 pass**. DB/in-container e2e need `.env`.
- Branch `feat/bom-default-pick` is folded into `main` (ff) and can be deleted.
