# Client-workspace nav redesign + upload detail/preview + clickable table rows

Captured 2026-06-14. Four UX asks against the per-client workspace.

## Directions chosen (by user)

- **Nav**: regroup the 6-item "Dữ liệu" dropdown into **3 domain groups**
  (chosen via option pick): `Tổng quan · Danh mục▾ · Hải quan▾ · BOM▾ ·
  Tải lên · Trợ lý · Cấu hình▾`.
- **Đề xuất under BOM**: proposals is a BOM-change queue → it nests inside the
  BOM group, not as a sibling data tab.
- **Uploads**: page was too sparse → richer list + a per-upload detail view
  with original-file download and a faithful first-rows preview.
- **Tables**: clicking a data row should open its detail, not a tiny end-of-row
  icon (BCCT was the example).

## Changes

- `app/templates/_client_nav.html` — 3 `<details>` domain groups; active group
  highlights from `active_tab`. Group membership:
  - Danh mục: Danh mục vật tư (catalog) · Mã quy đổi (bqd)
  - Hải quan: BCCT · Tờ khai (declarations)
  - BOM: Định mức (BOM) · Đề xuất (proposals) · Cần xử lý · Hệ số quy đổi
    (`uom-factors` moved here from the Cấu hình group)
- `app/routes/uploads.py` — new `GET /uploads/{id}` (detail) + `GET
  /uploads/{id}/download` (original blob, unicode-safe content-disposition);
  `_get_upload` joins `hub.users` for uploader name; `_build_preview` renders
  the first 50×25 cells via `app/parsers/_excel.load_xlsx` (xlsx/xls) or `csv`,
  best-effort (never 500s the page).
- `app/templates/clients/upload_detail.html` — new. Metadata grid (uploader,
  SHA-256, MIME, bytes, rows, parsed-at, storage), parse-result JSON
  (collapsible), and the preview table.
- `app/templates/clients/uploads.html` — added "Người tải" column, filename →
  detail link, localized status badges, `data-row-href`.
- `app/static/js/row-link.js` — new. Whole-row click → `data-row-href`; ignores
  clicks on links/buttons/form controls/`<summary>`; Enter / middle-click /
  ctrl-cmd-shift open as expected. Included globally in `base.html`.
- `data-row-href` applied to: BCCT, Danh mục, BOM, Đề xuất, Tờ khai, Tải lên.
- `app/static/css/app.css` — `tr[data-row-href]` cursor/hover/focus; upload
  metadata grid + preview table styles.
- `app/i18n.py` — nav-group labels + upload-detail/preview/status strings
  (VI + EN, parity 547/547).

## Tests / proof

- `tests/test_uploads_detail.py` — 8 cases: detail metadata + xlsx preview,
  download bytes + unicode disposition, csv preview, unknown→404, uploader
  column + row-href, nav 3-groups with proposals under BOM, customs-group active
  highlight, BCCT rows clickable.
- `tests/test_bcct_paging.py` — row-count proxy switched to `data-row-href`
  (one per `<tr>`; the inspect `<a>` now shares the same path).
- Full suite: **1488 passed, 16 skipped**.
- Screenshots: `screenshots/` (via `ui_smoke.py`).

## Known pre-existing gap (not changed)

The uploads "Xem ánh xạ" link only renders for `parse_status=='proposed_mapping'`,
but BCCT files awaiting mapping carry `mapping_pending` — so the link never
shows. Pre-existing (original code had the same guard); badge is now localized
but the link condition was left untouched to avoid disturbing the parse-mapping
flow. Fix separately if wanted.
