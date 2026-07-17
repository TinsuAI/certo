# Feature: Tài liệu hướng dẫn sử dụng CO + Data Hub (có screenshot)

**Date:** 2026-06-20 · **Type:** Documentation deliverable (no app code change)

## Mục tiêu
Soạn tài liệu hướng dẫn vận hành (tiếng Việt) cho nhân viên làm C/O, bao trùm **cả CO và Data Hub**,
có screenshot UI thật, minh hoạ bằng một **công ty demo hư cấu sạch**.

## Quyết định phạm vi (user chốt qua AskUserQuestion)
- Đối tượng/ngôn ngữ: **Nhân viên vận hành — Tiếng Việt**.
- Phạm vi: **Cả CO + Data Hub, có screenshot** (chạy cả 2 app).
- Dữ liệu: **Tạo công ty demo hư cấu sạch**.

## Đã làm
1. **Seed công ty demo** `Demo Furniture Co.` (`demo-furniture`, identity mode) vào DB Data Hub bằng
   `seed_demo_furniture.py` (nhân pattern `data-hub/app/seed.py:_seed_growatt`, dùng đúng parsers + `create_artifact`).
   - 8 NVL + 2 TP, 8 tờ khai nhập E11 + 2 tờ khai xuất E42, 2 BOM `manual_flat` (flat đầy đủ → picker CO nhận).
   - Idempotent (`--reset` xoá sạch theo client_id qua mọi bảng có cột client_id).
2. **Verify end-to-end trên CO** (`verify_co_flow.cjs`): công ty tự hiện trong CO (đọc live từ DH),
   tạo case → origin sheet (CHAIR01/TABLE01) → Load BOM → Tính (LVC 77–84%) → Chốt. PASS.
   - Phát hiện vận hành: công ty mới **phải refresh tồn CO 1 lần** (cold-start) trước khi Tính, nếu không
     NVL thiếu đơn giá → guard chặn Chốt (đúng thiết kế).
3. **Screenshot Data Hub** (`shoot_datahub.cjs` + `_extra`): login `admin@data-hub.local`/`admin123`,
   chụp clients (lọc), overview, catalog, BCCT, BOM list + detail, proposals → 8 ảnh.
4. **Screenshot CO** (`shoot_co.cjs` + `_finish`): full luồng 5 bước + tồn CO + create modal + substitute
   modal → 13 ảnh.
5. **Guide**: `docs/huong-dan-su-dung/README.md` (tiếng Việt) + `images/` (21 ảnh).

## Vị trí
- Tài liệu: `docs/huong-dan-su-dung/README.md` (+ `images/`).
- Tooling tái tạo: thư mục này (`seed_demo_furniture.py`, `verify_co_flow.cjs`, `shoot_datahub*.cjs`, `shoot_co*.cjs`).

## Lưu ý
- Công ty demo nằm trong **DB Data Hub** (`data_hub`), không trong git. Re-seed bằng lệnh ở mục 5 của guide.
- Trang lỗi graceful (404 styled) **không chụp được** qua GET URL sai (case/client không tồn tại ném 500 thô,
  `500s NOT caught` theo thiết kế) → mô tả bằng text trong guide thay vì ảnh.
- TABLE01 trong ảnh `co-11` ở trạng thái "Đã nạp BOM" (chưa chốt) → minh hoạ dashboard trạng thái hỗn hợp,
  cố ý giữ để dạy (1/2 chốt).
