# Project Status

## Current State
- **CO-case LIST page redesign — DONE + DEPLOYED PROD + DEMO (`ee70a4b`, run 27089129326).**
  Prod `barry-co.tinsu.ai` + demo `demo-co.tinsu.ai` healthz 200 post-deploy. Replaced the
  bulky `co-command-bar` + wrong 4-step mini-flow with a slim header + clickable **summary stat
  band** (Tổng/Đang xử lý/Đã chốt/Có vấn đề/Đã xuất); moved the spacy create panel into a
  `+ Tạo hồ sơ` **modal** (reused all existing form macros/JS); redesigned the dossier table to
  show **real workflow status** (badge `Đã chốt`/`Đang xử lý`/`Có vấn đề` + `✓ Đã xuất` +
  `X/Y bảng kê chốt` progress bar + inline issue chips), real status filter, and per-row `⋯`
  menu (Mở / Lưu trữ / Xoá). Added **archive**: `archived` flag (round-trips file-mode +
  PG-payload, no migration), `set_case_archived` store fn (bypasses close-gate on purpose),
  archive/unarchive routes, hidden-by-default + `Hiện đã lưu trữ (N)` toggle. Status derivation
  is one shared cheap helper `co_case_status_view` (no source-context calls); `pages.py`
  dashboard now delegates to it. Brief `.ai/features/2026-06-07-co-case-list-redesign.md`;
  screenshots `.ai/screenshots/2026-06-07-co-case-list-redesign/`. Tests **484 passed**
  (+ new `tests/test_co_case_list_status.py`; 3 `test_co_demo` assertions updated for the new
  markup). **Two CSS contrast/clip fixes during review:** (1) `.co-stat` is a `<button>` so the
  un-classed "Tổng" number inherited the UA button color and vanished → set explicit
  `color: var(--foreground)` (recurring bug, memory `css-no-opacity-muted-text` updated with this
  second mechanism); (2) `.dossier-list{overflow:hidden}` clipped the `⋯` dropdown → scoped
  `overflow:visible` to `.co-dossier-list`. **Next:** push/deploy when ready; consider deleting
  dead CSS (`co-flow-mini`/`co-overview-create`/`co-case-index-layout`).
- **UX/UI redesign — GitHub Primer "operations console" — DONE + DEPLOYED PROD + DEMO
  (`a33eaae`).** Full visual+IA overhaul: neutral Primer palette (slate + single blue accent
  `#1f6feb` + status colors, flat/solid-border, both themes, WCAG AA) via token-value swap so
  `co_case.html` inherits it untouched; CO-centric company dashboard + richer company-list
  cards; grouped per-client nav (Dữ liệu/Cấu hình dropdowns); per-data-page metric dashboards
  (cheap sources only — Tồn CO via materializer SQL); config grouped company-vs-system (FX
  moved to Settings). Consumes Data Hub's `bom` block on `/source-summary` for the BOM
  dashboard (export trio `exported_with_bom/exported_total`; fulfils
  `.ai/api-requests/2026-06-07-products-total-count.md`). Verified live: prod
  `barry-co.tinsu.ai` + demo `demo-co.tinsu.ai` both serve `--primary:#1f6feb`, healthz 200.
  Tests 477 passed. Memories `ui-design-direction-primer`, `dh-products-endpoint-50-cap`.
  **Caveat:** BOM dashboard shows real numbers only where Data Hub has deployed the `bom`
  block; degrades to a qualitative card otherwise (safe) — confirm DH deployed it to prod.
  This deploy also shipped the prior `dc1b582` background-dossier-export (was pending deploy).
- **Customer feedback "HIỆN TRẠNG BARRY CO" (2026-06-05)** tracked in
  `.ai/feedback/2026-06-05-hien-trang-barry-co.md`. Done+deployed: #9 (F5 BOM race), #7 (tên
  hàng cắt → tooltip + 2-dòng), #8 (toggle "chỉ hiện mã đủ tồn"). Still open: #12 (số tồn
  tổng), #13 (chốt BOM hàng loạt — cần /discover), #14 (BOM mặc định theo mã), #4 (mã thay
  thế — đẩy DH ranking).
- **Dossier "tờ khai ghép" (merged TKX/TKN PDF) — DONE + DEPLOYED PROD.** DH renders the
  official tờ khai layout and merges per direction; CO embeds them during dossier export.
  Merged-PDF-ONLY (raw `.xls` download.zip path dropped). Contract
  `.ai/api-requests/2026-06-05-declarations-merged-pdf.md`. Memory `dossier-merged-declaration-pdf`.
- **Dossier export = background job — DONE + COMMITTED `dc1b582`, NOT pushed/deployed yet.**
  Was a sync ~45s request that silently dropped the import TKN PDF on a slow DH render. Now:
  download.pdf gets a 180s timeout + loud README/MANIFEST warning on failure; embedded PDFs
  renamed `{case_code}-to-khai-xuat/nhap.pdf`; the build runs off-request in
  `app/dossier_export_service.py` (in-process thread, JWT via `copy_context`), status+zip
  persisted per case keyed to `dossier_content_revision` (reopen+edit → stale → "Xuất lại");
  review page server-renders state + polls only while running. Live-verified on
  `johnson-vn/co-case-ec000d03522e` (real 194-TKN import PDF). Brief
  `.ai/features/2026-06-07-background-dossier-export.md`; memories `background-dossier-export`,
  `css-no-opacity-muted-text`. **Open follow-up:** push + deploy; consider ProcessPool only if
  GIL-starvation appears under real load (measured fine — DH render is I/O).
- **DH security: declarations-download leak — found, fixed by DH, verified closed.** Public
  `download.pdf`/`download.zip`/`declarations` were served with NO auth (enumerable customs
  files). DH now enforces auth on **all** `/v1/hub/*` → no-auth = 401. Verified on prod.
  Regression-test prompt filed (`2026-06-06-declarations-auth-regression-tests-dh-prompt.md`) —
  DH still owes confirmation that the route-guard test + post-deploy public smoke are wired.
- **CO→DH auth model:** operator-JWT passthrough via contextvar (`main.py` middleware →
  `current_data_hub_token`). **No service token** (decided 2026-06-06 not to add one; the empty
  prod `DATA_HUB_API_TOKEN` is the WRONG name anyway — CO reads `DATA_HUB_SERVICE_TOKEN`).
  Memory `dh-auth-enforced-co-token-model`.
- **Static assets now content-hash cache-busted** (`asset_url()`), fixing 4h Cloudflare-stale
  CSS after deploys. Memory `static-asset-cache-busting`.
- App healthy on prod (`barry-co.tinsu.ai`, container Up/healthy), CI green, nightly refreshed.

## Recent Changes (latest first)
- **UX redesign `3090f76`..`a33eaae`** (2026-06-07, merged to `main`, **deployed prod+demo**):
  Primer design system (`app.css` tokens); CO dashboard + company cards + grouped nav;
  per-data-page metric dashboards + DH `bom`-summary consumer; config grouping; tests;
  API-request doc; carry-over of prior handoffs. `a33eaae` = post-push CI fix (a stale
  `test_data_hub_integration` assertion the local file-mode subset missed; deploy was correctly
  gated/skipped on the first push so prod never broke). CI/CD on tinsu runner: tests → build →
  deploy-on-tinsu + nightly refresh.
- `dc1b582` feat(co-case): background dossier export + fix missing import TKN PDF (2026-06-07).
  13 files, dossier-only. **Now pushed + deployed** (rode along the UX-redesign deploy `a33eaae`).
- `1c7f5b6` feat: #7 tooltip+2-line name, #8 stock-only toggle (`co_case.html`, `app.css`).
- `a394d32`+`925654d` feat: `asset_url()` content-hash cache-busting; registered on BOTH Jinja
  instances (`templating.py`, `portfolio.py`) — portfolio uses its own instance.
- `206f9c8` fix: item-head material code + chevron were invisible (inherited button color =
  white on light / dark on dark); set explicit theme colors.
- `fd8015e` feat: merged-PDF dossier — `download_declarations_pdf` adapter,
  `_try_fetch_declaration_pdfs`, `create_dossier_zip(declaration_pdfs=)`, policy allowlist.
- `e979423` refactor: merged-PDF-only — dropped `_try_fetch_declaration_archives` + the
  `declaration_archives` path.
- `a26f085`+`60f8ced` docs: DH leak defect + regression-test prompts.
- `bb4ed6d` ci: Data Hub deploy smoke made auth-tolerant (was `curl -fsS .../v1/hub/dncxs`
  no-token → 401 → deploy exit 22 after DH enforced auth).

## Next Steps (priority order)
0. ~~**Confirm Data Hub deployed the `bom` block to prod.**~~ ✅ DONE 2026-06-07 — confirmed
   via in-container probe (johnson 574/651, growatt 20/63); prod BOM dashboard now renders the
   real export trio end-to-end. Only loose end: fill the exact DH commit hash in the Approval
   section of `.ai/api-requests/2026-06-07-products-total-count.md` (from the data-hub repo).
0b. (optional) Live UI smoke on prod with demo login `claude-check@local` / `claude-temp-2026`
   to screenshot the real authed pages (dashboard/data dashboards) — local verified, prod CSS
   confirmed but authed pages not yet screenshotted.
1. ~~**AUDIT — trừ-lùi không được là biến số của logic.**~~ ✅ DONE 2026-06-07
   (`.ai/audits/2026-06-07-trului-not-a-logic-variable-audit.md`). Verdict: runtime logic
   CLEAN — chỉ `opening_qty_override`+`used_qty` vào logic qua `fold_baseline` (qty-only);
   guard + mọi read path dùng folded `remaining_qty`+ledger; không field giá/đơn vị nào điều
   khiển logic; không heuristic quy đổi kg↔tấn trong `app/`. **Việc CÒN LẠI cần làm = F1
   (MEDIUM):** import KHÔNG kiểm đơn vị workbook ≠ đơn vị BCCT → workbook lệch đơn vị vẫn âm
   thầm hỏng snapshot (×1000 + over-alloc), hiện chỉ chữa hậu-kỳ bằng `scripts/fix_trului_unit.py`.
   Fix: thêm cảnh báo lúc import ở `routers/co_stock.import_co_stock_workbook` (door guard,
   KHÔNG auto-convert — fold giữ dumb). Minor (low): dead flags `adjustment_applied`/
   `opening_qty_adjusted`, deprecated `apply_adjustments` + docstring cũ, 8 field workbook
   lưu-mà-không-đọc (latent). Memory `trului-unit-mismatch-fold`.
2. ~~**#12** số tồn tổng~~ ✅ DONE + DEPLOYED (commits `3bbcfe8`/`f0efe05`). Strip "Tồn CO để
   kiểm soát" đầu trang làm CO: tổng giá trị tồn tự do (VNĐ) + tổng số lượng (gộp đơn vị) + số
   mã + số dòng lot, filter theo ngày ĐK tờ khai nhập. Bug đơn vị dây hàn đã fix data trên
   PROD + DEMO (1.929 tỷ → 520,1 tỷ). Verify prod OK.
3. **BACKLOG — AUDIT: xoá hồ sơ đang giữ tồn → nhả tồn, lịch sử tồn CO ghi nhận thế nào?**
   Modal xác nhận xoá hiện: "Hồ sơ đang giữ N dòng tồn trên M lot. Xác nhận xoá sẽ nhả toàn bộ
   tồn về kho. Thao tác không thể hoàn tác." Audit flow `delete_case_record(..., release_claims=
   True)` (`app/co_case_store.py`) + `co_stock_ledger`: khi nhả claim (status→'released',
   `claim_release` events) rồi xoá case row — **lịch sử/ledger tồn CO được ghi nhận ra sao** (còn
   truy được hồ sơ nào từng giữ lot đó không, hay mất dấu khi case_id biến mất?), và **đánh giá
   có hợp lý không** (audit trail, khả năng truy vết, có nên soft-delete/giữ lịch sử thay vì xoá
   cứng). Liên quan audit gap "silent Tồn CO leak HIGH #2".
3. **#14** BOM mặc định theo mã — persist `bom_product_artifact_overrides` làm default (quyết
   per-client vs global).
3. **#13** chốt BOM hàng loạt → chạy tồn 1 lần → tổng hợp mã thiếu — luồng mới, `/discover` trước.
4. **#4** mã thay thế chưa phù hợp — đẩy DH ranking qua `.ai/api-requests/`.
5. Đòi DH confirm đã wire **regression route-guard test + post-deploy public smoke** (mục 4
   của regression prompt) — nếu chưa, leak có thể tái diễn ở deploy lỗi config.
6. ~~Chụp 1 lượt dossier export THẬT có PDF ghép~~ ✅ DONE 2026-06-07 — HTTP 200 thật trên
   `johnson-vn/co-case-ec000d03522e`: zip 22MB có cả TKX (8 trang) + TKN (5668 trang, 194 tờ
   khai). Screenshots panel `.ai/screenshots/2026-06-07-background-dossier-export/`.
7. ~~**Push + deploy** background dossier export + smoke nút "Xuất hồ sơ" trên prod~~ ✅ DONE
   2026-06-07 — đã deploy (rode `a33eaae` trước đó); smoke prod qua demo login OK:
   `johnson-vn/co-case-0e829a5368ab` Xuất lại → running → done ~88s → tải zip 9.50 MB hợp lệ.
8. (tùy) Bug phụ `origin_calculation_lock` không nhả — tái hiện trước rồi mới fix.

## Notes for Next AI Session
- **Local dev:** `npm run co:serve` → `127.0.0.1:8001` (auth off, `--reload` watches app/**.py,
  *.html, *.css). Cases store = PG `barry_co` (chỉ có `growatt` 2 stub); johnson-vn cases trên
  HTTP là **seed/demo in-memory**, không persist. co_stock johnson-vn materialized (~60k rows).
- **DH local/dev = `127.0.0.1:8754`** (qua `.env DATA_HUB_API_BASE_URL`); có endpoint merged-PDF
  + đã fix download.zip bytes. Probe bằng `set -a; . ./.env; set +a; PYTHONPATH=. uv run python …`.
- **Verify CO↔DH path không cần HTTP:** import `app.routers.co_case.portfolio_service` +
  `_try_fetch_declaration_pdfs` — trả PDF hợp lệ. Dossier export route gọi nó trong-request nên
  có operator JWT.
- **Prod probe recipe:** `ssh tinsu "docker exec -i co-app-1 python -" < script.py` (env DH có
  sẵn). Public DH = `https://ttdatahub.tinsu.ai`; internal = `http://data-hub-app:8754`.
- **Playwright:** `PWDIR=$(dirname "$(ls -d ~/.npm/_npx/*/node_modules/playwright|head -1)"); NODE_PATH=$PWDIR node script.js`. Demo login prod: `claude-check@local` / `claude-temp-2026`.
- **Deploy:** push `TinsuAI/co main` → CI. Health-check 401-sau-`{"status":"ok"}` = DH smoke
  (đã fix). Memory `deploy-remote-tinsu-co`, `dh-auth-enforced-co-token-model`.
- **Git:** `60f8ced` (docs) chưa push — gom lần deploy sau. `.ai/sessions/2026-06-05-*.md` (2
  file) còn untracked từ phiên trước.
- **⚠️ Cây làm việc còn ~900 dòng pre-existing CHƯA COMMIT từ một luồng việc KHÁC** (không phải
  dossier): `clients.html`, `workspace.html`, `routers/pages.py`, `web/client_context.py`,
  `bom_service.py`, `routers/bom.py`, `routers/co_stock.py`, nhiều template, + phần lớn `app.css`
  và một số test trong `test_co_demo.py`; untracked `app/templates/_source_stats.html`,
  `.ai/api-requests/2026-06-07-products-total-count.md`, `.ai/audits/...trului...`,
  `.ai/sessions/2026-06-07-trului-logic-audit.md`. `dc1b582` đã được tách sạch chỉ-dossier khỏi
  đống này (dùng `git apply --cached` từng hunk cho 2 file trộn). **Đừng gộp đại** — luồng kia
  cần chủ nhân của nó review/commit riêng. STATUS.md + session log này cũng đang unstaged.
- **Dossier export note:** htmx KHÔNG được load trong app (mọi `hx-boost` là no-op) → poll bằng
  vanilla JS; staleness key là content-hash `dossier_content_revision` (KHÔNG dùng
  `co_cases.revision` vì nó null ở file-mode); job mồ côi sau restart phát hiện qua `_FUTURES`
  rỗng (không TTL).
- **Đừng làm lại:** toggle #8 uncheck "không khôi phục" — test cạn 25+ trigger local + prod,
  KHÔNG tái hiện; logic đúng, nghi cache trình duyệt phía khách. Service token: đã quyết KHÔNG
  làm (operator-JWT chặt hơn).
