# Project Status

## Current State
- Repo vẫn ở pha discovery, nhưng legal corpus cho mảng C/O đã có full batch output thay vì chỉ pilot: `71/71` văn bản hiện có canonical file trong `docs/legal/canonical/corpus/`, wiki pages, source registry, source inventory, và source packets.
- Canonical corpus hiện đang chạy theo non-`TVPL` policy: chỉ dùng `official-text`, `ocr-recovery`, hoặc `ecosys-extracted`; `TVPL` không còn nằm trên critical path của build.
- Phân bố source của canonical corpus hiện tại là `28 official-text`, `19 ocr-recovery`, `24 ecosys-extracted`. Điều này có nghĩa là coverage đã full, nhưng chất lượng chưa đồng đều; nhiều văn bản vẫn đang sống bằng OCR hoặc raw extraction.
- Legal lookup server vẫn đang phục vụ tại `http://127.0.0.1:4173/`.

## Recent Changes
- Thêm full canonical corpus builder ở `scripts/build-legal-canonical-corpus.mjs` và script npm `legal:build-canonical-corpus`.
- Mở rộng source-selection để có thể exclude lane theo policy, hiện dùng để loại `TVPL` khỏi canonical build trong `scripts/lib/legal-canonical-normalization.mjs`.
- Vá `VBPL` enrichment để seed chết hoặc fetch lỗi không làm crash cả batch; nếu fetch live lỗi thì fallback sang cache cũ hoặc trả `unresolved/fetch_failed`.
- Thêm `source inventory` và `source packets` như artifact audit riêng cho toàn corpus, cùng các index markdown tương ứng.
- Rebuild toàn bộ artifact chính: `source-enrichment.json`, `text-source-registry.json`, `source-inventory.json`, `source-packets.json`, `docs/legal/canonical/corpus/`, `docs/legal/indexes/canonical-corpus.md`, và wiki.

## Next Steps
- Siết `source preservation policy` theo block-type, không chỉ theo document-level source. Cần xử lý riêng bảng, công thức, appendix, và PSR/list lookup thay vì flatten tất cả vào prose canonical.
- Thay canonical selection kiểu “một source thắng hết” bằng fusion theo block cho các văn bản có attachment text tốt (`DOCX/PDF`) nhưng official HTML hoặc OCR không bảo toàn cấu trúc.
- Audit nhóm đang dùng `ecosys-extracted` và `ocr-recovery` để ưu tiên promote sang lane tốt hơn khi attachment hoặc official binary cho chất lượng cao hơn.
- Dọn taxonomy và metrics để `TVPL` chỉ còn là reference artifact nếu còn giữ lại, không được diễn giải như live-fetchable source.

## Blockers
- `VBPL HTML` ở một số văn bản vẫn là Word-clipped HTML bẩn (`msohtmlclip`, `clip_image`, `file:///...`), không an toàn cho công thức/bảng nếu dùng nguyên trạng làm canonical.
- `TVPL` vẫn bị Cloudflare chặn cho auto-pipeline trong môi trường hiện tại; các file TVPL trên disk chỉ là artifact cũ/thủ công, không phải lane fetch ổn định.
- Full canonical corpus hiện mới là “đã có output cho 71/71”, chưa phải “71/71 sạch chuẩn tuyệt đối”; `24` văn bản vẫn đang đi từ `ecosys-extracted`, `19` từ `OCR`.

## Notes for Next AI Session
- Người dùng muốn ưu tiên correctness của dữ liệu hơn UI. UI hiện chỉ là audit surface; không nên đầu tư thêm UI ngoài nhu cầu review kết quả.
- User đã chốt: tạm gác `TVPL`, tập trung vào `VBPL + VNTR + eCoSys + OCR`.
- `source-inventory.json` hiện báo `withCanonical: 71`; `source-packets.json` hiện báo `canonicalExists: 71`. Đây là chỉ số “đã có canonical output”, không phải chỉ số “đã sạch hoàn toàn”.
- Duplicate issue code `05/2022/TT-BCT` vẫn tồn tại trong corpus vì đó là hai văn bản khác nhau cùng issue code; các script hiện xử lý được nhờ slug theo `issueCode + title`.
