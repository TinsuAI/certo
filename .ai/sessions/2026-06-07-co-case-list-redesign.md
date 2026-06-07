# Session 2026-06-07 — CO-case list page redesign

## Goal
User: redesign the CO-case list page (`/clients/{id}/co-case`). Complaints: `co-command-bar`
eats space; the list mini-flow (Invoice→Thị trường→Form→HS) is inconsistent with the real
5-step workflow; the create panel is spacy/confusing; the dossier table lacks real
workflow/completion status (chốt chưa, bao nhiêu chốt, vấn đề gì), summary counts, useful
filters, per-row actions, and an archive. "mày recommend đi" → I decided all design calls.

## What was done
Brief: `.ai/features/2026-06-07-co-case-list-redesign.md`. All in `co_case.html` list-mode
(detail-mode untouched).

- **Store** (`app/co_case_store.py`): `co_case_status_view(case, *, exported=False)` — one cheap
  shared status helper (sheets_total/locked from `products[].origin_sheet_status=="locked"`,
  completed from `co_case_is_completed`, issues list, status_key done/progress/attention,
  archived). `set_case_archived(client, case_id, archived)` — flips `archived` directly under
  `case_lock`+`save_state`+`_persist_case_row`, **bypassing the `update_case_record` close-gate**
  (you archive *completed* cases). `archived` round-trips: file-mode JSON via save_state, PG via
  the `payload` JSONB (`_co_case_record_fields` stores `dict(case)`) — no migration.
- **Routes** (`app/routers/co_case.py`): `POST .../{case_id}/archive` (+ `archived=0` unarchive),
  redirect + co_flash.
- **Context** (`app/web/co_case_context.py`): in index mode attach `dossier.status_view` per case
  (reads `state["dossier_exports"][case_id].status=="done"` for the exported flag) and a
  `co_case_summary` aggregate (total/progress/done/attention/exported over non-archived +
  archived count).
- **Dashboard** (`app/routers/pages.py`): `_dashboard_case_view` now delegates to
  `co_case_status_view` so list + company dashboard agree.
- **Template** (`co_case.html`): removed command-bar + mini-flow; slim header + `+ Tạo hồ sơ`;
  clickable stat band (quick-filters the status select); filter bar (search/status/market +
  `Hiện đã lưu trữ` toggle when any archived); redesigned 7-col table (status badge + `✓ Đã xuất`
  + `X/Y bảng kê chốt` progress bar + issue chips); per-row `⋯` `<details>` menu (Mở inline +
  Lưu trữ/Xoá); create form moved verbatim into a modal (same macros/`data-*` hooks → existing
  market-picker→form-preview JS still works). JS: archived-toggle filtering, stat quick-filter
  wiring, create-modal open/close/Esc.
- **CSS** (`app.css`): new `.co-case-index`/stat band/`.co-status`/`.co-tag`/progress/`.row-menu`
  /create-modal styles; dossier grid 9→7 cols.

## Decisions
- No flow diagram on the list — the real 5-step flow lives in the detail tabs; the summary band
  is more useful here. The list mini-flow was both wrong and low-value.
- Attention badge label = "Có vấn đề" (matches stat band); specific blockers go in chips (avoids
  the badge+chip duplication seen in the first render).
- Archive done properly (flag + store fn + routes + toggle), not just sort — user named it a need.
- Out of scope: bulk multi-select (feedback #13 has its own discovery), TKN "thiếu tờ khai" in the
  list (needs source context — too expensive per row).

## What didn't work / fixed mid-session
- **`.co-stat` "Tổng" number invisible** — `.co-stat` is a `<button>`; the un-classed number
  inherited the UA button text color (not `--foreground`) and vanished on the white card, while
  status-colored siblings showed. User flagged it as the recurring contrast bug. Fixed with
  explicit `color: var(--foreground)` on the button + its `strong`. Updated memory
  `css-no-opacity-muted-text` with this second (inheritance, not opacity) mechanism.
- **`⋯` dropdown clipped** — `.dossier-list{overflow:hidden}` (rounded corners) cut off the
  last-row menu. Scoped `overflow:visible` to `.co-dossier-list`, re-rounded header corners.

## Verification
- `uv run pytest` → **484 passed, 8 skipped** (after updating 3 `test_co_demo` assertions to the
  new markup; new `tests/test_co_case_list_status.py` covers archive round-trip incl. on a
  completed case + status derivation).
- Local render `127.0.0.1:8001/clients/johnson-vn/co-case` HTTP 200; stats `2/0/1/1/1` match the
  2 seed cases; screenshots (list, create modal, stat band, open row menu) under
  `.ai/screenshots/2026-06-07-co-case-list-redesign/`.

## Open items
- Not committed / not deployed — user hasn't asked to commit.
- Dead CSS for removed `co-flow-mini`/`co-overview-create`/`co-case-index-layout` (+ their
  `@media` refs) left in place; safe to delete later.
- johnson-vn cases are seed/in-memory on HTTP → archive won't persist there; growatt (PG) does.
