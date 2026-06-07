# Changelog

Nhật ký thay đổi của Barry CO dành cho người dùng. Định dạng theo
[Keep a Changelog](https://keepachangelog.com/vi/); chỉ ghi thay đổi có ảnh
hưởng tới người dùng (bỏ qua refactor nội bộ, hạ tầng test). Phiên bản theo
[SemVer](https://semver.org/lang/vi/).

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
