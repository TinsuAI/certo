# Xác Nhận Logic Nghiệp Vụ C/O

**Mục đích**: Rà soát và xác nhận lại logic nghiệp vụ làm `C/O` với Đại lý, dựa trên quy trình hiện tại, workbook đang vận hành, và các bộ hồ sơ đã hoàn thiện.

**Phạm vi**: Tài liệu này tập trung vào nghiệp vụ `Certificate of Origin (C/O)` như đang được quan sát từ:
- quy trình xin C/O đang lưu trong repo
- workbook đang dùng để xử lý dữ liệu và chứng minh xuất xứ
- các hồ sơ đã hoàn thiện của `Growatt`, `Do Thanh`, `Hong An`

Trọng tâm là:
- logic hồ sơ
- logic tái sử dụng chứng cứ
- logic xác định xuất xứ
- logic phân bổ và theo dõi `tồn C/O (CO stock)` trong workbook

Tài liệu này nhằm xác nhận cách Đại lý đang làm hiện nay.
Tài liệu này không giả định rằng mọi loại mẫu C/O, mọi hiệp định, hoặc mọi loại hồ sơ đều đang đi cùng một logic.

**Chưa bao gồm đầy đủ**:
- đối chiếu chi tiết từng loại mẫu C/O theo toàn bộ FTA
- kết luận pháp lý cuối cùng cho từng hiệp định
- đặc tả phần mềm hoặc quy trình triển khai hệ thống

**Cách dùng**: Mỗi mục là một khẳng định hoặc một câu hỏi mở. Quý Công ty vui lòng đánh dấu `☐ Đúng / ☐ Sai` hoặc ghi chú bổ sung để xác nhận cách hiểu nghiệp vụ hiện tại.

---

## Phần 1 — Khái Niệm Cơ Bản

### 1.1 C/O là gì trong thực tế vận hành

#### 1.1.1 — C/O được cấp theo từng lô hàng xuất khẩu

Một `C/O` không phải là hồ sơ đăng ký sản phẩm chung, mà là chứng từ được cấp cho một lô hàng xuất khẩu cụ thể.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 1.1.2 — C/O không chỉ là bộ chứng từ nộp hồ sơ

Để ra được kết quả `C/O`, nghiệp vụ thực tế gồm cả:
- chuẩn bị hồ sơ
- xác định tiêu chí xuất xứ áp dụng
- chứng minh hàng hóa đạt tiêu chí đó
- nộp và theo dõi kết quả trên hệ thống cấp

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 1.1.3 — Logic C/O có ít nhất 4 lớp nghiệp vụ

Theo cách hiểu hiện tại, nghiệp vụ C/O nên tách thành 4 lớp:
- `Hồ sơ thương nhân (Trader profile registration)`
- `Hồ sơ xuất xứ sản phẩm (Product-origin evidence)`
- `Hồ sơ theo lô hàng (Shipment-level filing)`
- `Đánh giá xuất xứ và phân bổ (Origin evaluation and allocation)`

Trong đó, ngoài `Hồ sơ thương nhân`, 3 lớp còn lại có thể hiểu ngắn gọn như sau:
- `Hồ sơ xuất xứ sản phẩm`: là bộ bằng chứng ở cấp sản phẩm để giải thích vì sao một mã hàng có thể đạt xuất xứ theo một hiệp định / quy tắc cụ thể. Trong workbook Excel, đây là phần đang gom và đối chiếu thông tin nền như mã hàng, BOM / định mức, nguyên liệu đầu vào, chứng từ nguồn và điều kiện xuất xứ dự kiến.
- `Hồ sơ theo lô hàng`: là bộ hồ sơ nộp ra ngoài cho từng lần xin C/O, gắn với một lô xuất cụ thể. Trong workbook Excel, đây là phần đang theo dõi lô nào xuất ngày nào, số lượng bao nhiêu, đi theo bộ chứng từ nào, và cần lấy phần bằng chứng / nguyên liệu nào để chứng minh cho đúng lô đó.
- `Đánh giá xuất xứ và phân bổ`: là phần xử lý nội bộ để nối 2 lớp trên lại với nhau, tức quyết định lô này sẽ chứng minh xuất xứ theo cách nào và sẽ dùng phần nguồn nào để chứng minh. Trong workbook Excel, đây là phần đang tính, đối chiếu, phân bổ lượng / giá trị từ nguồn sang lô xuất, đồng thời giữ lịch sử đã dùng và phần còn lại.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 1.1.4 — `Đánh giá xuất xứ và phân bổ` là phần xử lý nội bộ đang diễn ra trong workbook Excel

Tên gọi này là cách tạm dùng để chỉ phần việc nội bộ đang làm trong Excel, chứ không phải tên một bộ hồ sơ có sẵn.

Cụ thể hơn, đây là bước:
- xác định lô hàng đang xin C/O thuộc hiệp định / mẫu C/O / quy tắc xuất xứ nào
- kiểm tra lô đó có đủ điều kiện hay không dựa trên BOM, nguyên liệu và chứng từ nguồn
- chọn đúng phần dữ liệu đầu vào sẽ dùng để chứng minh cho lô xuất cụ thể
- phân bổ phần đã dùng / còn lại để tránh trùng hoặc thiếu khi nhiều lô cùng dùng chung một nguồn
- cập nhật hoặc hoàn tác lịch sử khi có điều chỉnh

Nói ngắn gọn: nếu 3 lớp hồ sơ bên ngoài là `mình có những bộ hồ sơ gì`, thì `đánh giá xuất xứ và phân bổ` là `mình đang dùng các bộ hồ sơ đó trong workbook Excel như thế nào để ra được một bộ C/O cho từng lô hàng`.

Theo cách hiểu hiện tại từ workbook:
- các sheet / logic kiểu `X-N` đang đóng vai trò nơi gắn lô xuất với phần nguồn dùng để chứng minh
- các sheet / logic kiểu `Save` và `Tru lui` đang giữ dấu vết phân bổ tiến / lùi, tức đã dùng bao nhiêu, hoàn lại bao nhiêu, còn lại bao nhiêu

Có thể hiểu mục này tương đương với `phần tính và phân bổ chứng từ / nguyên liệu để chứng minh xuất xứ cho từng lô`.

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 1.2 Ba lớp hồ sơ bên ngoài

#### 1.2.1 — Hồ sơ đăng ký thương nhân là dữ liệu cấp doanh nghiệp

Đây là lớp thông tin doanh nghiệp dùng để đủ điều kiện nộp hồ sơ trên eCoSys hoặc hệ thống cấp tương đương, không phải dữ liệu riêng của từng lô hàng.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 1.2.2 — Hồ sơ xuất xứ sản phẩm là dữ liệu cấp sản phẩm

Đây là lớp bằng chứng giải thích vì sao một sản phẩm hoặc nhóm sản phẩm có thể đạt tiêu chí xuất xứ theo một quy tắc / hiệp định cụ thể.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 1.2.3 — Hồ sơ xin C/O là dữ liệu cấp lô hàng

Mỗi lô hàng vẫn cần hồ sơ riêng gồm tờ khai xuất, hóa đơn, phiếu đóng gói, vận đơn, mẫu C/O, đơn đề nghị và các chứng từ liên quan.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 1.2.4 — Ba lớp này không nên gộp thành một khối duy nhất

Nếu gộp chung toàn bộ thành một loại hồ sơ duy nhất, sẽ khó tách bạch phần chứng cứ của sản phẩm với phần dữ liệu thay đổi theo từng lô hàng.

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 1.3 Khái niệm “hàng có xuất xứ Việt Nam”

#### 1.3.1 — “Có xuất xứ Việt Nam” không đồng nghĩa “mọi đầu vào đều từ Việt Nam”

Các hồ sơ đã hoàn thiện cho thấy vẫn có nhiều đầu vào `Không xuất xứ`, nhưng thành phẩm vẫn được kết luận đạt xuất xứ theo quy tắc áp dụng.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 1.3.2 — Kết luận xuất xứ là kết luận theo quy tắc áp dụng

Hiểu đúng hơn là:
- hàng được sản xuất tại Việt Nam
- và đáp ứng quy tắc của hiệp định tương ứng

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 1.3.3 — Cùng một doanh nghiệp hoặc nhóm sản phẩm có thể đi theo nhiều quy tắc khác nhau

Các hồ sơ thực tế đã cho thấy cùng nhóm sản phẩm vẫn có thể dùng `CTH`, `CC`, `PSR`, hoặc `RVC + CTSH` tùy trường hợp.

> ☐ Đúng / ☐ Sai
> Phản hồi:

---

## Phần 2 — Đăng Ký Thương Nhân

### 2.1 Vai trò của hồ sơ đăng ký thương nhân

#### 2.1.1 — Doanh nghiệp phải có hồ sơ thương nhân hợp lệ trước khi nộp hồ sơ C/O

Theo cách hiểu hiện tại từ quy trình và tài liệu pháp lý đã đối chiếu, đây là bước điều kiện đầu vào trước khi nộp hồ sơ cho lô hàng.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 2.1.2 — Hồ sơ thương nhân là dữ liệu dùng lại được

Hồ sơ này không cần lập lại cho từng lô hàng nếu thông tin doanh nghiệp chưa thay đổi và trạng thái trên hệ thống vẫn còn hiệu lực.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 2.1.3 — Thông tin điển hình trong hồ sơ thương nhân

Theo quy trình hiện tại, hồ sơ thương nhân thường bao gồm:
- thông tin doanh nghiệp
- đăng ký kinh doanh / mã số thuế
- mẫu dấu
- mẫu chữ ký người có thẩm quyền
- danh sách cơ sở sản xuất

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 2.2 Chu kỳ hiệu lực và cập nhật

#### 2.2.1 — Hồ sơ thương nhân phải cập nhật khi thông tin thay đổi

Nếu thay đổi về pháp nhân, người ký, mẫu dấu, cơ sở sản xuất hoặc thông tin nền tảng khác, doanh nghiệp phải cập nhật trước khi nộp hồ sơ mới.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 2.2.2 — Hồ sơ thương nhân có cần rà soát hoặc xác nhận lại theo chu kỳ hay không

Nếu có, đề nghị Quý Công ty xác nhận rõ:
- có áp dụng chu kỳ hiệu lực hay không
- mốc thời gian đang áp dụng trong thực tế là bao lâu
- trường hợp nào phải làm mới dù chưa hết chu kỳ

> Phản hồi:

#### 2.2.3 — Đại lý hiện đang áp dụng chu kỳ nào cho hồ sơ thương nhân

Đề nghị trả lời theo cách vận hành thực tế hiện nay, kể cả khi khác với cách hiểu từ văn bản pháp lý.

> Phản hồi:

### 2.3 Vấn đề cần xác nhận thêm

#### 2.3.1 — Hồ sơ thương nhân được theo dõi tập trung hay theo từng nhân viên xử lý

Nếu một doanh nghiệp làm nhiều hồ sơ, Đại lý đang quản lý trạng thái hồ sơ thương nhân ở đâu và ai chịu trách nhiệm cập nhật?

> Phản hồi:

#### 2.3.2 — Mỗi doanh nghiệp có thể có nhiều cơ sở sản xuất / người ký không

Nếu có, quy tắc chọn đúng cơ sở sản xuất / người ký cho từng mẫu hoặc từng lô hàng hiện nay đang được kiểm soát thế nào?

> Phản hồi:

---

## Phần 3 — Hồ Sơ Xuất Xứ Sản Phẩm

### 3.1 Bản chất của lớp hồ sơ này

#### 3.1.1 — Đây không phải là bộ hồ sơ C/O nộp riêng cho từng sản phẩm

Theo cách hiểu hiện tại, đây là lớp bằng chứng cấp sản phẩm hoặc nhóm sản phẩm.
Bộ bằng chứng này được gắn vào hồ sơ C/O của từng lô hàng khi phù hợp, thay vì là một bộ hồ sơ nộp riêng cho từng sản phẩm.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 3.1.2 — Hồ sơ sản phẩm có thể tái sử dụng khi sản phẩm ổn định

Nếu sản phẩm không đổi và quy tắc áp dụng không đổi, Đại lý không cần dựng lại toàn bộ bộ chứng cứ từ đầu cho từng lô hàng.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 3.1.3 — Hồ sơ sản phẩm cần có phiên bản / lịch sử thay đổi

Khi BOM, quy trình, nhà cung cấp, mã HS hoặc quy tắc áp dụng thay đổi, bộ chứng cứ cũ có thể không còn đủ để đại diện cho trạng thái sản phẩm mới.

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 3.2 Thành phần điển hình của hồ sơ sản phẩm

#### 3.2.1 — Hồ sơ sản phẩm thường bao gồm BOM / định mức

Đây là một trong những nền tảng để chứng minh cấu thành của thành phẩm và hỗ trợ đánh giá quy tắc xuất xứ.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 3.2.2 — Quy trình sản xuất là tài liệu quan trọng

Các trường hợp thực tế cho thấy tài liệu quy trình sản xuất thường được dùng để chứng minh có công đoạn gia công / chế biến đủ điều kiện tại Việt Nam.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 3.2.3 — Hồ sơ sản phẩm có thể cần tờ khai nhập và hóa đơn VAT đầu vào

Tùy quy tắc và cơ cấu nguồn đầu vào, hồ sơ có thể cần:
- tờ khai nhập
- hóa đơn VAT mua nội địa
- khai báo của nhà cung cấp / nhà sản xuất
- C/O đầu vào khi liên quan

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 3.2.4 — Tiêu chí áp dụng là một phần của hồ sơ sản phẩm

Hồ sơ sản phẩm không chỉ là tập file nguồn, mà còn phải chỉ ra sản phẩm đang được đánh giá theo quy tắc nào, ví dụ:
- `RVC`
- `CTH`
- `CTSH`
- `CC`
- `PSR`
- quy tắc kết hợp như `RVC 35% + CTSH`

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 3.3 Chu kỳ tái sử dụng

#### 3.3.1 — Với sản phẩm cố định, một số chứng từ có thể dùng lại trong khoảng thời gian nhất định

Theo cách hiểu hiện tại, các tài liệu như bản khai báo tiêu chí, quy trình sản xuất, khai báo nhà sản xuất / nhà cung cấp có thể được dùng lại nếu các dữ kiện nền chưa thay đổi.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 3.3.2 — Đại lý hiện đang áp dụng mốc hiệu lực nào cho bộ hồ sơ sản phẩm

Đề nghị trả lời theo cách vận hành thực tế:
- có giới hạn thời gian tái sử dụng hay không
- nếu có thì là bao lâu
- tài liệu nào được dùng lại và tài liệu nào phải lập mới

> Phản hồi:

#### 3.3.3 — Những thay đổi nào buộc phải lập lại hồ sơ sản phẩm

Theo vận hành thực tế, những thay đổi nào dưới đây làm bộ hồ sơ sản phẩm cũ không còn dùng được:
- đổi BOM
- đổi quy trình sản xuất
- đổi nguồn cung / nhà cung cấp
- đổi mã HS thành phẩm
- đổi hiệp định hoặc đổi loại mẫu C/O

> Phản hồi:

---

## Phần 4 — Hồ Sơ Theo Lô Hàng Và Nộp C/O

### 4.1 Bản chất của hồ sơ theo lô hàng

#### 4.1.1 — Mỗi lô hàng vẫn cần hồ sơ riêng ngay cả khi sản phẩm không đổi

Việc tái sử dụng hồ sơ sản phẩm không làm mất đi yêu cầu phải nộp bộ chứng từ riêng cho từng lô hàng xuất khẩu.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 4.1.2 — Bộ hồ sơ theo lô hàng là nơi gắn bằng chứng sản phẩm vào một giao dịch xuất khẩu cụ thể

Nói cách khác, hồ sơ theo lô hàng là lớp kết nối giữa:
- lô hàng thực tế
- loại mẫu C/O / hiệp định mục tiêu
- bằng chứng xuất xứ của sản phẩm

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 4.2 Chứng từ điển hình theo lô hàng

#### 4.2.1 — Tờ khai xuất khẩu là chứng từ lõi của lô hàng

Các bộ hồ sơ hoàn chỉnh đều cho thấy tờ khai xuất là một trong những đầu vào trung tâm của từng trường hợp.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 4.2.2 — Hóa đơn, phiếu đóng gói, vận đơn là bộ chứng từ chuẩn của lô hàng

Đây là nhóm chứng từ xuất hiện lặp lại trong các hồ sơ hoàn thiện đã kiểm tra.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 4.2.3 — Đơn đề nghị và mẫu C/O là bộ chứng từ nộp cấp lô hàng

Chúng không thay thế chứng cứ sản phẩm, mà là phần hồ sơ chính thức để nộp và nhận kết quả cấp.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 4.2.4 — Một lô hàng có thể kéo theo nhiều bảng chứng minh ở cấp mã hàng / sản phẩm

Trường hợp Growatt cho thấy cùng một lô hàng có thể chứa nhiều mã hàng và mỗi mã hàng có bảng chứng minh hoặc kết luận riêng.

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 4.3 Kênh nộp và trạng thái

#### 4.3.1 — eCoSys là nền tảng nộp chính hiện tại

Theo các tài liệu quy trình đang dùng trong repo, đây là nền tảng vận hành chính cho đăng ký và nộp hồ sơ điện tử.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 4.3.2 — Chữ ký số là yêu cầu vận hành bắt buộc

Hồ sơ điện tử không chỉ là upload file mà còn gắn với hành vi ký số và theo dõi trạng thái trên hệ thống.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 4.3.3 — Điện tử và giấy là hai luồng vận hành khác nhau

Không nên giả định rằng “nộp điện tử” có nghĩa là không còn chứng từ bản giấy hoặc mẫu in màu trong mọi trường hợp.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 4.3.4 — Những trạng thái lô hàng nào Đại lý đang theo dõi thực tế

Ví dụ: soạn hồ sơ, chờ bổ sung, đã nộp, bị yêu cầu sửa, đã cấp, đã in, đã lưu hồ sơ.

> Phản hồi:

---

## Phần 5 — Nguồn Dữ Liệu Và Chứng Từ Đầu Vào

### 5.1 Nguồn dữ liệu nghiệp vụ

#### 5.1.1 — Dữ liệu C/O không chỉ đến từ bộ hồ sơ xuất khẩu

Để xác định xuất xứ, Đại lý phải dùng kết hợp nhiều nguồn:
- chứng từ xuất khẩu
- chứng từ nhập khẩu
- BOM / định mức
- quy trình sản xuất
- khai báo nguồn gốc đầu vào
- workbook lịch sử phân bổ

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 5.1.2 — Hồ sơ đã hoàn thiện là nguồn tham chiếu để kiểm chứng cách áp dụng quy tắc trong thực tế

Hồ sơ đã làm xong giúp đối chiếu xem quy tắc được áp dụng ra sao trong các tình huống thực tế, nhưng không thay thế được bản thân quy tắc chuẩn hay logic vận hành trong workbook.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 5.1.3 — Workbook hiện tại là nguồn sự thật vận hành cho phần phân bổ / truy vết

Nếu muốn hiểu đúng cách vận hành hiện tại, không thể bỏ qua logic trong workbook vì đây là nơi đang giữ lịch sử sử dụng đầu vào và kết quả tính toán.

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 5.2 Nhóm dữ liệu đầu vào cho tính toán

#### 5.2.1 — Tờ khai nhập là nguồn đầu vào quan trọng cho xuất xứ truy vết của vật tư

Trong workbook hiện tại, mức chi tiết đang bám theo dòng nguồn nhập, không chỉ theo mã vật tư tổng hợp.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 5.2.2 — BOM và quy trình sản xuất là cầu nối giữa nguồn đầu vào và thành phẩm

Không có lớp dữ liệu này thì khó giải thích vì sao cùng một tập vật tư lại tạo ra thành phẩm đủ điều kiện theo quy tắc cụ thể.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 5.2.3 — Dữ liệu giá trị / FOB / CIF là bắt buộc khi quy tắc có yếu tố tỷ lệ giá trị

Ví dụ với `RVC` hoặc `LVC`, chỉ có mapping vật tư là chưa đủ.

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 5.3 Vấn đề cần xác nhận

#### 5.3.1 — Đại lý hiện yêu cầu khách cung cấp file chuẩn nào cho một hồ sơ C/O mới

Đề nghị liệt kê theo nhóm:
- nhóm hồ sơ thương nhân
- nhóm hồ sơ xuất xứ sản phẩm
- nhóm hồ sơ theo lô hàng
- nhóm nguồn nguyên liệu / giá trị / file workbook hỗ trợ

> Phản hồi:

#### 5.3.2 — Có trường hợp khách chỉ có dữ liệu Excel thủ công không

Nếu có, Đại lý đang xử lý việc chuẩn hóa dữ liệu đó như thế nào trước khi đưa vào workbook / logic tính?

> Phản hồi:

#### 5.3.3 — Với đầu vào mua trong nước, hiện đang dùng bộ chứng từ nào để chứng minh nguồn

Đề nghị làm rõ các trường hợp đang dùng:
- hóa đơn VAT mua nội địa
- khai báo của nhà cung cấp / nhà sản xuất
- tờ khai nhập ở chuỗi trước
- C/O đầu vào
- tổ hợp nhiều chứng từ

Đồng thời cho biết các dữ liệu này hiện có được đưa vào workbook hay đang được theo dõi ngoài workbook.

> Phản hồi:

---

## Phần 6 — Workbook Và Logic Phân Bổ

### 6.0 Thuật ngữ dùng trong phần này

- `Tồn C/O (CO stock)`: lượng đầu vào còn có thể dùng trong mô hình chứng minh xuất xứ của workbook.
- `Tồn kho vật lý`: lượng tồn kho theo kho thực tế hoặc theo kế toán nội bộ.
- `Phân bổ`: gắn nhu cầu của một lô hàng xuất với các dòng nguồn đầu vào đã có.
- `Trừ lùi`: cách gọi hiện tại cho thao tác giảm trừ / hoàn nguyên / điều chỉnh lịch sử; ý nghĩa nghiệp vụ chính xác vẫn cần Quý Công ty xác nhận thêm.
- `Dòng nguồn (source row)`: một dòng đầu vào cụ thể; theo quan sát hiện tại, tối thiểu đang bám tới `số tờ khai + dòng hàng + mã vật tư`.

### 6.1 Workbook hiện tại đang làm gì

#### 6.1.1 — Workbook không phải chỉ là file tổng hợp chứng từ

Workbook đang đóng vai trò:
- chuẩn hóa dữ liệu
- chọn đợt xử lý / nhóm xuất
- phân bổ nguồn đầu vào
- lưu lịch sử tiêu dùng
- tạo bảng chứng minh theo từng quy tắc

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 6.1.2 — Workbook là một hệ thống có trạng thái lịch sử

Kết quả của lô hàng hiện tại phụ thuộc vào lịch sử phân bổ trước đó, chứ không phải phép tính độc lập một lần.

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 6.2 Vai trò của các sheet chính

#### 6.2.1 — Theo cách hiểu hiện tại, `NK` / `NK2` là lớp chuẩn hóa phía nhập

Theo phân tích hiện tại, đây là nơi thể hiện và chuẩn hóa các dòng nguồn từ phía nhập khẩu / đầu vào.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 6.2.2 — Theo cách hiểu hiện tại, `XK` là lớp nguồn phía xuất

Đây là nguồn phục vụ xác định nhu cầu của lô hàng hoặc đợt xuất cần xử lý.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 6.2.3 — Theo cách hiểu hiện tại, `DM` / `Xuat` là lớp chọn đợt xử lý hiện tại

Workbook không tính toàn bộ mọi lô hàng cùng lúc, mà có cơ chế chọn nhóm / đợt xử lý trước khi phân bổ.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 6.2.4 — Theo cách hiểu hiện tại, `X-N` là sheet đối chiếu trung tâm

Đây là nơi quan hệ giữa nhu cầu xuất và lịch sử nguồn đầu vào được thể hiện rõ nhất.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 6.2.5 — Theo cách hiểu hiện tại, `Save` đang đóng vai trò sổ theo dõi phân bổ thuận

Theo kiểm tra sheet/XML hiện tại, `Save` lưu các dòng đã cấp phát từ một dòng nguồn sang một đợt xuất cụ thể.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 6.2.6 — Theo cách hiểu hiện tại, `Tru lui` đang đóng vai trò sổ theo dõi giảm trừ / hoàn nguyên / chuyển tiếp

Theo cách hiểu hiện tại, đây là lớp theo dõi lượng đã xuất, lượng còn lại, lượng dùng kỳ này và lượng để lại cho đợt sau.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 6.2.7 — Theo cách hiểu hiện tại, các sheet như `RVC`, `CTH`, `CTSH`, `EUR1` là nơi xuất ra bảng chứng minh theo quy tắc

Nếu cách hiểu này đúng, đây không chỉ là sheet trình bày mà là nơi thể hiện kết quả phân bổ và đánh giá quy tắc.

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 6.3 Mức chi tiết của `tồn C/O (CO stock)`

#### 6.3.1 — `Tồn C/O` đang được theo dõi theo dòng nguồn, không chỉ theo mã vật tư tổng hợp

Phân tích trực tiếp workbook cho thấy một mã vật tư có thể có nhiều nhóm tồn riêng theo từng dòng nguồn.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 6.3.2 — Granularity tối thiểu hiện thấy là `số tờ khai + dòng hàng + mã vật tư`

Đây là mức chi tiết tối thiểu đã quan sát được từ `NK2`, `Save`, `Tru lui`.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 6.3.3 — Việc tách theo dòng nguồn nhằm giữ khả năng truy vết, không phải chỉ để tính tồn tổng

Mục tiêu là biết lô hàng nào đã dùng nguồn nào, dùng bao nhiêu, còn lại bao nhiêu để phục vụ giải trình xuất xứ.

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 6.4 `Tồn C/O` và tồn kho vật lý

#### 6.4.1 — `Tồn` trong workbook không nên hiểu mặc định là tồn kho vật lý

Theo phân tích hiện tại, các trường `Tồn` trong workbook phản ánh lượng còn có thể dùng trong mô hình chứng minh xuất xứ / phân bổ, không nhất thiết là số tồn kho kế toán / kho thực.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 6.4.2 — `Tồn C/O` và `tồn kho vật lý` là hai khái niệm khác nhau

Chúng có thể liên quan và cần đối chiếu, nhưng không nên bị hiểu như một số dư duy nhất.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 6.4.3 — Có cần đối chiếu định kỳ giữa `tồn C/O` và tồn kho thực tế không

Nếu có, Đại lý hiện đang làm theo quy tắc nào và mức độ đối chiếu tới đâu?

> Phản hồi:

### 6.5 Điều chỉnh và hoàn nguyên

#### 6.5.1 — Workbook hiện có logic điều chỉnh / giảm trừ lịch sử

Sự tồn tại của `Tru lui` cho thấy hệ thống hiện tại không chỉ cộng dồn, mà còn có cơ chế sửa ngược hoặc điều chỉnh lượng đã phân bổ.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 6.5.2 — Điều chỉnh có thể ảnh hưởng đến các lô hàng sau

Vì sổ theo dõi này có tính lịch sử, một sửa đổi quá khứ có thể làm thay đổi lượng còn khả dụng cho những hồ sơ đi sau.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 6.5.3 — Những tình huống nào hiện nay buộc phải “trừ lùi” hoặc hoàn nguyên

Ví dụ:
- sửa lô hàng
- đổi lượng xuất
- loại một dòng nguồn
- làm lại bảng chứng minh theo quy tắc khác
- quay lui do hồ sơ bị bác / bị yêu cầu sửa

> Phản hồi:

---

## Phần 7 — Logic Xác Định Xuất Xứ

### 7.1 Bản chất của bộ quy tắc xuất xứ

#### 7.1.1 — Logic xác định xuất xứ hiện nay không chỉ có một công thức duy nhất

Các hồ sơ đã kiểm tra đủ để kết luận rằng không thể dùng một công thức duy nhất cho mọi trường hợp.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 7.1.2 — Quy tắc áp dụng có phụ thuộc vào `hiệp định áp dụng + trường hợp sản phẩm`

Không nên giả định rằng một sản phẩm luôn luôn dùng cùng một quy tắc trong mọi lô hàng.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 7.1.3 — Khi kết luận đạt / không đạt, Đại lý có cần lưu lại lý do và dữ liệu chứng minh hay không

Nếu có, đề nghị mô tả hiện nay Quý Công ty đang lưu phần giải thích đó ở đâu và ở mức chi tiết nào.

> Phản hồi:

### 7.2 Các nhóm quy tắc đã quan sát được

#### 7.2.1 — `RVC`

Đã quan sát được trường hợp dùng quy tắc giá trị khu vực, trong đó cần dữ liệu `FOB` và giá trị đầu vào không có xuất xứ.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 7.2.2 — `CTH`

Đã quan sát được trường hợp giày Hong An kết luận đạt `CTH`.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 7.2.3 — `CTSH`

Đã quan sát được trường hợp Do Thanh và trường hợp kết hợp với `RVC`.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 7.2.4 — `CC`

Đã quan sát được trường hợp Hong An đi theo `CC`.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 7.2.5 — `PSR`

Đã quan sát được trường hợp EUR.1 của Hong An đi theo `PSR`.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 7.2.6 — Quy tắc kết hợp như `RVC 35% + CTSH`

Đã quan sát được trường hợp Growatt sử dụng quy tắc kết hợp, nghĩa là trong thực tế có trường hợp phải đồng thời đáp ứng nhiều điều kiện.

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 7.3 Dữ liệu đầu vào theo từng loại quy tắc

#### 7.3.1 — Với `RVC`, cần dữ liệu giá trị của đầu vào không có xuất xứ

Không thể đánh giá `RVC` chỉ bằng BOM định lượng.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 7.3.2 — Với các quy tắc chuyển đổi mã số, cần so sánh HS của thành phẩm và đầu vào không có xuất xứ

Điểm cốt lõi là xác định mức chuyển đổi mã số theo quy tắc yêu cầu.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 7.3.3 — Với `PSR`, logic có thể đặc thù theo mã hàng / chương hàng

Đề nghị Quý Công ty xác nhận hiện nay `PSR` có đang được tra cứu riêng theo từng trường hợp hay không.

> Phản hồi:

#### 7.3.4 — Quy trình sản xuất là một phần của bằng chứng, không chỉ BOM

Các hồ sơ thực tế cho thấy tài liệu quy trình sản xuất có vai trò chứng minh công đoạn chuyển đổi tại Việt Nam.

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 7.4 Đầu vào không có xuất xứ

#### 7.4.1 — Việc có đầu vào `Không xuất xứ` là bình thường, không phải ngoại lệ

Các hồ sơ hoàn chỉnh đều cho thấy việc tồn tại đầu vào không có xuất xứ là rất phổ biến.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 7.4.2 — Khi có đầu vào không xuất xứ, kết luận đạt / không đạt vẫn phụ thuộc vào quy tắc áp dụng

Kết luận còn phụ thuộc vào quy tắc, công đoạn sản xuất và dữ liệu chứng minh đi kèm.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 7.4.3 — Đại lý hiện xác định `trạng thái xuất xứ` của từng đầu vào theo những nguồn nào

Ví dụ:
- tờ khai nhập
- VAT nội địa
- khai báo của nhà cung cấp
- khai báo của nhà sản xuất
- C/O đầu vào

> Phản hồi:

---

## Phần 8 — Các Mẫu Logic Đã Quan Sát Từ Hồ Sơ Thực Tế

### 8.1 Trường hợp Growatt

#### 8.1.1 — Một lô hàng có thể có nhiều mã hàng và mỗi mã hàng có kết luận riêng

Trường hợp Growatt cho thấy cùng một lô hàng nhưng nhiều mã hàng inverter được đánh giá riêng trên các sheet chứng minh.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 8.1.2 — Rule áp dụng là `RVC 35% + CTSH`

Các bảng chứng minh đã kiểm tra đều thể hiện rõ tiêu chí áp dụng và kết luận đạt theo quy tắc kết hợp này.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 8.1.3 — Dù có nhiều input `Không xuất xứ`, sản phẩm vẫn có thể đạt

Điểm này là bằng chứng thực tế mạnh cho việc logic xuất xứ phải mang tính theo quy tắc.

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 8.2 Trường hợp Do Thanh

#### 8.2.1 — Một trường hợp có thể chỉ cần quy tắc chuyển đổi mã số mà không cần quy tắc tỷ lệ giá trị

Trường hợp Do Thanh hiện được quan sát theo `CTSH`, không nhất thiết phải cần `RVC`.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 8.2.2 — Input mix có thể gồm cả nguồn Việt Nam và nguồn không xuất xứ

Việc trộn nguồn không làm hồ sơ tự động không đạt nếu thành phẩm vẫn đáp ứng quy tắc tương ứng.

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 8.3 Trường hợp Hong An

#### 8.3.1 — Cùng một nhóm sản phẩm rộng vẫn có thể đi theo `CTH`, `CC`, `PSR`

Các hồ sơ Hong An đã kiểm tra cho thấy quy tắc có thể thay đổi giữa các trường hợp theo hiệp định áp dụng và bối cảnh của hồ sơ.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 8.3.2 — `PSR` cần được coi là một nhóm quy tắc độc lập trong nghiệp vụ hiện tại

Nếu đã xuất hiện trong hồ sơ thật, đây không nên bị coi là ghi chú ngoài lề hoặc ngoại lệ hiếm.

> ☐ Đúng / ☐ Sai
> Phản hồi:

---

## Phần 9 — Kiểm tra, Truy vết Và Lưu trữ

### 9.1 Khả năng truy vết

#### 9.1.1 — Mỗi kết quả C/O cần truy ngược được về bộ chứng cứ đã dùng

Nếu không truy lại được phiên bản chứng cứ, các dòng nguồn, quy tắc áp dụng và chứng từ của lô hàng, thì rất khó giải trình khi bị hỏi lại.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 9.1.2 — Khả năng truy vết phải xuống được tới nguồn đầu vào đã bị phân bổ

Đây là lý do mức chi tiết theo dòng nguồn trong workbook là điểm rất quan trọng cần xác nhận rõ.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 9.1.3 — Bộ hồ sơ lưu cần có cả phần giải thích “vì sao đạt”, không chỉ “đã cấp”

Hồ sơ lưu cần đủ để tái dựng logic ra quyết định, không chỉ lưu các file cuối cùng.

> ☐ Đúng / ☐ Sai
> Phản hồi:

### 9.2 Lưu trữ

#### 9.2.1 — Quý Công ty hiện đang lưu hồ sơ và chứng từ C/O trong bao lâu

Đề nghị xác nhận:
- mốc lưu trữ tối thiểu hiện đang áp dụng
- phân biệt giữa hồ sơ điện tử và hồ sơ giấy nếu có
- trường hợp nào cần giữ lâu hơn mức thông thường

> Phản hồi:

#### 9.2.2 — Đại lý hiện lưu hồ sơ theo đơn vị nào

Ví dụ:
- theo lô hàng
- theo sản phẩm
- theo doanh nghiệp
- theo năm / hiệp định / mẫu

> Phản hồi:

---

## Phần 10 — Phạm Vi Không Xử Lý Hoặc Chưa Chốt

### 10.1 Những điểm chưa nên coi là đã xác nhận

#### 10.1.1 — Chưa khóa đường chạy cuối cùng của macro

Hiện vẫn còn câu hỏi mở liệu `RunUpgrade` là đường chạy thực tế chính, hay còn song song với các nhánh cũ.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 10.1.2 — Chưa chốt chính xác ý nghĩa của khóa nhóm trong `DM`

Đây là điểm quan trọng nếu sau này cần mô hình hóa cách chọn đợt xử lý giống workbook hiện tại.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 10.1.3 — Chưa chốt đầy đủ phạm vi loại mẫu C/O ưu tiên cần xác nhận trước

Đã quan sát nhiều quy tắc và nhiều mẫu hồ sơ, nhưng chưa có xác nhận loại mẫu C/O nào cần ưu tiên xác nhận trước.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 10.1.4 — Chưa xác nhận đầy đủ scope của `Save` và `Tru lui`

Cần xác nhận rõ các sổ theo dõi này đang được hiểu là:
- dùng chung theo doanh nghiệp
- theo file workbook sao chép
- theo kỳ / theo năm
- hay theo cách khác

> Phản hồi:

### 10.2 Những gì tài liệu này chủ động chưa kết luận

#### 10.2.1 — Tài liệu này chưa cố gắng chốt toàn bộ cách hiểu pháp lý cho mọi FTA

Mục tiêu của tài liệu là xác nhận nghiệp vụ đang làm, không phải thay thế bản phân tích pháp lý đầy đủ.

> ☐ Đúng / ☐ Sai
> Phản hồi:

#### 10.2.2 — Tài liệu này chưa phải đặc tả phần mềm

Mục tiêu ở đây là xác nhận logic nghiệp vụ với Đại lý, không phải mô tả chi tiết hệ thống sẽ được xây ra sao.

> ☐ Đúng / ☐ Sai
> Phản hồi:

---

## Phần 11 — Câu Hỏi Mở Cần Quý Công Ty Xác Nhận

### 11.1 Về phạm vi nghiệp vụ

#### 11.1.1 — Trong thực tế hiện nay, Đại lý đang ưu tiên những loại mẫu C/O / hiệp định nào nhiều nhất

Đề nghị liệt kê theo thứ tự ưu tiên thực tế, không cần liệt kê toàn bộ lý thuyết.

> Phản hồi:

#### 11.1.2 — Với một sản phẩm cố định, khi nào Đại lý cho phép tái sử dụng hồ sơ sản phẩm mà không dựng lại từ đầu

Đề nghị mô tả quy tắc vận hành thực tế, kể cả khi khác với cách đọc từ văn bản.

> Phản hồi:

### 11.2 Về phân bổ / workbook

#### 11.2.1 — `Save` hiện được dùng như sổ theo dõi toàn cục hay chỉ trong phạm vi một file / một khách / một kỳ

> Phản hồi:

#### 11.2.2 — `Tru lui` được kích hoạt trong những tình huống nghiệp vụ nào

> Phản hồi:

#### 11.2.3 — Có trường hợp nào Đại lý phải phân bổ đầu vào theo logic khác ngoài cách truy vết theo dòng nguồn hiện đã quan sát không

Ví dụ:
- gộp nhiều dòng nguồn
- ghi đè bằng quyết định nghiệp vụ
- ưu tiên nội địa trước nhập khẩu
- ưu tiên chứng từ khai báo cụ thể

> Phản hồi:

### 11.3 Về quy tắc xuất xứ

#### 11.3.1 — Khi một nhóm sản phẩm có thể đi theo nhiều quy tắc, Đại lý đang chọn quy tắc theo nguyên tắc nào

Ví dụ:
- theo hiệp định của thị trường đích
- theo form khách yêu cầu
- theo quy tắc dễ chứng minh nhất
- theo hồ sơ đã đăng ký trước đó

> Phản hồi:

#### 11.3.2 — Với `PSR`, Đại lý hiện đang lưu / tra cứu quy tắc này ở đâu

> Phản hồi:

#### 11.3.3 — Đại lý có cần giải thích các trường hợp không đạt theo cùng mức độ chi tiết như các trường hợp đạt không

Nếu có, đề nghị mô tả hiện nay Quý Công ty đang giải thích các trường hợp không đạt bằng cách nào.

> Phản hồi:

### 11.4 Về dữ liệu nguồn

#### 11.4.1 — Khách hàng thường thiếu loại dữ liệu nào nhất khi bắt đầu một hồ sơ mới

> Phản hồi:

#### 11.4.2 — Khi dữ liệu BOM, chứng từ nguồn và workbook mâu thuẫn nhau, Đại lý ưu tiên nguồn nào

> Phản hồi:

#### 11.4.3 — Có cần lưu rõ nguồn gốc của từng quyết định điều chỉnh thủ công không

Ví dụ ai sửa, sửa vì lý do gì, ảnh hưởng tới lô hàng nào.

> Phản hồi:

---

## Tóm Tắt Cách Hiểu Hiện Tại

1. Nghiệp vụ C/O không chỉ là “nộp một bộ chứng từ”, mà gồm ít nhất 4 lớp nghiệp vụ tách biệt.
2. Workbook hiện tại là một công cụ phân bổ có trạng thái lịch sử, không phải file tính toán tạm thời.
3. `Tồn C/O (CO stock)` cần được hiểu là tồn khả dụng trong mô hình chứng minh xuất xứ, không đồng nhất với tồn kho vật lý.
4. Logic xác định xuất xứ hiện nay không chỉ có một công thức duy nhất, vì các hồ sơ thực tế đã dùng `RVC`, `CTH`, `CTSH`, `CC`, `PSR`, và quy tắc kết hợp.
5. Bằng chứng sản phẩm có tính tái sử dụng, nhưng hồ sơ theo lô hàng vẫn là đơn vị nộp hồ sơ độc lập.
6. Những điểm chưa đủ chắc chắn đã được giữ lại dưới dạng câu hỏi mở để Quý Công ty xác nhận.
