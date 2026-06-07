# Feature: CO-case list page redesign

`GET /clients/{id}/co-case` — `co_case.html` list-mode (the `{% if not case ... %}` index
branch, lines ~364–565). Detail-mode is out of scope.

## Problem (user)
1. `co-command-bar` eats vertical space, low information value.
2. List-page `co-flow-mini` (Invoice→Thị trường→Form→HS) is inconsistent with the real
   5-step workflow (Lô hàng→Chứng từ→Bảng kê C/O→TKX/TKN→Review&Xuất).
3. `co-overview-create` ("Tạo hoặc mở hồ sơ") panel is spacy/confusing.
4. The dossier table lacks real workflow/completion status (chốt chưa, bao nhiêu chốt,
   vấn đề gì), summary counts, useful status filter, per-row actions, and an archive.

## Scope
IN:
- Replace command-bar + decorative mini-flow with a slim header + a **summary stat band**
  (Tổng / Đang xử lý / Đã chốt / Có vấn đề / Đã xuất); stats act as quick-filters.
- Move create form into a `+ Tạo hồ sơ` **modal** (reuse existing modal pattern; keep all
  current form markup + JS: invoice lookup, market picker, form preview, optional fields).
- **Archive**: `archived` flag on the case record; hidden by default; `Hiện đã lưu trữ (N)`
  toggle; per-row Lưu trữ / Bỏ lưu trữ.
- Real per-case status (cheap derivation, no source-context calls):
  - `sheets_total`, `sheets_locked` from `case.products[].origin_sheet_status == "locked"`.
  - `completed` from `co_case_is_completed` (status in COMPLETED_CASE_STATUSES = đã đóng).
  - `exported` from `state["dossier_exports"][case_id].status == "done"`.
  - `issues[]` cheap: thiếu invoice/tờ khai, thiếu B/L, chưa có bảng kê, N bảng kê chưa chốt.
  - `status_key`: `done` (completed) / `attention` (missing invoice·BL·products) / `progress`.
- Table redesign: status badge + `X/Y bảng kê chốt` progress + `Đã xuất` badge + inline
  issue chips; real status filter; per-row `⋯` menu (Mở / Lưu trữ / Xoá).

OUT (defer):
- Bulk multi-select actions (chốt/xuất hàng loạt) — feedback #13 has its own discovery.
- TKN "thiếu tờ khai" detection in the list (needs source context — too expensive per row).
- Detail-view changes.

## Decisions
- **Single status helper.** Promote `pages.py::_dashboard_case_view` to one shared cheap
  helper (e.g. `app/co_case_store.py::co_case_status_view` or in `co_case_context`) so the
  list page and company dashboard agree. Extend it with `sheets_total/locked`, `exported`,
  `issues`, `archived`.
- **Archive bypasses the close-gate.** `update_case_record` rejects edits to completed cases
  (status gate). Archiving a *completed* case is the common path, so add a dedicated
  `set_case_archived(client, case_id, archived)` that flips the flag directly under
  `case_lock` + `save_state` + `_persist_case_row`, not through `update_case_record`.
- **Hide-archived default.** `get_case_workspace`/list loop returns all; the view filters
  archived out unless `?archived=1` (or template toggle). Count of archived shown on toggle.
- **No flow diagram on the list.** Showing the real 5-step flow on the list adds height for
  little value; the flow lives in the detail tabs. The summary band replaces it.
- **Reuse, don't rewrite, the create form.** Same fields/hidden inputs/`data-*` hooks so the
  existing market-picker→form-preview JS keeps working; only its container moves into a modal.

## Risks
- `co_case.html` is 5082 lines and shared list/detail; the list branch is well isolated
  (`co-case-index-layout`), but CSS classes (`co-command-bar`, `co-flow-mini`,
  `co-overview-create`) are list-only — safe to restyle/remove. Verify no detail-mode reuse.
- Persistence parity: `archived` must round-trip in both file-mode (`save_state`) and the
  PG row (`_persist_case_row`). Check `_persist_case_row` column set; if it only stores known
  columns, archived may need to live in the JSON blob, not a column.
- johnson-vn cases on HTTP are seed/in-memory (don't persist) — archive will reset on
  restart there; growatt (PG) persists. Acceptable for demo; note it.
- The create modal must not double-submit / must keep `hx-boost="false"`.
- Don't fabricate counts: every stat must come from the real records.

## Open Questions
- None blocking. (Bulk actions + TKN-missing flagged out-of-scope above.)

## Next step
Standard feature: add store tests (archive round-trip + status derivation) → implement store
+ routes + context helper → restyle template + CSS → `/rev` → run full `uv run pytest` →
browser-verify on local `127.0.0.1:8001` (johnson-vn) → commit.
