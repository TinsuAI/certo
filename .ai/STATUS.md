# Project Status

## Current State
- **Customer feedback "HIỆN TRẠNG BARRY CO" (2026-06-05)** tracked in
  `.ai/feedback/2026-06-05-hien-trang-barry-co.md`. Done+deployed: #9 (F5 BOM race), #7 (tên
  hàng cắt → tooltip + 2-dòng), #8 (toggle "chỉ hiện mã đủ tồn"). Still open: #12 (số tồn
  tổng), #13 (chốt BOM hàng loạt — cần /discover), #14 (BOM mặc định theo mã), #4 (mã thay
  thế — đẩy DH ranking).
- **Dossier "tờ khai ghép" (merged TKX/TKN PDF) — DONE + DEPLOYED PROD.** DH renders the
  official tờ khai layout and merges per direction; CO embeds `03-to-khai/TKX-ghep.pdf` /
  `TKN-ghep.pdf` during dossier export. Merged-PDF-ONLY (raw `.xls` download.zip path dropped).
  Contract `.ai/api-requests/2026-06-05-declarations-merged-pdf.md`. Memory
  `dossier-merged-declaration-pdf`.
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

## Recent Changes (this session, commits `1c7f5b6`..`60f8ced`)
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
1. **AUDIT — trừ-lùi không được là biến số của logic.** Rà toàn codebase tìm logic CÒN dựa
   vào workbook trừ-lùi/adjustment kiểu "đáng nhẽ không nên có mà lại có". Nguyên tắc (chốt
   2026-06-06): workbook trừ-lùi chỉ là **snapshot tồn để sync/điều chỉnh về thực tế**, KHÔNG
   được điều khiển logic hệ thống. Bối cảnh: vừa phát hiện bug đơn vị (workbook kg vs BCCT
   metric-tons → giá trị ×1000) — đã sửa bằng cách coi là **lỗi DATA** (`scripts/fix_trului_unit.py`),
   `fold_baseline` giữ "dumb" (đã revert phương án nhét quy đổi vào fold). Audit xem còn chỗ
   nào khác lỡ để adjustment ảnh hưởng logic (vd quy đổi/đoán đơn vị, phụ thuộc field workbook,
   nhánh xử lý đặc biệt theo adjustment). Cân nhắc thêm cảnh báo lúc import khi đơn vị workbook
   ≠ đơn vị BCCT (chưa làm). Xem memory `trului-unit-mismatch-fold`, `co-stock-folded-remaining-model`.
2. ~~**#12** số tồn tổng~~ ✅ DONE + DEPLOYED (commits `3bbcfe8`/`f0efe05`). Strip "Tồn CO để
   kiểm soát" đầu trang làm CO: tổng giá trị tồn tự do (VNĐ) + tổng số lượng (gộp đơn vị) + số
   mã + số dòng lot, filter theo ngày ĐK tờ khai nhập. Bug đơn vị dây hàn đã fix data trên
   PROD + DEMO (1.929 tỷ → 520,1 tỷ). Verify prod OK.
3. **#14** BOM mặc định theo mã — persist `bom_product_artifact_overrides` làm default (quyết
   per-client vs global).
3. **#13** chốt BOM hàng loạt → chạy tồn 1 lần → tổng hợp mã thiếu — luồng mới, `/discover` trước.
4. **#4** mã thay thế chưa phù hợp — đẩy DH ranking qua `.ai/api-requests/`.
5. Đòi DH confirm đã wire **regression route-guard test + post-deploy public smoke** (mục 4
   của regression prompt) — nếu chưa, leak có thể tái diễn ở deploy lỗi config.
6. (tùy) Chụp 1 lượt dossier export THẬT có PDF ghép khi có case prod đã-đóng-có-tờ-khai (hiện
   mới chứng minh bắc cầu; chưa có 1 HTTP 200 nào kèm PDF nhúng vì case local/seed đóng được thì
   0 tờ khai).
7. (tùy) Bug phụ `origin_calculation_lock` không nhả — tái hiện trước rồi mới fix.

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
- **Đừng làm lại:** toggle #8 uncheck "không khôi phục" — test cạn 25+ trigger local + prod,
  KHÔNG tái hiện; logic đúng, nghi cache trình duyệt phía khách. Service token: đã quyết KHÔNG
  làm (operator-JWT chặt hơn).
