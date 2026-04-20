# Project Status

## Current State
- Repo vẫn ở pha discovery, nhưng đã có một legal corpus workbench chạy được cho mảng C/O: mirror eCoSys, source registry, enrichment, OCR fallback, canonical pilot, wiki, và legal lookup webview.
- `http://127.0.0.1:4173/` hiện đang chạy legal lookup server từ `scripts/legal-lookup-server.mjs`; lớp UI đã được tách `Home / Search / Document view`, mặc định tiếng Việt, và trang tài liệu đã được redesign theo hướng reading-room gọn hơn.
- Corpus hiện đã có text source cho toàn bộ `71` văn bản; trong đó một phần đáng kể đã được promote lên `official-text`, một nhóm `QĐ-BCT` đang sống bằng `ocr-recovery`, và `docs/legal/canonical/pilot/` là lớp đọc được tốt nhất hiện tại cho các văn bản ưu tiên.
- Blocker quan trọng nhất hiện tại không còn là “thiếu dữ liệu”, mà là `source preservation policy`: với một số văn bản như `04/2024/TT-BCT`, `official HTML` từ VBPL làm vỡ công thức/bảng, nên pipeline chọn nguồn hiện tại chưa đủ an toàn cho corpus tra cứu chuẩn.

## Recent Changes
- Thêm pipeline pháp lý đầy đủ trong `scripts/` và `scripts/lib/`: mirror eCoSys, enrich sources, build source registry, quality audit, OCR recovery, build wiki, build canonical pilot, và legal lookup server.
- Xây `docs/legal/` như một không gian tra cứu: wiki pages, indexes, legal reference docs, canonical pilot outputs, và mô hình legal text resolution/source registry.
- Bật lane `official-text` từ `VNTR` và `VBPL`, cộng với `ocr-recovery` có kiểm soát cho nhóm `official_pdf_scan` và nhiều `QĐ-BCT` vận hành.
- Thêm UI legal lookup song ngữ, tách trang search riêng, redesign document view, rút gọn `Nguồn đối chiếu` chỉ còn các link thực sự có nghĩa, và thêm tool chụp màn hình `scripts/capture-legal-screenshot.mjs` để review UI.
- Viết `docs/origin-rules-specification.md`, link nó vào `docs/README.md`, rồi chỉnh lại taxonomy theo review để tách `legal-source structure` khỏi `internal evaluator taxonomy`.

## Next Steps
- Sửa `source selection policy` cho toàn corpus theo thứ tự bảo toàn nội dung: `official HTML` chỉ thắng khi qua quality gate; nếu HTML làm vỡ bảng/công thức thì ưu tiên `official DOC/DOCX`; nếu không có nữa mới dùng `PDF`.
- Thêm preservation lane riêng cho `công thức`, `bảng danh mục`, `PSR lookup`, và các phụ lục quan trọng: không flatten bừa vào prose markdown; phải giữ `table block`, `formula block`, hoặc snapshot/crop có đối chiếu.
- Rebuild canonical layer và document viewer trên policy mới, bắt đầu từ các văn bản có công thức/bảng quan trọng như `04/2024/TT-BCT` và nhóm thông tư `Danh mục quy tắc`.
- Chỉ sau khi source policy ổn mới tiếp tục chuẩn hóa dữ liệu bảng để đổ vào database tra cứu sau này.

## Blockers
- `VBPL HTML` ở một số văn bản là Word-clipped HTML bẩn (`msohtmlclip`, `clip_image`, `file:///...`) nên nếu coi đó là canonical text thì công thức và bố cục bảng sẽ hỏng.
- TVPL không dùng được cho auto-pipeline trong môi trường hiện tại vì Cloudflare challenge lặp vô hạn, kể cả browser-assisted/headed/native Windows.

## Notes for Next AI Session
- Người dùng muốn ưu tiên tuyệt đối việc bảo toàn bảng tra cứu và công thức; với pháp quy C/O, “đọc được” là chưa đủ nếu làm mất cấu trúc để sau này vào database.
- User preference đã chốt: `official-first`, nhưng trong official sources phải chọn theo `preservation quality`, không phải cứ `HTML` là thắng.
- Với trang tài liệu, người dùng thích chrome gọn, metadata nhỏ, nguồn đối chiếu tối giản; tránh kiểu dashboard nặng.
- Server hiện đang chạy trong PTY session `55003` trên cổng `4173`.
