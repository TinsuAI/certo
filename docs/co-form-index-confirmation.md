# C/O Form Index Confirmation

Tài liệu này dùng để xác nhận với Trọng Tín trước khi coi cấu hình chọn thị trường và form C/O là rule vận hành chính thức.

## Phạm Vi Đợt Đầu

Ưu tiên 4 form đang cần cho workflow CO hiện tại:

| Form | Vai trò trong hệ thống | Nguồn seed |
| --- | --- | --- |
| Form B | Fallback không ưu đãi / xuất xứ chung khi không có form ưu đãi phù hợp hoặc khách yêu cầu C/O thường | `temp/CO-TABLE-FORM.jpg`, eCoSys, Thông tư 05/2018/TT-BCT và các sửa đổi |
| Form CPTPP | Form ưu đãi cho các thị trường CPTPP trong cấu hình | `temp/CO-TABLE-FORM.jpg`, VNTR/MOIT CPTPP |
| Form EUR.1 | Form ưu đãi cho EU/EVFTA trong cấu hình | `temp/CO-TABLE-FORM.jpg`, eCoSys, Thông tư EVFTA hiện hành |
| Form AI | Form ưu đãi ASEAN-India cho thị trường Ấn Độ | `temp/CO-TABLE-FORM.jpg`, MOIT AIFTA, `15/2010/TT-BCT` |

Các form khác trong bảng tổng hợp như `D`, `E`, `AK`, `AJ`, `VJ`, `AANZ`, `VC`, `VK`, `EAV`, `AHK`, `VN-CU`, `RCEP`, `UKVFTA` sẽ bổ sung sau khi 4 form đầu ổn định.

## Mapping Market -> Form Đang Seed

| Market / alias chính | Form gợi ý | Ghi chú cần xác nhận |
| --- | --- | --- |
| United States, Hoa Kỳ, Mỹ | Form B | Không nằm trong bảng C/O hưởng ưu đãi đang seed; hệ thống fallback Form B. |
| India, Ấn Độ | Form AI | Xác nhận có luôn ưu tiên AI cho shipment sang Ấn Độ hay có trường hợp dùng Form B. |
| Canada, Japan, Australia, Mexico, Peru, Singapore | Form CPTPP | Xác nhận danh sách market CPTPP vận hành thực tế và thứ tự ưu tiên nếu market cũng có form khác. |
| EU và các nước thành viên EU | Form EUR.1 | Xác nhận danh sách alias tiếng Việt/tiếng Anh và nguồn thông tư EVFTA đang dùng. |

## Runtime Behavior

1. CO lấy invoice và gọi Data Hub `invoice-matches`.
2. Nếu Data Hub trả đúng một `market_hint` high-confidence, CO tự điền thị trường.
3. Nếu không có hint hoặc nhiều hint conflict, operator phải chọn thị trường thủ công.
4. CO dùng form index để đề xuất form. Operator vẫn có quyền override.
5. Sau khi form được chọn, HS từ BCCT export được dùng để lookup tiêu chí PSR từ bảng `HS Criteria` trong cùng form index. Đợt này mới seed rule preview theo HS scope; parser legal tự động chi tiết vẫn là work item riêng.

## HS/PSR Criteria Seed

Bảng `HS Criteria` hiện được seed từ corpus pháp lý local thay vì chỉ vài dòng mẫu:

| Form | Số dòng HS/PSR seed | Nguồn hiện tại | Trạng thái |
| --- | ---: | --- | --- |
| Form B | 5,609 | `44/2023/TT-BCT`, Phụ lục I sửa đổi `05/2018/TT-BCT` | Extracted từ local corpus, chờ Trọng Tín xác nhận |
| Form CPTPP | 1,156 | `03/2019/TT-BCT`, Phụ lục I | Extracted từ local corpus, có bridge HS2022 cho `8541` |
| Form EUR.1 | 128 | `11/2020/TT-BCT`, Phụ lục II local corpus | Cần refresh/đối chiếu với `14/2026/TT-BCT` trước khi chốt |
| Form AI | 1 | `15/2010/TT-BCT`, Điều 4 Phụ lục 1; MOIT/ASEAN AIFTA legal text | Rule chung `AIFTA 35% FOB + CTSH`; chưa tìm thấy bảng PSR all-HS chính thức để seed tự động |

HS scope match theo độ cụ thể cao nhất: HS 6 số trước, rồi HS 4 số/chapter, rồi `Any HS` fallback. Scope cấp chương được lưu bằng 2 số HS (`01`, `02`, `85`), không lưu dạng chữ `Chương 1`. Ví dụ `850440` sẽ match `8504.40` nếu có; nếu không có sẽ rơi về `8504`, `85` hoặc `Any HS`.

Scope có tiền tố `ex`, ví dụ `ex 0307`, nghĩa là rule chỉ áp dụng cho một phần của nhóm/phân nhóm HS đó theo mô tả hàng hóa trong bảng pháp lý, không áp dụng cho toàn bộ `0307`. Thuật toán hiện chỉ có HS code nên các dòng `ex` được đánh dấu `requires_manual_lookup`; operator phải đối chiếu mô tả hàng hóa trước khi áp dụng PSR.

Lưu ý Form AI: nguồn online đã kiểm tra gồm trang văn kiện AIFTA của MOIT, legal text ASEAN, hướng dẫn Enterprise Singapore và index pháp lý CIL/NUS. Các nguồn này xác nhận quy tắc chung cho hàng không thuần túy là `35% AIFTA content + CTSH`; index pháp lý còn ghi `Appendix B: Product Specific Rules (Under negotiation)`. Vì vậy seed hiện tại không tự sinh các dòng HS riêng cho Form AI nếu chưa có bảng PSR chính thức hoặc xác nhận vận hành từ Trọng Tín.

Nguồn online chính:

- MOIT AIFTA legal document page: <https://fta.gov.vn/index.php?id=904&r=site%2Fcontent>
- ASEAN AIFTA Trade in Goods Agreement: <https://www.asean.org/wp-content/uploads/images/archive/22677.pdf>
- CIL/NUS legal-text index: <https://cil.nus.edu.sg/databasecil/2009-agreement-on-trade-in-goods-under-the-framework-agreement-on-comprehensive-economic-cooperation-between-the-association-of-southeast-asian-nations-and-the-republic-of-india/>
- Enterprise Singapore AIFTA guidance: <https://www.enterprisesg.gov.sg/grow-your-business/go-global/international-agreements/free-trade-agreements/find-an-fta/aifta>

Bảng `04_HS kiểm trước` trong file Excel đã được rà lại từ BCCT file local/sibling project ngày 2026-05-04, không dùng Data Hub làm nguồn chọn HS ưu tiên.

| Doanh nghiệp | File BCCT rà lại | HS xuất khẩu ưu tiên | Ghi chú |
| --- | --- | --- | --- |
| Growatt | `data/local/source-modules/clients/growatt/bcct/.../BaoCaoHangChiTiet 01.01.2025 - 31.12.2025 08.01 or.xlsx` | `85044090`, `85076039`, `85371099`, `90328931` | Lọc dòng `E42`; lần lượt 389, 86, 36, 18 dòng theo HS. |
| Johnson | `Johnson/output/CLEAN_BCCT.csv`, từ `BaoCaoHangChiTiet năm 2025.xls` | `95069100` | `E42` có 2.893 dòng HS `95069100` trong 2.938 dòng xuất khẩu; các HS còn lại chủ yếu phế liệu/không phải nhóm C/O ưu tiên. |
| DKE | `BCQT-DKE/input/28.03 XU LY DINH MUC/BaoCaoHangChiTiet 2025 Official.xls` | `85249900`, `85285910` | Lọc dòng `E42`; lần lượt 112 và 4 dòng. |
| Đô Thành | `bcqt-dothanh/data/extracted/BCQT SXXK 2025/BaoCaoHangChiTietE62.xls` | `85419000`, `76042190`, `76169990`, `76109099` | Lọc dòng `E62`; lần lượt 204, 43, 14, 4 dòng. |

Bảng dưới là các anchor quan trọng cho nhóm HS ưu tiên, không phải toàn bộ danh sách:

| Form | HS scope | Tiêu chí seed | Nguồn / ghi chú xác nhận |
| --- | --- | --- | --- |
| Form B | `8504` | `LVC 30% hoặc CTH` | `44/2023/TT-BCT`, Phụ lục I sửa đổi `05/2018/TT-BCT`; cần Trọng Tín xác nhận cách áp dụng cho mã thành phẩm thực tế. |
| Form B | `8541` | `LVC 30% hoặc CTSH` | Có ghi chú ngoại lệ cho một số phân nhóm `8541.42/8541.43`; cần xác nhận theo HS 6 số. |
| Form B | `Any HS` | `Tra PSR Form B theo Phụ lục I` | Fallback khi chưa map tự động HS cụ thể. |
| Form CPTPP | `8504` | `CTH hoặc RVC 30/40/50 tùy công thức` | `03/2019/TT-BCT`, Phụ lục II; cần xác nhận công thức RVC dùng trong hồ sơ thực tế. |
| Form CPTPP | `8541` | `CTSH hoặc RVC 30/40/50 tùy công thức` | `03/2019/TT-BCT`, Phụ lục II; cần xác nhận theo phân nhóm HS. |
| Form EUR.1 | `85` | `Sử dụng nguyên liệu từ bất kỳ Nhóm nào để sản xuất, ngoại trừ Nhóm của sản phẩm; hoặc trị giá nguyên liệu không vượt quá 70% giá xuất xưởng` | Anchor từ local corpus `11/2020/TT-BCT`; cần đối chiếu `14/2026/TT-BCT`. |
| Form AI | `Any HS` | `AIFTA 35% FOB + CTSH` | `15/2010/TT-BCT`, Điều 4 Phụ lục 1; nguồn online chưa đủ căn cứ để seed PSR theo từng HS, thêm override nếu Trọng Tín xác nhận PSR riêng. |

## Câu Hỏi Xác Nhận Với Trọng Tín

1. US/Hoa Kỳ có mặc định Form B cho khách Growatt không?
2. CPTPP: danh sách market trong vận hành thực tế có gồm đầy đủ Australia, Brunei, Canada, Chile, Japan, Malaysia, Mexico, New Zealand, Peru, Singapore không, hay chỉ dùng một subset?
3. Japan có ưu tiên CPTPP trong phạm vi đợt đầu không, dù bảng tổng hợp còn có AJ/VJ/RCEP?
4. EU/EUR.1: xác nhận alias thị trường dùng trong hồ sơ thực tế, đặc biệt các tên tiếng Việt có dấu/không dấu.
5. Có market nào trong 4 form đầu cần mặc định Form B thay vì form ưu đãi vì thực tế khách không xin ưu đãi không?
6. Với từng form ưu tiên, Trọng Tín muốn map PSR theo HS 4 số hay 6 số cho các mặt hàng Growatt hiện tại?
7. Với EUR.1, dùng bản `14/2026/TT-BCT` làm nguồn chốt hay vẫn chấp nhận seed từ corpus `11/2020` trong lúc chờ refresh?
8. Khi một HS chưa có rule cụ thể, hệ thống nên fallback `Any HS` để operator tra thủ công hay chặn workflow tới khi bổ sung rule?

## Cách Cấu Hình Trong CO

Mở `/settings/co-forms`.

- `Form Priority`: thứ tự form khi một thị trường có nhiều candidate.
- `Form Definitions`: bật/tắt form, sửa tên hiển thị, hiệp định, văn bản và nguồn.
- `Market Aliases`: map market/alias sang form; tick `Picker` nếu muốn hiện shortcut trong combobox tạo hồ sơ.
- `HS Criteria`: map form + HS scope sang tiêu chí PSR preview; có thể thêm dòng mới hoặc tắt rule chưa dùng.

Config được lưu local tại `data/local/runtime/co-form-index.json` hoặc path trong biến môi trường `CO_FORM_CONFIG_PATH`.
