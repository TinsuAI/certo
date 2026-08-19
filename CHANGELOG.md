# Changelog

Nhật ký thay đổi của Barry CO dành cho người dùng. Định dạng theo
[Keep a Changelog](https://keepachangelog.com/vi/); chỉ ghi thay đổi có ảnh
hưởng tới người dùng (bỏ qua refactor nội bộ, hạ tầng test). Phiên bản theo
[SemVer](https://semver.org/lang/vi/).

## [0.18.0] — 2026-08-19
### Mới
- **Số lẻ hiển thị của Đơn giá / Trị giá đặt được cho từng bảng kê** (⚙ Cấu hình → **Số lẻ**). Mặc định **"Theo tiền tệ"**: dòng khai bằng **VND thì không có số lẻ** (83.634 thay vì 83.634,102869), ngoại tệ giữ 6 số cho đơn giá và 2 cho trị giá. Dòng có giá trị quá nhỏ (ví dụ đơn giá 0,078 VND) vẫn hiện đủ chữ số — không bao giờ bị rút thành "0", vì "0" là cách hệ thống báo *thiếu đơn giá*. Đây là **cài đặt màn hình**: file xuất giữ nguyên số và theo định dạng của mẫu bảng kê HQ.
### Cải tiến
- **Lưu cấu hình là bảng kê tự tính lại**, không phải nhớ bấm "Tính bảng kê" nữa. Đổi tiêu chí / ngưỡng / hiệp định / chiều tối ưu ở ⚙ Cấu hình, hoặc chọn tiêu chí cho cả lô, thì các bảng kê liên quan tính lại ngay và ô LVC, CTC cập nhật theo đúng tiêu chí vừa chọn. (Trước đây bảng kê vẫn ghi "Đã tính" trong khi ô đạt/không đạt còn tính theo tiêu chí cũ.) Đổi **Tiền tệ** hoặc **Số lẻ** thì không cần tính lại — số không đổi, chỉ đổi cách hiển thị.
- **Bỏ nhãn "(VND)" khỏi lựa chọn "Nguyên tệ"**: nay ghi **"Nguyên tệ (theo tờ khai)"**. Chữ trong ngoặc trước đây là tiền tệ FOB của riêng bảng kê đó, trong khi các dòng NVL đến từ nhiều tờ khai và có thể khác tiền tệ — đọc thành "nguyên tệ nghĩa là VND", ngược hẳn ý nghĩa.
- Dòng trong danh sách **Review** ghi rõ tiêu chí đang theo **lô hàng** / **riêng sheet này** / **khuyến nghị**; trước đây chọn tiêu chí cho cả lô xong mọi dòng vẫn ghi "khuyến nghị".

## [0.17.0] — 2026-08-19
### Mới
- **Chọn tiêu chí xuất xứ bằng nút, không gõ tay**: "Tiêu chí cho cả lô" nay mở một cửa sổ có sẵn các nút WO · PE · CC · CTH · CTSH · RVC · LVC · PSR (thêm "Khác…" nếu cần ghi nguyên văn), ô "hoặc" để ghép tiêu chí thứ hai, và ô Ngưỡng % tự hiện khi chọn RVC/LVC — đúng như cửa sổ **⚙ Cấu hình** của từng bảng kê. Trước đây đây là ô nhập tự do, gõ sai chữ là hệ thống không nhận ra tiêu chí nào.
- **Xác nhận hệ số quy đổi ĐVT trong cửa sổ, chọn được phạm vi**: khi ĐVT trên tờ khai nhập khác ĐVT trong BOM, dòng NVL có nút "Cần hệ số EA→CAY"; bấm vào mở cửa sổ hỏi đúng một câu "1 CAY = mấy EA" và cho chọn áp cho **chỉ mã này** hay **mọi mã có cặp EA → CAY**. Xác nhận một lần cho cả cặp là gỡ được toàn bộ các dòng cùng loại.
### Cải tiến
- **Không phải F5 nữa**: lưu tiêu chí cho cả lô, lưu/reset **⚙ Cấu hình bảng kê**, hoặc lưu hệ số ĐVT đều tự cập nhật lại màn hình ngay tại chỗ (trạng thái sheet, chip tiêu chí, LVC/CTC).
- **Tìm NVL thay thế hiện đầy đủ**: ô "Tìm kiếm" trong cửa sổ thay NVL nay trả về tới **200** mã thay vì 20, kèm dòng đếm "N NVL khớp …", và **mã có tồn xếp trước**. Tìm "bu lông" ra đủ cả "Bu lông…", "Bộ bu lông…", "Bộ ốc vít, bu lông…"; gõ không dấu ("bu long") cũng ra.
- **Dòng NVL bớt nhiễu**: chỉ còn hiện dấu quy đổi ĐVT khi thật sự có việc phải làm (chưa có hệ số) hoặc khi số lượng thật sự đã bị quy đổi. Các cặp cùng nghĩa (EA / PIECES / CÁI) không còn gắn nhãn "⇄" trên hàng trăm dòng không đổi gì.
### Sửa lỗi
- **"Chốt tất cả" không còn đòi tính lại sau khi thay NVL**: thay NVL hoặc xoá NVL rác hàng loạt nay tính lại **mọi bảng kê bị ảnh hưởng** (các sheet đứng sau trong thứ tự trừ tồn), không chỉ sheet vừa sửa. Trước đây "Tổng hợp NVL" báo "Đủ tồn cho tất cả SP" trong khi danh sách sheet vẫn ghi "Cần tính lại" và Chốt tất cả bỏ qua chúng.
- **"Bỏ chọn" tiêu chí cho cả lô nay thật sự bỏ**: trước đây bấm xong tiêu chí cũ vẫn còn nguyên sau khi tải lại trang.
- **"Tính tồn tất cả (SP)" không còn đụng vào bảng kê đã chốt**: bảng kê đã chốt giữ nguyên số liệu đã nộp và giữ trạng thái 🔒 (trước đây bị tính lại và mở chốt âm thầm).

## [0.16.0] — 2026-06-19
### Mới
- **Ưu tiên mã NVL thay thế đã từng dùng**: trong cửa sổ "Tìm NVL thay thế", những mã từng được dùng để thay cho NVL này trong các bảng kê **đã chốt** trước đây sẽ được đẩy lên **đầu** danh sách khuyến nghị, kèm nhãn "↺ đã từng thay" và số lần đã dùng — kể cả mã mà gợi ý tự động chưa từng đề xuất. Mã dùng nhiều hơn xếp trên; giúp tái dùng nhanh lựa chọn quen thuộc từ các hồ sơ trước.
### Cải tiến
- **Lỗi luôn được báo rõ ràng, không còn "nuốt" lỗi âm thầm**: thao tác bị lỗi (ví dụ bấm "Xuất bảng kê HQ" khi còn bảng kê chưa tính/chốt) nay hiện thông báo ngay tại chỗ và **giữ nguyên trang**, thay vì nhảy sang trang dữ liệu thô khó hiểu. Lỗi khi mở trang/điều hướng thì hiện **trang báo lỗi thân thiện** có nút "Quay lại". Cả các thao tác chạy nền cũng đều báo khi gặp sự cố.

## [0.15.0] — 2026-06-19
### Mới
- **Xử lý tuần tự**: nút mới ở bước "Bảng kê C/O" dẫn bạn xử lý từng sản phẩm lần lượt — Tính → xem lại bảng kê → Chốt, rồi tự sang sản phẩm sau theo đúng thứ tự trừ tồn. Có thanh hướng dẫn nổi hiển thị "Bước k/N", tiến độ và LVC; mỗi bước mở thẳng bảng kê để bạn duyệt trước khi chốt. Sản phẩm còn thiếu BOM/đơn giá sẽ báo lý do và không cho chốt cho tới khi sửa.
- **Ghim BOM mặc định (★)**: cạnh ô chọn phiên bản BOM của mỗi sản phẩm có dấu ★ để ghim phiên bản làm mặc định cho mã thành phẩm đó của khách — hồ sơ C/O sau tự chọn sẵn phiên bản này, khỏi chọn lại. Phiên bản đang là mặc định được đánh dấu trong danh sách.
### Cải tiến
- Chọn phiên bản BOM trong ô chọn giờ chỉ áp cho hồ sơ hiện tại; muốn đặt mặc định cho khách thì bấm ★ (trước đây cứ chọn là tự thành mặc định, gây khó hiểu).
### Sửa lỗi
- Chặn **chốt/xuất bảng kê** khi còn NVL không xuất xứ **thiếu đơn giá** — vì khi đó VNM thiếu nên LVC chỉ là tạm tính (dễ bị thổi lên ~100%). Cần bổ sung đơn giá rồi tính lại trước khi chốt/xuất. (Bảng kê chỉ thiếu tồn vẫn chốt được như cũ.)
- Không còn hiện nhãn "★ Mặc định" trên sản phẩm "Chưa có BOM".
### Thay đổi
- Tạm khoá 2 nút "Chạy tồn (tất cả SP)" và "Chốt tất cả" (đang xây dựng lại) — dùng "Xử lý tuần tự" để xử lý lần lượt.

## [0.14.0] — 2026-06-14
### Mới
- Thiết kế lại bước "Bảng kê C/O": bảng tổng quan các sheet (trạng thái, tóm tắt BOM, cấu hình, số cảnh báo); bấm vào một sheet để mở chế độ xem toàn màn hình kiểu Excel với tab sheet ở dưới, dấu 🔒 cho sheet đã chốt, và cấu hình gom vào nút ⚙.
### Cải tiến
- "Đổi công ty" / "Đổi hồ sơ" mở ngay tại chỗ bằng cửa sổ chọn, không rời trang.
- "Tính bảng kê" chỉ bật khi cần (chưa tính hoặc cần tính lại); khi đã tính thì làm mờ kèm nhắc "sửa bảng kê sẽ tự tính lại", và đổi nhãn thành "Tính lại" khi cần.
- "Load BOM" cảnh báo trước khi ghi đè một bảng kê đang có dữ liệu hoặc chỉnh sửa.
- Xoá NVL: xoá lẻ không hỏi lại (dòng được gập lại, hoàn tác bằng Ctrl+Z); chỉ khi xoá hàng loạt mới xác nhận.
- Thông báo (toast) dễ đọc hơn: nền đặc, ở góc dưới-phải, hiển thị lâu hơn.
### Sửa lỗi
- Sửa lỗi nghiêm trọng khi xoá NVL trên bảng kê: trước đây xoá 1 dòng có thể làm mất thêm dòng khác và đếm "đã xoá" sai (mất dữ liệu → sai LVC/VNM); nay xoá đúng số dòng đã chọn, dòng đã xoá được gập lại và khôi phục được.

## [0.13.0] — 2026-06-07
### Mới
- Trang "Có gì mới" và hiển thị phiên bản ứng dụng ở chân trang mọi màn hình.

## [0.12.0] — 2026-06-07
### Mới
- Tách "Load BOM" (dựng cấu trúc) khỏi "Tính bảng kê" (phân bổ tồn): nạp BOM
  xong có thể sửa NVL rồi mới tính, không bị ghi đè.
### Cải tiến
- Gỡ rối máy trạng thái tồn CO: bỏ khoá "đang giữ phiên tính tồn" (không còn
  chặn hồ sơ song song hay kẹt 60 phút); hai người có thể tính cùng lúc.
### Sửa lỗi
- Làm mới tồn từ Data Hub: snapshot rỗng nay buộc kéo lại toàn bộ thay vì kẹt
  bảng tồn trống.
- Nút "Tính bảng kê" không còn hiện nhầm spinner "Load BOM".

## [0.11.0] — 2026-06-07
### Mới
- Thiết kế lại giao diện theo hệ "Primer console": bảng điều khiển tổng quan
  cho từng trang dữ liệu, điều hướng nhóm, danh sách công ty và hồ sơ gọn hơn.
- Trang danh sách hồ sơ mới: trạng thái workflow, lưu trữ, tạo hồ sơ qua modal.
- Nhận diện thương hiệu: khung tím, monogram, viền topnav.
- Tổng giá trị tồn CO hiển thị ngay trên trang hồ sơ.
### Cải tiến
- Xuất bộ hồ sơ chạy nền (gửi → theo dõi → tải), không treo trình duyệt.

## [0.10.0] — 2026-06-06
### Mới
- Bộ hồ sơ nhúng tờ khai ghép TKX/TKN thành một PDF in chuẩn.
### Cải tiến
- Xác thực CO → Data Hub qua phiên đăng nhập của người dùng (bỏ service token).

## [0.9.0] — 2026-06-05
### Cải tiến
- Tồn CO: gộp trừ-lùi vào số dư còn lại; lịch sử số dư có dấu, dễ đọc hơn.
- Bộ chọn BOM bỏ các BOM phẳng nông; chỉ lấy cây BOM đầy đủ từ Data Hub.
- NVL thay thế: tooltip tên đầy đủ + bộ lọc "chỉ hiện mã đủ tồn".
### Sửa lỗi
- Đóng lỗ hổng tính tồn vượt mức (over-claim) trong luồng chốt.
- Tài nguyên tĩnh thêm hash nội dung để trình duyệt không dùng bản cũ.

## [0.8.0] — 2026-06-01
### Mới
- Tìm NVL thay thế đa trường + lọc gợi ý trực tiếp.
- Xoá hàng loạt dòng NVL và đặt lại thứ tự bảng kê.
- Vai trò quản lý có thể xoá hồ sơ CO.
### Sửa lỗi
- Khắc phục treo khi tính bảng kê.

## [0.7.0] — 2026-05-31
### Mới
- Tải tờ khai và theo dõi trạng thái tệp tờ khai.
- Tiêu thụ BOM theo lô từ Data Hub kèm phương án dự phòng.
### Cải tiến
- Làm mới dữ liệu Data Hub theo gia số (incremental) thay vì kéo lại toàn bộ.
- Báo lỗi rõ ràng khi Data Hub gặp sự cố (503/502 thay vì 500 chung chung).

## [0.5.0] — 2026-05-05
### Mới
- Tỷ giá hải quan cấp ứng dụng.
- Tiêu thụ BOM từ Data Hub; chuyển BOM cho tính LVC theo xuất xứ.
- Phân bổ tồn CO theo nhiều dòng.
### Cải tiến
- Cảnh báo LVC và workbook xuất xứ rõ ràng hơn; tăng tốc trang hồ sơ.

## [0.4.0] — 2026-05-02
### Mới
- Tích hợp Data Hub (consumer mode): CO dùng dữ liệu nguồn từ Data Hub.
- Đăng nhập một lần (SSO) qua Data Hub; lưu cache JWKS để chịu được mất kết nối.

## [0.3.0] — 2026-04-30
### Cải tiến
- Chuyển toàn bộ trạng thái (công ty, cấu hình, chỉ mục nguồn, trạng thái
  workflow) sang Postgres để bền vững và nhất quán.

## [0.2.0] — 2026-04-28
### Mới
- Ứng dụng demo CO đầu tiên: dựng BOM, nguồn dữ liệu có phiên bản, hỗ trợ
  schema HQ.
- Cấu hình theo công ty + điều kiện tồn CO; luồng hồ sơ và tệp đính kèm.

## [0.1.0] — 2026-04-15
### Mới
- Khởi tạo workspace nghiên cứu CO: tài liệu nghiệp vụ, phân tích workbook/VBA,
  pipeline trích xuất kho lưu trữ.
