# Session: 2026-05-01 — Post-autopilot UX iteration

**Companion to:** `2026-05-01-autopilot-mvp-scaffold.md` (the autopilot build session that came right before this).

User woke up to the autopilot-built app, tested it, then drove 4 rounds of UX feedback. This session covers everything after the autopilot ended: restructure to client-workspace pattern, breadcrumb, dual-source detection, payload jsonb, button restyle, i18n overhaul, settings page redesign.

## What Was Done

Commits in chronological order (after `6cd5d6f docs: README`):

1. **`a6eee76` — Client workspace restructure + i18n EN/VI + auto-seed**
   - Migration `007_dncx_to_clients.sql`: rename `hub.dncxs → hub.clients`, `dncx_id → client_id` across 10 tables. Global Python rename (16 files updated) via regex script.
   - URLs reorganized: top-level `/clients` + `/clients/new`; everything else nested under `/clients/{client_id}/{tab}`. No more global "all materials across clients" view.
   - Top-nav reduced from 6 entity links to single "Khách hàng" link.
   - 17 templates rewritten using barry-CO-main classes: `page-bar`, `zone`, `zone-head`, `zone-muted`, `tab-link`, `hero`, `hero-stat`, `module-tile`, `module-link`, `rowlist`, `rowitem`, `chip-row`, `chip-active`, `callout`, `mini-panel`, `subsection-head`.
   - `_client_nav.html` partial: client header (page-bar) + tab strip (Overview/Catalog/BQD/BCCT/BOM/Proposals/Uploads/Config). Included by every workspace page.
   - i18n module: `app/i18n.py` with VI (default) + EN dicts (~120 keys initially); `t()` callable in Jinja context via context_processor. Cookie `data_hub_lang`. Toggle button in topnav next to theme.
   - Auto-seed: `app/seed.py` runs in lifespan when 0 clients. Creates Growatt VN (full data set: 10 catalog + 8 BQD with 1:n + 10 BCCT + 4 BOM + 2 proposals) and Johnson VN (4 catalog identity-mode + 3 BCCT + 1 BOM). Disable via `DATA_HUB_AUTO_SEED_DEMO=0`.

2. **`fa67765` — Dynamic breadcrumb + dual-source badge**
   - Topnav-links replaced with breadcrumb component built inline in `base.html` from existing `client` + `active_tab` context.
   - Initial form: `Khách hàng / {ClientName} / {TabName}` (3 levels).
   - Dual-source detection: catalog list query joined to BCCT-imports + BOM-products EXISTS subqueries. Material is `is_dual_source=true` if its `customs_code` appears both as BCCT direction='import' AND as a published BOM `product_code`.
   - Catalog template renders "⇄ dual" badge (badge-dual class, purple) next to category when flag is true.
   - Approach matches Growatt's `classify_complexity()` algorithm: dual-source is computed at query time from cross-table joins, NOT stored as a category attribute.
   - Added HEATSINK-A BOM (made from AL-100) to seed for demo purposes.

3. **`8278ba8` — 2-level breadcrumb + raw HQ payload + button restyle**
   - Breadcrumb capped at 2 levels per user request: just `Khách hàng / {ClientName}`. Tabs are visible inside `_client_nav.html`, no need to duplicate in topnav.
   - BCCT parser now captures EVERY source workbook column into `payload` jsonb keyed by original Vietnamese header names ("Số tờ khai", "Mã loại hình", "Ngày đăng ký", etc.). Insert handler serializes via `json.dumps(ensure_ascii=False)`. Real HQ Excels with 25-30 cols will preserve everything; typed columns are query/index layer on top.
   - Buttons restyled to match barry-CO-main lean style: padding 0.5rem 0.95rem (was chunky 1.4rem), min-height 2.25rem, font-weight 700, primary uses `--primary` token, inline-flex centering, subtle hover/active transitions.

4. **`4bd6d3a` — i18n comprehensive overhaul + settings page redesign**
   - i18n keys grew from ~120 to ~150. Added: `workspace.stat.*`, `workspace.module.*_meta` with `{n}` placeholder, `bom.material/qty_per_unit/uom/bom_code/bom_variant/row_index/context`, `proposals.materialized/parent/decided_at/decided_by/decision_reason/hash/status_*`, `catalog.search_placeholder/upload_help/upload_hint_sheet/dual_source_tooltip`, `bcct.search_placeholder/upload_help`, `bqd.upload_help/basis_label`, `uploads.summary_done/error/pending`, `status.*`, `clients.mode.*` (human-readable mode descriptions), `clients.row.tax`.
   - Comprehensive audit fixed all hardcoded English in: workspace.html (stat labels, module tile descriptions), bom_version_detail.html (table headers), proposal_detail.html (table headers), bqd.html (resolver hint), all 4 *_upload.html pages (file format hints).
   - Settings page (formerly "Sửa khách hàng") fully redesigned:
     - **Title**: "Cấu hình & Thông tin" (was awkward "Sửa khách hàng").
     - 5 sections, each with title + meta description: Identity / Code resolution / BOM auto-approval / Lifecycle / Notes.
     - Code resolution dropdown shows human-readable labels: "Identity — mã nội bộ trùng mã hải quan", "Simple mapping — bảng quy đổi 1-1 hoặc 1:n có ưu tiên", "Batch aggregate — disambiguate 1:n bằng số lượng BCCT".
     - Save+Cancel sticky in both top page-bar and bottom settings-footer.
     - New CSS: `.settings-form`, `.settings-section`, `.settings-grid` (responsive 280px min), `.field-wide`, `.field-required`, `.field-hint`, `.settings-footer`.
   - Phrase rephrasings: "Sửa khách hàng" → "Cấu hình & Thông tin"; "Đổi khách hàng" → "← Danh sách khách hàng"; "Sửa" → "Chỉnh sửa"; "Save" → "Lưu thay đổi"; "Upload BOM/BCCT/BQD" → "Tải lên BOM/BCCT/BQD"; "& Parse" → "& xử lý"; "Audit trail các proposal" → "Lịch sử yêu cầu thay đổi BOM"; "BOM (Bill of Materials)" → "Định mức (BOM)"; "Mỗi product = 1 version mới" → "Mỗi sản phẩm = một phiên bản BOM mới".

## Decisions Made

- **Client workspace pattern over global views.** When user said "Mental model: Chọn 1 khách hàng → quản lý data của họ", that was the right call. Removes ambiguity of which-client-am-I-viewing-now from every entity page; client identity moves to URL + breadcrumb + page-bar header instead of being a query param dropdown.
- **DNCX → Client at schema level**, not just UI. Migration 007 renames table + column. Cleaner to commit fully than maintain dual naming. 16 Python files touched via global regex; tests still pass.
- **Dual-source NOT stored as material attribute.** Computed at query time via EXISTS subqueries on existing indexes. Reasoning: scale is small (10s-100s materials per client), subqueries are fast, no cache invalidation complexity. Aligns with Growatt's `classify_complexity()` algorithm in `bcqt-growatt/settlement/code_map.py` which also computes dual-source at settlement runtime, not as material attribute.
- **Multi-category materials answer:** keep single primary category per material. Dual-source is a derived classification, not a category. Override available via existing `category_override` + `override_reason` columns (UI not exposed yet but schema ready). Settlement-time complexity (BTP no BOM, ĐVT mismatch, R&D only, dual-source) is BCQT's job, not Data Hub's.
- **BCCT payload jsonb captures all columns** by original Vietnamese header name. Typed columns are query/index layer; payload is the raw archive that preserves anything we don't promote. This is the answer to the user's "Các cột thì nên cho vào payload jsonb hết đi".
- **Breadcrumb capped at 2 levels.** Tabs are visible inside `_client_nav.html`; duplicating tab name in breadcrumb is redundant.
- **Code resolution mode is immutable post-creation** — UI shows lock badge, form field disabled but value preserved as hidden input.
- **i18n via `t()` callable** in Jinja context (not a filter). Adds the function to template_context; templates call `{{ t('key') }}`. For interpolated strings, use Jinja's `|replace('{n}', value|string)` pattern.
- **CO's CSS is the design language** — Data Hub's CSS is mostly inherited verbatim (~1300 lines from `barry-CO-main/app/static/css/app.css`). Only ~150 lines added (breadcrumb, settings page, dual badge, button override, dark theme tweaks).

## What Didn't Work

- **Initial auto-seed had FK violation.** Tried to insert BCCT rows before `file_uploads` stub row. Fixed by reordering: insert stub first, then call `_insert_bcct` referencing it.
- **First i18n pass missed many hardcoded English strings.** User pointed it out: "Lam i18n triet de di may, tao thay nhieu cho van tron lan TA - TV". Required full audit pass: workspace stat labels, BOM version detail headers, proposal detail row labels, upload page hints, etc. Used `grep -rn -E '<th>[A-Z]|placeholder="[A-Z]'` to find candidates.
- **First button styling looked wrong.** User: "may cai btton tao dang thay ky qua". Original `.btn-primary` had chunky `padding: 0.65rem 1.4rem`; redesigned to CO's lean `0.5rem 0.95rem` with `min-height: 2.25rem`, `font-weight: 700`. Much better.
- **First seed didn't have any actual dual-source materials** — added HEATSINK-A as a BOM product (made from AL-100) to demo the badge.
- **"Sửa khách hàng" sounded awkward in Vietnamese** — user: "De y ngon ngu 'Sua khach hang' nghe rat chuong tai". Rephrased to "Cấu hình & Thông tin".
- **Linter / hot-reload race conditions** — modifying many files in a batch sometimes had Edit tool fail with "File has been modified since read" because uvicorn `--reload` triggered intermediate state changes. Worked around by deleting and rewriting fresh in a single Write call.

## Open Items

1. **Real Growatt data validation** — synthetic seed has 10 BCCT rows; real files at `~/workspace/client/bcqt-growatt/data/` have thousands. Test parser performance + resolver correctness at scale.
2. **Other reference clients** — DKE, Dothanh, Johnson real data not yet validated against parsers. May surface different goods-name patterns (Growatt regex `_PAT_F1`/`_PAT_F3`/`_PAT_F4` may not cover all shapes; e.g., `(CU-WIRE-2.A1)` with dashes was noted to fail).
3. **Background job for resolver** — runs synchronously inside BQD/BCCT upload handlers; will block on big uploads. Move to async queue (RQ / arq / celery) when first slow upload happens in real use.
4. **SSO design** (M9 deliverable #4) — currently single-deployment cookie session. Cross-app SSO design needed for BCQT/CO federation.
5. **Service-discovery to CO** for auto-rule criterion #2 (`context.case_id` references active CO case) — DROPPED from MVP because CO has no HTTP API. Reinstate when CO grows one.
6. **Manual + hybrid BOM review modes** — schema is shaped to accept (`bom_change_requests.status`, `decided_by`, `decision_reason`, `failed_conditions`). Phase 2 work: notification system, latency SLO, review queue endpoints (`GET /v1/hub/proposals?status=pending`, `:approve`, `:reject`, `:withdraw`).
7. **Production deployment shape** (M9 deliverable #6) — systemd, pg_dump backup, Litestream for BCQT per-project SQLite (cross-app), nginx reverse proxy, real DNS, TLS certs.
8. **JWT scope auth on read API** — currently accepts any non-empty bearer; phase 2 JWT scope check (`hub:read:bcct`, `hub:read:materials`, etc.).
9. **`bom.growatt_multi_workbook` and `johnson_sap_exploded` profiles** — exist as parser code but only `manual_flat` validated against synthetic seed. Need real Growatt + Johnson files to verify.
10. **Tombstone UI** — schema has `tombstoned_at` + `tombstone_reason`; no UI to invoke. Add when needed.
11. **Material `category_override` + `override_reason` UI** — schema ready; admin UI not exposed.
12. **API versioning gate when /v2 lands** — currently `/v1/...` is implicit; no version negotiation logic. Add when /v2 needed.

## How to Resume

```bash
cd ~/workspace/client/data-hub
# server should be running already; if not:
uv run uvicorn app.main:app --port 8754 --host 127.0.0.1 --reload
# Visit http://127.0.0.1:8754, login admin@data-hub.local / admin123
# Auto-seed creates Growatt + Johnson on first boot if DB is empty.

# Reset to fresh state:
psql -d data_hub -c "truncate hub.clients cascade"
# (re-seed runs on next request because lifespan re-runs)

# Test:
uv run pytest                    # 28 tests
uv run python scripts/screenshot.py  # captures 27 UI screenshots

# To experiment with real Growatt data:
ls ~/workspace/client/bcqt-growatt/data/02.04.2026/   # latest data dump
# Upload via UI: /clients/growatt-vn/{catalog,bqd,bcct,bom}/upload
```
