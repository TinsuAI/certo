# Feature: Cẩm nang HTML gộp CO + Data Hub (host trong app, kiểu audit-hq)

**Date:** 2026-07-28 · **Type:** Documentation deliverable (static site, no app code change)

## Mục tiêu
Dựng cẩm nang hướng dẫn dạng **trang HTML tĩnh host trong app** (giống
`audit-hq-mvp/app/static/docs/huong-dan/index.html`) cho CO + Data Hub, tiếng Việt,
ảnh chụp thật có **khung đỏ + số thứ tự** khớp bước.

## Quyết định phạm vi (user chốt)
1. **Một trang gộp** CO + Data Hub (hai hệ thống coupled chặt; tách sau nếu cần).
2. **Chụp mới trên local + chú thích** (không dùng lại ảnh cũ, không chụp prod).
3. **Host ở cả hai repo** — cùng một file phục vụ từ CO và Data Hub.

## Đã làm
1. **Template gốc**: `audit-hq-mvp/app/static/docs/huong-dan/index.html` (một file HTML tự chứa,
   inline CSS/JS; sidebar TOC + tìm kiếm + light/dark + lightbox; ảnh khung đỏ). Cơ chế chú thích:
   `audit-hq-mvp/scripts/guide_screenshots.py::annotate()`.
2. **Shoot + annotate**: `shoot_guide.cjs` (Puppeteer, port lại `annotate()` — khung đỏ 2.5px `#e11d48`
   + badge số). Chụp cả Data Hub (`:8754`, login admin) và CO (`:8001`, auth-off), ghi thẳng vào
   `barry-CO-main/app/static/docs/huong-dan/`. 21 ảnh: `dh-00..dh-07`, `co-01..co-13`.
   - `NOLOCK=1` → chạy tới bước Tính (không Chốt) → re-runnable, không hao tồn.
   - `ONLY=dh|co` → chỉ chụp một app.
3. **Trang cẩm nang**: `barry-CO-main/app/static/docs/huong-dan/index.html` (25 thẻ, 4 mục:
   Tổng quan 1.1–1.2 · Data Hub A1–A10 · CO 5 bước B1–B10 · Lưu ý c1–c2). CSS + JS bê nguyên từ template;
   nội dung Việt hoá từ `README.md` + bản đồ luồng nạp từ agent. Số bước trong `<ol>` khớp badge trên ảnh.
4. **Bổ sung phần NẠP dữ liệu** (sau review — trước đó chỉ dạy XEM, công ty trống không đi tới C/O được):
   thêm A2b tạo công ty + mode khớp mã, A4 nạp danh mục, A5 cổng map→xem trước→xác nhận, A6 nạp quy đổi
   (điều kiện), A7 nạp BCCT, A8 nạp BOM+flatten, A9 kiểm tra + lịch sử tab Tải lên; Tổng quan thêm checklist
   thứ tự nạp (1.2); Lưu ý thêm bảng empty-state→nguyên nhân + phân quyền (c2). Sửa "Tải lên" tab = lịch sử,
   không phải nơi nạp; sửa câu "Phần A làm việc đó".
   - Ảnh nạp: `INGEST=1 node shoot_guide.cjs` → 6 form GET (dh-new-company, dh-catalog/bqd/bcct/bom-upload,
     dh-uploads; không ghi dữ liệu). Cổng map/preview: upload file mẫu (`catalog_demo.xlsx`, openpyxl) →
     chụp `dh-catalog-mapping` + `dh-catalog-preview` → **Reject** (không confirm → danh mục demo giữ nguyên 10).
5. **Deploy 2 repo**: copy `index.html` + 29 `.png` sang `data-hub/app/static/docs/huong-dan/`.
6. **Verify**: cả hai serve 200, TOC dựng 25 link, 0 ảnh vỡ, không lỗi JS.
7. **Review**: 2 agent — map luồng nạp DH (route/template/selector) + review độ đầy đủ. Lỗ hổng G1–G7
   (thiếu toàn bộ write path) đã đóng. Ghi chú DH: tab "Tải lên" chỉ là audit; nạp thật ở từng tab domain.
8. **Round 3 (agent fable review độ chi tiết + graph)** — sửa 2 thẻ SAI: **B9** (bước 4 không upload —
   là kiểm tra + tải zip từ DH; TKN chỉ hiện sau khi chốt), **B10** (thêm cổng "Đóng hồ sơ" → xuất zip
   job nền → Mở lại; "Xuất bảng kê HQ" không cần đóng). Thêm **3 sơ đồ SVG inline** (theme-aware, không
   thư viện): D1 phụ thuộc DH→CO + chiều ngược đề xuất BOM (thay flow 1.1); D2 vòng đời sheet (B8);
   D3 vòng đời tồn CO một lô (B2). Bổ sung text: bảng "Nút mờ — vì sao" (B8), legend cấu hình + 3 nghĩa
   xuất xứ cột (7)/(8)/(9) + thao tác Bước 3 (B6), chiều sâu DH A5/A7/A8 (skip-map 24h/LLM, confirm_diffs/
   UoM gate, 8 profile BOM/flatten-decision), khôi phục v0.16 (toast/trang lỗi) vào c1. Layout: nâng
   `.wrap max-width` 1180→1460 (bỏ dải trống bên phải). Vẫn 25 thẻ, 29 ảnh; không chụp mới.

## URL (dev)
- CO: `http://127.0.0.1:8001/static/docs/huong-dan/index.html`
- Data Hub: `http://127.0.0.1:8754/static/docs/huong-dan/index.html`
- Prod (sau deploy): `https://barry-co.tinsu.ai/...` và `https://ttdatahub.tinsu.ai/...`

## Tái tạo ảnh
Cần: Data Hub `:8754` + CO `:8001` chạy, công ty demo `demo-furniture` đã seed trong DB `data_hub`
(schema `hub`), tồn CO đã materialize.

    # nếu Chốt bị chặn "thiếu tồn" do case demo cũ giữ claim: giải phóng rồi refresh
    psql postgresql:///barry_co -c "set search_path=co; delete from co_stock_events where client_id='demo-furniture'; delete from co_stock_claims where client_id='demo-furniture';"
    curl -sX POST http://127.0.0.1:8001/clients/demo-furniture/co-stock/refresh -H 'Content-Type: application/json' -d '{}'
    # chụp lại + chú thích (full flow, có Chốt → co-09/co-11/co-12)
    node .ai/features/2026-07-28-co-datahub-guide-site/shoot_guide.cjs
    # hoặc re-runnable, không Chốt:
    NOLOCK=1 node .ai/features/2026-07-28-co-datahub-guide-site/shoot_guide.cjs
    # đồng bộ sang data-hub
    cp app/static/docs/huong-dan/*.png app/static/docs/huong-dan/index.html \
       /home/vp/workspace/client/data-hub/app/static/docs/huong-dan/

## Lưu ý
- Sửa số bước trong `index.html` thì sửa cả `marks` trong `shoot_guide.cjs` (và ngược lại) — số phải khớp.
- Chưa commit (cả hai repo đang ở `main`; push `main` data-hub kích hoạt prod CD). Chờ user chốt commit/branch.
- Bản markdown cũ `docs/huong-dan-su-dung/README.md` + PDF vẫn giữ; trang HTML này là hình thức mới, cùng nội dung.
