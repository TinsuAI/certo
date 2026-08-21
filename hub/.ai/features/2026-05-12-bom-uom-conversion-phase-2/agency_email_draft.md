# Email gửi agency Johnson — xác nhận đơn vị tính

**Mục đích:** thu thập factor quy đổi đơn vị tính (UoM) cho 220 mã
NPL/SP có khai báo BOM kỹ thuật và BCCT khác họ đơn vị, để Data Hub
quy đổi tự động khi quyết toán Mẫu 15a.

**Tệp đính kèm:** `agency_qa_johnson.xlsx` (gồm 5 tab + 1 hướng dẫn).

---

## Tiêu đề email

```
[Data Hub] Xác nhận đơn vị tính khác họ — Johnson — 220 mã
```

## Thân email (tiếng Việt)

```
Kính gửi anh/chị Johnson Health Tech Industry,

Trong quá trình tổng hợp dữ liệu BOM kỹ thuật (file SAP gửi ngày
06/05/2026) và đối chiếu với BCCT (BaoCaoHangChiTiet NK + XK,
06/05/2026) của Johnson, hệ thống Data Hub phát hiện 220 mã NPL/SP
được khai báo bằng đơn vị tính khác họ giữa 2 nguồn:

  • 176 mã: BOM khai 'EA' (chiếc) – BCCT khai 'SETS' (bộ)
  • 41 mã:  BOM khai 'EA' – BCCT khai 'CAY'
  • 3 mã:   BOM khai 'EA' – BCCT khai khối lượng (KILO-GRAMMES /
            METRIC-TONS)

Để hệ thống quy đổi đúng giữa BOM ↔ BCCT khi sinh báo cáo quyết
toán, kính nhờ anh/chị điền tỉ lệ quy đổi cho từng mã trong file
đính kèm. File đã có:

  • Tab 'Hướng dẫn' tóm tắt mục đích + cách điền.
  • 3 tab tương ứng 3 nhóm trên, mỗi mã đã kèm tên BOM (SAP) +
    tên BCCT + Mã HS để dễ đối chiếu.
  • Cột 'Quy đổi (Johnson điền)' để anh/chị nhập factor.
  • Cột 'Ghi chú' để giải thích nếu factor thay đổi tùy lô / tùy
    nhà cung cấp.

Sau khi nhận được file điền hoàn chỉnh, chúng tôi sẽ:
  1. Nạp factor vào hệ thống làm cơ sở quy đổi tự động.
  2. Re-ingest toàn bộ BOM + BCCT để phản ánh quy đổi đúng.
  3. Phát hành phiên bản BOM mới với UoM thống nhất theo catalog.

Trân trọng cám ơn,
[Tên người gửi]
[Vai trò]
Data Hub – Tinsu AI
```

## Câu hỏi phụ (nếu cần email follow-up sau)

Không gửi trong email đầu — chỉ dùng nếu Johnson có thắc mắc:

1. **EA↔SETS có thể thay đổi tùy thời điểm không?** Ví dụ tháng
   này 1 SETS gồm 4 chiếc, tháng sau gồm 6 chiếc. Nếu có, Data
   Hub cần ghi nhận factor theo phiên bản (effective_from /
   effective_to). Nếu factor ổn định lâu dài, mỗi mã 1 factor là
   đủ.
2. **CAY (cây) có ngữ cảnh đặc biệt nào không?** Ví dụ: nguyên
   liệu thanh dài 6m bán theo 'CAY', sau đó cắt nhỏ thành EA?
   Nếu có, ghi rõ chiều dài cây + chiều dài piece để Data Hub
   ghi nhận.
3. **Khối lượng bao bì** (gross weight) có khác khối lượng tịnh
   (net) không? Tab 3 EA→Mass: đề nghị điền theo khối lượng
   tịnh (chỉ NPL, không tính bao bì).

## Internal note

- **System-side fixes (KHÔNG hỏi agency):**
  - Vietnamese multi-meaning tokens (`Kiện/Hộp/Bao/Gói`,
    `Chai/Lọ/Tuýp`, `Thanh/Mảnh/Miếng`, `Viên/Hạt`, `SOI`) →
    `client_parser_rules` split per row context (HS code /
    goods_name heuristic).
  - `FT` (Steel Rope, mã `1000485239` + `1000491610`) → 100%
    confidence là feet (mô tả "Φ4.8x2500Ft"). Add canonical
    `('ft', 'length', 0.3048)` + alias `'FT'→'ft'`. Cả 2 mã đều
    là BTP-internal, không qua HQ → không ảnh hưởng settlement.
  - `CV` (PE Membrane, mã `0000096095`) → cũng BTP-internal, mã
    không có trong BCCT. Phỏng đoán "16 kg/box" từ mô tả; mark
    `has_uom_drift` để staff resolve sau nếu cần. Không ảnh
    hưởng settlement.
- Sau khi nhận factor: nạp vào `hub.client_uom_overrides` qua
  admin UI (Phase 2 step 7) hoặc bulk SQL nếu UI chưa sẵn.
- Email này không cần phản hồi gấp — block bulk re-ingest, không
  block development Phase 2 mig + flatten engine wiring.
