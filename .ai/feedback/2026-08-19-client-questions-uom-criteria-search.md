# Phản hồi khách 2026-08-19 — ĐVT, tiêu chí, chốt tất cả, tìm NVL

Nguồn: 6 câu hỏi/ảnh của Thanh Tâm trên hồ sơ johnson-vn (VNG26030079 / VNG26030107).
Phần **Trả lời gửi khách** ở cuối có thể chuyển thẳng cho khách.

---

## Tổng kết kỹ thuật

| # | Khách báo | Kết luận | Trạng thái |
| --- | --- | --- | --- |
| 1 | Sau khi upload BOM + BCCT còn phải sửa ĐVT nữa không | CO **không đọc được** 516 hệ số quy đổi mà khách đã nhập bên Data Hub (`hub.client_uom_overrides`) — Data Hub chưa có API `/v1/hub` cho bảng này | Yêu cầu API đã viết, **chờ Data Hub duyệt**; CO-side đã làm phần tạm |
| 2 | Ô nhập tiêu chí là form gõ tay | Đúng — `window.prompt()` tự do; gõ sai chữ thì engine không nhận ra tiêu chí nào | **Đã sửa**: cửa sổ chọn bằng nút, giống ⚙ Cấu hình bảng kê |
| 3 | Chọn tiêu chí xong phải F5 | Đúng — route lưu xong chỉ hiện toast, không render lại | **Đã sửa**: tự cập nhật tại chỗ (cả ⚙ Cấu hình và hệ số ĐVT) |
| 4 | Tổng hợp NVL báo đủ tồn nhưng các bảng kê vẫn "Cần tính lại" | **Không phải lỗi ĐVT.** Thay/xoá NVL hàng loạt đánh dấu mọi sheet phía sau là stale nhưng chỉ tính lại sheet vừa sửa | **Đã sửa**: tính lại mọi sheet bị ảnh hưởng |
| 5 | "Chưa thể quy đổi ĐVT" | Cùng gốc với #1 — CO không có hệ số nên chặn Chốt | **Đã sửa phần CO**: cửa sổ xác nhận có chọn phạm vi |
| 6 | Tìm NVL thay thế không ra hết | Server trả tối đa **20** kết quả; lọc theo tồn dùng so khớp nguyên cụm, có dấu | **Đã sửa**: 200 kết quả, so khớp theo từ, không dấu cũng ra |

---

## #1 + #5 — ĐVT (phần chưa xong nằm ở Data Hub)

**Đo được:**
- Data Hub johnson-vn có **516 hệ số** ở `/clients/johnson-vn/uom-factors` (bảng `hub.client_uom_overrides`, migration 055), gồm `EA → CAY`, `ROLL → PIECES`.
- Data Hub chỉ expose bảng này qua **giao diện admin HTML**, không có endpoint `/v1/hub/*` nào đọc được (`app/routes/client_uom_factors.py`).
- CO giữ kho riêng `co_uom_factor` (`app/uom_factor_store.py`), hiện **trống** cho johnson-vn → mọi cặp khác đại lượng đều rơi vào `unconfirmed` và chặn Chốt.

**Quy ước hệ số hai bên trùng nhau** (đây là điểm dễ đảo ngược nhất): Data Hub ghi
`số lượng (Sang) = số lượng (Từ) × hệ số`; CO cũng cần đúng hệ số biến lượng BOM thành
lượng theo ĐVT tờ khai. Nên `from_uom → bom_uom`, `to_uom → lot_uom`, không phải nghịch đảo.

**Đã làm:** `.ai/api-requests/2026-08-19-client-uom-factors-read.md` — hợp đồng
`GET /v1/hub/clients/{client_id}/uom-factors`, scope `hub:read`, gồm phân trang, độ chính
xác (factor là **chuỗi** thập phân, không phải float), test phía Data Hub và kế hoạch tiêu
thụ ở `app/data_hub_client.py`. **Chưa implement phía CO** — theo quy tắc dự án phải có
Data Hub duyệt hợp đồng trước.

**Đã làm ngay ở CO (không phải chờ):**
- Nút trên dòng đổi từ `⇄ CAY?` thành **"Cần hệ số EA→CAY"** — nói thẳng việc phải làm.
- Bấm vào mở cửa sổ hỏi đúng một câu **"1 CAY = mấy EA"**, có chọn phạm vi
  **chỉ mã này** / **mọi mã có cặp EA → CAY**. Trước đây route luôn ghi phạm vi "chỉ mã này"
  dù kho đã hỗ trợ dòng client-wide → khách phải xác nhận lại từng mã.
- Bỏ nhãn `⇄ PIECES` trên các dòng **không quy đổi gì**. EA / PIECES / CÁI là một đơn vị
  viết khác nhau (hệ số 1), nên nhãn đó đang xuất hiện trên 145 dòng của một sheet Johnson
  mà không có gì để làm. Nay chỉ hiện khi (a) thiếu hệ số, hoặc (b) số lượng thật sự đã đổi.

---

## #4 — "Đủ tồn" nhưng sheet vẫn "Cần tính lại"

Tồn được trừ **tuần tự** theo thứ tự sheet, nên sửa sheet 1 làm đổi phần còn lại cho sheet
2..N — `mark_origin_sheets_stale` đã chuyển tất cả sang "Cần tính lại". Nhưng hai route
`bulk-substitute` và `bulk-delete-rac` chỉ gọi `recalculate_origin_sheet_and_status` cho
**sheet vừa sửa**. Trong khi đó bảng "Tổng hợp NVL" chạy `allocate_whole_case_preview` mới
toàn bộ nên báo "Đủ tồn cho tất cả SP". Hai bề mặt đọc hai nguồn khác nhau.

Sửa: `origin_codes_to_recalculate()` trả về **mọi sheet từ vị trí sửa trở đi**, trừ sheet đã
chốt (sheet đã chốt giữ nguyên số liệu đã nộp; ledger đang giữ `co_stock_claims` theo đúng
các dòng phân bổ đó).

**Phát hiện kèm theo (đã sửa luôn):** "Tính tồn tất cả (SP)" ghi đè **cả sheet đã chốt** —
`allocate_whole_case_preview` dựng lại mọi sản phẩm, rồi route đóng dấu trạng thái cho từng
sản phẩm, tức là mở chốt âm thầm trong khi ledger vẫn giữ claim cũ. Nay sheet đã chốt được
giữ nguyên cả snapshot lẫn trạng thái.

---

## #2 + #3 — Tiêu chí

`window.prompt()` với ô text tự do được thay bằng cửa sổ dùng **đúng bộ nút của ⚙ Cấu hình
bảng kê**: WO · PE · CC · CTH · CTSH · RVC · LVC · PSR + "Khác…", hàng "hoặc" để ghép tiêu chí
thứ hai, ô **Ngưỡng %** chỉ hiện với RVC/LVC. Chuỗi ghi ra đặt tiêu chí chính lên đầu
("CTH hoặc RVC 40%") đúng như engine đọc.

Lưu xong màn hình tự dựng lại tại chỗ (fetch shell + swap) thay vì `window.location.reload()`
hoặc không làm gì. Áp cho cả ⚙ Cấu hình bảng kê (Lưu + Reset) và hệ số ĐVT.

**Lỗi phát hiện thêm:** "Bỏ chọn" chưa bao giờ hoạt động — route `pop("criteria_choice")`
khỏi dict, nhưng `update_case_record` chỉ copy các key **có mặt** trong case gửi vào, nên bản
lưu vẫn còn nguyên. Nay ghi `{}`.

---

## #6 — Tìm NVL thay thế

Client không gửi `limit` → server mặc định 20 (`min(limit, 50)`). Ngoài ra nhánh
"stock-first" lọc bằng so khớp **nguyên cụm, có dấu** nên "bu lông" trượt mọi tên có chữ chen
giữa, và "bu long" không dấu thì trượt hết.

Sửa: client gửi `limit=200`, server nới trần lên 200, và `build_stock_first_candidates` dùng
đúng luật của `material_search.match_score` (tách từ, bỏ dấu, AND theo từ / OR theo trường).

Đo trên johnson-vn `co-case-e0b390ead3b0`, sheet MFW0525-39:

| truy vấn | trước | sau |
| --- | --- | --- |
| `bu lông` | 21 | **192** |
| `bu long` (không dấu) | — | **192** |
| `bo oc vit bu long` | — | **111** |

Danh sách xếp **mã có tồn lên trước, tồn nhiều hơn xếp trên** (0000093519 · tồn 102.708 …),
và có dòng đếm "N NVL khớp …" phía trên.

---

## Trả lời gửi khách (tiếng Việt, có thể forward)

**1 + 5. Về đơn vị tính (ĐVT)**

Hiện tại **có**, vẫn phải xác nhận thêm ở Barry CO, và đây là điểm chúng tôi đang xử lý.
Các hệ số quy đổi anh/chị đã nhập bên Data Hub (516 dòng, ví dụ `EA → CAY`, `ROLL → PIECES`)
thì **Barry CO chưa đọc được** — Data Hub hiện mới có màn hình quản trị cho bảng này, chưa có
API để CO gọi sang. Chúng tôi đã gửi yêu cầu bổ sung API cho phía Data Hub; khi xong thì hệ số
nhập một lần bên Data Hub sẽ tự áp cho mọi hồ sơ C/O, không phải khai lại.

Trong lúc chờ, xin lưu ý là **không phải ĐVT nào cũng cần khai**:
- Cùng một đơn vị viết khác nhau (EA / PIECES / CÁI, BỘ / SET, CUỘN / ROLL): hệ thống tự hiểu,
  không hỏi.
- Cùng họ đo lường (KG → G, M → CM): hệ thống tự quy đổi.
- Chỉ những cặp **khác đại lượng** (ví dụ EA ↔ CAY, EA ↔ SETS) mới cần người xác nhận, vì
  "1 CAY là mấy EA" là thông tin về vật tư chứ không phải về đơn vị.

Từ bản này, khi gặp cặp cần khai, dòng NVL sẽ hiện nút **"Cần hệ số EA→CAY"**. Bấm vào, cửa sổ
hỏi đúng một câu "1 CAY = mấy EA", và cho chọn áp cho **chỉ mã đó** hay **mọi mã dùng cặp
EA → CAY**. Chọn phương án thứ hai là gỡ hết các dòng cùng loại trong một lần.

Chúng tôi cũng đã bỏ nhãn "⇄" trên các dòng **không có gì để quy đổi** — trước đây nó hiện trên
hàng trăm dòng mà số lượng không hề thay đổi, gây rối.

**2. Chọn tiêu chí**

Đã đổi thành **chọn bằng nút**, đúng như cửa sổ "Cấu hình bảng kê" của từng bảng kê con:
WO · PE · CC · CTH · CTSH · RVC · LVC · PSR, có ô "hoặc" để ghép tiêu chí thứ hai, và ô
"Ngưỡng %" tự hiện khi chọn RVC/LVC. Không còn ô gõ tay (vẫn giữ nút "Khác…" cho trường hợp
cần ghi nguyên văn một quy tắc đặc thù).

Xin trả lời rõ câu "AI có tự hiểu không": **hệ thống không tự chọn tiêu chí thay anh/chị**, và
trước đây nếu gõ tay sai chữ thì hệ thống **không** nhận ra đó là tiêu chí nào — số LVC và ô CTC
chỉ là đối chiếu tham khảo của chính tiêu chí đã chọn. Chọn bằng nút loại bỏ đúng rủi ro này.

**3. Không phải F5**

Đã sửa. Lưu tiêu chí cho cả lô, lưu/Reset "Cấu hình bảng kê", lưu hệ số ĐVT — màn hình tự cập
nhật ngay (trạng thái sheet, chip tiêu chí, LVC/CTC), không cần tải lại trang.

**4. "Đủ tồn" nhưng các bảng kê vẫn báo "Cần tính lại"**

Đây **không phải** lỗi ĐVT. Tồn được trừ lần lượt theo thứ tự bảng kê, nên khi thay NVL ở bảng
kê đầu thì các bảng kê sau cũng phải tính lại — nhưng hệ thống chỉ tính lại đúng bảng kê vừa
sửa, trong khi màn hình "Tổng hợp NVL" lại tính thử toàn bộ lô nên báo "Đủ tồn". Đã sửa: thay
hoặc xoá NVL hàng loạt nay tính lại **mọi bảng kê bị ảnh hưởng**, nên sau khi "Tổng hợp NVL"
báo đủ tồn thì "Chốt tất cả" chốt được ngay.

Kèm theo, chúng tôi phát hiện và sửa một lỗi nặng hơn: "Tính tồn tất cả (SP)" trước đây tính
lại **cả bảng kê đã chốt** và mở chốt nó âm thầm. Nay bảng kê đã chốt giữ nguyên số liệu đã nộp.

**6. Tìm NVL thay thế**

Đã sửa. Ô "Tìm kiếm" nay trả về tới **200** mã (trước là 20), có dòng đếm "N NVL khớp …", và
**mã còn tồn được xếp lên trước, tồn nhiều hơn xếp trên** để anh/chị so được lượng tồn ngay
trên danh sách. Tìm "bu lông" ra đủ cả "Bu lông…", "Bộ bu lông…", "Bộ ốc vít, bu lông…"; gõ
không dấu ("bu long") cũng ra. Trên hồ sơ Johnson, cùng một truy vấn "bu lông" trước ra 21 mã,
nay ra 192 mã.
