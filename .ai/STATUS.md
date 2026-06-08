# Project Status

## Current State
- **B2 stepper status + picker search/cap — COMMITTED + PUSHED (deploy in flight),
  2026-06-08.** Two clean commits on `main`:
  - **B2 (`0374edb`)** — `co_case_step_status` → `{status,label}`; tập trạng thái
    done/in_progress/attention/todo, nhãn theo bước; bước 3 derive từ
    `products[].origin_sheet_status` ⇒ chốt hết = `done` "Đã chốt N/N" (hết kẹt
    "Cần soát"); bỏ Preview/dead `wip`/opacity-mute. Test `test_co_case_step_status.py`
    (20). Brief `.ai/features/2026-06-08-workflow-step-status-display.md`.
  - **Picker (`69e1de2`)** — modal "Đổi công ty"/"Đổi hồ sơ" hết **tràn** khi nhiều
    mục: fix scroll (grid `minmax(0,1fr)` + `min-height:0` + `.picker-row[hidden]`),
    cap 8 + "Hiện tất cả (N)", search client-side accent-insensitive (đ→d, NFD-fold).
    Verified puppeteer trên case 845 hồ sơ.
  - **Dev DB cleanup:** growatt có **845 hồ sơ rác test** (DB-backed test ghi vào DB
    dev dùng chung, không dọn). Đã purge (backup `data/local/backups/`), giờ 0. Gốc =
    test không cô lập → backlog **T1** + brief `.ai/features/2026-06-08-test-db-isolation.md`.
    Memory [[co-case-store-db-json-reseed]] (purge phải clear cả DB lẫn `cases.json` fallback).
- **UI backlog B (B1/B3/B4) + breadcrumb nav — MERGED + DEPLOYED + PROD-VERIFIED
  (prod + demo, 2026-06-08, HEAD `7253412`).**
  - **B1** — "Đổi công ty" / "Đổi hồ sơ" giờ là **lazy-fetch modal picker** (không
    redirect). Fragment endpoints `GET /clients-picker` (cross-client) +
    `GET /clients/{id}/co-case-picker` (per-client); template `_picker_clients.html`
    / `_picker_cases.html`; JS picker chung trong `base.html`
    (`[data-picker-open]` + `data-picker-url` + `data-picker-target` → fetch →
    inject); CSS `.picker-*`. Highlight mục đang xem.
  - **B3** — width bảng kê origin keyed theo `[data-origin-column]` thay vì
    `th:nth-child(N)` (cột `select` chèn vào làm lệch 1 cột → STT/Mã NVL phình, Tên
    NVL bị bóp). Cột select `width:1%`→`2.6rem` (1% co lại dưới `table-layout:fixed`
    ⇒ clip checkbox = phần i).
  - **B4** — trang chi tiết hồ sơ full-width qua `{% block shell_modifier %}`
    (`.shell-wide`), scope chỉ khi `co_case_active_step != "index"` (không đụng
    list/catalog/…).
  - **Breadcrumb** — `Công ty › {công ty} › Hồ sơ C/O › {mã hồ sơ}` trong
    `_client_nav.html` (partial included mọi trang client + case). Các cấp trên là
    link để quay lại; adapt theo `active` + `co_case_active_step`.
  - **Prod-only auth fix (phát hiện lúc verify):** client picker trả **403** vì
    `guard_response` đọc segment-2 của `/clients/picker` thành `client_id="picker"`
    rồi chặn theo visible-set. Local auth OFF nên không repro. Sửa: dời sang
    top-level `/clients-picker` (`client_id_from_path`→"") + thêm vào
    `should_guard_path` + regression test `tests/test_co_auth_path_guard.py`.
    Memory [[cross-client-fragment-route-403]].
  - **Verified:** file-mode **521 passed / 9 skipped**; prod browser test (login
    `claude-check@local`) — breadcrumb 4 cấp, case picker 6 dòng, client picker 2
    dòng (đúng visible-set), crumb-nav quay về list, **0 console error**.
- **B2 — DISCOVERED only** → brief `.ai/features/2026-06-08-workflow-step-status-display.md`.
  Phát hiện chính: **Phase 2 (Load BOM / Tính split, `bom_loaded`) ĐÃ ship** (endpoint
  `/load-bom` riêng) ⇒ B2 hết phụ thuộc Phase 2. Lỗi lõi: stepper bước 3 không phản
  ánh chốt-sheet (best state luôn "Cần soát"), "Preview" nhãn tiếng Anh, review/preview
  trùng màu, `step.wip` dead code, `todo` mờ bằng opacity. Next = `/tdd`.
- **Deployed baseline (prod `barry-co.tinsu.ai` :8755 + demo `demo-co.tinsu.ai` :8765,
  all on `main`):** P1 origin cold-load perf (`a1ac2ed`), CO-stock detangle Phase 1+2+3
  (Load BOM split + over-claim FOR UPDATE + lot-history fold), app versioning + changelog,
  background dossier export, merged TKX/TKN PDF, content-hash cache-busting, CO→DH
  operator-JWT auth. CI green.

## Recent Changes (latest first)
- **`69e1de2`** feat(co-case): picker search + capped list (no overflow).
- **`0374edb`** feat(co-case): B2 — rework stepper per-step status.
- **`7253412`** fix(auth): client picker 403 prod fix (`/clients/picker`→`/clients-picker`
  + guard whitelist + regression test).
- **`e3f26a2`** docs(backlog): mark B1/B3/B4 done + B2 discovery brief.

## Next Steps (priority order)
1. **BACKLOG D1 — audit delta-vs-full / Data Hub refresh.** Vẫn là item rủi ro cao nhất
   (SAI TỒN). `/discover` + parity tests. See `.ai/BACKLOG.md` D1.
2. **BACKLOG T1 — test DB isolation.** Test chạy `.env` ghi vào DB dev dùng chung, không dọn
   (845 case growatt = rác, đã purge). `/discover` conftest schema-isolation. See brief.
3. **Index page (case list) 4.27s** johnson-vn — N+1 `claims_summary_for_case`
   (`co_case_context.py:2760-2767`).
4. **(Optional) P1 follow-up:** scope `/calculate` stock theo lô của sản phẩm (~540ms/calc).
5. **DH reciprocal cleanup (cần user OK):** DH demo `/version` còn `0.0.0`; DH prod thiếu
   `COPY CHANGELOG.md`.
6. Feedback backlog: #14 (BOM default per code), #13 (batch chốt BOM), #4 (DH substitute ranking).
7. Phase 3 leftover: delete-case audit R1/R2/R3 (`.ai/audits/2026-06-07-delete-case-stock-history-audit.md`).

## Notes for Next AI Session
- **Branch/deploy:** `main` HEAD `69e1de2` (B2 + picker) = pushed, deploy in flight. Push
  `TinsuAI/co main` → runner auto-deploys ~1-2min (NO `[skip ci]` on tip or deploy skips;
  re-trigger `gh workflow run ci.yml --ref main`). `origin` + `tinsu` đều = TinsuAI/co.
- **Working tree:** chỉ còn 2 untracked session log đời trước (`2026-06-08-co-app-versioning-changelog.md`,
  `2026-06-08-origin-cold-load-perf.md`) — leave or commit at will; không phải việc session này.
- **Auth gotcha (MỚI — memory [[cross-client-fragment-route-403]]):** auth chỉ active khi auth ON
  ⇒ **phải browser-test PROD** cho mọi thay đổi liên quan route-guard/auth; local auth OFF che 403.
  Cross-client fragment phải là path top-level; per-client thì dưới `/clients/{id}/...`.
- **Picker pattern:** lazy modal = trigger `[data-picker-open data-picker-url data-picker-target]`
  → JS chung trong `base.html` fetch fragment → inject vào `[data-picker-body]`. Reuse cho picker mới.
- **Local dev:** `npm run co:serve` → `127.0.0.1:8001` (auth OFF, `--reload` watch app/**). Server
  đang chạy session này.
- **Tests:** file-mode `PYTHONPATH=. uv run python -m pytest` (NO .env) = 521 passed. DB co_stock +
  real-Johnson parity e2e cần `.env` (memory [[test-env-filemode-vs-datahub]]). Mới:
  `tests/test_co_auth_path_guard.py`.
- **Prod browser test recipe:** script `/tmp/prod_verify.js` (Playwright via `NODE_PATH=$PWDIR`),
  login `claude-check@local` / `claude-temp-2026` (manager, growatt-vn + johnson-vn), client id phải
  dạng `-vn`. Memory [[browser-test-recipe]] + [[demo-test-account]].
- **Screenshots:** `.ai/screenshots/2026-06-08-ui-backlog-b/` (local `01..07` + `prod-01..03`).
