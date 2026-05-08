-- 041_prune_payload_typed_keys.sql
--
-- Brief: ad-hoc per user 2026-05-08 — drop redundant keys from
-- payload jsonb after Tier 1 + 2 promotion (migs 039 + 040).
--
-- Before: parser stored EVERY source XLSX header in payload, including
-- ones already extracted into typed columns. ~38 redundant keys per
-- row. Wasted storage + slower jsonb scan.
--
-- After: payload contains ONLY tax-detail + free-text + audit keys
-- that don't have typed columns:
--   STT (per-file running number — audit)
--   Thuế suất XNK / VA / TV / BVMT / TTĐB (sparse tax rates)
--   Mã biểu thuế XNK
--   Tiền thuế XNK / VAT / TV / MT / TTĐB (sparse tax amounts)
--   Ghi chú (free-text notes)
--
-- Use jsonb `-` operator on text array to drop multiple keys at once.

begin;

update hub.bcct_rows
   set payload = payload - ARRAY[
     -- Identifiers + classification (typed since mig 005/010)
     'Số TK', 'STT hàng', 'Mã loại hình', 'Ngày ĐK',
     -- Material + description (mig 005)
     'Mã NPL/SP', 'Tên hàng', 'Mã HS',
     -- Quantity + unit (mig 005)
     'Tổng số lượng', 'Đơn vị tính',
     'Tổng số lượng 2', 'Đơn vị tính 2',
     -- Value/price/tax/currency (mig 039)
     'Đơn giá tính thuế', 'Đơn giá',
     'Tổng trị giá', 'Trị giá NT',
     'Đơn vị tiền tệ', 'Tổng tiền thuế', 'Địa điểm dỡ hàng',
     'Tỷ giá thanh toán',
     -- Misc identifiers (mig 005)
     'Xuất xứ', 'Số hóa đơn',
     -- 12 CO-essential typed columns (mig 010)
     'Tên doanh nghiệp', 'Mã doanh nghiệp', 'Tên đối tác',
     'Điều kiện giá hóa đơn',
     'Trọng lượng', 'Mã ĐVT trọng lượng',
     'Số lượng kiện', 'Mã ĐVT kiện',
     'Ngày hóa đơn', 'Ngày khởi hành vận chuyển',
     'Mã địa điểm đích', 'Tên địa điểm đích cho vận chuyển bảo thuế',
     'Mã hiệu PTVC',
     -- Tier 2 (mig 040)
     'Số hợp đồng', 'Ngày hợp đồng',
     'Số quản lý nội bộ', 'Ký hiệu và số hiệu bao bì'
   ]
where payload is not null and payload <> '{}'::jsonb;

commit;
