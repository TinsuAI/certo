# FLOW-PROPOSAL — CO, flow and information architecture

Companion to `DESIGN.md`. `DESIGN.md` owns the visual contract (tokens, shell,
components) and has already decided the shell shape: 52px header + 228px grouped
sidebar + a pipeline `rail`, company switcher in the header, theme toggle in the
user menu. This file owns what goes *in* that structure, in what order, and what
would have to change in routes or handlers to get there. Nothing here is built —
`DESIGN.md` §5 puts route changes, endpoint contracts and step logic out of scope
for this round.

**Measurement base.** Live local `:8001` (auth off, real Data Hub `:8754`),
client `johnson-vn`, case `co-case-e0b390ead3b0` (`CO-JOHNSON-VN-INV-E0B3`), 4
products / 267 NVL rows (105 + 44 + 59 + 59). Byte counts are from saved
responses; the origin page was captured before the reskin agent's sidebar landed
in `base.html`, so it shows the pre-redesign nav. Where a timing appears it is a
number already verified in `.ai/STATUS.md` or a session summary, not one of my
own curl timings (the server was reloading under a parallel agent throughout).

---

## 1. The operator's real job

A CO dossier preparer works one client company at a time and, inside it, one
export shipment at a time. Before any case can be worked, the client's background
data must exist: catalog (products + materials) and BCCT come from Data Hub, BOM
is either published in Data Hub or proposed from CO, and CO derives its own
**Tồn CO** snapshot — the import lots still eligible to back a C/O — from BCCT
through `co_stock_materializer`, filtered by the client's eligible import
declaration types and the `min_days_before_export` rule. For each shipment the
operator creates a case and records the shipment identity (invoice no, bill of
lading, export declaration numbers, destination market — the market is what
drives the form recommendation; `co_form_type` set at step 1 is a label and binds
to nothing downstream, per BACKLOG RD1), then uploads the 3 required documents
(BL, Invoice, Packing) plus up to 4 supplementary ones. The real work is step 3:
for every finished product on the invoice, load its BOM, let the engine allocate
import lots to each NVL line, and then clear whatever the allocation could not
resolve — rows whose code appears in no import declaration (`declarable_unmatched`)
must be substituted or deleted, non-material rows (`excluded_non_material`)
deleted, cross-unit pairs (EA→CAY) given a conversion factor, and missing đơn giá
supplied — because each of those blocks the lock. The operator picks an origin
criterion and threshold (per sheet, or once for the whole lô), presses **Tính**,
reads the LVC/CTC verdict, and presses **Chốt**, which writes `co_stock_claims`
into the ledger and freezes that sheet's snapshot. Sheets are worked **in order**:
stock is allocated sequentially down `origin_product_order`, so sheet 1 consumes
lots before sheet 2 sees them, and editing sheet *n* marks every sheet after it
stale (`origin_codes_to_recalculate`). Once all sheets are locked the operator
goes to step 4 to pull TKX/TKN declaration files from Data Hub, then step 5 to
close the case and export the dossier `.zip` (chứng từ + TKX/TKN + bảng kê HQ).
The whole loop repeats per shipment; the background-data screens are touched only
when something in step 3 turns out to be missing.

---

## 2. Current screen inventory

"Clicks from work" = forward clicks from the origin step of an open case to reach
the screen, then back to the same origin step. Two numbers: **out / back**.
"old" = the nested `<details>` nav in `_client_nav.html` still present today;
"new" = the sidebar the reskin agent has landed in `base.html`. Browser Back
collapses the return leg to 1 and is what operators actually use — the number
below is the cost of the app's own navigation.

| Route | Template | What it is for | Job step | How reached | Out / back |
|---|---|---|---|---|---|
| `/`, `/clients` | `clients.html` | Company picker + open-case counts | 0 (entry) | Brand, sidebar "Danh sách công ty" | 1 / 3 |
| `/clients-picker` | `_picker_clients.html` | Company switch modal fragment | 0 | `[data-picker-open]` in header | 1 / 0 |
| `/clients/{id}` | `workspace.html` | Client dashboard: recent cases + data readiness | 0 | Sidebar "Tổng quan" | 1 / 3 |
| `/clients/{id}/catalog` (+`/materials`,`/products`) | `catalog.html`, `catalog_table.html` | Product/material catalog, upload, templates | prep | old: Dữ liệu ▾ → link; new: sidebar | old 2 / new 1 · back 3 |
| `/clients/{id}/bom` | `bom.html` | BOM view + upload + BOM config | prep | same | old 2 / new 1 · back 3 |
| `/clients/{id}/bcct` (+`/imports`,`/exports`) | `bcct.html` | BCCT rows, import/export tabs, upload | prep | same | old 2 / new 1 · back 3 |
| `/clients/{id}/co-stock` | `co_stock.html` | Tồn CO snapshot, **Refresh từ Data Hub**, import/export snapshot | prep + unblocks step 3 | same | old 2 / new 1 · back 3 |
| `/clients/{id}/co-stock/workbook-tool` | `co_stock_workbook_tool.html` | Convert agency trừ-lùi `.xlsm` → snapshot | prep (rare) | Only two callouts inside `/co-stock` | old 3 / new 2 · back 3 — **≥3 under the old nav** |
| `/clients/{id}/config` | `client_config.html` | Per-client runtime config: legal name/MST, lot policy, `min_days_before_export`, `features.bulk_delete_junk_rows`, allocation-code strategy, column (9) mode, TKN PDF part size | rules for step 3 | old: Cấu hình ▾ → link; new: sidebar | old 2 / new 1 · back 3 |
| `/clients/{id}/cost-allocation` | `cost_allocation.html` | Cost-allocation coefficients (applied from the origin toolbar) | rules for step 3 | same | old 2 / new 1 · back 3 |
| `/clients/{id}/suppliers` | `suppliers.html` | NCC evidence flags (Phụ lục X / C/O nhập) — 136 rows for johnson-vn | rules for step 3 | same | old 2 / new 1 · back 3 |
| `/clients/{id}/co-case` | `co_case.html` (index branch) | Case list, status chips, create/archive/delete, time filter | 1 (entry) | old: tab; new: sidebar | 1 / 2 |
| `/clients/{id}/co-case-picker` | `_picker_cases.html` | Case switch modal fragment | any | "Đổi hồ sơ" in case header | 1 / 0 |
| `/clients/{id}/co-case/{case}` | `co_case.html` step `shipment` | Invoice / B/L / export declarations / market | 1 | Rail step 1; **every case link lands here** | 1 / 1 |
| `…/{case}/documents` | same | 7 upload slots (3 required, 4 supplementary) | 2 | Rail step 2 | 1 / 1 |
| `…/{case}/origin` | same | Bảng kê C/O — the work | 3 | Rail step 3 | — |
| `…/{case}/exports` | same | TKX/TKN status + declaration file download | 4 | Rail step 4 | 1 / 1 |
| `…/{case}/review` | same | Close case + export dossier `.zip` + 3-row checklist | 5 | Rail step 5 | 1 / 1 |
| `…/{case}/export-dossier-zip/status` | `_dossier_export_status.html` | Polled background-export status fragment | 5 | Auto-poll | — |
| `/settings` | `settings.html` | Hub page: 3 tiles | admin | User menu → Cài đặt (old); sidebar (new) | old 2 / new 1 · back 3 |
| `/settings/co-forms` | `co_form_settings.html` | Market aliases, form priority, PSR sources | admin | Only via `/settings` tile | old 3 / new 2 · back 3 — **≥3 under the old nav** |
| `/settings/technical` | `data_hub_settings.html` | CO↔DH URLs, SSO/JWKS, connection test | admin (dev role) | User menu, or `/settings` tile | 2 / 3 |
| `/settings/data-hub` | `data_hub_settings.html` | **Same handler, same template as `/settings/technical`** | admin | **Not linked from any template** | ∞ — URL only |
| `/customs-exchange-rates` | `customs_exchange_rates.html` | Shared customs FX table + refresh | rules for step 3 | `/settings` tile (old); sidebar (new) | old 3 / new 1 · back 3 — **≥3 under the old nav** |
| `/clients/{id}/customs-exchange-rates` | — | 303 → `/customs-exchange-rates`, drops client context (`customs_fx.py:88-90`) | — | **Not linked from any template** | ∞ — URL only |
| `/user` | `user.html` | Session, role, claims | admin | User menu → Tài khoản | 2 / 3 |
| `/whats-new` | `whats-new.html` | Changelog | — | Footer (old); sidebar (new) | 1 / 3 |
| `/portfolio/` | `portfolio.html` | Source-portfolio dashboard, mounted sub-app (`main.py:85`) | — | **Not linked from any CO template**; its own body links to raw JSON endpoints | ∞ — URL only |
| `/auth/login`, `/auth/callback`, `/sso_logout` | `sso_logout.html` | SSO | — | Login chip | — |
| (exception handler) | `error.html` | Error page (`main.py:131`) | — | — | — |

**Unreachable in under 3 clicks from an open case** (or at all):
`/portfolio/`, `/settings/data-hub`, `/clients/{id}/customs-exchange-rates` — no
link exists anywhere. Under the old nav also: `/co-stock/workbook-tool` (3),
`/settings/co-forms` (3), `/customs-exchange-rates` (3). The new sidebar fixes
the last three; it does not touch the first three.

---

## 3. Named problems

Ordered by cost to the operator per case.

**1. The origin step renders the whole case into one document, and every
save re-fetches it.**
`GET …/origin` for `co-case-e0b390ead3b0` returns **3,992,010 bytes**: 274,908
bytes of inline JS and **3,717,102 bytes of DOM** — 419 `<tr>` across 4 grids,
**15,414 hidden `<input>`** carrying per-row state, 607 `<button>` with 339
distinct labels, 5 `origin-config-panel` instances ("Cấu hình bảng kê" appears 20
times), 10 `modal-backdrop` layers. `?sheet=<code>` does **not** reduce this:
`origin_view` / `active_sheet_code` (`co_case_context.py:393-396`) are consumed
only as a CSS class and a data attribute (`co_case.html:864-866`); the sheet loop
is ungated, so sheet switching is a client-side show/hide over a fully-rendered
DOM. Cost: per-sheet **Tính** and per-sheet **⚙ Lưu** call
`refreshCaseShellInPlace`, which re-fetches the current URL as `text/html` — the
full 4 MB — to update one sheet. On the measured case that is 4 sheets × (1 Load
BOM + ≥1 Tính + 1 Chốt + n config saves) full-document round trips.

**2. Every case page ships the origin step's JavaScript.**
Inline JS is **274,908 bytes on all five steps and on the case list**
(`/co-case` = 278,214). Content bytes per step: shipment 23,021 · documents
24,841 · exports 20,046 · review 18,174. On the review step **93.8 %** of the
response is JS for surfaces that are not on the page. The "Tìm NVL thay thế"
modal and the "Hệ số quy đổi đơn vị tính" modal, plus the buttons `Xoá dòng này`
/ `Khuyến nghị` / `Tìm kiếm` / `Lưu và tính lại`, render into the DOM of the
shipment, documents, exports and review steps **and the case list**, none of
which has an NVL row.

**3. Opening a case always lands on step 1, never on the work.**
Every case link — `workspace.html` "Hồ sơ C/O gần đây", the case-list row
(`co_case.html:334-430`), the client card on `/clients` — points at
`/clients/{id}/co-case/{case_id}`, i.e. `step=shipment`. Step 1 is a form filled
once at creation. Cost: **+1 click per case open**, plus one step-1 render (23,021
bytes of content behind 274,908 bytes of JS) before the operator can click step 3.

**4. Four settings that change step-3 numbers live on a screen outside the case,
and the config form is all-or-nothing.**
`bang_ke_column9_mode` and `bang_ke_unknown_origin_label` (column 9 text),
`features.bulk_delete_junk_rows` (gates the rác bulk-delete buttons on the origin
step), `co_stock_min_days_before_export` and the eligible import declaration types
(decide which lots exist at all) are all on `/clients/{id}/config`. Round trip
from the origin step: 1 click out (new sidebar) + Lưu + **3 clicks back**
(Hồ sơ C/O → case row → step 3), landing on step 1 on the way. Worse, the second
half of `save_client_config_route` (`pages.py:328-340`) is **not** presence-gated
the way the first half is: `co_stock_lot_policy`, `allocation_code_strategy`,
`description_regex`, `allocation_code_fallback` fall back to hardcoded defaults
and `features_bulk_delete_junk_rows` falls back to `False` when the field is
absent. A partial POST would reset `growatt-vn` from `description_regex` to
`same_as_customs_code` — **2,145/2,236 distinct BOM codes match down to
101/2,236** (DECISIONS 2026-07-16) — and then call `refresh_client_indexes`.

**5. The Tồn CO refresh that unblocks step 3 is on a different screen with no
signal from step 3.**
`POST /clients/{id}/co-stock/refresh` is reachable only from the "Refresh từ Data
Hub" chip on `/co-stock`. The origin step reports the consequence (thiếu tồn,
"thiếu đơn giá" blocking Chốt on a cold client — memory note
`demo-company-seed-co-datahub`) but offers no way to act on it. Cost when it
happens: 1 click out + refresh + 3 clicks back + Tính lại = 6 forward clicks plus
a client-wide re-derivation the operator triggers blind.

**6. Two triage surfaces for the same rows, two default scopes.**
Unmatched/non-material rows are triaged both in the aggregate "▦ Tổng hợp NVL
thiếu tồn" panel and in each sheet's `[data-sheet-rac-mount]`, rendered by the
same `racPanelHtml` / `wireRacPanel`. The substitute picker has the same split
(aggregate `bulk-substitute` vs per-row `substitute-row`), and the two carried
different scope defaults until 2026-08-06 flipped the aggregate to `everywhere`.
On the measured case the aggregate lists 63 foldable rows while the four sheets
list 27 / 11 / 13 / 12 of the same population.

**7. Seven stacked navigation strips above the first grid row on the origin
step** (pre-redesign capture): `nav.breadcrumb`, `.page-bar` (client h1 + MST +
status badge), `nav.tabs.client-tabs`, `.zone.co-case-header` (case code + "Đổi
hồ sơ"), `nav.workflow-stepper`, `.origin-page-bar`, `.origin-review-toolbar`.
Three of them name the company or the case; two are navigation the new sidebar
duplicates. The reskin agent's `base.html` now carries the sidebar and the header
company switcher, and has already stripped the "Đổi công ty" button out of
`_client_nav.html`, but `.page-bar` and `nav.tabs.client-tabs` (with both
`<details>` dropdowns) are still emitted on every client page — so a client page
renders **two** client navigations at once.

**8. Sheet allocation order is decided behind a modal.**
"Đổi thứ tự sheet" opens `#origin-reorder-title`; the order it sets is what
`origin_product_order` uses to allocate stock sequentially, and changing it marks
every downstream sheet stale. The only on-screen statement of this is a hint line
("Thứ tự quyết định sheet nào trừ tồn trước."). The sheet chips do render "Bước
N", but the connection between the number and the modal is not made.

**9. Three screens are unreachable by clicking.** `/portfolio/` (mounted at
`main.py:85`, body links to raw JSON API endpoints), `/settings/data-hub`
(identical handler and template to `/settings/technical`,
`settings.py:428-436`), `/clients/{id}/customs-exchange-rates` (303 that discards
the client id, `customs_fx.py:88-90`). Cost is zero per case but they are three
routes, three templates and a mount to keep working.

**10. Step 5 is a router, not a screen.** `review` renders 18,174 bytes: two
buttons ("Đóng hồ sơ", "Xuất hồ sơ .zip") and a 3-row checklist whose rows are
"Mở →" links back to steps 2, 3 and 4. It has no content of its own.

---

## 4. Proposed IA

### 4.1 Sidebar groups — literal labels

Paste text for `app/templates/base.html`. Group labels name the step of the job,
not the data type (DESIGN.md §5). Delta from what is in `base.html` today is
marked; the item set is close, the grouping and the labels are not.

```
CÔNG TY                       ← was "Hồ sơ"
  Tổng quan
  Hồ sơ C/O            <n>    ← add the open-case count pill

CHUẨN BỊ DỮ LIỆU              ← was "Dữ liệu nguồn"
  Danh mục mã hàng     <n>
  BOM                  <n>
  BCCT                 <n>
  Tồn CO               <n>

QUY TẮC TÍNH                  ← was "Cấu hình công ty"
  Cấu hình công ty
  Hệ số phân bổ
  NCC / Phụ lục X

DÙNG CHUNG                    ← was "Hệ thống"
  Danh sách công ty
  Tỷ giá hải quan
  Bộ form C/O                 ← new entry, today only a tile inside /settings
  Cài đặt
  Có gì mới
```

Rules: only the four groups above; no nested `<details>`; the client-scoped three
groups render only when `nav_client` is set, `DÙNG CHUNG` always. `Cài đặt kỹ
thuật` stays in the user menu behind the dev-role check — it is not part of the
job.

### 4.2 Case pipeline rail — literal labels

`.rail` under the header, visible on all five case steps, every step always shown,
current step marked, completed steps dimmed. Labels are the `label` values in
`CO_CASE_WORKFLOW_STEPS` (`app/web/co_case_context.py:209-240`); the `key` values
stay untouched so every route and every status test keeps working.

```
1  Lô hàng
2  Chứng từ
3  Bảng kê C/O
4  Tờ khai XK / NK        ← was "TKX / TKN"
5  Đóng & Xuất hồ sơ      ← was "Review & Xuất"
```

Status text under each label already comes from `co_case_step_status` and reads,
on the measured case: `Thiếu thị trường` · `Chưa tải` · `Đang làm · 0/4 chốt` ·
`Đủ` · `Sẵn sàng`. Keep it.

### 4.3 Sheet sub-rail inside step 3

A second rail row, visible only on step 3, replacing the bottom sheet tabs and
the "Xử lý tuần tự / ▦ Tổng hợp NVL" toggle:

```
▦ Tổng hợp NVL   │   1 · MFW0525-39   2 · MFW0520-17   3 · MFW0504-39   4 · MFW0502-39   │   ⇅ Đổi thứ tự
```

The leading number is the allocation order, so problem 8 is answered by the
layout instead of a hint line; "⇅ Đổi thứ tự" sits next to the numbers it changes.
Locked sheets keep the 🔒 already added by BACKLOG B8.

### 4.4 What merges, what becomes a panel, what disappears

**Merge**
- `/clients/{id}/co-stock/workbook-tool` → a panel inside `/clients/{id}/co-stock`.
  It is already reachable only from two callouts on that page; its two POST routes
  (`convert-workbook`, `import-snapshot`) are unchanged and the route stays as a
  permalink.
- `/settings/data-hub` → drop the alias; `/settings/technical` is the same handler
  and the same template.
- `/settings/co-forms` and `/customs-exchange-rates` → promote both out of the
  `/settings` tile grid into the sidebar. `/settings` then holds only the account
  tile and the technical link, and can itself be folded into the user menu later.

**Panel inside another screen**
- The five per-sheet `⚙ Cấu hình bảng kê` panels → one modal instance parameterised
  by the active sheet, plus the existing case-level one. Today the same markup is
  emitted 5 times into one document.
- Customs FX → a read-only "tỷ giá đang dùng" line on `/clients/{id}/config`
  linking to the shared table, so the operator can see the input without leaving.
- The case-relevant knobs from `/clients/{id}/config` → a "⚙ Quy tắc công ty"
  modal on the origin toolbar (see §5, item H — this one needs a route change).

**Disappear**
- `.page-bar` and `nav.tabs.client-tabs` in `_client_nav.html` — replaced by the
  header switcher and the sidebar. Keep the file: it also renders the breadcrumb
  and the server-side `{% if message %}` / `{% if error %}` flashes.
- `.zone.co-case-header`'s client-name repetition; keep the case code, status and
  "Đổi hồ sơ".
- `/portfolio/` — unlinked dashboard pointing at raw JSON. Either delete the mount
  or link the JSON endpoints from `/settings/technical` and delete
  `portfolio.html`.
- `/clients/{id}/customs-exchange-rates` — a 303 with no caller.

---

## 5. Proposed flow changes

### Safe, nav-only

**A. Delete the duplicate client navigation.**
*Today:* on a client page the operator sees breadcrumb → client h1 + "Đổi công
ty" → tab bar (with two `<details>` dropdowns) → page content, and — since the
reskin agent's `base.html` landed — a sidebar and a header switcher saying the
same things.
*Instead:* header switcher + sidebar only. `_client_nav.html` keeps the breadcrumb
and the flash blocks.
*Code:* `app/templates/_client_nav.html` — remove the `<section class="page-bar">`
and `<nav class="tabs client-tabs">` blocks. All 9 templates that
`{% include "_client_nav.html" %}` are unaffected.
*Risk:* do not delete the include — the server-side flash messages
(`{% if message %}` / `{% if error %}`) have no other renderer, and the breadcrumb
is the only in-case path back to the case list. The reskin agent has already
removed the "Đổi công ty" button and the `#client-picker-modal` copy from this
file (both now live in `base.html`), so only the two blocks named above are left
to remove.

**B. Move the workflow stepper into the shell `rail`.**
*Today:* `nav.workflow-stepper` is at `co_case.html:524`, inside the page body,
below four other strips.
*Instead:* a `{% block rail %}` in `base.html` rendered directly under the header;
`co_case.html` fills it from the unchanged `co_case_workflow_steps()`.
*Code:* `base.html`, `app/templates/co_case.html:524`.
*Risk:* the stepper currently lives inside `[data-co-case-shell]` and is refreshed
by `replaceCaseShellFromResponse`; moved outside that region, step status stops
updating after an in-place Tính/Chốt. Either keep the rail inside the swapped
region or extend `replaceCaseShellFromResponse` to swap the rail node too — and
because in-app step nav uses `importNode`, any new wiring must go into
`refreshCaseShellInteractions`, not an inline `<script>`.

**C. Relabel steps 4 and 5.**
*Code:* `app/web/co_case_context.py:209-240` — `label` only, `key` unchanged.
*Risk:* `tests/test_co_demo.py:1943` asserts the literal `"TKX / TKN"` in the
exports response; update it. `tests/test_co_case_step_status.py` keys on `key`,
not `label`.

**D. Sidebar group relabel and the `Bộ form C/O` promotion (§4.1).**
*Code:* `app/templates/base.html:246-277`, `app/templates/settings.html`.
*Risk:* none.

**E. Number the sheet chips by allocation order and put "⇅ Đổi thứ tự" beside
them (§4.3).**
*Code:* `app/templates/co_case.html` sheet-tab markup + `.origin-review-toolbar`.
*Risk:* none — "Bước N" is already rendered in the review rows; this moves the
same value into the chip label.

**F. Drop the three unreachable routes (§4.4).**
*Code:* `app/main.py:85` (portfolio mount), `app/routers/settings.py:429/440`
(`/settings/data-hub` alias), `app/routers/customs_fx.py:88-90`.
*Risk:* check `tests/` for direct `client.get("/portfolio/...")` and
`"/settings/data-hub"` calls before removing; the portfolio *service* class is
used everywhere and must not be touched — only the HTML mount.

### Needs a route or logic change

**G. Render one sheet at a time on the origin step.**
*Today, click by click:* open step 3 → 3,992,010 bytes → click sheet 2 →
client-side show/hide, 0 bytes → press Tính → `POST …/origin/sheet/{code}/calculate`
→ `refreshCaseShellInPlace` re-fetches the same 4 MB → press ⚙ Lưu → another 4 MB.
*Instead:* step 3 lands on the aggregate only; a sheet chip navigates to
`?sheet=<code>` which renders the aggregate + that sheet; Tính/Lưu refresh only
that URL.
*Code:* `app/templates/co_case.html` sheet loop under `[data-origin-sheet-workspace]`
(gate on `active_sheet_code`), `app/web/co_case_context.py:393-396` (already
computes the value), the sheet-tab click handler and
`replaceCaseShellFromResponse` / `refreshCaseShellInPlace` in `co_case.html`.
*Risk: high.* Per-sheet client state lives in the DOM — `override_history` / redo
per sheet and the 30s autosave (memory note
`bangke-post-save-undo-override-history`). Dropping a sheet's nodes drops its
unsaved edits, so the chip navigation must go through the same dirty check the
Excel-like save model already applies. The aggregate must keep rendering: it is
what reports the downstream-stale set from `origin_codes_to_recalculate` and the
`folded_rac` list, and hiding it would recreate the 2026-08-17 defect where the
panel invited "Chốt tất cả" while the lock gate refused.

**H. Bring the case-relevant client-config knobs into the origin step.**
*Today:* origin step → sidebar "Cấu hình công ty" (1) → change → Lưu (2) →
sidebar "Hồ sơ C/O" (3) → case row (4, lands on step 1) → rail step 3 (5).
*Instead:* a "⚙ Quy tắc công ty" button on the origin toolbar opening a modal with
`bang_ke_column9_mode`, `bang_ke_unknown_origin_label`,
`features.bulk_delete_junk_rows` and `co_stock_min_days_before_export`, posting to
the existing `POST /clients/{id}/config`, then `refreshCaseShellInPlace`.
*Code:* `app/routers/pages.py:258-357`, `app/templates/co_case.html` (modal +
`refreshCaseShellInteractions`).
*Risk: high, and the mechanism is specific.* The first half of that route is
presence-gated (`if "legal_name" in form`, `if "bang_ke_column9_mode" in form`, …)
and a partial POST is safe for those. The second half (`pages.py:332-340`) is
**not**: `form.get("co_stock_lot_policy", "line_level")`,
`form.get("allocation_code_strategy", "same_as_customs_code")`,
`form.get("description_regex", "")`, `form.get("allocation_code_fallback", …)` and
`form.get("features_bulk_delete_junk_rows") == "1"` all overwrite with defaults
when the field is absent. A partial POST from the modal would silently reset
growatt-vn's allocation strategy (96 % → 4.5 % BOM match, DECISIONS 2026-07-16)
and then run `refresh_client_indexes`. Either split a narrow route for the four
knobs or make the second half presence-gated first. Separately, changing
`bang_ke_column9_mode` calls `_apply_client_column9_mode_flip`, which marks
calculated sheets stale **across every case of that client** — that confirm must
stay, and it must state how many sheets in how many cases go stale, not only the
open one. Changing
`co_stock_min_days_before_export` moves the CO-stock eligibility predicate; keep
that one out of the in-case modal or gate it behind the same confirm as a
snapshot re-derivation.

**I. "Làm mới tồn CO" from inside the origin step.**
*Today:* origin shows thiếu tồn → sidebar Tồn CO (1) → Refresh từ Data Hub (2) →
sidebar Hồ sơ C/O (3) → case row (4) → step 3 (5) → Tính lại (6).
*Instead:* a button in the aggregate panel calling the existing
`POST /clients/{id}/co-stock/refresh` (already JSON), then `refreshCaseShellInPlace`.
*Code:* `app/routers/co_stock.py` refresh route (unchanged), `co_case.html`
aggregate toolbar, `refreshCaseShellInteractions`.
*Risk: medium.* The refresh re-derives the **client-wide** snapshot, not this
case's; other open cases read the same rows, and locked sheets hold
`co_stock_claims` against lot lines a re-derivation can renumber. Needs a confirm
that names how many cases are affected, and it must refuse while any sheet of this
case is mid-Tính. This is why the control is on a separate screen today; moving it
is a convenience change that must not become an implicit one.

**J. Split the case JS bundle so a step ships only its own handlers.**
*Today:* 274,908 bytes of inline JS on all five steps and the case list; 93.8 % of
the review response.
*Instead:* extract the origin-only blocks (grid editing, substitute modal, ĐVT
modal, rác panel, undo/redo, autosave) into `app/static/js/origin.js`.
*Code:* `app/templates/co_case.html` (extract), `base.html` (`asset_url`).
*Risk: medium.* A `<script src>` injected by a shell swap does not execute under
`importNode` either, so the file must be loaded once from `base.html` `<head>`;
conditional loading per step then breaks in-app nav into step 3. Load it
unconditionally on case routes, or load it always and accept one cached request.
Check first which of those handlers the case list actually needs — the substitute
and ĐVT modals render there too, which suggests at least one binding does.

**K. Land case links on the step the operator left.**
*Today:* every case link targets `…/co-case/{case_id}` = step 1.
*Instead:* target the case's current step — `origin` whenever the case has
products and is not closed, `review` when it is closed.
*Code:* `app/templates/workspace.html`, `app/templates/co_case.html` case rows,
`app/templates/clients.html`; the target step is derivable from the same
`co_case_step_status` data the rows already render.
*Risk: low-medium.* Step 3 is the expensive render (problem 1) and the first open
of a new case pays the source-context build — `.ai/STATUS.md` records ~15 s
residual first-open on prod johnson-vn after the 2026-07-27 fix (124.88 s → 0.31 s
for the shipment path). Landing on step 3 by default moves that cost to the case
list click. Do this **after** G, not before.

**L. Fold `workbook-tool` into `/co-stock` as a modal (§4.4).**
*Risk: low-medium.* It owns two POST routes and a file upload; a modal keeps both.
Keep the route as a permalink so existing links and any operator bookmark survive.

---

## 6. What I would not change

These are correctness surfaces. Each one looks like friction an IA pass would
remove, and each one is doing work.

1. **Chốt is per sheet, explicit, and separate from Tính.** Lock writes
   `co_stock_claims` into the ledger; reopen soft-releases them (`status='released'`,
   overlay drops) and an overclaim returns 409. Do not merge Tính and Chốt, do not
   make "Chốt tất cả" the primary action, and do not auto-lock on a green LVC.

2. **The missing-đơn-giá lock gate stays hard.** `co_case.py:2591` and
   `co_case_context.py:1568/1884` refuse the lock while a non-origin material has no
   unit price, because LVC is only *tạm tính* without it. Three belts exist
   (`0e7128a`, `b89e187`); they are load-bearing, not redundant.

3. **The `declarable_unmatched` gate stays hard.** A code that appears in no import
   declaration must be substituted or deleted before lock
   (`co_case_context.py:1854`). The aggregate warns rather than inviting Chốt while
   any remain — that is the fix from 2026-08-17 (D3), and an "onboarding-friendly"
   ✓ state would undo it. `excluded_non_material` deliberately does **not** block.

4. **Sequential allocation in `origin_product_order`, and the staleness that
   follows from it.** Sheet order decides which sheet consumes a lot first;
   `origin_codes_to_recalculate` marks every sheet from `min(edited index)` onward.
   Do not let a sheet be calculated out of order, do not recalculate only the edited
   sheet, and do not hide the order from the operator (§4.3 makes it *more* visible,
   not less).

5. **Locked sheets are skipped by every recalculation path.**
   `RECALCULABLE_SHEET_STATUSES` excludes `locked` and `draft` on a config save;
   `calculate_all_route` restores locked products after
   `allocate_whole_case_preview` rebuilds them. A locked sheet is a filed artifact
   whose claims are already in the ledger — rewriting it while the ledger still
   holds the old allocation lines is the 2026-08-19 defect, not a feature.

6. **The split between number-changing and display-only settings.**
   `NUMBER_AFFECTING_OVERRIDES` (form / criteria / both thresholds / optimization)
   recalculate on save because `lvc_status` and `tariff_shift_status_label` are
   stamped at Tính, not derived at render. `currency_mode` and `display_decimals`
   do not, because they only pick which of two lanes already on every lot gets
   printed. Do not make every knob recalculate, and do not make a number-changing
   one display-only.

7. **`co_config_fingerprint` on the case.** A config change must never retroactively
   alter a case that is already filed. Any in-case config affordance (§5 H) inherits
   this: it may change what the *next* Tính computes, never what a locked sheet says.

8. **Export is a pure renderer of the web grid.** All logic runs at Tính;
   `bang_ke_xml_generator` takes `number_format` from the HQ template and writes the
   raw value. Never add an "apply X on export" step, and never let the screen's
   `display_decimals` reach the filed file.

9. **The decimals truncation guard.** A non-zero value never prints as "0", found by
   truncation and not rounding, because "0" is exactly how this app says *thiếu đơn
   giá* and johnson-vn really declares đơn giá `0.078` VND.

10. **Data Hub stays read-only from CO.** The `bcct` config section is DH-owned and
    rendered read-only; CO owns `allocation_code` and `co_stock`
    (DECISIONS 2026-07-16). No CO screen gets an "edit BCCT" or "add ĐVT factor to
    Data Hub" affordance — the ĐVT gap is an approved-contract question
    (`.ai/api-requests/2026-08-19-client-uom-factors-read.md`), not a UI gap.

11. **Step 2's 3-required-document counter and the "Đóng hồ sơ trước" gate on the
    `.zip` export** (`co_case.py:1736`). The dossier is what gets filed; a partial
    export that looks complete is worse than a blocked button.

12. **The per-pair ĐVT confirmation.** Until the Data Hub endpoint is approved, a
    cross-quantity pair (EA→CAY) is confirmed once by a human and blocks Chốt until
    it is. Defaulting a factor to 1 would silently change every quantity on the
    sheet.
