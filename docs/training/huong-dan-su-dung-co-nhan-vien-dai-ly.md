# Hướng dẫn sử dụng C/O cho nhân viên đại lý

Tài liệu này dành cho nhân viên đại lý thủ tục hải quan trực tiếp lập hồ sơ cấp **Giấy
chứng nhận xuất xứ (C/O)** trên hệ thống C/O. Đây là **phần tiếp theo** của *Hướng dẫn sử
dụng Data Hub*: dữ liệu gốc (danh mục, mã quy đổi, BCCT, định mức BOM, tồn) được chuẩn bị
ở Data Hub trước; tài liệu này hướng dẫn dùng những dữ liệu đó để ra một bộ hồ sơ C/O hoàn
chỉnh. Đọc theo trình tự 5 bước của một hồ sơ; phần cuối có mục xử lý sự cố và bài tập thực
hành.

---

## 1. Hệ thống C/O là gì và quan hệ với Data Hub

Hệ thống C/O giúp lập **bộ hồ sơ chứng nhận xuất xứ theo từng lô hàng xuất**: từ định mức
sản phẩm và dữ liệu nhập khẩu, hệ thống lập **bảng kê** vật tư, tính **hàm lượng giá trị**
để xác định lô hàng có **đạt tiêu chí xuất xứ** hay không, rồi gom chứng từ thành dossier
để nộp.

C/O **đọc** dữ liệu từ Data Hub, **không sửa thẳng** dữ liệu gốc:

- Danh mục vật tư, **định mức BOM**, **BCCT** (tờ khai nhập/xuất), **tồn** — đều lấy từ
  Data Hub.
- Khi cần điều chỉnh BOM cho một hồ sơ, C/O **gửi đề xuất (proposal)** về Data Hub để đại
  lý duyệt (xem mục 7.7 và *HD Data Hub* mục 10.5), chứ không ghi đè BOM gốc.

Hệ quả thực hành quan trọng: nếu số liệu nguồn sai (thiếu mã, BOM lệch, tồn sai, tờ khai
thiếu file), hãy **sửa ở Data Hub rồi làm mới ở C/O** — đừng cố nắn số trên C/O. Chất lượng
dữ liệu ở Data Hub quyết định độ chính xác của C/O.

Một hồ sơ C/O đi qua **5 bước**:

1. **Lô hàng** — thông tin shipment, invoice, B/L, thị trường.
2. **Chứng từ** — upload B/L, Invoice/Packing và chứng từ bổ sung.
3. **Bảng kê C/O** — tính từng sheet, khớp tồn, tính LVC, chốt (bước nặng nhất).
4. **TKX / TKN** — đối chiếu tờ khai xuất/nhập từ Data Hub.
5. **Review & Xuất** — kiểm tra dossier và xuất file .zip tổng hợp.

---

## 2. Đăng nhập và giao diện chung

1. Mở địa chỉ C/O của đại lý (do Admin cấp).
2. Đăng nhập **dùng chung tài khoản với Data Hub** (cùng email + mật khẩu — đăng nhập một
   lần). Quên mật khẩu hoặc chưa có tài khoản → liên hệ Admin của đại lý.

Vai trò và quyền dùng chung với Data Hub (**Staff / Manager / Admin** — xem *HD Data Hub*
mục 2). Bạn chỉ thấy các công ty được phân công; nếu không thấy một công ty hay một menu,
thường là do quyền, không phải lỗi.

Khi một tác vụ nặng chạy nền xong (xuất dossier, làm mới tồn…), hệ thống **báo kết quả**
ngay trên trang — không cần ngồi chờ (xem mục 12).

---

## 3. Chọn công ty và hồ sơ

Mọi hồ sơ đều thuộc về một **công ty** cụ thể (cùng danh sách công ty với Data Hub). Một
**hồ sơ (case)** C/O tương ứng với **một lô hàng xuất** cần cấp C/O.

- **Đổi công ty** — bấm để mở bảng chọn công ty ngay tại chỗ (không rời trang); chọn công
  ty cần làm.
- **Đổi hồ sơ** — mở bảng chọn các hồ sơ của công ty đang xem.
- **Tạo hồ sơ C/O** — tạo hồ sơ mới; nhập thông tin lô hàng ban đầu (xem bước 1).

Hồ sơ đang xem được tô đậm trong bảng chọn để dễ định vị.

---

## 4. Tổng quan luồng 5 bước

Trên đầu trang hồ sơ luôn có **thanh tiến trình 5 bước**. Mỗi bước hiển thị trạng thái
hiện tại (xem mục 11), bấm để chuyển bước. Trình tự khuyến nghị đi theo đúng thứ tự 1 → 5,
vì các bước sau phụ thuộc bước trước:

- Bước **3 (Bảng kê)** cần đã có lô hàng (bước 1) để biết hóa đơn/sản phẩm nào.
- Bước **4 (TKX/TKN)** và **5 (Xuất)** chỉ có ý nghĩa **sau khi đã chốt bảng kê** ở bước 3.

Không bắt buộc làm xong tuyệt đối bước này mới sang bước kia, nhưng kết quả cuối (dossier)
chỉ đầy đủ khi cả 5 bước hoàn tất.

---

## 5. Bước 1 — Lô hàng

Khai thông tin lô hàng xuất của hồ sơ:

1. **Số hóa đơn (invoice)** và **số vận đơn (B/L)** — dùng để khớp với tờ khai và dữ liệu
   nhập ở Data Hub.
2. **Thị trường đến (market)** — quan trọng: thị trường quyết định **mẫu C/O gợi ý** (ví
   dụ EUR.1 cho EU, mẫu khác cho ASEAN…). Mẫu thực sự áp cho từng sheet được chọn ở bước 3.

Hệ thống dùng số hóa đơn/B/L để tìm các dòng nhập-xuất liên quan trong Data Hub, làm đầu
vào cho bảng kê.

---

## 6. Bước 2 — Chứng từ

Upload chứng từ của lô hàng. Có **7 ô tài liệu**:

- **3 ô bắt buộc**: Vận đơn (B/L), Hóa đơn (Invoice), Phiếu đóng gói (Packing list).
- **4 ô bổ sung**: các chứng từ kèm theo khi cần.

Thao tác:

- **Kéo-thả** một hoặc nhiều file vào ô; upload chạy ngay, có **thanh tiến độ**, không tải
  lại trang.
- Mỗi file hiện thành một chip (tên · dung lượng · nút xóa); xóa file sai ngay tại chỗ.
- Bộ đếm "**Bắt buộc N/3**" cho biết đã đủ chứng từ bắt buộc chưa.

Lưu ý: **file gốc tờ khai (TKX/TKN)** không nạp ở đây mà xử lý ở bước 4 / tại Data Hub.

---

## 7. Bước 3 — Bảng kê C/O

Đây là bước trọng tâm: lập bảng kê vật tư và xác định xuất xứ cho từng sản phẩm xuất.

### 7.1. Cách hoạt động

Mỗi **sản phẩm xuất là một sheet bảng kê** riêng. Các sheet được tính **tuần tự**: phải
**chốt** sheet trước thì mới tính/chốt được sheet sau. Các tab sheet nằm ở đáy màn hình
(giống các tab của một file Excel).

### 7.2. Load BOM

Bấm **Load BOM** để nạp cấu trúc vật tư của sản phẩm từ **định mức (BOM artifact) ở Data
Hub** — dùng bản đã **làm phẳng (flatten)**.

> Cảnh báo: bấm **Load BOM** lần nữa sẽ **nạp lại từ BOM gốc và GHI ĐÈ** bảng kê hiện tại —
> mọi chỉnh sửa (thêm/xóa/thay thế/sửa định mức), kể cả đã lưu, sẽ bị bỏ. Chỉ Load lại khi
> thực sự muốn làm mới từ đầu.

### 7.3. Tính bảng kê

Bấm **Tính bảng kê**. Hệ thống sẽ:

1. **Khớp từng vật tư với tồn** — tìm lô nhập khẩu (từ BCCT) tương ứng theo mã.
2. **Phân bổ trị giá** vật tư theo các lô đã khớp.
3. **Tính hàm lượng** — LVC (hàm lượng giá trị nội địa) hoặc RVC theo ngưỡng của mẫu (mặc
   định **30%**).
4. Kết luận: **Đạt LVC** hoặc **Tạm không đạt LVC**, kèm phần trăm cụ thể.

Phải **Tính bảng kê** lại mỗi khi chỉnh sửa NVL hoặc khi dữ liệu nguồn thay đổi (xem
nguyên tắc 4, mục 13).

### 7.4. Đọc bảng kê

- **Cột Mã** hiển thị **mã hải quan (HQ)** của lô đã khớp — đây là mã dùng để khai báo. Mã
  nội bộ (nếu khác) chỉ dùng để tra cứu.
- **Cột tồn / lô** cho biết vật tư được phân bổ từ lô nhập nào, số lượng bao nhiêu.
- **Cột xuất xứ** — mặc định mọi vật tư coi là **không có xuất xứ** (bảo thủ), tức tính vào
  phần giá trị nước ngoài; điều này làm LVC thấp đi (an toàn cho phát hành).
- **Cột tiêu chí** — tiêu chí xuất xứ áp cho dòng/sheet.

### 7.5. Tồn vật tư trên bảng kê

- "**Không có tồn**" trên một dòng nghĩa là vật tư đó **chưa khớp được lô nhập nào** — do mã
  trong BOM chưa có trong tồn, hoặc tồn chưa được làm mới. Xem mục 9 và phần xử lý sự cố.
- "**Vượt tồn**" nghĩa là nhu cầu của bảng kê lớn hơn tồn còn lại của lô.

Các dòng chưa khớp tồn sẽ được đánh dấu **cần đối soát**; nên xử lý hết trước khi chốt.

### 7.6. Chỉnh sửa bảng kê

Trên từng sheet có thể:

- **Thêm dòng** / **xóa dòng** vật tư (xóa là xóa mềm — dòng vẫn được giữ lại có đánh dấu để
  không làm lệch các dòng khác).
- **Thay thế (substitute)** một vật tư bằng lô/mã khác phù hợp.
- **Đổi tiêu chí** hoặc **ngưỡng LVC/RVC** cho sheet.
- **Chọn mẫu C/O (form)** cho sheet: ví dụ EUR.1 dùng phụ lục/PSR; các mẫu còn lại dùng
  LVC. Mẫu này chi phối tiêu chí và bản in xuất khẩu.

Sau mọi chỉnh sửa, bấm **Tính bảng kê** lại để cập nhật kết quả.

### 7.7. Đề xuất BOM mới (proposal)

Nếu cấu trúc vật tư thực tế của hồ sơ khác với BOM gốc ở Data Hub, bấm **Lưu BOM mới** để
gửi một **đề xuất** về Data Hub. C/O **không** sửa thẳng BOM gốc.

- Khi đã gửi, nút đổi thành **Đã propose ✓** và hiển thị mã artifact đề xuất.
- Đại lý vào **Data Hub → BOM → Đề xuất** để **duyệt / từ chối** (xem *HD Data Hub* mục
  10.5). Mọi quyết định được lưu vết.

### 7.8. Chốt bảng kê (lock)

Bấm **Chốt** khi sheet đã tính xong và kết quả đạt yêu cầu. Điều kiện chốt:

- Sheet đang ở trạng thái **đã tính** (không phải "cần tính lại").
- Đã xử lý các dòng **chưa khớp tồn** (cần đối soát).
- Chốt **theo thứ tự**: phải chốt các sheet trước đó rồi mới chốt sheet sau.

Chốt một sheet sẽ **giữ chỗ (claim) tồn** của các lô đã dùng, để hồ sơ khác không dùng
trùng. Cần sửa lại sheet đã chốt → bấm **Mở chốt** (claim sẽ được nhả ra).

---

## 8. Bước 4 — TKX / TKN

Sau khi chốt bảng kê, hệ thống truy vấn các **tờ khai xuất (TKX)** và **tờ khai nhập
(TKN)** liên quan đến lô hàng từ Data Hub.

- Danh sách cho biết tờ khai nào **thiếu file gốc**.
- File gốc tờ khai được quản lý ở **Data Hub → Tờ khai** (xem *HD Data Hub* mục 8). Bổ sung
  ở Data Hub rồi quay lại làm mới — C/O sẽ thấy file vừa thêm.

---

## 9. Tồn C/O

Tồn là số vật tư còn lại để bảng kê khớp vào. Một lô tồn được tính như sau:

> **tồn còn lại = tồn mở đầu − đã xuất (off-app) − các claim từ hồ sơ C/O**

- **Tồn mở đầu** lấy từ **BCCT của Data Hub** (dòng nhập khẩu).
- **Đã xuất off-app** chỉ áp dụng cho công ty nạp tồn từ **workbook trừ-lùi** của khách
  (số "đã xuất" được chốt sẵn ngoài hệ thống).
- **Claim** là phần tồn bị các hồ sơ C/O giữ chỗ khi **chốt** sheet; tự nhả khi mở chốt
  hoặc xóa hồ sơ.

Trên trang **Tồn C/O** có thể:

- Xem tồn theo từng lô và **lịch sử thay đổi của một lô**.
- **Làm mới từ Data Hub** — kéo BCCT mới nhất về (cập nhật tồn mở đầu).
- **Nạp tồn từ workbook trừ-lùi** — công cụ chuyển workbook trừ-lùi của khách sang template
  chuẩn rồi nạp (dành cho công ty chốt tồn ngoài hệ thống).

Lưu ý: số liệu tồn gốc thuộc Data Hub. Nếu tồn sai do dữ liệu nhập, sửa ở Data Hub
(BCCT) rồi làm mới.

---

## 10. Bước 5 — Review & Xuất

- **Review** — bảng tổng hợp tình trạng hồ sơ: các bước, các sheet đã chốt chưa, còn gì
  thiếu.
- **Xuất dossier (.zip)** — gom thành một file nén: chứng từ (bước 2) + tờ khai TKX/TKN
  (bản PDF ghép) + bảng kê hải quan của các sheet đã chốt.

Việc xuất chạy **nền**: bấm xuất → hệ thống xử lý → tải về khi xong (không cần chờ trên
trang). Nếu dữ liệu hồ sơ thay đổi sau khi đã xuất, hệ thống nhận biết bản dossier cũ và
nhắc **xuất lại**.

---

## 11. Trạng thái hồ sơ và sheet

**Trạng thái mỗi bước** (trên thanh tiến trình):

- **Chưa làm** (xám) — chưa bắt đầu.
- **Đang làm** (xanh dương) — đang xử lý dở.
- **Cần soát** (vàng) — có việc cần chú ý (ví dụ còn dòng chưa khớp, sheet cần tính lại).
- **Đã xong** (xanh lá) — hoàn tất (ví dụ "Đã chốt N/N" ở bước bảng kê).

**Trạng thái mỗi sheet bảng kê**:

- **Nháp** → **Đã nạp BOM** → **Đã tính** → **Đã chốt**.
- **Cần tính lại** — khi dữ liệu nguồn (tồn, BOM, danh mục) đã đổi sau lần tính gần nhất.
  Sheet "cần tính lại" **không chốt được** cho tới khi tính lại.

---

## 12. Tác vụ nền

Một số việc có thể chạy lâu, đặc biệt với công ty nhiều dữ liệu:

- **Mở bảng kê lần đầu** cho một hồ sơ mới — cần nạp dữ liệu nguồn từ Data Hub (lần sau
  nhanh hơn vì đã có sẵn).
- **Làm mới tồn** từ Data Hub.
- **Xuất dossier**.

Những việc này chạy nền: cứ làm việc khác, hệ thống báo kết quả khi xong. Không cần ngồi
chờ trên trang.

---

## 13. Năm nguyên tắc cần nhớ

1. **Tính và chốt tuần tự.** Mỗi sản phẩm là một sheet; phải tính rồi chốt theo thứ tự —
   chốt sheet trước mới sang sheet sau.
2. **Sửa BOM = gửi đề xuất về Data Hub.** C/O không ghi đè BOM gốc; đề xuất được đại lý
   duyệt ở Data Hub.
3. **Số liệu nguồn đọc từ Data Hub.** Tồn, BOM, BCCT, tờ khai sai thì sửa ở Data Hub rồi
   làm mới ở C/O, không nắn số trên C/O.
4. **"Cần tính lại" thì phải tính lại trước khi chốt/xuất.** Số liệu tính từ dữ liệu cũ có
   thể sai — ví dụ một sheet chưa khớp được tồn có thể hiện "đạt 100%" giả; tính lại mới ra
   con số thật.
5. **Mã trên bảng kê là mã hải quan (HQ).** Mã nội bộ chỉ để tra cứu, không phải mã khai báo.

---

## 14. Xử lý sự cố thường gặp

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Nhiều dòng "Không có tồn" | Mã trong BOM chưa khớp tồn, hoặc tồn chưa làm mới | Làm mới tồn từ Data Hub; nếu vẫn thiếu, kiểm BOM/danh mục/mã quy đổi ở Data Hub rồi tính lại |
| Báo "Vượt tồn ở N lô" | Nhu cầu bảng kê lớn hơn tồn còn lại của lô | Kiểm định mức và đối chiếu tồn; thay thế bằng lô khác nếu cần |
| Sheet ở trạng thái "Cần tính lại" | Dữ liệu nguồn đổi sau lần tính gần nhất | Bấm **Tính bảng kê** lại |
| LVC "đạt 100%" nhưng nhiều dòng không có tồn | Bảng kê tính khi gần như không khớp tồn (số ảo) | Làm mới tồn + **Tính bảng kê** lại; chỉ tin con số sau khi đã khớp tồn |
| Không bấm được **Chốt** | Chưa tính / sheet trước chưa chốt / còn dòng chưa khớp tồn | Tính xong, chốt các sheet trước, xử lý dòng cần đối soát |
| Tờ khai báo "thiếu file" | File gốc TKX/TKN chưa có ở Data Hub | Bổ sung file ở **Data Hub → Tờ khai** rồi làm mới |
| Bấm **Load BOM** xong mất hết chỉnh sửa | Load BOM ghi đè bảng kê từ BOM gốc | Chỉ Load lại khi muốn làm mới hoàn toàn; nếu chỉ muốn cập nhật, dùng **Tính bảng kê** |
| Mở bảng kê lần đầu rất chậm | Đang nạp dữ liệu nguồn từ Data Hub | Chờ hoặc làm việc khác; các lần sau nhanh hơn |
| Xuất dossier "đứng" | Đang chạy nền | Để chạy nền; hệ thống báo khi xong |

---

## 15. Bài tập thực hành

Gợi ý một lượt làm quen end-to-end (sau khi dữ liệu công ty đã sẵn ở Data Hub):

1. **Tạo hồ sơ C/O** cho một lô hàng; nhập số hóa đơn, B/L, thị trường (bước 1).
2. Upload đủ **3 chứng từ bắt buộc** (B/L, Invoice, Packing) ở bước 2.
3. Vào **Bảng kê C/O**: **Load BOM** → **Tính bảng kê** cho sheet đầu; đọc LVC và cột tồn.
4. Thử **thay thế** một vật tư hoặc **xóa** một dòng, **Tính bảng kê** lại, quan sát LVC đổi.
5. **Chốt** sheet đầu; sang sheet kế và làm tương tự.
6. Sang **Review & Xuất**, **xuất dossier .zip** và mở ra xem các thành phần.

Tài liệu liên quan:

- *Hướng dẫn sử dụng Data Hub cho nhân viên đại lý* — chuẩn bị dữ liệu nguồn (danh mục,
  BOM, BCCT, tồn) trước khi làm C/O: `huong-dan-su-dung-nhan-vien-dai-ly.md`.
