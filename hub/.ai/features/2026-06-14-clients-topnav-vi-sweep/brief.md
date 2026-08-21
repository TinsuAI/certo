# Clients page + top nav redesign + Vietnamese sweep

**Date:** 2026-06-14 · **Status:** shipped (local; tests + screenshots green)

Three of four user directives (2026-06-14). The 4th — "mỗi lần push prod phải update
CHANGELOG" — is a standing process rule, saved to memory
(`feedback_changelog_on_prod_push`) and applied here (CHANGELOG `[Unreleased]`).

## Directions chosen (by user)

- **Top nav** → "dọn gọn + menu người dùng" (user re-picked this after an initial
  mis-tap on the polish option).
- **Clients page** → keep row list, add search, Việt hoá badges, condense module grid.
- **Language** → keep customs acronyms (BCCT/BOM/HS/MST/NVL/TP/BTP/ĐVT/DNCX/CO/BCQT)
  **and** admin-technical terms (Adapter, Parser, Service token, Preset, UoM);
  translate feature names + raw enum values + casual English.

## Changes

**#2 Clients page (`clients/list.html` + CSS)**
- Instant client-side search (`#client-filter`, filters rows by name/code/MST via
  `data-search`; small inline script; `clients.search_placeholder/_empty` keys).
- Resolution-mode badge now Vietnamese (`clients.mode.<x>.short`: Mã trùng /
  Ánh xạ đơn giản / Gộp theo lô) instead of the raw enum.
- Bottom 6-tile "Dữ liệu nền" grid condensed to a one-line chip legend.
- CSS: `.zone-head .client-filter` (specificity > global `input[type=search]`
  `width:100%`), `.module-legend`.

**#3 Top nav (`base.html` + CSS)**
- Reworked to global chrome + user menu. Left: brand + section links
  `.topnav-nav` (Khách hàng · Quản trị, active from `active_root`). Right: theme
  toggle (standalone) + `.user-avatar` `<details>` dropdown (`.user-menu`, reuses
  `.nav-menu`/`.nav-menu-panel`, right-aligned) holding name+role, language switch,
  logout.
- Breadcrumb removed from the topnav — the client name already lives in the page
  header `<h1>` (via `_client_nav.html`), so global vs per-client is cleaner.
- Dead CSS left in place (`.topnav-breadcrumb`/`.breadcrumb-*`/`.topnav-user`); can
  be swept later.

**#4 Vietnamese sweep (`app/i18n.py` vi block + templates)**
- Tabs: Overview→Tổng quan, Proposals→Đề xuất, Uploads→Tải lên, Config→Cấu hình.
- Mode descriptions de-prefixed (Identity/Simple mapping/Batch aggregate →
  Mã trùng/Ánh xạ đơn giản/Gộp theo lô); + new `.short` label keys (vi+en).
- Proposal mode display label keys (`clients.proposal_mode.auto/manual/hybrid` →
  Tự động/Thủ công/Kết hợp); workspace config summary shows the VN label only.
- Field/meta de-Englished: "Chế độ resolve"→"Chế độ khớp mã"; bom_proposal_mode_meta,
  bom_tolerance_meta, bom_approver_tier_meta, bom_mode.*, approver_tier.*;
  module metas (version→phiên bản, request→đề xuất, auto-rule audit→nhật ký luật
  tự động, upload→tải lên, parse→đọc file); proposals.subtitle/review.body;
  upload titles; bcct.upload_help (Internal code→Mã nội bộ).
- Admin nav: "UoM standards"→"Chuẩn ĐVT".

## Kept English on purpose

Role identifier set (Dev/Admin/Manager/**Staff**) — translating only "Staff" would
break the set. Admin-technical terms per the chosen policy. Customs acronyms.

## Deferred (language follow-up, captured for a later pass)

Lower-visibility / genuinely-technical surfaces left untouched to keep this change
reviewable:
- **BOM flatten pages** — flatten / materialize / shallow / full_flat / unresolved /
  decision vocabulary (`flatten.*` keys, `bom.upload_profile` "Profile parser").
  No clean Vietnamese; staff-advanced surfaces.
- Admin sub-page sentences with lowercase "staff" (`admin.staff_assign.*`,
  `admin.manager_clients.*`).

## Tests / proof

Full suite **1480 passed / 16 skipped**. Screenshots (light+dark) in `screenshots/`:
`01_clients` (search + VN badges + legend), `02_clients_filter` (instant filter →
Johnson only), `03_workspace` (VN tabs/tiles/config + top-nav separator).
Regenerate: `uv run python .ai/features/2026-06-14-clients-topnav-vi-sweep/ui_smoke.py`.
