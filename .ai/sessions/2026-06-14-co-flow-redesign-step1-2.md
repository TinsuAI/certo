# Session 2026-06-14 — Redesign luồng làm CO: bước 1 (bỏ form) + bước 2 (dropzone async)

Khởi động sáng kiến redesign toàn luồng CO 5 bước. Phiên này: trả lời câu hỏi về form ở bước 1,
ship RD1 + RD2, note RD3 cho phiên sau. Commit `09509ae`, push, deploy + verify prod.

## What Was Done

1. **Điều tra: "chọn form bước 1 có ảnh hưởng outcome không?" → Gần như KHÔNG.** Trace `co_form_type`
   (case-level) xuống calc + export: nó chỉ là label trang trí (lưu + round-trip workbook `workbook_io.py:112/187`
   + hiển thị list/header), KHÔNG vào công thức calc, KHÔNG chọn template export HQ. Form thực sự chi phối là
   **per-sheet ở bước 3**: `effective_form = form_override or sheet_form_recommendation(market, finished_hs)`
   (`co_case_context.py:1190, 1179`). Template export HQ rẽ nhánh theo per-sheet form (`workbook_io.py:441`:
   EUR.1 → Phụ lục VII/PSR; còn lại → LVC). Input bước 1 có nghĩa = **destination_market**.

2. **RD1 — bỏ "chọn form" ở bước 1** (user chọn phương án a: bỏ form, chỉ giữ market):
   - `co_case.html`: bỏ block `co-form-preview` "Form gợi ý" (modal tạo + bước Lô hàng); bỏ macro chết
     `form_lane_matrix()` (định nghĩa nhưng không nơi gọi); refactor `updatePreview` JS để hidden input
     `co_form_type` vẫn auto-set khi đổi market dù đã bỏ preview block.
   - **Phát hiện qua ảnh:** chỗ form lộ rõ nhất bước 1 là **3 thẻ `invoice-form-hints`** (Form B/CPTPP/EUR.1)
     trong preview invoice → bỏ luôn (server template + JS `renderInvoicePreview`), giữ "Gợi ý thị trường" +
     nút "Dùng thị trường" (nút này vẫn carry `data-form-name` để set `co_form_type` ngầm).
   - Dọn mồ côi: CSS `.form-lane*` / `.mini-rule-list*` / `.invoice-form-hints*` (tách giữ `.invoice-facts span`);
     bỏ `.form-lane-grid` khỏi media query; bỏ context key `form_lanes` (`co_case_context.py:257` — giữ local var
     ở 239-240 vì `selected_form_lane`/`recommended_form_lane` vẫn cần). `suggested_forms` GIỮ (nút market dùng).

3. **RD2 — dropzone async chứng từ** (user chọn "dropzone async toàn diện"):
   - **Backend** (`co_case_store.py` + `routers/co_case.py`): thêm `delete_supporting_file(client, case_id, upload_id)`
     (mirror save: case_lock → pop row → unlink blob → save_state + persist row + supporting_files). Route
     `DELETE /supporting-files/{upload_id}` (409 nếu case completed, 404 nếu không thấy). POST upload giờ
     content-negotiate: `Accept: application/json` → `JSONResponse({ok, file})` (helper `_supporting_file_view`);
     không có Accept → 303 redirect cũ (progressive enhancement). Helper `_wants_json`.
   - **Frontend** (`co_case.html`): block documents viết lại với macro Jinja `doc_slot_card` (7 slot: 3 bắt buộc +
     4 bổ sung). Mỗi card = dropzone `<form>` (giữ `<noscript>` upload baseline) + file list. JS `initDocumentUploads`
     (idempotent, trong `refreshCaseShellInteractions`): drag-drop highlight, click-to-browse, multi-file, XHR upload
     với progress bar (pending chip → real chip), xoá inline qua DELETE fetch, counter "Bắt buộc N/3 · Bổ sung N",
     sync slot status. Bỏ ô invoice/BL lặp ở mỗi slot.
   - **CSS** (`app.css`): block `.doc-*` mới (Primer: neutral + blue accent, viền solid, dashed dropzone,
     hover/drag-over `--primary-soft`, chip ext-badge + size + remove, progress bar). Thay sạch `.document-*` +
     `.upload-form-inline` cũ (đã grep confirm không còn ref).

4. **BACKLOG**: thêm section **"Redesign luồng làm CO" (RD1–RD3)**. RD1/RD2 đánh dấu DONE; **RD3 (bảng kê,
   "thay đổi lớn") note cho phiên sau** — chưa chốt nội dung.

5. **Verify (dev-flow mới của user):**
   - Local e2e `.ai/scripts/e2e_documents_flow.cjs`: login-off, đi full flow, upload→chip→delete async +
     walkthrough 5 bước → **13/13 check, no console error**. Soi từng ảnh `.ai/screenshots/2026-06-14-co-flow-redesign/`.
   - Backend: 92 targeted test (`co_case`/`store`/`policy`/`document`) + guardrail `test_data_hub_policy` pass; 214 demo test pass.
   - Commit `09509ae` → push TinsuAI/co main → CI/CD `27488573657` success → prod deploy. `/version` git_sha `09509ae`.
   - Prod e2e `.ai/scripts/e2e_prod_documents.cjs`: login SSO (claude-check@local) → soi dropzone trên case thật
     `growatt-vn/co-case-67b4baae17d3` → **5/5 check, no console error**, footer `09509ae`. Render khớp local.

## Decisions Made

- **RD1 = bỏ form khỏi bước 1, KHÔNG bind thành default** (user chọn a thay vì b). Lý do: form là dẫn xuất từ
  market; bind chỉ thêm ràng buộc thừa. `co_form_type` vẫn auto-suy ngầm để list/header không vỡ.
- **Bỏ luôn `invoice-form-hints`** (ngoài phạm vi sửa ban đầu) vì ảnh cho thấy đó mới là "form bước 1" nổi nhất —
  đúng directive "form biến mất khỏi bước 1". Giữ market hint vì hữu ích (EU → EUR.1) và không phải "chọn form".
- **Async upload = progressive enhancement** (content-negotiation, giữ 303 + `<noscript>`) thay vì JS-only, để
  không regress no-JS baseline.
- **Per-file XHR** (không multi-file 1 request) để có progress + cô lập lỗi từng file.
- **1 commit thay vì 2** (RD1+RD2): `co_case.html`/`app.css` có hunk xen kẽ, env không hỗ trợ `git add -p`.
- **KHÔNG upload thật lên prod**: soi visual đủ (cùng git_sha, async đã chứng minh local) — tránh để file rác
  trên dossier khách thật.

## What Didn't Work / Gotchas

- **zsh glob phá `grep`/`rg`**: `--include=*.py` và `app/static/js/*.js` bị glob-expand → "no matches found" làm
  hỏng cả lệnh. Dùng `rg` với `-t py`, hoặc quote glob. [[shell-grep-alias-gotcha]].
- **`updatePreview` guard ngược**: ban đầu `if (!preview) return` đứng trước phần set hidden input → bỏ preview
  block sẽ làm `co_form_type` không update. Phải set hidden input TRƯỚC, preview sau (guard `?.`).
- **`.invoice-facts span` bị gộp selector với `.invoice-form-hints div`** — không xoá cả rule, phải tách giữ lại.
- **Macro `form_lane_matrix()` là dead code** từ trước (định nghĩa, không gọi) — gỡ luôn.

## Open Items

- **RD3 — bảng kê C/O "thay đổi lớn": chờ user nêu chi tiết.** Việc tiếp theo của sáng kiến. `/discover` trước.
- **Handoff docs treo:** STATUS.md (đã ghi đè phiên này) + `2026-06-09-…md` (sửa từ phiên trước, vẫn uncommitted)
  + session log này + untracked `e2e_prod_documents.cjs`. Commit + (hỏi trước) push.
- **Optional polish (user hỏi, chưa làm):** viền đỏ 3 card bắt buộc hơi gắt — có thể làm nhẹ hơn nếu user muốn.
- Backlog cũ: DC1/DC3, M1, save-model, D1 parity, P1 index N+1, T1 test-DB isolation.
