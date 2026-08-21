# 2026-05-29 PM — Email cập nhật dữ liệu + CO cho Trọng Tín

Sau handoff F.1 (`49d9175`), user yêu cầu soạn email gửi Trọng Tín
Consulting (đơn vị tư vấn xuất nhập khẩu, vận hành CO cho Growatt +
Johnson) để: (1) cập nhật trạng thái dữ liệu 2 khách hàng trên Data
Hub, (2) giới thiệu tính năng CO hiện có, (3) khuyến khích họ bắt
đầu dùng hệ thống CO cho lô Johnson để rút ngắn vòng phản hồi.

## What Was Done

- Pull số liệu chính xác per-client từ local DB (BCCT NK/XK, file
  khai báo, danh mục TP/BTP/NVL, BOM artifacts) để có con số thực
  cho email.
- Survey tính năng CO hiện có qua `~/workspace/client/barry-CO-main/
  .ai/STATUS.md` (BOM picker, state machine, load BOM perf, 2-day
  gap rule, form support D/E/AK/AANZ/AJ/RCEP/UKVFTA/VK/VC/VJ).
- Xác định vai trò Trọng Tín = outsourced compliance operator
  (knowledge file `~/workspace/client/barry-CO-main/.ai/knowledge/
  2026-04-15-co-notes-from-v-notes.md`).
- Draft email v1 (English-leaning terminology), iterate 5 vòng theo
  feedback user:
  1. Đổi "chúng tôi" → "em" (xưng em với anh/chị)
  2. Thêm thông báo lịch hỗ trợ qua Zalo/điện thoại do nghỉ lễ
     Singapore + tham chiếu bản demo đầu tiên đã trình bày
  3. Việt hóa ngôn ngữ — bỏ jargon Anh (BOM picker → "bộ lọc",
     stock ledger → "sổ tồn", v.v.)
  4. Đổi "đại lý" → "Trọng Tín" cho rõ chủ thể
  5. Thêm section 3 "Cập nhật dữ liệu mới lên Data Hub" — hướng
     dẫn upload BCCT/TKNK/TKXK/BOM định kỳ

## Decisions Made

- **Không lưu draft vào docs/ hay templates/.** Email là one-shot
  comm tới một customer cụ thể, không tái sử dụng. Save trong session
  log đủ — user copy/paste qua mail client của mình.
- **Số liệu lấy từ local DB (post-F.1).** Local + demo byte-identical
  nên dùng local cho tốc độ. Mốc ngày tờ khai mới nhất hardcode vào
  email: Growatt 2026-05-20, Johnson 2026-05-06.
- **Mô tả CO bằng nghiệp vụ, không bằng tên tính năng.** "Load BOM 45s
  → 2-3s warm" → "thời gian mở BOM rút từ 45 giây xuống 2-3 giây".
  "Substitute material logic" → "hỗ trợ thay thế vật tư khi cần".

## What Didn't Work

- Draft đầu dùng nhiều thuật ngữ Anh — user phản hồi "khó hiểu". Bài
  học: khi viết email cho compliance operator (không phải nhân sự kỹ
  thuật), default sang nghiệp vụ + Việt hóa, dùng thuật ngữ Anh chỉ
  khi không có từ Việt tương đương (BOM giữ nguyên, có giải thích
  trong ngoặc lần đầu là "định mức").

## Open Items

- **User tự gửi email** (qua mail client cá nhân). Tinsu AI chưa có
  template/CRM thống nhất nên drafter mỗi lần lại từ đầu — đáng tính
  cho tương lai nhưng chưa tới mức cần ngay.
- **Chân email "[Tên người gửi]"** vẫn placeholder — user fill khi
  send.
- **Lịch demo cụ thể chưa hứa** — đợi Trọng Tín đề xuất ngày.

## Final Email Text

```
Tới:    Trọng Tín Consulting
Từ:     Tinsu AI
Chủ đề: Cập nhật dữ liệu Growatt + Johnson và tình hình hệ thống CO

Kính gửi anh/chị bên Trọng Tín,

Em xin cập nhật tình hình dữ liệu hai khách hàng đang triển khai trên
Data Hub (kho dữ liệu dùng chung) và các tính năng đã sẵn sàng trên
hệ thống cấp CO.

## 1. Tình hình dữ liệu trên Data Hub

### Growatt Việt Nam
- Tờ khai hải quan: 1.403 tờ nhập + 500 tờ xuất, trải dài từ tháng
  11/2022 đến 20/05/2026 — tổng cộng 38.287 dòng nhập và 916 dòng xuất.
- File khai báo kèm theo: 4.038 file.
- Danh mục vật tư: 457 mã — gồm 21 thành phẩm, 153 bán thành phẩm,
  283 nguyên vật liệu.
- Định mức (BOM): 823 phiên bản BOM cho 57 sản phẩm hoàn chỉnh và
  212 bán thành phẩm được phân rã tự động, thêm 14 BOM do Trọng Tín
  tự khai cho các bán thành phẩm mà nhà cung cấp không có file kỹ
  thuật.
- Tình trạng: vừa hoàn tất đợt làm sạch và nhập lại từ file XLSX gốc
  ngày 29/05, đã đồng bộ giữa môi trường nội bộ và máy chủ demo.

### Johnson Việt Nam
- Tờ khai hải quan: 2.353 tờ nhập + 869 tờ xuất, từ tháng 04/2025
  đến 05/2026 — tổng 60.173 dòng nhập và 5.673 dòng xuất.
- File khai báo kèm theo: 3.221 file.
- Danh mục vật tư: 13.132 mã — 650 thành phẩm, 3.031 bán thành phẩm,
  9.451 nguyên vật liệu.
- Định mức (BOM): 12.994 phiên bản cho 106 sản phẩm chính từ hệ SAP
  của Johnson cộng 3.031 bán thành phẩm phân rã tự động và 517 BOM
  do Trọng Tín tự khai.
- Tình trạng: ổn định từ đợt nhập đầy đủ ngày 11/05, đã qua nhiều
  vòng rà soát chất lượng (gộp trùng bán thành phẩm, xử lý vai trò
  vật tư, đối chiếu mâu thuẫn giữa các nguồn).

Nhìn tổng thể, dữ liệu Johnson hiện đang đầy đủ và sạch nhất trong
hệ thống — đủ lớn (13 nghìn mã vật tư, 66 nghìn dòng tờ khai) để
phản ánh đúng vận hành thực tế của một nhà máy gia công cỡ lớn.

## 2. Hệ thống cấp CO

Hệ thống cấp CO (https://barry-co.tinsu.ai) đã hoàn thiện các luồng
nghiệp vụ chính. Về cơ bản nghiệp vụ giống bản demo đầu tiên mà em
đã trình bày với anh/chị trước đây — phiên bản này là bản hoàn thiện
thêm về tốc độ, độ ổn định, và một số tinh chỉnh nhỏ. Cụ thể:

- Quản lý từng lô CO độc lập — mở hồ sơ, lưu trạng thái, khóa khi
  đang xử lý để tránh ghi đè, lưu tài liệu hỗ trợ kèm theo từng lô.
- Tự động lấy BOM và danh mục vật tư từ Data Hub — có bộ lọc theo
  trạng thái, theo loại BOM (phân rã hay không), theo phiên bản mới
  nhất, theo lô đang xử lý. Thời gian mở BOM đã rút từ 45 giây
  xuống còn 2-3 giây kể từ lần thứ hai.
- Tính xuất xứ tự động: WO / CTC / RVC / LVC theo công thức của Bộ
  Công Thương (áp dụng sau khi thẩm quyền cấp CO chuyển từ VCCI về
  Bộ Công Thương từ tháng 5/2025).
- Quản lý tồn kho nguyên vật liệu theo từng lô CO — có sổ tồn, kiểm
  tra điều kiện sử dụng, hỗ trợ thay thế vật tư khi cần.
- Quy tắc tối thiểu 2 ngày trước xuất khẩu — chặn không cho dùng
  nguyên vật liệu mới nhập trong khoảng thời gian quá ngắn, ngưỡng
  có thể tùy chỉnh theo từng khách hàng.
- Hỗ trợ nhiều mẫu form CO: mẫu AI (ASEAN-Ấn Độ) đã chạy ổn định;
  các mẫu D / E / AK / AANZ / AJ / RCEP / UKVFTA / VK / VC / VJ
  đang được bổ sung dần.
- Đồng bộ với Data Hub gần như tức thì — chỉnh BOM trên Data Hub
  thì hệ thống CO nhận được trong vòng tối đa 30 giây.

## 3. Cập nhật dữ liệu mới lên Data Hub

Để hệ thống CO luôn tính xuất xứ trên dữ liệu mới nhất, mong anh/chị
duy trì thói quen đẩy dữ liệu mới lên Data Hub ngay khi phát sinh:

- Báo cáo BCCT mới — sau mỗi đợt khai báo, anh/chị xuất file BCCT từ
  hệ thống hải quan rồi upload lên Data Hub theo từng khách hàng
  (Growatt hoặc Johnson). Hiện dữ liệu mới nhất trên hệ thống là
  Growatt đến 20/05/2026 và Johnson đến 06/05/2026 — bất kỳ tờ khai
  nào sau mốc này đều cần đẩy lên.
- Tờ khai nhập (TKNK) và tờ khai xuất (TKXK) — upload kèm file
  PDF/ZIP của từng tờ khai vào Data Hub để hệ thống CO có đủ chứng
  từ khi tính xuất xứ và xuất bằng kê. Cách làm: vào trang khách
  hàng → mục "Tờ khai" → "Tải lên".
- Định mức (BOM) mới hoặc chỉnh sửa — khi nhà máy cập nhật định mức
  cho sản phẩm mới hoặc thay đổi định mức cũ, upload file XLSX lên
  mục "BOM" của khách hàng tương ứng. Hệ thống tự động giữ lịch sử
  các phiên bản.
- Tần suất gợi ý: ít nhất 1 lần/tuần, hoặc ngay trước khi bắt đầu
  xử lý một lô CO mới — để dữ liệu phục vụ tính xuất xứ luôn khớp
  với thực tế xuất nhập trong kỳ.

Hệ thống xử lý theo nguyên tắc gộp tăng cường (upsert) — anh/chị
upload lại file cũ cũng không gây trùng lặp, các dòng đã có sẽ được
giữ nguyên, chỉ thêm vào những dòng mới.

## 4. Đề xuất: bắt đầu cấp CO Johnson trên hệ thống

Để rút ngắn vòng phản hồi và đưa hệ thống vào sử dụng thực tế sớm,
em đề xuất Trọng Tín bắt đầu cấp CO cho lô hàng Johnson ngay trong
các tuần tới:

- Dữ liệu Johnson đang đầy đủ và sạch nhất, không có rào cản nào
  để bắt đầu.
- Khi xử lý lô thật, sẽ lộ ra ngay những điểm cần tinh chỉnh (giao
  diện, biểu mẫu, các tình huống đặc biệt) mà việc kiểm tra nội bộ
  khó phát hiện hết.
- Mỗi lô CO Trọng Tín xử lý trên hệ thống là một vòng phản hồi rất
  giá trị cho tốc độ hoàn thiện sản phẩm.
- Khi luồng Johnson chạy ổn định, em sẽ chuyển tiếp Growatt vào
  sau, áp dụng các cải tiến rút ra từ giai đoạn đầu.

## 5. Hỗ trợ trong thời gian tới

Mấy ngày tới đúng dịp nghỉ lễ ở Singapore, em không tiện ngồi máy
trực tiếp, nhưng vẫn sẵn sàng hỗ trợ anh/chị qua Zalo hoặc điện
thoại bất kỳ lúc nào — giải đáp nghiệp vụ, hướng dẫn thao tác, hoặc
xử lý ngay các tình huống phát sinh khi anh/chị dùng thử hệ thống.
Mọi yêu cầu chỉnh sửa từ phản hồi của anh/chị sẽ được em ưu tiên xử
lý ngay khi quay lại làm việc đầy đủ.

Anh/chị xác nhận giúp em vài lô Johnson dự kiến sẽ làm trong tuần
tới để em đồng hành cùng theo dõi vòng đầu tiên.

Trân trọng cảm ơn anh/chị,

[Tên người gửi]
Tinsu AI
```
