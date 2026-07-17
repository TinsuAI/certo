# Changelog

Tất cả thay đổi đáng chú ý của Data Hub được ghi tại đây.
Định dạng theo [Keep a Changelog](https://keepachangelog.com/);
phiên bản theo [SemVer](https://semver.org/).

> Các phiên bản trước **0.13.0** được tái dựng từ lịch sử git + nhật ký
> phiên làm việc (`.ai/sessions/`). Giai đoạn pre-MVP chưa cắt tag, nên
> mốc phiên bản gom theo từng đợt tính năng chính, không phải bản phát
> hành đã đóng gói tại thời điểm đó.

## [Unreleased]
### Sửa
- **Trang "Mã chờ duyệt" nay chọn được từng mã, và duyệt một mã mở hộp thoại riêng thay vì form chen trong bảng:** trước đây chỉ duyệt được **toàn bộ** tập khớp bộ lọc — không tích chọn được 5 mã rồi bỏ mã thứ 6. Nay mỗi dòng có ô tích; tích cả trang thì hiện dải băng «Chọn tất cả N mã khớp bộ lọc» (kiểu Gmail). Nút duyệt đổi nhãn theo lựa chọn: chưa chọn thì tắt, chọn rồi thì «Duyệt N mã đã chọn», chọn cả tập thì «Duyệt toàn bộ N mã khớp bộ lọc». Về mặt an toàn: máy chủ **không tin** danh sách mã client gửi — nó tự tính lại tập khớp bộ lọc rồi **giao** với danh sách đã chọn, nên một mã đã thành vật tư, mã máy móc, mã ngoài bộ lọc, hay mã bịa đặt bỏ vào request đều bị loại; bộ lọc vẫn là giới hạn ngoài, chỉ thu hẹp chứ không nới rộng được tập ghi vào. Nút «Duyệt» ở từng dòng nay mở hộp thoại (modal) điền sẵn tên/danh mục/UoM theo dữ liệu, thay cho form 5 ô chen trong ô bảng; danh mục điền sẵn đúng theo cách duyệt hàng loạt suy ra (lá phẳng → NVL) nên không còn mặc định nhầm sang loại đầu bảng. Refs #55.
- **Bộ lọc ở trang "Mã chờ duyệt" nay báo đúng số và không tự bỏ bớt điều kiện:** số trên mỗi nhãn lọc (NB / HQ / BCCT / BOM / BQD…) trước đây được đếm mà không tính các điều kiện lọc đang bật, trong khi bấm vào nhãn đó lại giữ chúng — nên con số hiện ra không phải con số nhận được. Trên dữ liệu Growatt, tìm "001.0033" ra 2 dòng nhưng nhãn NB vẫn ghi 93 và nhãn BOM ghi 73. Nặng hơn: mỗi nút lọc chỉ mang theo một phần điều kiện của các nút khác, nên đang lọc "chỉ lá BOM đã làm phẳng" (2.106 mã) rồi bấm nhãn NB để lọc hẹp lại thì điều kiện "lá phẳng" bị bỏ âm thầm và kết quả **rộng ra** thành 2.683 mã — trong khi nút «Duyệt N mã đang lọc» ngay bên cạnh ghi số theo tập rộng đó và duyệt đúng tập rộng đó vào danh mục. Nay mọi nút lọc dựng đường dẫn từ cùng một chỗ giữ đủ sáu điều kiện, và số trên mỗi nhãn được đếm đúng ở trạng thái mà chính nó dẫn tới — bấm nhãn ghi N thì nhận đúng N dòng. Refs #54.
- **Mã NB được ít nhất hai nguồn dữ liệu xác nhận không còn nằm chờ duyệt:** hệ thống tự ghi nhận vật tư vào danh mục cho mọi mã HQ đã khai trên tờ khai, nhưng mã NB bóc tách từ ngoặc đơn trong tên hàng — nằm trên đúng dòng tờ khai đó — thì không, mà xếp vào hàng chờ người duyệt. Trên dữ liệu Growatt có 2.593 mã (2.590 mã NB + 3 mã thống nhất) được **ít nhất hai trong ba nguồn** xác nhận — 2.048 mã có đủ cả ba (tờ khai + BOM + BQD), 540 mã có tờ khai + BQD, 5 mã có BOM + BQD — nhưng vẫn nằm ở trang "Mã chờ duyệt" như thể cần người xác nhận; trong khi suốt lịch sử hệ thống chưa từng có mã nào bị từ chối, và nút duyệt hàng loạt chưa từng được người dùng bấm lần nào kể từ khi ra mắt. Số mã này nay đã vào danh mục theo đúng phân loại quan sát được (2.570 nguyên vật liệu + 23 thành phẩm), ghi nhật ký dưới tên tác nhân hệ thống chứ không ghi là người dùng duyệt. Lý do đòi hai nguồn: bóc tách từ ngoặc là suy đoán bằng biểu thức chính quy, còn BOM và BQD là chuỗi lấy nguyên văn từ tệp do khách hàng lập — nên một quy tắc bóc tách sai chỉ sinh ra mã có mỗi nguồn tờ khai, và mã như vậy vẫn nằm chờ duyệt. Cùng lẽ đó, 73 mã chỉ có trong BOM (mã nội bộ nhà cung cấp), 34 mã chỉ có trong BQD và 4 mã chỉ có trên tờ khai cũng được giữ lại chờ duyệt. Hàng đợi Growatt trên máy chủ: 2.912 → 318 mã (111 mã hiện + 207 mã máy móc vốn đã ẩn); danh mục 850 → 3.443 vật tư; số mã BOM chưa có vật tư trong danh mục: 2.109 → 74. Khách hàng Johnson không bị ảnh hưởng (không dùng mã NB trong ngoặc nên không có mã nào chờ duyệt). Refs #53.
- **Mã đã khai với hải quan không còn nằm chờ duyệt như thể là mã máy suy đoán:** khi nhập tờ khai bằng script nhập liệu (thay vì qua giao diện web), hệ thống ghi dòng tờ khai nhưng bỏ qua bước tự ghi nhận vật tư vào danh mục — hai lối nhập cho ra hai kết quả khác nhau. Hậu quả trên dữ liệu Growatt: 393 mã đã khai với hải quan không có vật tư tương ứng trong danh mục, và hiện ra ở trang "Mã chờ duyệt" như thể là mã do máy suy đoán, cần người xác nhận; thực tế đó là mã khách hàng đã khai, không có gì để duyệt. Nay mọi lối nhập tờ khai đều tự ghi nhận vật tư như nhau. 393 mã tồn đọng đã được đưa vào danh mục theo đúng phân loại quan sát được (349 nguyên vật liệu + 44 thành phẩm), ghi nhật ký dưới tên tác nhân hệ thống chứ không ghi là người dùng duyệt. Hàng đợi Growatt: 3.306 → 2.912 mã. Refs #52.
- **Ký hiệu giữ chỗ `..` của Growatt không còn tự sinh vật tư rác:** ngoài `.`, Growatt còn ghi `..` ở cột mã HQ cho dòng tài sản cố định (một dòng: súng hút thiếc mua làm công cụ, tờ khai 2022). Ký hiệu này nay được cấu hình chung chỗ với `.` (`hub.clients.customs_code_placeholders`), nên các dòng đó không còn sinh vật tư và không còn hiện ở "Mã chờ duyệt". Refs #52.
- **Duyệt một mã ở trang "Mã chờ duyệt" nay vào thẳng danh mục ở trạng thái «Hoạt động»:** trước đây nút duyệt từng mã đưa mã vào danh mục ở trạng thái «Chờ duyệt», trong khi nút «Duyệt N mã đang lọc» ngay bên cạnh lại đưa vào «Hoạt động» — hai nút trên cùng một trang cho ra hai kết quả khác nhau. Nghịch lý hơn: mã tự ghi nhận từ tờ khai (không ai xem xét) vào thẳng «Hoạt động», còn mã do người dùng chủ động duyệt lại phải chờ duyệt thêm một lần nữa ở trang chi tiết — lối thoát duy nhất là bấm vào từng mã một. Trạng thái «Chờ duyệt» nay được bỏ hẳn: việc duyệt đã nằm ở chính trang "Mã chờ duyệt", không cần thêm một cửa duyệt thứ hai. Trạng thái hợp lệ còn `active` / `deprecated` / `tombstoned` / `inactive`. Refs #49.

### API
- **In tờ khai nhập cho hồ sơ CO chỉ còn trang bìa và trang có dòng nguyên vật liệu được dùng:** một tờ khai nhập thực tế của Growatt dài 52-54 trang cho 50 dòng hàng — mẫu in ECUS xếp khoảng một dòng hàng mỗi trang — trong khi một hồ sơ CO thường chỉ dùng vài dòng, nên khoảng 90% số trang in ra không liên quan. Thêm `POST /v1/hub/clients/{mã_khách}/declarations/download.pdf` nhận kèm danh sách số dòng cần in cho từng tờ khai. Trang được chọn theo chính ký hiệu số dòng `<NN>` mà mẫu in ECUS in sẵn trên mỗi trang hàng; trang không mang ký hiệu này (trang bìa và trang cuối — số lượng thay đổi tùy tờ khai, có tờ 2 trang bìa, có tờ 3 trang bìa kèm 1 trang cuối) luôn được giữ. Tờ khai không nêu số dòng thì in đầy đủ như cũ, nên hồ sơ không bao giờ bị thiếu chứng từ. Trang giữ lại là bản sao nguyên vẹn của tờ khai đã nộp — hệ thống chỉ bỏ nguyên trang, không sửa nội dung trang. Lệnh `GET` cũ giữ nguyên, không đổi một byte nào. Đây cũng là cách xử lý giới hạn ~2MB của Ecosys mà tùy chọn `quality=compact` trước đây không giải quyết được, vì dung lượng phụ thuộc số trang. Chi tiết: `docs/API_CHANGELOG.md` (2026-07-17, Additive). Refs #50.
- **Sửa: lệnh lấy BOM "mới nhất" hàng loạt không còn lẫn bản sửa theo hồ sơ CO:** `POST /v1/hub/products/bom/artifacts:batch` và `GET /v1/hub/products/{mã}/bom/artifacts` khi gọi mặc định (không truyền `intents`/`case_id`) trước đây có thể trả về một bản BOM `modified_for_case` (bản sửa riêng cho một hồ sơ CO) làm bản "mới nhất" của sản phẩm — lệch với `GET /v1/hub/products/{mã}/bom/latest` vốn luôn loại bản này. Nay bản `modified_for_case` luôn bị giới hạn theo `case_id`: chỉ trả về khi người gọi nêu đúng hồ sơ, nên lệnh lấy "mới nhất" không kèm hồ sơ sẽ không bao giờ nhận nhầm bản sửa theo hồ sơ. Ứng dụng đồng hành (CO) không bị ảnh hưởng vì luôn gọi kèm `intents` + `case_id`. Chi tiết: `docs/API_CHANGELOG.md` (2026-07-17, Additive). Refs #47.

## [0.21.0] — 2026-07-11
### Mới
- **"Mã chờ duyệt" tính trực tiếp từ dữ liệu nguồn, không còn bảng trung gian:** danh sách mã chờ duyệt nay được tính thẳng từ tờ khai + BOM + BQD mỗi lần xem — không còn bảng lưu sẵn có thể lệch so với nguồn, không còn khái niệm "làm mới danh sách". Từ chối một mã được ghi vào bảng chặn riêng (`hub.catalog_rejections`) và không bị dữ liệu mới "hồi sinh"; duyệt một mã ghi thẳng vào danh mục kèm nguồn gốc đúng theo luồng phát hiện (tờ khai / BOM / BQD — trước đây luôn ghi cứng "quan sát từ tờ khai"). Toàn bộ 1.207 quyết định duyệt cũ được lưu vĩnh viễn vào nhật ký (`bom_audit_events`) trước khi bỏ bảng cũ; khôi phục một mã đã từ chối không còn để sót dữ liệu duyệt cũ.
- **Danh mục nhận diện đúng mã NB nằm trong ngoặc đơn của tên hàng:** với khách hàng khai mã NB trong ngoặc ở tên hàng trên tờ khai (dạng Growatt), số lần quan sát, hướng XNK và ngày quan sát của các mã đó trước đây hiển thị 0 ở trang danh mục (chỉ trang chi tiết có số đúng nhờ một bước tính tạm). Nay kết quả bóc tách được lưu lại (`hub.bcct_nb_codes`, tự cập nhật sau mỗi lần nhập tờ khai hoặc sửa quy tắc bóc tách) và mọi trang đọc chung một nguồn — số liệu nhất quán ở cả danh sách lẫn chi tiết.
- **Đánh dấu mã phụ tùng máy móc:** mã NB chỉ xuất hiện trên các dòng tài sản cố định (dòng ký hiệu giữ chỗ, vd xe nâng/giá kệ loại hình E13) được phân loại `excluded_non_material` — vẫn hiển thị, không bị xóa; mã nào từng xuất hiện trên dòng sản xuất hoặc từng được khai trực tiếp thì không bị đánh dấu. Growatt: 207 mã được đánh dấu, 11 mã dùng chung không đánh dấu.
- **Duyệt danh mục hàng loạt — bộ lọc chính là quy tắc:** trang "Mã chờ duyệt" thêm bộ lọc tín hiệu (chỉ lá của BOM đã làm phẳng, ngưỡng số lần quan sát, ẩn/hiện mã máy móc) và một nút «Duyệt N mã đang lọc» duyệt toàn bộ số mã đang khớp bộ lọc trong một thao tác — danh mục lấy theo đề xuất (lá phẳng → NVL), tên/UoM lấy theo dữ liệu quan sát. Mã máy móc (`excluded_non_material`) mặc định bị loại khỏi lượt duyệt; mã chưa phân loại được thì bỏ qua để duyệt thủ công. Mỗi lượt duyệt hàng loạt ghi đúng một dòng nhật ký kèm điều kiện lọc, số lượng và danh sách mã. Với Growatt: 3.306 mã chờ → 2.156 mã đủ điều kiện duyệt theo quy tắc lá phẳng. Việc duyệt hàng loạt không làm kích hoạt cơ chế đánh dấu BOM "cần làm mới" theo từng dòng mà gộp lại chạy một lần.

### Sửa
- **Trang "Mã chờ duyệt" mở nhanh hơn (~0.4s thay vì ~2.2s trên dữ liệu Growatt):** trước đây mỗi lần mở trang (kể cả chuyển trang) hệ thống quét lại toàn bộ tờ khai và ghi lại hàng nghìn dòng "mã chờ duyệt". Nay việc quét chỉ chạy sau mỗi lần nhập liệu (BCCT / BOM / BQD) và khi bấm nút «Làm mới» trên trang; mở trang chỉ đọc, không ghi gì vào hệ thống.
- **Ký hiệu giữ chỗ trên tờ khai không còn tự sinh "vật tư" rác:** một số khách hàng ghi ký hiệu giữ chỗ (vd `.`) vào cột mã HQ cho các dòng tài sản cố định (xe nâng, giá kệ — loại hình E13). Trước đây các dòng này tự sinh một "vật tư" tên `.` trong danh mục. Nay ký hiệu giữ chỗ được cấu hình riêng cho từng khách hàng (`hub.clients.customs_code_placeholders`, Growatt + Johnson dùng `.`), các dòng đó được bỏ qua khi tự ghi nhận vật tư từ tờ khai, và hai "vật tư" `.` cũ đã được xóa khỏi danh mục. Không đổi API; các mã phụ tùng máy móc sẽ được đánh dấu ở giai đoạn 3 (#33).

### API
- **Danh mục vật tư qua API mặc định chỉ trả về mã còn hiệu lực:** `GET /v1/hub/materials` (danh sách và tra theo mã) bỏ qua các mã đã khai tử (`tombstoned`) hoặc ngừng dùng (`inactive`), để ứng dụng đồng hành không hiển thị mã đã loại bỏ. Mã đang chờ duyệt (`under_review`) và mã cũ (`deprecated`) vẫn trả về như trước. Thêm tham số `?status=` để xem đúng một trạng thái khi cần, kể cả mã đã khai tử. Dữ liệu hiện tại chưa có mã khai tử nên phản hồi không đổi. Chi tiết: `docs/API_CHANGELOG.md` (2026-07-11, Additive).

## [0.20.0] — 2026-07-10
### Mới
- **Không còn bị đăng xuất giữa ca khi đang làm việc trên ứng dụng đồng hành:** Data Hub cấp thêm một "vé gia hạn" (refresh token) để ứng dụng đồng hành tự làm mới phiên ngầm, thay vì bắt thao tác viên đăng nhập lại mỗi ~10 phút — kể cả khi đang dở một thao tác trên cùng một trang. Vé truy cập vẫn hết hạn nhanh sau 10 phút như cũ, nên mức bảo mật không đổi; chỉ có việc gia hạn là tự động. Vé gia hạn trượt theo 12 giờ không thao tác, tối đa 7 ngày, và mất hiệu lực ngay khi đăng xuất khỏi Data Hub.

### Sửa
- **Trang lỗi thân thiện thay cho JSON thô:** mọi trang giao diện khi gặp lỗi giờ hiển thị trang thông báo gọn gàng — kèm nội dung lỗi cụ thể đã Việt hóa (vd "Không tìm thấy khách hàng", "Không có quyền truy cập") — thay vì chuỗi JSON `{"detail": ...}`. Chưa đăng nhập mà mở trang cần quyền sẽ tự chuyển về trang đăng nhập và quay lại đúng trang sau khi đăng nhập. API cho ứng dụng đồng hành (`/v1/hub`, `/api/v1`) và các lời gọi fetch giữ nguyên định dạng JSON — không đổi.
- **Hết tình trạng đăng nhập từ ứng dụng đồng hành thỉnh thoảng bị từ chối:** mã đăng nhập một lần trước đây chỉ nằm trong bộ nhớ của một tiến trình, nên khi Data Hub chạy nhiều tiến trình, một phần lượt đăng nhập bị báo "mã không hợp lệ hoặc đã hết hạn" dù mã còn tốt. Mã nay lưu tập trung nên đăng nhập ổn định. Kèm theo: đăng xuất khỏi Data Hub vô hiệu hóa ngay các mã đăng nhập còn treo.

### API
- `POST /v1/auth/exchange` trả thêm `refresh_token`; thêm `POST /v1/auth/refresh` để đổi vé gia hạn lấy vé truy cập mới, không cần thao tác người dùng. Bổ sung thuần, tương thích ngược hoàn toàn — không truyền gì mới thì phản hồi giữ nguyên. Chi tiết: `docs/API_CHANGELOG.md` (2026-07-10, Additive).

## [0.19.0] — 2026-06-18
### API
- **Ghép PDF tờ khai nhanh hơn + chia nhỏ vừa cổng Ecosys cũ:** endpoint `download.pdf` (bản Bearer cho CO và bản cookie cho thao tác viên) thêm 2 tham số tùy chọn:
  - `quality` — `print` (mặc định, giữ nguyên) hoặc `compact` (dedup không mất dữ liệu: gộp font trùng giữa các tờ khai + nén lại content stream, giảm ~9% trên tờ khai thật, không bao giờ lớn hơn `print`).
  - `max_part_bytes` — khi PDF ghép vượt ngưỡng, trả về ZIP nhiều phần `...-part-NNN.pdf` cắt theo ranh giới từng tờ khai (không cắt giữa tờ khai), mỗi phần ≤ ngưỡng; tờ khai đơn lẻ vượt ngưỡng được gắn cờ `X-Pdf-Oversize-Nos`. Phục vụ giới hạn ~2 MB của cổng Ecosys.
- Render các bản chưa có trong cache giờ chạy **song song** (đo được ~2.8× trên tập nặng); thêm header `X-Render-Ms`, `X-Render-CacheHits/Misses`, `X-Pdf-Bytes/Parts/Quality`.
- **Tương thích ngược tuyệt đối:** không truyền tham số mới → phản hồi giống y như trước (byte-for-byte). Header mới chỉ bổ sung. Chi tiết: `docs/API_CHANGELOG.md` (2026-06-18, Additive).

## [0.18.0] — 2026-06-14
### API
- **Đọc NXT / chốt tồn kho theo trang + lọc:** thêm endpoint `/v1/hub` lấy danh sách dòng có phân trang cho từng bảng NXT và từng bản chốt tồn kho (phục vụ artifact lớn như SAP MB5B ~20k dòng), kèm lọc theo mã / vai trò / kho và tổng số dòng chính xác. Lọc danh sách NXT theo năm quyết toán, danh sách chốt tồn kho theo năm. Hai endpoint trả toàn bộ dòng cũ giữ nguyên (additive). Chi tiết: `docs/API_CHANGELOG.md` (2026-06-14, Additive).

## [0.17.0] — 2026-06-14
### Mới
- **NXT theo năm quyết toán:** mỗi khách hàng một bảng NXT cho mỗi năm; bắt buộc nhập "Năm quyết toán" khi tải lên, tải lại cùng năm sẽ thay thế bản cũ. Chốt tồn kho bắt buộc nhập "Ngày chốt".
- **Xem dữ liệu đã ingest:** trang chi tiết cho từng bảng NXT và từng bản chốt tồn kho — xem toàn bộ dòng (có phân trang), tồn cuối suy ra / chênh lệch (sổ sách vs thực đếm) được tô khi lệch; click cả hàng ở danh sách để mở chi tiết. Danh sách NXT thêm cột "Năm".
- **Liên kết sang Danh Mục:** mã trong bảng NXT / chốt tồn kho link sang trang chi tiết của mã đó ở Danh Mục (khi mã có trong danh mục).

### API
- `/v1/hub` NXT (danh sách + chi tiết) thêm trường `period_year`. Chi tiết: `docs/API_CHANGELOG.md` (2026-06-14, Additive).

## [0.16.0] — 2026-06-14
### Mới
- Quản lý dữ liệu **Nhập-Xuất-Tồn (NXT)** và **Chốt tồn kho cuối kỳ**: nhóm "Quyết toán" mới trong view khách hàng, luồng tải lên → xem trước → xác nhận cho cả hai loại; tồn cuối / chênh lệch (sổ sách vs thực đếm) tự tính khi xem.
- Mẫu chuẩn hệ thống tải về cho NXT (3 sheet NVL/TP/BTP) và chốt tồn kho.
- Parser linh hoạt nhận nhiều định dạng ERP có sẵn: EZSOFT/3TSoft (Growatt), SAP MB5B (Johnson), MISA "Cân đối tồn kho" (Hồng Phúc/An), kiểm kê đa-kho (DKE) — tự nhận diện định dạng. Định dạng lạ: gán cột qua giao diện (có gợi ý bằng LLM), hệ thống ghi nhớ cho các lần sau.
- Trang quản trị "Adapter Quyết toán": xem các parser đã đăng ký và đặt parser mặc định theo từng khách hàng.

### API
- Thêm endpoint đọc cho hệ thống quyết toán (BCQT): danh sách/chi tiết NXT, danh sách/chi tiết chốt tồn kho, và đối chiếu tồn-cuối ↔ đầu-kỳ ↔ kiểm kê theo từng mã. Chi tiết: `docs/API_CHANGELOG.md` (2026-06-14, Additive).

## [0.15.0] — 2026-06-14
### Mới
- Trang chi tiết cho từng lần tải lên: metadata đầy đủ (người tải, SHA-256, kích thước, số dòng, kết quả parse), nút tải lại file gốc, và xem trước nội dung file (50 dòng đầu của xlsx/xls/csv) ngay trên trình duyệt.
- Bảng dữ liệu: click vào cả hàng để mở trang chi tiết (BCCT, Danh mục, BOM, Đề xuất, Tờ khai, Tải lên) thay vì phải bấm icon nhỏ ở cuối hàng.

### Cải tiến
- Điều hướng trong view khách hàng gom lại thành 3 nhóm domain (Danh mục · Hải quan · BOM); "Đề xuất" chuyển vào nhóm BOM cùng Định mức / Cần xử lý / Hệ số quy đổi.
- Trang Tải lên: thêm cột "Người tải" và Việt hoá nhãn trạng thái.
- Làm rõ chiều hệ số quy đổi UoM ở mọi nơi staff nhìn: gợi ý trên trang hệ số, tooltip cột, và sheet "Hướng dẫn" của template import. Quy ước: hệ số = 1 đơn vị "Từ" quy ra bao nhiêu đơn vị "Sang"; số lượng (Sang) = số lượng (Từ) × hệ số.
- Bước materialize BOM cảnh báo khi một mã leaf nhận nhiều đơn vị quy về canonical khác nhau (vd g và kg), tránh cộng số lượng khác đơn vị trước khi quy đổi.

### Sửa lỗi
- Trang hệ số quy đổi UoM: ô xem trước không còn hiện ra thành một ô trống vô duyên khi chưa nhập đủ "Từ UoM / Sang UoM / Hệ số" (CSS `display` đè lên thuộc tính `hidden`).
- Quy đổi UoM: khi chỉ khai hệ số một chiều (vd B→A), bước làm phẳng BOM nay tự suy chiều ngược (lấy nghịch đảo) — trước đây panel danh mục/cảnh báo báo "quy đổi được" nhưng làm phẳng vẫn báo thiếu hệ số.
- Template import hệ số UoM: sửa dòng mẫu bị ngược (EA→SETS hệ số 4 ⇒ nay là SETS→EA hệ số 4, khớp ghi chú "1 SETS = 4 EA").

## [0.14.0] — 2026-06-14
### Mới
- Phân loại "khả năng khai báo" (`customs_relevance`) cho từng dòng leaf của BOM — declarable / declarable_unmatched / non-declarable — theo mô hình hai lớp: (1) bằng chứng nhập khẩu từ BCCT (tổng quát, không cần cấu hình); (2) bản đồ Material Group theo từng khách hàng (tùy chọn, để gom rác). Cho phép lọc mềm dòng non-declarable khỏi bảng kê bằng cờ `exclude_non_declarable` theo từng khách hàng (mặc-định-OFF, không xóa gì — BOM bất biến). (mig 078/079)
- Quản lý "module" adapter BOM: trang Adapter BOM (registry) chỉ-xem liệt kê các parser đã đăng ký + tín hiệu mỗi adapter phát ra; UI bản đồ Material Group theo khách hàng; gán adapter mặc định theo từng khách hàng. (mig 080/081)
- Trang Khách hàng: ô tìm kiếm tức thì (lọc theo tên · mã · MST), badge chế độ khớp mã bằng tiếng Việt, lưới module thu gọn thành dải chip.
- Thanh điều hướng admin gom nhóm dùng chung mọi trang admin (Người dùng · Dữ liệu tham chiếu · Adapter BOM · Hệ thống), tự sáng mục đang mở; trang "Cài đặt embedding" trước đây mồ côi nay đã có lối vào.

### Cải tiến
- Việt hoá giao diện: nhãn tab (Tổng quan / Tải lên / Đề xuất / Cấu hình), chế độ khớp mã + chế độ duyệt hiển thị bằng tiếng Việt thay cho mã enum thô (batch_aggregate_resolution → "Gộp theo lô", …), bỏ tiếng Anh lẫn lộn trong mô tả module + đề xuất + tải lên.
- Top nav dọn gọn: nav khu vực dạng chữ bên trái (Khách hàng · Quản trị), bên phải gộp tên/vai trò/đổi ngôn ngữ/đăng xuất vào một menu avatar; bỏ breadcrumb (tên khách hàng đã nằm ở tiêu đề trang).

### Sửa lỗi
- BOM: chọn adapter dạng cây (sap_indented_walk / multi_sheet_per_root) qua binding theo khách hàng hoặc dropdown thủ công nay đi đúng đường raw_graph + materialize; trước đây bị lưu phẳng (manual_flat) và bỏ qua flatten (MPL0100-39).

## [0.13.1] — 2026-06-08
### Mới
- Thiết kế lại trang chuẩn ĐVT toàn cục + trang hệ số quy đổi theo từng khách hàng; bảng hệ số có phân trang.
- Panel "lệch ĐVT" trên trang chi tiết vật tư: phân loại tương đương / quy đổi được / cần xác nhận / không quy đổi được.

### Cải tiến
- Cảnh báo lệch ĐVT nhận biết khả năng quy đổi: BOM khác BCCT, hay các dòng BCCT khác nhau, đều được chấp nhận nếu quy đổi về nhau được (cùng họ đơn vị, có hệ số khách hàng, hoặc alias) — chỉ báo khi thật sự không quy đổi được. Hết báo động giả cho kg/g, m/cm, SETS/PCS.
- Cờ "BOM cũ" (staleness) chỉ bật khi ĐVT giữa BOM và danh mục không quy đổi được. Sửa ĐVT danh mục theo kiểu quy-đổi-được (ví dụ kg→g) không còn báo nhầm BOM cũ; số lượng cần xử lý giảm, sát thực tế hơn.

## [0.13.0] — 2026-06-07
### Mới
- Trang "Có gì mới" hiển thị nhật ký thay đổi cho mọi người dùng.
- Hiển thị phiên bản ứng dụng (semver + mã commit) ở chân trang.
- Endpoint GET /version công bố phiên bản đang chạy.
- Khối tóm tắt BOM trên /source-summary (độ phủ xuất khẩu).

### Cải tiến
- Đồng bộ giao diện với hệ thiết kế "Primer console" của Barry CO.
- Dấu hiệu nhận diện ứng dụng: monogram xanh lá + khung viền 4 cạnh.
- Xếp hạng adapter theo điểm khớp; cảnh báo vật tư đa vai trò khi tải lên.
- Thông báo lỗi phân tích thân thiện hơn.

## [0.12.0] — 2026-06-06
### Mới
- Gộp tờ khai TKN/TKX thành một PDF chuẩn in (download.pdf).
- Nút "Render PDF còn thiếu" chạy nền.
- Tự phục vụ thu hồi phiên bản BOM + xóa upload lỗi.

### Cải tiến
- Surface các tờ khai đã đăng ký nhưng thiếu file gốc.

### Sửa lỗi
- Bắt buộc đăng nhập và chặn CDN cache khi tải file tờ khai (rò rỉ truy cập).

## [0.11.0] — 2026-06-05
### Mới
- Tìm kiếm khớp cả mã linh kiện/NVL, không chỉ mã sản phẩm.
- Tự động ánh xạ cột cho file tin cậy, bỏ qua bước map thủ công.
- Cấu hình alias cột theo từng khách hàng + trang quản trị.
- Hỗ trợ file không có dòng tiêu đề (ánh xạ theo vị trí cột).

### Cải tiến
- Adapter dạng cây tải lên thành raw_graph thay vì flat.
- Lưới phát hiện bất thường khi cột giá bị đảo; phản hồi upload trung thực hơn.

## [0.10.0] — 2026-05-31
### Mới
- Endpoint gộp POST /v1/hub/products/bom/artifacts:batch (gom ~150 lệnh gọi của CO còn 1).
- Quản lý token tài khoản dịch vụ: chọn/hiển thị hạn + tự gia hạn trượt.
- Kéo dữ liệu tăng dần cho CO (`since` + `include_tombstones`).
- Bản mirror Bearer của declarations download.zip.

### Gỡ bỏ
- Bỏ URL alias BOM vocab v1 (308 → 404) — thay đổi phá vỡ.
- Bỏ cột không dùng materials.category_override / override_reason — thay đổi phá vỡ.

## [0.9.0] — 2026-05-27
### Mới
- Chuỗi thời gian BCCT theo từng vật tư trên trang chi tiết.
- Tải lên hàng loạt qua ZIP (XLS/PDF theo từng tờ khai).
- Mô hình staleness có điều kiện + cột trạng thái; trang "cần xử lý" theo cụm.
- Cột NK/BOM-only + xuất Excel trên trang artifact phẳng.

### Cải tiến
- Gom near-duplicate tên hàng để giảm nhiễu drift; backup đầy đủ + restore drill.

## [0.8.0] — 2026-05-15
### Mới
- Nhập BOM khai hải quan theo Mẫu 16 (manual_flat).
- Hàng đợi rà soát xung đột tại /catalog/conflicts.
- Trạng thái file tờ khai + tải ZIP hàng loạt cho CO.

### Cải tiến
- Bulk materialize + nhập Mẫu 16 đều áp quy đổi UoM và phát tín hiệu drift.

## [0.7.0] — 2026-05-12
### Mới
- Onboarding Johnson: tờ khai, AI danh mục, vật tư thay thế, việc nền.
- Endpoint bcct/by-codes cho CO suy ra tồn kho thay thế.

### Cải tiến
- Hợp nhất materials.unit → uom (mã chuẩn duy nhất).
- Dedup các lát BTP đa vị trí; mirror tra cứu vật tư thay thế tại /v1/hub/* (Bearer cho CO).

### Sửa lỗi
- Parser SAP-indented lấy đúng lượng theo từng cha (MENGE), không lấy lũy kế (MNGKO).

## [0.6.0] — 2026-05-10
### Mới
- Multi-source: provenance, audit, vai trò dual-source, "mã chờ duyệt".
- Cổng kiểm UoM drift tại thời điểm nhập (BOM + BCCT), 3 mức nghiêm trọng.
- Track D — cờ phụ thuộc lỗi thời (staleness) + tuyến refresh; refresh quy đổi UoM theo chính sách 3 tầng.
- lineage_root_id định danh tuple phiên bản logic.

### Cải tiến
- Dọn từ vựng (template + i18n); admin UI cho client_uom_overrides; harness bất biến thứ tự nhập.

## [0.5.0] — 2026-05-08
### Mới
- Bộ định danh sản phẩm/vật tư chuẩn + hàng đợi rà soát.
- Engine luật phân tích cấu hình theo từng khách hàng.
- Phân loại btp_sourcing + UI danh mục + huy hiệu đa vai trò.
- View vai trò vật tử (v_material_roles) + cảnh báo xung đột toàn vẹn.

### Cải tiến
- Đẩy payload JSONB → cột định kiểu (Tier 1/2) + cắt khóa trùng; resolver Stage 2 (bóc trong ngoặc) thắng Stage 1.

## [0.4.0] — 2026-05-06
### Mới
- Mô hình BOM v3 ba shape + pipeline nhập theo lô nhà cung cấp.
- Xuất/nhập theo từng khách hàng + cờ dữ liệu tham chiếu.
- Nhãn cha người-đọc-được + panel lineage trong UI phiên bản.

### Cải tiến
- Phát hiện BTP cho dạng Johnson (cây sâu theo file nhà cung cấp); giữ first_seen, demote có kiểm soát.

## [0.3.0] — 2026-05-04
### Mới
- Phân trang + sắp xếp + tìm kiếm cho mọi bảng dữ liệu (BCCT, danh mục, BQD, BOM).
- Stack Docker Compose cho demo + backup nhận biết Compose.

### Cải tiến
- Connection pool psycopg (reset khi trả kết nối); lưu raw edges kỹ thuật.

## [0.2.0] — 2026-05-03
### Mới
- Engine flatten BOM thuần + thư viện UoM + phân loại + định danh.
- Registry adapter BOM cắm-được; nhập technical_flatten + preview thiết kế lại.
- Luồng ánh xạ hợp nhất (catalog / BQD / BOM manual_flat / BCCT).
- Rà soát đề xuất thủ công + hybrid; kill-switch API auth chỉ cho dev.

### Sửa lỗi
- Cắt đuôi .0 ở các trường khóa BCCT; backfill 6 cột BCCT bị parser cũ gán sai.

## [0.1.0] — 2026-04-30
### Mới
- Bản scaffold đầu tiên: quản lý hồ sơ khách hàng, danh mục NVL/SP/BTP,
  BOM, tờ khai hải quan (BCCT), đăng nhập SSO.
