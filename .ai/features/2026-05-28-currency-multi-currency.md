# Feature: Multi-currency on origin sheet — per-row FX with customs fallback + realtime toggle

Source request (Vietnamese, paraphrased): hiện tab Bảng kê C/O luôn coi mọi giá trị là VND.
Trên thực tế CO là cho hàng xuất khẩu, đơn hàng thường ở ngoại tệ (USD…). Mỗi
dòng tồn (BCCT row) lấy theo nguyên tệ + tỷ giá tại ngày nhập khẩu lưu trên dòng;
nếu thiếu thì fallback sang "Tỷ giá HQ" của ngày đó. Toggle Nguyên tệ / VND trên
origin sheet phải phản ánh real-time (không reload).

## Current gap (audited 2026-05-28)

Hạ tầng đã có nhưng **chuỗi quy đổi chưa được nối**:

| Layer | Trạng thái |
|------|-----------|
| Toggle UI (`currency_mode` ở `co_case.html`) | persist OK vào `origin_sheet_states[product_code]` |
| Renderer / table render | KHÔNG đọc `currency_mode` — luôn hiển thị `unit_value` như-có |
| `customs_fx_store.lookup_exchange_rate(currency, date)` | tồn tại, chưa bao giờ được gọi từ pipeline tính giá NVL |
| `co_stock_rows.payload` | có `currency`, KHÔNG có `exchange_rate` per dòng |
| `bang_ke_renderer.py` + `bang_ke_xml_generator.py` | `_decimal(product.get("fob"))` không hỏi đơn vị, không quy đổi |
| `stock_allocation_line()` (`main.py:3457-3505`) | trả `unit_value` as-is theo nguyên tệ allocation, không quy đổi |
| `origin_material_from_bom_row()` (`main.py:3284-3422`) | gán `currency` từ allocation/stock/material, không có VND-mode |
| `cost_allocation` coefficient × FOB | giả định FOB cùng đơn vị với hệ số (thực tế không xác định) |

Kết quả: khi user chọn "VND" trên toggle, page persist setting nhưng không có gì
xảy ra. Khi user chọn "Nguyên tệ", page hiển thị whatever came từ BCCT — vô tình
đúng cho hầu hết case VN BCCT vì BCCT lưu sẵn VND, nhưng sai khi NVL nhập có giá
USD.

## Scope

In:
- **Per-row FX rate** trên `co_stock_rows`: thêm field `payload.exchange_rate_to_vnd`
  + `payload.exchange_rate_source` (`bcct_declared` / `customs_lookup` / `missing`).
  Materializer chịu trách nhiệm điền — đọc từ BCCT row nếu có, fallback sang
  `customs_fx_store.lookup_exchange_rate(currency, declaration_date)` nếu thiếu.
- **Lookup fallback** ở `customs_fx_store`: đã có hàm, gọi với `(currency_code,
  effective_date=declaration_date)`. Trả `None` thì đánh dấu `missing` để UI cảnh báo.
- **Allocation pipeline**: `stock_allocation_line()` trả thêm `unit_value_vnd` (=
  `unit_value × fx_rate` nếu currency ≠ VND, else = unit_value).
- **Material builder**: `origin_material_from_bom_row()` gắn cả `unit_value_native`
  + `unit_value_vnd` + `material_value_native` + `material_value_vnd` lên material
  object. Currency string vẫn giữ nguyên tệ.
- **Renderer Approach A** (`bang_ke_xml_generator.py`) + **Approach B**
  (`bang_ke_renderer.py`): nhận `currency_mode` từ `origin_sheet_states[product_code]`
  qua context. Khi `vnd`: dùng `unit_value_vnd` + footer FOB đã quy đổi. Khi `native`:
  dùng `unit_value_native` (giữ behavior hiện tại với cảnh báo "currency unset" khi
  FOB không có currency).
- **Realtime toggle (frontend)**: thay vì chỉ persist + chờ reload, JS đọc cả 2 bộ
  giá trị từ hidden inputs (`data-base-unit-value-native` + `data-base-unit-value-vnd`)
  và swap text khi `currency_mode` đổi. Lock metrics live recompute (LVC/VNM)
  trên client side.
- **FX source badge** trên mỗi dòng: chip nhỏ ở cột "Nguồn" cho biết FX đến từ
  BCCT-declared / customs-lookup / missing (warning).
- **FOB currency**: thêm trường `product.fob_currency` (mặc định `product.currency`).
  Renderer in cùng FOB block. Khi `currency_mode = vnd`: in `fob × fx_at_invoice_date`
  từ customs store (single rate; case-level).

Out (phase 2 nếu cần):
- Re-compute LVC theo công thức build-up (FOB - VNM) / FOB với VND base — phase 1
  chỉ visual swap (LVC math luôn chạy bằng cùng đơn vị giữa FOB và VNM ở phía
  server; client-side swap chỉ đổi display, không đổi engine math).
- Multi-currency case (TP có FOB USD + EUR cùng 1 case). Phase 1: 1 case = 1 export
  currency.
- Lưu lịch sử FX dùng cho từng case (snapshot). Phase 1 luôn dùng FX live tại
  thời điểm calculate; re-calculate khi FX rate thay đổi.
- Migrate dữ liệu cũ. Forward-only: case tính trước migration tiếp tục hoạt động
  với `exchange_rate_source = missing` → render mode `native` only.

## Decisions (proposed, cần confirm)

1. **Quy đổi xảy ra tại `stock_allocation_line`** thay vì tại renderer. Lý do: cost-allocation
   coefficient (Phase 1 hiện tại) cũng đọc `product.fob` — phải quyết định 1 đơn vị
   nền tảng. Build-down LVC dùng VND base ổn định hơn vì FX biến động.
2. **Phase 1 ngầm**: persist FX `exchange_rate_to_vnd` ở `co_stock_rows.payload` mỗi
   lần materializer refresh. Không thêm column SQL — JSONB payload đủ. Index không
   cần.
3. **Realtime toggle = client-side**: server render cả 2 bộ giá trị vào hidden
   inputs; JS swap khi user đổi `currency_mode`. Không API call. Sau cùng khi
   user "Lưu cấu hình" thì persist `currency_mode` để lần sau page load đúng mode.
4. **FX lookup miss handling**: nếu BCCT row không có FX + customs store cũng
   không có rate cho ngày đó → đánh dấu `missing`, để `exchange_rate_to_vnd = 1`
   (= treat as VND) + log warning. UI hiện chip cảnh báo trên dòng.
5. **Backwards compat**: case state cũ chưa có FX → engine vẫn render `native`
   mode. Khi user toggle `vnd` lần đầu: trigger refresh materializer cho client →
   FX field populated → reload → mode vnd hoạt động.
6. **`fob_currency`**: nullable; default = `product.currency`. Case nào không có
   currency thì show "—" + cảnh báo. Không enforce.

## Risk

- **HIGH — engine semantics drift**: hiện tại LVC math chạy với mixed-currency số liệu
  (FOB có thể USD, NVL có thể VND) — phép trừ (FOB − VNM) ra số vô nghĩa nhưng KHÔNG
  ai phát hiện vì cả 2 side đều "có vẻ hợp lý". Sau khi quy đổi đúng, LVC% của
  case cũ có thể nhảy ±10-30%. Bắt buộc snapshot LVC trước/sau với 5-10 case thật
  + review với agency trước khi ship.
- **MED — bảng kê HQ export đã in chính thức** đang gặp same issue. Khi quy đổi
  đúng, các bảng kê đã in/nộp có thể không khớp với engine mới. Đưa ra "fix
  ngày X" để cắt mốc; xuất trước ngày X dùng engine cũ.
- **MED — customs FX refresh không tự động**: `customs_exchange_rate_rows` chỉ
  được refresh khi user bấm nút trên admin page. Nếu user materialize stock vào
  thứ Sáu nhưng customs FX cập nhật cuối tuần → FX dùng là rate cũ. Cần guidance
  cho operator + dấu hiệu UI cho biết FX dùng là rate của ngày nào.
- **LOW — `co_stock_rows.payload` swell**: thêm 2 field × ~60k rows × ~30 bytes
  ≈ 3 MB. Negligible.
- **LOW — UI complexity**: chip "Nguồn FX" thêm vào cột "Nguồn" có sẵn — overhead
  visual nhỏ, có thể ẩn mặc định.

## Open questions (need user confirm)

1. **FX date semantics**: cho NVL nhập 2024 nhưng case xuất 2026, dùng FX của
   ngày nhập hay ngày xuất? Audit nói "ngày nhập khẩu của dòng đó" — confirm.
2. **FOB currency cho export**: ngày invoice xuất hàng hay ngày tờ khai xuất?
3. **Tỷ giá HQ là tỷ giá nào**: weekly customs rate hay daily? Hiện
   `customs_exchange_rate_rows` lưu `effective_date` per rate — schema đã đủ
   cho daily, nhưng customs.gov.vn publish theo tuần.
4. **Reset behavior khi đổi market**: hiện override (form/criteria/threshold)
   không reset khi market đổi (per `[[override-persistence]]`). Currency mode
   nên đi theo nguyên tắc nào? Mặc định gợi ý: giữ override (consistent).
5. **Cost-allocation hệ số × FOB**: hệ số coefficient đang là unit-less. Nếu FOB
   đổi đơn vị USD → VND, kết quả phải đổi đơn vị tương ứng. Confirm rằng coefficient
   không bị stale (vẫn áp đúng được cho VND base).

## Implementation order (proposed)

1. Schema: thêm 2 field vào `co_stock_rows.payload`. Cập nhật materializer.
2. `customs_fx_store.lookup_exchange_rate` wrapper với caching per-request.
3. `stock_allocation_line` + `origin_material_from_bom_row` populate dual values.
4. Template: hidden inputs `data-base-*-native` + `data-base-*-vnd`. JS swap on
   `currency_mode` change.
5. Renderer A + B: nhận `currency_mode` từ context, dùng `*_vnd` khi mode `vnd`.
6. FX source badge ở cột "Nguồn".
7. Snapshot tests + manual screenshot trên 5 case thật trước khi bật default.

## Acceptance

- Toggle Nguyên tệ ↔ VND trên 1 sheet đổi text các cột Đơn giá / Trị giá NVL /
  KXX/VNM ngay lập tức không reload.
- Bảng kê HQ export với `currency_mode = vnd`: cell FOB + cột Trị giá đúng VND;
  với `native`: cell FOB + cột Trị giá đúng nguyên tệ (USD/EUR/…).
- Dòng NVL có FX `missing`: chip warning + giá hiển thị nguyên tệ luôn (no fallback
  to "1" silently).
- LVC% snapshot trước/sau migration được review với agency cho ≥5 case thật.

## Files affected

- `db/migrations/` — không cần (payload-only)
- `app/co_stock_materializer.py` — populate FX fields lúc refresh
- `app/customs_fx_store.py` — đã có lookup; thêm cache wrapper
- `app/main.py:3284-3505` — `stock_allocation_line`, `origin_material_from_bom_row`
- `app/bang_ke_xml_generator.py` — accept `currency_mode`, use `*_vnd` cells
- `app/bang_ke_renderer.py` — same
- `app/workbook_io.py` — pass `currency_mode` through to renderer
- `app/templates/co_case.html` — hidden inputs + JS swap logic
- `app/static/css/app.css` — `.origin-fx-chip-*` warning style
