# Feature: Mục 6 — BOM mặc định per-client + luồng BOM hàng loạt (#13 + #14)

Source: client feedback `HIỆN TRẠNG BARRY CO` (#13, #14) = đợt `Barry CO - Trang tính1.pdf` Mục 6.
Discovery 2026-06-18; landscape mapped by 3 Explore agents (BOM selection, stock run, lock state machine).

## Scope

Ships in slices, **#14 first**, then **#13** in three sub-slices. Each slice = its own
write-tests → implement → `/rev` → commit cycle.

**Slice A — BOM mặc định per-client (#14).** Khi staff pick BOM (định mức) cho một mã SP, lưu
lựa chọn đó làm **mặc định cho client** (pin đúng version đã pick). Hồ sơ sau, mã đó tự dùng BOM
mặc định; staff vẫn override được per-case.

**Slice B — Chạy tồn 1 lần (preview) + tổng hợp mã thiếu (#13a).** Một nút "Chạy tồn (tất cả SP)"
chạy feasibility tồn cho **toàn bộ sản phẩm** ở cùng một export-anchor date, **KHÔNG trừ ledger**
(preview/dry-run). Trả về bảng tổng hợp **mã thiếu tồn** gom theo sản phẩm.

**Slice C — Thay định mức hàng loạt (#13b).** Từ bảng mã thiếu, chọn mã thay thế và áp loạt cho
nhiều SP cùng lúc; chạy lại preview.

**Slice D — Chốt tất cả (#13c).** Một nút khóa toàn bộ origin sheet của case (theo thứ tự), commit
claims vào ledger, skip-and-report sheet chưa sẵn sàng / overclaim.

**Out of scope:** cải thiện chất lượng ranking mã thay thế (#4 — thuộc Data Hub, gửi qua
`.ai/api-requests/`); số tồn TỔNG toàn kho (#12 — feature riêng); tự auto-upgrade BOM lên version
mới (đã chọn pin, không auto-nâng).

## Decisions

- **#14 lưu theo artifact_id (pin version), write-through khi pick.** Mỗi lần staff pick BOM cho một
  mã → ghi `{product_code: artifact_id}` vào store mặc định per-client. Không auto-upgrade khi có
  version mới (user chọn "pin").
- **Store mới, mô phỏng `cost_allocation_store`.** Bảng CO Postgres (vd `co_bom_product_default`) +
  JSON fallback dev (`config/bom-default/<client>.json`). CO-owned config, **không** phải
  client_config/overlay, không phải DH source-mode field — y như cost-allocation.
- **Áp default ở read-time, không chỉ seed-on-create.** Chèn một tầng fallback per-client default
  vào chuỗi precedence trong `selected_bom_rows_by_product()` (`co_case_context.py:1475-1538`):
  per-product override → case-level override → **client default (mới)** → aggregate default → latest.
  Tránh seed bị "đông cứng" khi thêm SP vào case sau này.
- **Chạy tồn loạt = preview không commit.** Tách rõ khỏi `lock` (commit). Preview gom qua
  `case_allocation_pool` + `co_stock_is_usable` (`co_case_context.py:1605-1671`) lặp toàn SP, **không**
  gọi `record_sheet_lock_claims`. Chốt tất cả mới ghi claims.
- **Chốt tất cả mô phỏng `bulk-apply-cost`** (`co_case.py:1556-1600`): load case → lặp
  `origin_product_order` → validate `origin_sheet_action_error(case, code, "lock")` →
  `record_sheet_lock_claims` (catch `StockOverclaimError`) → set `locked` → persist 1 lần → JSON
  summary `{locked:[], skipped:[{code,reason}]}`. **Skip-and-report**, không fail-fast.
- **UI mirror review-toolbar pattern** (`co_case.html:883-907` nút + summary, `:5512-5538` JS).

## Risks

- **Pin artifact lỗi thời / bị xóa (#14).** artifact_id mặc định có thể không còn resolve (BOM bị
  thay version/xóa) → phải fallback graceful sang latest + cảnh báo, không để vỡ case.
- **Lock ordering gate.** Single-lock yêu cầu sheet trước đã `locked`, không có sheet sau `locked`,
  bản thân phải `calculated` (`co_case_context.py:1354-1388`). Chốt tất cả PHẢI khóa đúng thứ tự
  `origin_product_order` để thỏa "prior locked".
- **Atomicity claim khi chốt loạt.** `record_sheet_lock_claims` ghi claim từng sheet trước khi persist
  state. Skip-and-report nghĩa là sheet đã khóa trước vẫn giữ claim khi sheet N fail — incremental,
  chấp nhận được nhưng phải report rõ sheet nào đã/chưa khóa.
- **Revision-token 409.** Bulk op đổi state nhiều SP; phải gửi/refresh `origin_case_revision` đúng để
  không bị "Origin case state changed" (`co_case_context.py:53-80`, `test_origin_case_revision.py`).
- **Preview vs commit drift.** Tồn có thể đổi giữa lúc preview và chốt (case khác claim cross-case
  ledger). Preview chỉ tư vấn; lock cuối re-check overclaim → 409/skip. Chấp nhận.
- **Chất lượng mã thay thế (Slice C) phụ thuộc DH** (#4 chưa giải quyết) — gợi ý có thể chưa tốt.

## Open Questions

1. **"Chốt tất cả" có cần "Tính tất cả" trước không?** Lock yêu cầu `calculated`, mà calculate hiện
   per-sheet. Đề xuất: bulk-lock tự calculate-rồi-lock từng sheet (calculate là đọc snapshot,
   idempotent), HOẶC thêm nút "Tính tất cả" riêng. → chốt khi vào Slice D.
2. **Quản lý/xóa BOM mặc định (#14):** inline (badge "mặc định: vX" + link xóa cạnh select) hay trang
   admin riêng? Đề xuất: inline tối thiểu trước, quản lý đầy đủ sau.
3. **Preview có pre-fetch ranked substitutes cho mã thiếu không?** Nhiều round-trip DH có thể chậm.
   Đề xuất: lazy-load per mã trong panel, tái dùng `/substitute-stock` (`co_case.py:2044-2127`).

## Next Step

Bắt đầu **Slice A (#14)** theo `/tdd`: store mặc định per-client + write-through khi pick + tầng
fallback read-time. Đây là lát nhỏ nhất, value cao, không đụng luồng lock/stock.

## Key file refs
- BOM selection precedence: `app/web/co_case_context.py:1475-1538`; overrides set/persist:
  `app/routers/co_case.py:39-149`, `app/co_case_store.py:140-146`.
- Per-client store analog: `app/cost_allocation_store.py` (Mode B default pattern).
- Allocation pool / feasibility: `app/web/co_case_context.py:1605-1671`,
  `app/co_stock_eligibility.py:55-84`.
- Single-lock + claims: `app/routers/co_case.py:1793-1861`, `:168-190`.
- Bulk pattern (template): `app/routers/co_case.py:1556-1600`; UI `app/templates/co_case.html:883-907`,
  `:5512-5538`.
