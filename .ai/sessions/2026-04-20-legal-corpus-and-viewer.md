# Session Summary: Legal Corpus And Viewer

## What Was Done
- Xây một legal corpus workbench hoàn chỉnh quanh nguồn văn bản C/O từ eCoSys:
  - mirror danh sách văn bản và file gốc
  - normalize/extract text
  - source enrichment
  - quality audit
  - OCR recovery cho `official_pdf_scan`
  - source registry
  - canonical pilot builder
- Tổ chức lại `docs/legal/` thành nhiều lớp rõ ràng:
  - `wiki/` cho ingest/debug
  - `indexes/` cho registry và audit
  - `reference/` cho legal system docs
  - `canonical/pilot/` cho lớp đọc/tra cứu tốt nhất hiện tại
- Mở rộng official resolver:
  - `VNTR` cho nhiều văn bản pháp quy C/O trọng yếu
  - `VBPL` cho một batch thông tư, gồm cả các pilot như `23/2025/TT-BCT`, `39/2018/TT-BCT`, `44/2023/TT-BCT`, `41/2022/TT-BCT`, `37/2022/TT-BCT`, `04/2024/TT-BCT`, `02/2024/TT-BCT`, `01/2024/TT-BCT`
- Dùng OCR fallback có kiểm soát cho nhóm `QĐ-BCT` vận hành/eCoSys khi không có official text-based đủ tốt, rồi clean thêm canonical pilot cho nhóm này.
- Thêm web server tra cứu pháp lý tại `scripts/legal-lookup-server.mjs`:
  - homepage tổng quan corpus
  - search page riêng
  - document route `/doc/:slug`
  - route source đối chiếu
  - render markdown từ lớp tốt nhất hiện có
- Thiết kế lại document view theo hướng app-shell kỹ thuật nhưng tối giản hơn:
  - tách shell chung và shell riêng cho doc page
  - metadata nhỏ hơn
  - source compare tối giản
  - reading surface là trọng tâm
  - UI song ngữ, mặc định tiếng Việt
- Thêm tool screenshot `scripts/capture-legal-screenshot.mjs` để chụp full-page hoặc viewport và tự review UI.
- Viết và chỉnh `docs/origin-rules-specification.md`, cộng thêm feature note tại `.ai/features/2026-04-15-origin-rules-specification.md`.

## Decisions Made
- `eCoSys` chỉ là discovery feed và provenance layer, không phải canonical text corpus.
- Source selection phải là `official-first`, nhưng trong official sources phải xếp theo `preservation quality`, không phải theo nhãn HTML/PDF một cách mù quáng.
- `docs/legal/wiki/` không còn được coi là corpus user-facing; nó là ingest/debug layer.
- `docs/legal/canonical/pilot/` là lớp usable hiện tại cho review/tra cứu các văn bản ưu tiên.
- Với UI tra cứu, search tách thành surface riêng; document view phải giống reading room hơn là dashboard.
- `Nguồn đối chiếu` trên web chỉ nên hiện những nguồn thật sự có ý nghĩa cho operator: official page, eCoSys listing/file, raw mirrored binary.

## What Didn't Work
- TVPL auto-fetch không khả thi trong môi trường hiện tại:
  - bị Cloudflare challenge chặn ở fetch, headless Chromium, headed WSL, browser-assisted Windows, và native Windows flow
  - vì vậy TVPL bị hạ xuống lane tra cứu thủ công, không nằm trên critical path
- Browser session handoff giữa WSL và browser Windows qua remote debugging không chạy ổn; Chrome/Edge không expose DevTools port như kỳ vọng trong môi trường này.
- `official HTML` từ một số văn bản VBPL không đủ tốt để làm canonical text. Case rõ nhất là `04/2024/TT-BCT`: HTML là Word-clipped HTML bẩn, làm vỡ công thức RVC và có nguy cơ làm hỏng các bảng/phụ lục quan trọng.
- OCR cứu được khả năng tra cứu tạm thời, nhưng không đủ sạch để thay cho source preservation đối với công thức và bảng lookup.

## Open Items
- Sửa toàn bộ `source selection policy`:
  - `HTML` chỉ thắng nếu qua quality gate
  - nếu HTML vỡ công thức/bảng thì promote `official DOC/DOCX`
  - nếu không có thì dùng `PDF`
- Thêm preservation lane riêng cho:
  - công thức
  - bảng danh mục
  - phụ lục lookup
  - các đoạn cần round-trip vào database sau này
- Rebuild canonical layer và document viewer trên policy mới, bắt đầu từ các văn bản có công thức/bảng nhạy cảm như `04/2024/TT-BCT` và các thông tư “Danh mục quy tắc...”.
- Sau khi preservation policy ổn, mới tiếp tục chuẩn hóa bảng thành dữ liệu thật cho hệ thống CO:
  - thị trường / agreement
  - form type
  - thông tư áp dụng
  - HS / PSR / criteria lookup
