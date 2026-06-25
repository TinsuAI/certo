# Project Status

## Current State
- **2026-06-25 — bảng kê blank-export root cause + fix (`763fe74`, on `main`, PUSHED → CI deploying).**
  Client report "xuất bảng kê vẫn bị trống" = fast `/calculate` truyền catalog rỗng → materials mất
  TÊN **và** `customs_relevance` → rác/`declarable_unmatched` không bị loại → lọt export thành dòng
  trống (prod johnson: 1019/1909 trống → 0 khi có catalog). **OVERTURNS 2026-06-20 DC2 tên-theory**
  (DH có đủ tên). Fix: nạp catalog ở 4 chỗ build (Tính/load-bom/preview/recalc) + fallback tên/HS từ
  CO-stock; **export = render thuần** (customs_relevance round-trip form + web fold `declarable_unmatched`
  "không xuất" → export == web grid); per-sheet **undo/redo server-side** sống qua save; autosave
  2s→30s configurable. Suite **706 pass**; e2e + file-export + screenshot johnson thật verified.
  Session: `2026-06-25-bangke-blank-export-undo-export-parity.md`. **HARD RULE mới: export KHÔNG có
  logic riêng — mọi logic ở bước Tính** (memory [[bangke-export-equals-web-invariant]]).
- **`main` = `origin/main` = `cfb3e6e`** (pushed). **prod = nightly = `c483673`** (v0.16.0; verified
  `barry-co.tinsu.ai/version` + `demo-co.tinsu.ai/version` both `c483673`, build 2026-06-19T15:0x) — the
  two docs commits on top (`56f750d` reconcile + `cfb3e6e` handoff) are docs-only, so CI/CD will advance
  prod/nightly git_sha to `cfb3e6e` with no app change. Tree clean except `uv.lock` (unrelated, uncommitted).
  **v0.16.0 RELEASED** (`bfd7aff`) — the 3 features below + CHANGELOG shipped; `c483673` renders
  `**bold**` in changelog bullets on the "what's new" UI.
- **This session shipped 3 features** (all live on `c483673` / v0.16.0):
  1. **NVL thay thế — ưu tiên lịch sử** (`4e40b63`): substitute modal pins materials previously used to
     replace this NVL in past **locked** dossiers to the TOP, badge "↺ đã từng thay ·N", ranked by usage
     count; injects history substitutes even when Data Hub never proposed them. CO-owned signal mined from
     case `origin_sheet_states[*].material_overrides` — **no Data Hub dependency** (distinct from DH-side
     ranking #4). See `app/substitution_history.py`.
  2. **Graceful error pages** (`a13661a`): global `HTTPException`/`RequestValidationError` handler renders
     a styled `error.html` for browser navigations, keeps JSON for fetch/XHR — a failed native form submit
     no longer dumps a raw `{"detail":…}` blob. Export "bảng kê HQ" form now submits via fetch → downloads
     on success, toasts the error in place.
  3. **Global fetch error surfacing** (`bad2c1a`): `base.html` wraps `window.fetch` → ANY non-ok response
     auto-toasts the server `detail` (no more silently-swallowed AJAX errors). `{quietError:true}` opt-out
     for self-handled/background calls; toasts de-dupe by visible text; `co_case` `toast()` delegates to
     the shared global `coToast`.
- Tests: full suite **691 pass, 10 skip** (+`test_substitution_history.py` 6, +`test_substitute_history_route.py`
  3, +`test_error_handling.py` 9). Browser-verified on live `:8001` w/ real growatt-vn data: history
  pin/inject, 404 → error page, blocked export → toast (stays on page), global fetch wrapper.
- **DATA NOT PURGED.** prod `co-db-1` có cases thật (johnson-vn) + Growatt cost-allocation. **Do NOT
  seed/test against prod; dùng nightly HOẶC local dev DB.**
- Cost-allocation, Mục 6, empty/no-BOM guard (#13c), missing-price guard, ★ BOM default, wizard — vẫn nguyên.

## Recent Changes (this session — live on `c483673` / v0.16.0, pushed to main)
- `4e40b63` feat(origin): pin previously-used NVL substitutes (`app/substitution_history.py`, route integ,
  badge + top-pin in `co_case.html`, `.origin-substitute-prior` CSS, 9 tests).
- `a13661a` feat(web): graceful error handling — `error.html` + `error_response()`/`_prefers_html_error()`
  in `main.py` (HTTPException + RequestValidationError + CaseClosedError/DH handlers routed through it);
  export form → fetch+download+toast; `.error-page` CSS; 9 tests.
- `bad2c1a` feat(web): global `window.fetch` wrapper in `base.html` (auto-toast + quietError + dedup).
- `bfd7aff` release: v0.16.0 — substitute-history priority + graceful error handling (CHANGELOG + version bump).
- `c483673` fix(whats-new): render `**bold**` in changelog bullets safely on the "what's new" UI.
- `56f750d` docs: **reconcile BACKLOG/STATUS with shipped work** (verified 16 items vs code at `c483673`
  via 5 parallel agents) — **NOT pushed yet**. See session `2026-06-19-backlog-status-reconciliation.md`.

## Next Steps (priority order)
0. **(2026-06-25 follow-ups)** — (a) **P2 perf** (BACKLOG): fast `/calculate` giờ pull thêm catalog
   (~13k, cache 90s) cho tên+`customs_relevance` → tối ưu bằng materialize vào snapshot tồn. (b) Sheet
   **đã CHỐT trước fix** giữ materials `customs_relevance=0` → export vẫn theo bản cũ; cần mở chốt +
   Tính lại để dọn (KHÔNG vá ở export — đúng nguyên tắc). (c) Verify prod sau deploy: `curl …/version`
   + export 1 hồ sơ johnson thật ra 0 dòng trống.
1. **Ranking mã thay thế #4 (DH-side)** — history-priority (CO-side, shipped) only floats *previously-used*
   codes; the root issue that a high-score-but-low-stock candidate gets buried (FINDINGS #2) is still
   DH-side. Needs `.ai/api-requests/` for a score+feasibility blended ranking from Data Hub.
2. **Phase 2 bulk/wizard rework** — **backend đã BUILT, KHÔNG phải placeholder**: routes
   `preview_stock_all_route` / `bulk_substitute_route` / `bulk_lock_route` (`co_case.py:1635/1646/1732`)
   chạy được; nút "Chạy tồn"/"Chốt tất cả" bị **gate tắt cố ý** ("đang xây dựng", `834e1da`, routes untouched).
   - Quyết định: re-enable batch flow mạch lạc HAY retire — pre-flight summary trước batch-lock (sheet nào lock/skip + lý do).
   - Wizard: vẫn **chọn BOM version im lặng** — show "BOM: #N (mặc định)" trước Tính (`co_case.html:6018-6021`, chưa đọc dataset version).
3. **Client feedback 2026-06-05 còn lại:** **#12** số tồn TỔNG = **PARTIAL** (`#13a c9f5183` đã gộp thiếu-tồn
   per-material `co_case_context.py:1675-1716`, nhưng **chưa có cột SUM tổng across SP** — `co_case.html:5782` chỉ "Thiếu tồn: N mã/M SP"); **#4** ranking (DH-side, = #1).
4. **Correctness (backlog, ưu tiên):** **DC3a** update-BOM còn ship rác · **DC3c** `declarable_unmatched=0 → LVC thổi`
   **chưa chặn cứng** Chốt/Xuất (DC3b export đã strip render-time, nhưng sheet pre-mig-078 còn lọt tới khi re-Tính);
   **B6** re-scoped → verify **độ chính xác FX** (toggle native↔VND đã chạy, hết "luôn VND").
5. `compact` PDF profile toggle; **EX1** column-K ref; **XX1** NVL có xuất xứ cột M-N (mới blank M-N tạm).
   Backlog mở: **M1** (cả 2 sub-bug còn) · **D1** (còn C/E/F + parity harness) · **P1** (~40s) · **T1** (DB isolation) · **DC2** · **CS3** park ×2 · **LK1** review rộng.

## Notes for Next AI Session
- **BACKLOG is freshly reconciled vs code (2026-06-19, `56f750d`)** — markers are accurate as of `c483673`.
  Newly-closed since last backlog edit: **B7** (`cb3504b`), **CS1** (`ca11c37`); **D1** mostly done
  (`2c856da`, only C/E/F + parity left); **B6** re-scoped (toggle works, verify FX only); **DC3b** export
  strips rác render-time. Still-open w/ refreshed refs: **M1**, **DC3a/DC3c**, **#12** (partial), wizard "BOM #N".
- **Substitution history** (`app/substitution_history.py`): mines `origin_sheet_states[sp].material_overrides`
  across the client's cases; counts ONLY sheets with `status=="locked"` (committed dossiers); keyed by the
  base BOM `material_code` (= what the substitute-candidates route receives). 60s TTL cache, busted via
  `invalidate_co_case_source_cache` (called on lock/reopen). Pure `build_substitution_history` is unit-tested;
  route pins via `previously_used`/`history_rank`; client floats them in `reorderRecommendedByStock`.
- **Error handling pattern:** `error_response(request, code, detail)` in `main.py` picks HTML-vs-JSON via
  `_prefers_html_error` (browser = `Sec-Fetch-Dest: document` OR (`text/html` Accept & no `X-Requested-With`);
  fetch = JSON). New error-prone routes get this for free. **Global fetch wrapper** (`base.html` `<head>`)
  toasts every non-ok fetch — pass `{quietError:true}` for background/self-handled calls; `coToast` de-dupes.
  500s deliberately NOT caught (keep dev tracebacks); add a friendly 500 page only if prod needs it.
- **Sequential pipeline (quan trọng):** origin sheets xử lý **tuần tự + xen kẽ** — `/calculate` sheet N
  đòi N-1 đã **locked**. Wizard xen kẽ tính→chốt là đúng thiết kế.
- **★ chỉ render khi có DH BOM:** picker version chỉ populate từ DH BOM artifacts; local dev không có cho
  hầu hết SP. Ngoại lệ: **`growatt-vn` PV00.0048500 CÓ** DH BOM #3 (~300 NVL) → dùng để verify ★/wizard.
- **Local dev = auth-off + DB-mode** (`.env`: `CO_AUTH_REQUIRED=0`, `BARRY_DATABASE_URL`→`barry_co`,
  `DATA_HUB_ENABLED=1`→DH `:8754`). `npm run co:serve` = `:8001` (--reload watches app/ *.py/*.html/*.css).
- **Scratch e2e harnesses (gitignored, under `.ai/screenshots/`):**
  - `2026-06-19-substitute-history/seed_and_shoot.py` (+`shoot.cjs`) — seed locked-history case + drive
    modal; opens it via a synthetic `[data-origin-substitute-trigger]` (run-stock button disabled, and
    hand-seed `-vn` rows don't render in detail).
  - `2026-06-19-error-handling/seed_and_shoot.py` (+`shoot.cjs`) — 404 page + blocked-export toast;
    `global_fetch_check.cjs` — global fetch wrapper (toast/quietError/dedup).
  - `2026-06-19-co-flow-walkthrough/` — earlier lifecycle/wizard harnesses + FINDINGS.md.
  - Run with `.env` sourced + `PYTHONPATH=$(pwd)` + `NODE_PATH=$(pwd)/node_modules` via `uv run python`.
- **Verify after merge:** `curl …/version` git_sha (prod=barry-co, nightly=demo-co). **NEVER** ghi literal
  CI-skip token trong commit msg → skip cả pipeline ([[ci-skip-token-in-commit-msg]]).
- **Test env:** full file-mode (NO `.env`) = **691 pass**. DB/in-container e2e cần `.env`.
- PR convention (rule của user): commit/PR English, **không** trailer/co-author AI.
