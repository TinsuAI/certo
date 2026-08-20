# Vietnamese On-Screen Copy Audit — CO + Data Hub

| | |
|---|---|
| Scanned | 2026-08-20T00:29+08:00 |
| CO | `/home/vp/workspace/client/barry-CO-redesign` · branch `redesign/2026-08-ui` · HEAD `d876fd9` |
| Data Hub | `/home/vp/workspace/client/data-hub-redesign` · branch `redesign/2026-08-ui` · HEAD `ac98289` |
| CO surface | `app/templates/*.html` — 28 files, 11,061 lines (`co_case.html` = 7,561) |
| DH surface | `app/templates/**/*.html` — 60+ files, 10,250 lines, plus `app/i18n.py` (589 `vi` keys, lines 10–640) |
| Excluded | `design_gallery.html` + `design_gallery.py` in both repos — untracked dev component galleries created during this redesign, sample content only, actively being edited |
| Reference | CO `.ai/GLOSSARY.md` (179 lines) — authority for `tồn CO`, `xuất xứ`, `allocation_code`, BOM precedence |

**`i18n.py` line numbers are relative to the `vi` dict window (file lines 10-640) and the file was edited concurrently — the i18n key name is the anchor for every `i18n.py` row, not the number.** The only absolute `i18n.py` range measured is `flow.*` at 1299-1318.

**Template line numbers are a snapshot and already drifted during this audit.** Ten agents are editing both worktrees concurrently; `co_case.html` shifted by 4-7 lines between the first and last scan pass. Line numbers below were re-anchored at 2026-08-20T00:35+08:00. **The quoted string is the stable anchor — grep for it, do not trust the number.**

**Method.** Every string in this document was extracted mechanically: HTML text nodes outside `<script>`/`<style>`, rendering attributes (`title`, `placeholder`, `aria-label`, `alt`, `data-tip`), and JS/Jinja string literals containing Vietnamese diacritics. Counts labelled "visible" come from that extraction (deduplicated by file+line). Counts labelled "raw" are unfiltered `grep` matches and include identifiers, URLs and CSS class names.

---

## 0. Headline findings

1. **The two apps name the same entity differently.** CO says **Công ty** (49 visible strings, 11 files). DH says **Khách hàng** (43 `i18n.py` keys + 9 hardcoded template strings). Same `client_id`, same operator, same dossier.
2. **CO says `Upload`, DH says `Tải lên`, and CO also says `Nạp`.** Three labels, one action, 18 + 22 + 11 visible places.
3. **`chốt` means two different operations across the apps.** In CO it is a verb — lock a bảng kê and draw stock down the ledger. In DH `Chốt tồn kho` is a noun phrase — a period-end settlement snapshot. Nothing on screen distinguishes them.
4. **Settings has 8 different names** across the two apps: `Cài đặt`, `Cài đặt hệ thống`, `Cài đặt kỹ thuật`, `Cấu hình`, `Thiết lập`, `Settings`, `Technical Settings`, `Runtime Settings`.
5. **DH's locale file covers only ~30% of its own Vietnamese.** 589 `vi` keys vs **1,393 hardcoded Vietnamese text nodes across 60 templates**. The `t()` helper is not the single source of copy; half the fixes below are template edits, not locale edits.
6. **Unaccented Vietnamese: zero instances.** Checked by diacritic-regex over all extracted visible strings in both apps. This is not a problem area.
7. **17 CO error messages are bare `Lỗi ${x}: ${err}` with no action.** No cause, no next step, raw HTTP status or exception text shown to an operator.

---

## 1. Term table

Canonical column = the one term to standardise on across both apps. `→` marks the app that must change.

### 1.1 công ty / khách hàng / doanh nghiệp

| | |
|---|---|
| **Canonical** | **Khách hàng** |
| CO variants | `Công ty` — `_client_nav.html:4,35,53`, `base.html:182,192,266,267,273,295,296,302`, `clients.html:2,13,14,20,28`, `client_config.html:2,10,11,144,162`, `bom.html:74,113,398`, `catalog.html:88`, `settings.html:8,31`, `error.html:10`, `_picker_cases.html:18`, `_picker_clients.html:15`, `co_case.html:441,804,898,902,2295,2325` (49 visible strings, 11 files) |
| CO variant 2 | `khách` — `co_case.html:6822` "Bật … ở **Cấu hình khách**" (the page it points to is titled `Cấu hình công ty`) |
| CO variant 3 | `client` in prose — `co_stock.html:44` "Chưa có snapshot tồn CO cho **client** này", `co_stock.html:200`, `co_stock_workbook_tool.html:22`, `client_config.html:78` |
| DH variants | `Khách hàng` — `i18n.py` 43 keys (`nav.clients`, `clients.title`, `clients.field.name`, `nav.switch_client`, …) + `admin/settings_embedding.html:38,146,151,166`, `admin/uom.html:30`, `clients/catalog_detail.html:313`, `jobs/list.html:79` |
| DH variant 2 | `client` in prose — `admin/client_material_group_map.html:60`, `admin/settings_technical.html`, `clients/uom_factors.html`, `clients/bom_upload_error.html` (≈20 hardcoded strings) |
| Not a variant | `client_config.html:27` `placeholder="CÔNG TY TNHH ..."` — a legal-name example, correct as written |
| **Why khách hàng** | DH's 43 uses sit in one dict; changing CO's 49 hardcoded strings across 11 files is the cheaper direction only if DH also drops its `client` prose. Choose `Khách hàng` because the agency's own vocabulary for who they work for is "khách", and because `Công ty` is ambiguous in a C/O context where the exporter, the supplier and the agency are all công ty. **Migration cost: 49 CO string edits in 11 files.** Do not revisit. |
| Drop entirely | `doanh nghiệp` — 1 use each (`CO:cost_allocation.html:21` "Mặc định cả doanh nghiệp (Mode B)", `DH:admin/client_type_presets.html:32` "Doanh nghiệp loại X"). Third synonym, no distinct meaning. |

### 1.2 hồ sơ / vụ việc / case / dossier

| | |
|---|---|
| **Canonical** | **Hồ sơ C/O** (short form `hồ sơ`) |
| Dominant | `hồ sơ` — 141 visible strings, 12 CO files. Already the de-facto standard. |
| Leak 1 | `case C/O` — `bom.html:414` "Chưa có sản phẩm trong **case C/O**.", `co_case.html:1094`, `co_case.html:2073` |
| Leak 2 | `C/O case` — `bcct.html:90` "Các dòng này chưa được dùng cho **C/O case** cho tới khi review." |
| Leak 3 | `dossier` in prose — `workspace.html:29` "…đánh giá xuất xứ và xuất **dossier**.", `workspace.html:49` "…xuất bộ **dossier** nộp.", `_dossier_export_status.html` (heading text) |
| `vụ việc` | 1 occurrence, and it is a false positive: `workspace.html:16` "phục **vụ việc** làm C/O" is a word-boundary artefact. Not in use. Do not introduce it. |
| Carve-out | URL segments (`/co-case/`), `data-*` attributes (`data-co-case-shell`, `data-delete-case-form`), Python/JS identifiers (`case_id`, `persisted_case_id`) legitimately stay English. This row is about on-screen prose only. |

### 1.3 bảng kê

| | |
|---|---|
| **Canonical** | **bảng kê** — already consistent, keep as is |
| CO | 126 visible strings across `co_case.html`, `client_config.html`, `suppliers.html`, `_dossier_export_status.html`. No competing synonym found. |
| DH | 6 references, all describing CO's artefact (`clients/bom_artifact_detail.html:236,241,251`, `clients/catalog.html:314`, `admin/client_material_group_map.html:22`) |
| Note | The formal name is *Bảng kê khai báo xuất xứ*. On screen the short form is correct and unambiguous. One export button says `Xuất bảng kê HQ` (`co_case.html:939,7257`) — "HQ" here means hải quan and is fine. |

### 1.4 tờ khai

| | |
|---|---|
| **Canonical** | **tờ khai** — already consistent, keep as is |
| CO | 70 visible strings, 7 files. Sub-forms `TKN` / `TKX` used as identifiers (`co_case.html:688,758,772,793,2213`) — keep. |
| DH | 41 visible strings, 14 files + 9 `i18n.py` keys (`tabs.declarations` = `Tờ khai`) |
| Only defect | `clients/declarations.html:135` "Tờ khai sinh ra từ BCCT — **ingest** BCCT trước" (see §4) |

### 1.5 nguyên vật liệu / NVL / vật tư

| | |
|---|---|
| **Canonical** | **NVL** as the short label and column header; **nguyên vật liệu** on first use in a page description. Retire **vật tư**. |
| CO | `NVL` — 107 visible strings, dominant everywhere (`co_case.html` 80, `catalog.html` 9, `client_config.html` 4, `bom.html` 2) |
| CO variant | `vật tư` only inside the fixed phrase `phi vật tư` — `co_case.html:1839,2053,2294,6751,6752,6797,6815,6816,7364` (10 strings). Reads as a different concept from `NVL` even though it is its negation. |
| DH | `vật tư` — 55 visible strings, 7 files, including the nav item `navgrp.catalog.item` = **`Danh mục vật tư`** (`i18n.py:129`) and the whole `clients/catalog.html` page (18 strings) |
| DH variant | `NVL` — 12 visible strings, used as a *category code* (`catalog.cat_nvl` = `NVL`, alongside `BTP SX`, `BTP NM`, `TP`, `CCDC`). Different job from CO's `NVL`. |
| Collision | CO's `Danh mục mã hàng` (`_client_nav.html:1,43`) and DH's `Danh mục vật tư` are the **same page reached from two apps**. Fix: both say `Danh mục NVL`. |
| Action | Rename `phi vật tư` → **`không phải NVL`** (9 CO strings), rename `Danh mục vật tư` → `Danh mục NVL` (DH `i18n.py:129`), keep `catalog.cat_nvl` as a category code. |

### 1.6 định mức

| | |
|---|---|
| **Canonical** | **Định mức** for the per-unit quantity; **BOM** for the structure |
| CO | Column header `Định mức` (`co_case.html:1694,1721,1857`), tooltip `định mức` (`co_case.html:1874,2683`), `workspace.html:75` "Định mức nguyên liệu theo thành phẩm" |
| CO variant | `ĐM` — `co_case.html:1395` "đổi **ĐM**", `co_case.html:4573` "Chọn thay (**ĐM** auto)". Unexplained abbreviation next to the spelled-out header. |
| DH | `navgrp.bom.list` = **`Định mức (BOM)`** (`i18n.py:134`), plus 8 keys and `clients/bom_preview.html:44,46,69` |
| Conflict | DH puts `Định mức` and `BOM` in one nav label; CO uses `BOM` alone in nav (`_client_nav.html:44`) and `Định mức` only as a column. |
| Action | Nav in both apps: **`BOM (định mức)`**. Column header stays `Định mức`. Expand `ĐM` → `định mức` in the 2 CO strings. |

### 1.7 tồn kho / tồn / tồn CO — **two different objects, do not unify**

| | |
|---|---|
| **Canonical A** | **Tồn CO** — CO's import-lot inventory for trừ-lùi. Defined in `.ai/GLOSSARY.md`: "inventory for C/O purposes, NOT C/O documents on hand"; one row per import-declaration line with `Đã xuất`/`Tồn`. |
| CO usage | 45 visible strings, 10 files (`co_stock.html` 15, `co_stock_workbook_tool.html` 10, `co_case.html` 7, `bcct.html` 4) |
| CO inconsistency | `Tồn CO` vs `Tồn C/O` — both spellings live in the same app: `Tồn CO` (`_client_nav.html:45`, `co_stock.html:2,11`, `portfolio.html:30,48`) vs `Tồn C/O` (`client_config.html:61`, `co_case.html` tooltips, `co_stock.html:78`). Pick **`Tồn CO`** (no slash) — the slash form reads as a second concept. |
| **Canonical B** | **Chốt tồn kho** — DH's period-end settlement snapshot (`inventory_snapshots`). A different table, a different lifecycle, a different operator task. |
| DH usage | 13 visible strings, 5 files (`clients/inventory_snapshot*.html`, `admin/settlement_adapters.html`, `i18n.py:141`) |
| Required change | DH `Chốt tồn kho` is a **verb collision** with CO's `Chốt` (see 1.8). Rename DH's to **`Tồn kho quyết toán`** — it already lives under `navgrp.settlement` = `Quyết toán`, so the label matches its own section and stops colliding. |
| Also DH | `Nhập-Xuất-Tồn` (`i18n.py:132`) — a third, distinct concept (NXT settlement report). Correct as written, leave alone. |

### 1.8 chốt / khoá / duyệt

| | |
|---|---|
| **Canonical** | **Chốt** = lock a bảng kê + draw stock down the ledger (irreversible without an explicit reopen). **Đóng hồ sơ** = close the whole dossier. **Duyệt** = a second person approves someone else's submission. |
| CO `chốt` | 76 visible strings, 4 files. Buttons: `Chốt` (`co_case.html:1357`), `Chốt tất cả` (`:937`), `Mở chốt` (`:1345`), `Chốt & sang bảng kê sau` (`:7283`) |
| CO variant `khoá` | Used interchangeably with `chốt` in prose describing the same operation: `co_case.html:2177` "Cần **khoá** toàn bộ bảng kê để tính đủ TKX/TKN" — the button that does it says `Chốt tất cả`. Also `co_case.html:930` "không **khoá**/không trừ sổ". |
| CO variant `nhả chốt` | `co_case.html:1832,2064` "Sheet đã chốt — **nhả chốt** để sửa NVL" — the button says `Mở chốt`. Two verbs for one undo. |
| CO variant `Đóng hồ sơ` | `co_case.html:2170,2165`, `_dossier_export_status.html:56,72` — a *different* operation (case-level), correctly named, but sits next to `Chốt` with no visual or verbal hierarchy explaining that one contains the other. |
| CO `duyệt` | 3 strings, none of them an approval action (`co_case.html:919` "xem lại", `sso_logout.html:14` "trình duyệt") |
| DH `duyệt` | 24 visible strings + 21 `i18n.py` keys — the real approval workflow (`proposals.review.approve_btn` = `Duyệt`, `status_pending` = `chờ duyệt`, `clients/catalog_candidates.html` 16 strings) |
| DH `chốt` | 17 strings, all inside `Chốt tồn kho` (see 1.7) |
| Action | Replace `khoá`/`nhả chốt` in CO prose with `chốt`/`mở chốt` (11 strings). Keep `duyệt` exclusively for DH's two-person approval. Rename DH `Chốt tồn kho` per 1.7. |

### 1.9 đề xuất

| | |
|---|---|
| **Canonical** | **Đề xuất BOM** |
| DH | `tabs.proposals` = `Đề xuất` (`i18n.py:124`), page title `proposals.title` = **`Yêu cầu duyệt BOM`** (`:457`), body text `proposals.review.body` = "**Đề xuất** này đang chờ…" (`:478`). Tab, title and body use three different nouns for one object. |
| DH leak | `proposals.review.withdraw_confirm` = "Rút lại **proposal** này? Người gửi sẽ phải **submit** lại…" (`:484`), `proposals.review.no_permission` = "…quyền duyệt **proposal** cho khách hàng này" (`:485`) |
| CO | The sending side. Button says **`Lưu BOM mới`**, tooltip says **`Lưu BOM artifact mới về Data Hub`**, helper text says `Bấm "Lưu BOM artifact mới" để gửi **đề xuất** sang Data Hub`, post-send state says **`Đã propose ✓`** — all at `co_case.html:1352–1403`. Four names, one action, one screen. The helper text quotes a button label that does not exist. |
| Action | CO button `Gửi đề xuất BOM`, state `Đã gửi đề xuất`. DH tab/title/body all `Đề xuất BOM`. Replace `proposal`/`submit` in the two DH strings. |

### 1.10 tải lên / nhập / ghi nhận / nạp

| | |
|---|---|
| **Canonical** | **Tải lên** (send a file from the operator's machine). **Nạp** stays for the distinct act of loading an already-uploaded file's contents into a live store. |
| CO | `Upload` — English, 18 visible places, 8 files: `bcct.html:56,64,69`, `bom.html:33,139,163,324,348`, `catalog.html:20,44,65,82`, `catalog_table.html:19`, `co_case.html:625`, `co_stock.html:78`, `co_stock_workbook_tool.html:22`, `cost_allocation.html:68,119` |
| CO variant | `Nạp` — 11 visible places, `co_stock.html:53,55,61,63,66,73`, `co_stock_workbook_tool.html:10,20,23,53`, `co_case.html:1337`. Genuinely a different step (workbook → snapshot → tồn CO), but the operator sees `Upload & nạp snapshot` (`co_stock.html:78`) with no explanation of the difference. |
| DH | `Tải lên` — 15 `i18n.py` keys + 22 template strings, 8 files. `tabs.uploads` = `Tải lên`. |
| DH variant | `upload` in prose — `clients/uploads.html` (27), `clients/upload_detail.html` (27), `uploads.delete_confirm` = "Xoá **upload** lỗi này?" (`i18n.py:501`), `staleness.last_upload` = "Lần **upload** gần nhất" (`:592`) |
| `ghi nhận` | 2 DH strings (`i18n.py:190,436`), 1 CO string (`co_case.html:964`). Not a file operation — leave alone, but do not spread it. |
| `nhập` | Ambiguous by construction: `nhập khẩu` (import), `nhập tay` (type by hand), `nhập liệu` (data entry). Never use bare `nhập` for uploading. Currently correct in both apps. |
| Action | CO: 18 `Upload` → `Tải lên`. DH: 4 `upload` → `tải lên` in prose. Keep `Nạp` but always qualify it: `Nạp vào tồn CO`. |

### 1.11 Cross-app terms not on the mandated list but with the same defect

| Concept | CO | DH | Canonical |
|---|---|---|---|
| Settings | `Cài đặt` (`base.html:210,235,275`), `Cài đặt hệ thống` (`settings.html:8`, `data_hub_settings.html:12`), `Cài đặt kỹ thuật` (`base.html:212,237`), `Cấu hình` (`bcct.html:79`, `co_stock.html:28`), `Settings` (`co_form_settings.html:11`, `user.html:9`), `Technical Settings` (`data_hub_settings.html:6`), `Runtime Settings` (`:57`) | `Thiết lập` (`nav.settings`), `Cấu hình` (`tabs.config`), `Cài đặt kỹ thuật` (`navgrp.admin.settings_technical`) | **`Cài đặt`** for app-wide, **`Cấu hình`** for per-khách-hàng. Two words, one rule. Retire `Thiết lập`, `Settings`, `Technical Settings`, `Runtime Settings`. |
| Workspace | `Workspace` (`workspace.html:17,49`), `Khu làm việc công ty` (`_client_nav.html:35`) | `Không gian làm việc` (`nav.group.workspace`), `Chọn khách hàng để vào không gian làm việc` (`clients.tagline`) | **`Không gian làm việc`** |
| Catalog | `Danh mục mã hàng` (`_client_nav.html:1,43`), `Catalog` (`catalog.html:88`), `DS NVL` / `DS SP` (`catalog.html:71,72,91,92`) | `Danh mục` (`tabs.catalog`), `Danh mục vật tư` (`navgrp.catalog.item`) | **`Danh mục NVL`** / **`Danh mục TP`** |
| Refresh | `Refresh` (`co_stock.html:27`, `customs_exchange_rates.html:33`, `co_case.html:2306`, `bcct.html`) | `Cập nhật` (`bom.action.refresh`) **and** `Refresh ngay` (`bom.stale.refresh`) | **`Cập nhật`** |
| Hệ số | `Hệ số phân bổ` = cost allocation (`cost_allocation.html:2,10`), `Hệ số quy đổi đơn vị tính` = UoM (`co_case.html:2300`) | `Hệ số quy đổi` = UoM (`navgrp.bom.uom`) | Keep both, but CO must never shorten either to bare `Hệ số` (currently does at `co_case.html:6512` `Cấu hình hệ số`, `:1592` `Áp hệ số`) |

---

## 2. Buttons that name the mechanism instead of the result

A button label should say what the operator ends up with. These say what the code does.

### CO

| Current | File:line | Proposed | What the operator actually gets |
|---|---|---|---|
| `Load BOM` | `co_case.html:1341` | `Nạp công thức NVL` | Fills the bảng kê with the BOM's material rows. The tooltip already says this in Vietnamese; the button is English and names the fetch. |
| `Lưu BOM mới` | `co_case.html:1353` | `Gửi đề xuất BOM` | Nothing is saved locally — it sends a proposal to Data Hub for approval. "Lưu" tells the operator the opposite of what happens. |
| `Đã propose ✓` | `co_case.html:1353` | `Đã gửi đề xuất` | State label, mixed-language. |
| `Tính bảng kê` | `co_case.html:1343` | `Tính bảng kê` — keep | Correct: names the artefact produced. |
| `Chốt` | `co_case.html:1357` | `Chốt & trừ tồn` | The irreversible half (drawing stock down the ledger) is invisible in the current label. |
| `Mở chốt` | `co_case.html:1345` | `Mở chốt & nhả tồn` | Symmetry with the above; the operator needs to know their stock comes back. |
| `Refresh từ Data Hub` | `co_stock.html:27` | `Cập nhật tồn từ Data Hub` | Names the direction of the call, not the resulting number. |
| `Upload & nạp snapshot` | `co_stock.html:78` | `Tải file lên và cập nhật tồn CO` | Two internal steps exposed; the operator cares about one outcome. |
| `Convert + xem trước` | `co_stock_workbook_tool.html:37` | `Đọc workbook và xem trước` | `Convert` is the code's word for parsing an Excel file. |
| `Nạp snapshot vào tồn CO` | `co_stock_workbook_tool.html:53` | `Ghi vào tồn CO` | `snapshot` is an implementation noun. |
| `Áp hệ số CP (tất cả SP)` | `co_case.html:910` | `Điền chi phí cho tất cả SP` | `Áp hệ số` describes the multiplication; the result is filled cost-buildup fields. |
| `Áp lại & ghi đè` | `co_case.html:6514` | `Điền lại, ghi đè số cũ` | |
| `Reset seed mặc định` | `co_form_settings.html:80` | `Khôi phục danh sách form gốc` | `seed` is a database word. |
| `Test connection` | `data_hub_settings.html:113` | `Kiểm tra kết nối` | English + names the probe, not the answer. |
| `Reset` | `co_case.html:1512` | `Về khuyến nghị mặc định` | The tooltip at `:1512` already explains this; the button does not. |
| `Xử lý tuần tự` | `co_case.html:918` | `Làm lần lượt từng bảng kê` | Names the loop strategy. |
| `Tính tồn tất cả (SP)` | `co_case.html:926,1104,7081` | `Tính tồn cho tất cả sản phẩm` | `(SP)` is a parenthetical abbreviation where a word fits. |
| `Dùng khuyến nghị` | `co_case.html:963,1028` | `Dùng tiêu chí hệ thống đề xuất` | Ambiguous: recommendation of what? |
| `Bỏ chọn` | `co_case.html:971,1032,1708,6712,6818` | `Bỏ chọn` — keep, but 5 buttons with one label do 3 different things | Disambiguate: `Bỏ chọn tiêu chí` / `Bỏ chọn dòng` / `Bỏ chọn tất cả` |
| `Tra` | `co_case.html:150` | `Tra cứu` | Truncated verb. |
| `Logout` / `Settings` / `Login with Data Hub` | `user.html:50,9,61` | `Đăng xuất` / `Cài đặt` / `Đăng nhập bằng Data Hub` | Fully English page in an otherwise Vietnamese app. |
| `Tiếp tục logout` | `sso_logout.html:18` | `Tiếp tục đăng xuất` | |
| `Mở CO` | `portfolio.html:13,59`, `data_hub_settings.html:13`, `co_form_settings.html:12` | `Về Barry CO` | "Mở CO" reads as "open a certificate of origin". |

### Data Hub

| Current | File:line | Proposed | Why |
|---|---|---|---|
| `Materialize {n} bản lưu` | `i18n.py:358` | `Tạo {n} phiên bản BOM` | `materialize` is the ORM's word. |
| `Reject` | `i18n.py:359` | `Từ chối` | English, next to a Vietnamese `Xác nhận`. |
| `Reject pending? Tất cả decisions sẽ bị xóa.` | `i18n.py:360` | `Từ chối file này? Toàn bộ lựa chọn đã tick sẽ mất.` | |
| `Refresh ngay` | `i18n.py:384` | `Cập nhật ngay` | DH's own `bom.action.refresh` already says `Cập nhật`. |
| `Tải lên & xử lý` | `i18n.py:43` | `Tải lên và đọc file` | `xử lý` says nothing. |
| `Lưu mapping & chạy parse` | `clients/_upload_mapping.html` | `Lưu cách gán cột và đọc lại file` | Two English implementation nouns in one button. |
| `+ extract material_identity candidates` | `clients/parser_rules.html:11` | `+ Tách mã NVL từ tên hàng` | Fully English, names an internal function. |
| `Chạy lại backfill cho client này` | `admin/settings_embedding.html` | `Tính lại vector tìm kiếm cho khách hàng này` | `backfill` is a migration word. |
| `Xem trước Refresh` / `Xác nhận Refresh` | `clients/bom_refresh_preview.html` | `Xem trước thay đổi` / `Cập nhật BOM` | |

---

## 3. Error and empty-state messages with no next action

Every message below states a failure or an absence and stops. Each proposal supplies a cause and one action.

### 3.1 CO — generic error handlers (one fix covers many surfaces)

| Current | File:line | Proposed |
|---|---|---|
| `Lỗi máy chủ (HTTP ${status}).` | `base.html:127` | `Máy chủ không xử lý được yêu cầu (mã ${status}). Thử lại; nếu vẫn lỗi, chụp màn hình và báo kỹ thuật.` |
| `Lỗi máy chủ (HTTP 401).` | `base.html:139` | `Phiên đăng nhập đã hết hạn. Đăng nhập lại ở tab mới rồi quay lại — thao tác đang làm vẫn được giữ.` |
| `Lỗi ${r.status}` | `co_case.html:286,4000`, `co_stock.html:422` | `Không tải được dữ liệu (mã ${r.status}). Tải lại trang rồi thử lại.` |
| `Lỗi mạng: ${err}` | `co_case.html:289` | `Mất kết nối tới máy chủ. Kiểm tra mạng rồi bấm lại — chưa có gì được ghi.` |
| `Lỗi chốt: ${err}` | `co_case.html:7158` | `Không chốt được bảng kê: ${err}. Tồn chưa bị trừ. Mở bảng kê để kiểm tra rồi chốt lại.` |
| `Lỗi thay NVL: ${err}` | `co_case.html:6641` | `Không thay được NVL: ${err}. Bảng kê giữ nguyên. Chọn mã khác hoặc tải lại trang.` |
| `Lỗi xoá NVL: ${err}` | `co_case.html:6741` | `Không xoá được dòng: ${err}. Bảng kê giữ nguyên. Tải lại trang rồi thử lại.` |
| `Lỗi tính tồn: ${err}` | `co_case.html:7045` | `Không tính được tồn: ${err}. Kiểm tra BOM và tồn CO của khách hàng rồi tính lại.` |
| `Lỗi áp hệ số: ${err}` | `co_case.html:6535` | `Không điền được chi phí: ${err}. Kiểm tra hệ số phân bổ và FOB rồi thử lại.` |
| `Lỗi hoàn tác: ${err}` | `co_case.html:6579` | `Không hoàn tác được: ${err}. Tải lại bảng kê để xem trạng thái thực tế.` |
| `Lỗi tìm NVL: ${err}` | `co_case.html:5076` | `Không tìm được NVL: ${err}. Thử lại hoặc nhập mã NVL trực tiếp.` |
| `Lỗi tải khuyến nghị: ${err}` | `co_case.html:5014` | `Không tải được khuyến nghị từ Data Hub: ${err}. Chọn mã thay thế thủ công ở tab Tìm kiếm.` |
| `Lỗi gọi resolve: ${err}` | `co_case.html:6471` | `Không tra được mã BOM: ${err}. Kiểm tra BOM của sản phẩm này trên Data Hub.` |
| `Lỗi mạng khi lưu cấu hình.` | `co_case.html:4023` | `Không lưu được cấu hình — mất kết nối. Cấu hình cũ vẫn giữ. Bấm Lưu lại.` |
| `Lỗi mạng khi lưu tiêu chí.` | `co_case.html:6205` | `Không lưu được tiêu chí — mất kết nối. Chọn lại và bấm Lưu.` |
| `Lỗi mạng khi reset.` | `co_case.html:4078` | `Không khôi phục được mặc định — mất kết nối. Thử lại.` |
| `Không lưu được override.` | `co_case.html` (settings modal) | `Không lưu được lựa chọn riêng cho bảng kê này. Tải lại trang rồi chọn lại.` |
| `Không reset được.` | `co_case.html` (settings modal) | `Không khôi phục được khuyến nghị mặc định. Tải lại trang rồi thử lại.` |
| `Lưu thất bại (HTTP ${status}).` | `co_case.html:5953` | `Không lưu được bảng kê (mã ${status}). Chỉnh sửa của bạn vẫn còn trên màn hình — bấm Lưu lại.` |
| `Refresh thất bại: ${errors}` | `co_stock.html:185` | `Không cập nhật được tồn từ Data Hub: ${errors}. Tồn hiện tại giữ nguyên. Kiểm tra BCCT trên Data Hub rồi thử lại.` |
| `Nạp lỗi: ${detail}` | `co_stock_workbook_tool.html:137` | `Không ghi được vào tồn CO: ${detail}. Tồn hiện tại chưa đổi. Kiểm tra file rồi nạp lại.` |
| `Lỗi ${status}: ${detail \|\| "convert thất bại"}` | `co_stock_workbook_tool.html:99` | `Không đọc được workbook (mã ${status}): ${detail}. Kiểm tra đúng sheet trừ-lùi rồi chọn file lại.` |
| `${file.name} — lỗi mạng` | `co_case.html:7473` | `${file.name} — mất kết nối, chưa tải lên. Bấm chọn file lại.` |
| `${file.name} — ${error \|\| "Upload thất bại"}` | `co_case.html:7468` | `${file.name} — không tải lên được: ${error}. Kiểm tra định dạng (.pdf/.xlsx) và dung lượng rồi thử lại.` |
| `Thiếu URL xoá — tải lại trang.` | `co_case.html:6761` | Internal fault leaked to the operator. → `Không xoá được do lỗi giao diện. Tải lại trang rồi thử lại.` |
| `Thiếu client_id hoặc mã TP — không gọi được resolve.` | `co_case.html:6434` | Same. → `Thiếu thông tin sản phẩm. Tải lại trang; nếu vẫn lỗi, báo kỹ thuật.` |

### 3.2 CO — empty states

| Current | File:line | Proposed |
|---|---|---|
| `Chưa có snapshot` | `co_stock.html:22` | `Chưa có tồn CO. Bấm "Cập nhật tồn từ Data Hub" để lấy lần đầu (khách hàng lớn mất ~10 giây).` |
| `Chưa có snapshot tồn CO cho client này` | `co_stock.html:44` | Same as above, plus drop `client`. |
| `Chưa có snapshot tồn C/O.` | `client_config.html:61` | `Chưa có tồn CO. Vào tab Tồn CO và bấm "Cập nhật tồn từ Data Hub".` |
| `Chưa có artifact BOM.` | `bom.html:279` | `Chưa có BOM nào. Tải BOM lên Data Hub, hệ thống sẽ tự hiện ở đây.` |
| `Chưa có artifact TP.` | `bom.html:340` | `Chưa có thành phẩm nào có BOM. Tải BOM lên Data Hub trước.` |
| `Chưa có composition BOM.` | `bom.html:306` | `Chưa có BOM tổng hợp. Tải BOM lên Data Hub và publish để dùng được cho bảng kê.` |
| `Chưa có audit BOM.` | `bom.html:389` | `Chưa có thay đổi BOM nào được ghi lại.` |
| `Chưa có upload BOM.` | `bom.html:370` | `Chưa có lần tải BOM nào.` |
| `Chưa có bảng kê` | `co_case.html:408` | `Chưa có bảng kê. Nạp BOM cho từng sản phẩm rồi bấm "Tính bảng kê".` |
| `Chưa có dữ liệu sản phẩm/BOM để tạo bảng kê.` | `co_case.html:55` | `Chưa có BOM cho sản phẩm nào trong lô này. Tạo BOM trên Data Hub rồi quay lại.` |
| `Chưa có sản phẩm trong case C/O này.` | `co_case.html:1094,2073`, `bom.html:414` | `Chưa có sản phẩm trong hồ sơ này. Thêm tờ khai xuất hoặc invoice ở bước Lô hàng.` |
| `Chưa có TKN nào — sheet phải được "Chốt" để TKN xuất hiện ở đây.` | `co_case.html:793` | `Chưa có tờ khai nhập nào. Chốt từng bảng kê để hệ thống liệt kê tờ khai nhập cần đính kèm.` |
| `Chưa có TKX nào tham chiếu trong hồ sơ.` | `co_case.html:761` | `Chưa có tờ khai xuất nào. Nhập số tờ khai xuất hoặc số invoice ở bước Lô hàng.` |
| `Chưa có dòng BCCT xuất khẩu khớp tham chiếu hồ sơ.` | `co_case.html:834` | `Không có dòng BCCT xuất khẩu nào khớp số tờ khai/invoice của hồ sơ. Kiểm tra lại số ở bước Lô hàng, hoặc cập nhật BCCT trên Data Hub.` |
| `Chưa có dữ liệu NCC` | `suppliers.html:33` | `Chưa có nhà cung cấp nào. Danh sách lấy từ tồn CO — bấm "Cập nhật tồn" ở tab Tồn CO trước.` |
| `Chưa có database — không ghi được cờ NCC` | `suppliers.html:23` | Internal state leaked. → `Chưa bật lưu trữ — không đánh dấu được nhà cung cấp có Phụ lục X. Báo kỹ thuật.` |
| `Chưa có hệ số nào. Upload file Excel hoặc nhập tay qua API.` | `cost_allocation.html:119` | `Chưa có hệ số phân bổ. Tải mẫu Excel về, điền, rồi tải lên.` — the current text tells an operator to call an API. |
| `Chưa có hồ sơ lưu riêng cho công ty này.` | `co_case.html:441` | `Khách hàng này chưa có hồ sơ C/O nào. Bấm "+ Tạo hồ sơ".` |
| `Chưa có khuyến nghị từ Data Hub.` | `co_case.html:2273` | `Data Hub chưa có mã thay thế nào cho mã này. Dùng tab Tìm kiếm để chọn thủ công.` |
| `Không có dữ liệu phù hợp.` | `_advanced_table.html:83` | `Không có dòng nào khớp bộ lọc. Xoá lọc để xem tất cả.` |
| `Không tìm thấy kết quả phù hợp.` | `base.html:346` | `Không tìm thấy khách hàng nào khớp. Thử tìm bằng mã số thuế.` |
| `Chưa có lần cập nhật nào trong store hiện tại.` | `customs_exchange_rates.html:43` | `Chưa có tỷ giá nào. Bấm "Cập nhật tỷ giá".` — `store` is an implementation word. |

### 3.3 CO — blocking messages that name a rule but not the fix

| Current | File:line | Proposed |
|---|---|---|
| `Còn NVL không xuất xứ thiếu đơn giá — bổ sung đơn giá rồi tính lại.` | `co_case.html:7290` | Good structure, but does not say *which*. → `${n} dòng NVL không xuất xứ chưa có đơn giá. Mở bảng kê, điền cột Đơn giá cho các dòng được tô đỏ, rồi bấm "Tính bảng kê".` |
| `Chưa có BOM/NVL đầy đủ — nạp BOM rồi tính lại.` | `co_case.html:7291` | `Bảng kê chưa có công thức NVL. Bấm "Nạp công thức NVL" rồi bấm "Tính bảng kê".` |
| `Chưa có hệ số thì dòng vẫn trừ tồn 1:1 và bảng kê không chốt được.` | `co_case.html:2333` | `Thiếu hệ số quy đổi ĐVT: dòng này trừ tồn theo tỉ lệ 1:1 và không chốt được. Nhập hệ số ở ô bên cạnh rồi bấm Lưu.` |
| `{{ n }} bảng kê chưa chọn tiêu chí — không chốt được` | `co_case.html:965` | `${n} bảng kê chưa chọn tiêu chí xuất xứ nên không chốt được. Chọn tiêu chí ở thanh trên (áp cho cả lô) hoặc mở từng bảng kê.` |
| `Tổng chi phí ngoài NPL = X > FOB Y — không hợp lệ.` | `co_case.html:6406` | `Tổng chi phí ngoài NPL (X) lớn hơn FOB (Y). Giảm chi phí hoặc kiểm tra lại FOB ở ô bên trên.` |
| `Tổng tồn không đủ (thiếu X).` | `co_case.html:4856` | `Thiếu X ${đvt} trong tồn CO. Chọn mã thay thế, hoặc cập nhật tồn từ Data Hub nếu đã có tờ khai nhập mới.` |
| `Thiếu SL invoice — không tính được Δ` | `co_case.html:4468` | `Chưa nhập số lượng trên invoice nên không so được chênh lệch. Điền số lượng ở bước Lô hàng.` |
| `Hồ sơ đã đổi — tải lại trang rồi chốt lại.` | `co_case.html:7148` | `Hồ sơ đã bị sửa ở nơi khác. Tải lại trang để lấy bản mới rồi chốt lại — chưa có bảng kê nào bị chốt.` |
| `Hệ số quy đổi phải là số lớn hơn 0.` | `co_case.html:6297` | Correct as written. |

### 3.4 Data Hub

| Current | File:line | Proposed |
|---|---|---|
| `error.500.body` = `Hệ thống gặp sự cố khi xử lý yêu cầu. Vui lòng thử lại sau ít phút.` | `i18n.py:30` | Add the action that matters: `…Nếu lặp lại, gửi ảnh màn hình kèm giờ xảy ra cho kỹ thuật.` |
| `error.generic.body` = `Yêu cầu không thể hoàn tất.` | `i18n.py:32` | `Không hoàn tất được thao tác. Quay lại trang trước và thử lại; dữ liệu chưa bị thay đổi.` |
| `uploads.preview.error` = `Lỗi đọc file` | `i18n.py:519` | `Không đọc được file. Kiểm tra đúng định dạng .xlsx/.xls rồi tải lại.` |
| `Parser không đọc được file.` | `clients/bom_upload_error.html` | `Không đọc được cấu trúc file. Chọn đúng kiểu file ở ô "Kiểu file", hoặc tải mẫu chuẩn về đối chiếu.` |
| `proposals.empty` = `Chưa có yêu cầu nào. CO sẽ gửi qua API.` | `i18n.py:462` | `Chưa có đề xuất BOM nào. Đề xuất xuất hiện ở đây khi nhân viên bấm "Gửi đề xuất BOM" bên Barry CO.` |
| `bom.empty` = `Chưa có BOM nào cho khách hàng này.` | `i18n.py:444` | `Chưa có BOM nào. Vào tab Tải lên, chọn file BOM kỹ thuật.` |
| `catalog.empty` = `Chưa có dữ liệu danh mục.` | `i18n.py:210` | `Chưa có danh mục NVL. Tải file Excel danh mục lên (cột: Mã HQ, Mã NB, Tên, Loại, ĐVT, HS).` |
| `bcct.empty` = `Chưa có dữ liệu BCCT.` | `i18n.py:262` | `Chưa có BCCT. Tải file BCCT lên ở tab Tải lên.` |
| `bqd.empty` = `Chưa có mapping.` | `i18n.py:239` | `Chưa có mã quy đổi nào. Tải file hai cột (Mã nội bộ + Mã hải quan) lên.` |
| `Không có gì để refresh` | `clients/bom_refresh_preview.html:36` | `BOM đã là bản mới nhất — không có gì cần cập nhật.` |
| `Không có header` | `clients/_upload_mapping.html:72` | `File không có dòng tiêu đề. Chọn dòng tiêu đề ở ô bên trên, hoặc để trống nếu dữ liệu bắt đầu từ dòng 1.` |
| `Không có file hợp lệ để ingest.` | `clients/declaration_zip_preview.html:102` | `File .zip không có tờ khai nào đọc được. Kiểm tra bên trong có file .xls tờ khai không.` |
| `⚠ File đã bị reject. Không có BOM version nào được tạo.` | `clients/bom.html:53` | `File đã bị từ chối — chưa tạo phiên bản BOM nào. Xem lý do ở tab Tải lên rồi sửa file và tải lại.` |
| `⚠ File đã bị reject. Không có mã nào được lưu.` | `clients/bqd.html:24` | `File đã bị từ chối — chưa lưu mã nào. Xem lý do ở tab Tải lên rồi sửa file và tải lại.` |
| `Không có candidate nào đang chờ duyệt.` | `clients/catalog_candidates.html:190` | `Không có ứng viên nào chờ duyệt. Bấm "Làm mới" để quét lại danh mục.` |
| `Chưa có tờ khai nào. Tờ khai sinh ra từ BCCT — ingest BCCT trước,` | `clients/declarations.html:135` | `Chưa có tờ khai nào. Tờ khai được tạo từ BCCT — tải BCCT lên trước.` |
| `Không có dòng nào có qty > 0 — nếu file không phải định mức (chỉ là danh sách thành phần), hãy reject.` | `clients/bom_preview.html:46` | `Không dòng nào có số lượng > 0. Nếu file chỉ là danh sách thành phần chứ không phải định mức, bấm "Từ chối".` |
| `flatten.decisions.empty` = `Không có quyết định nào cần staff xác nhận. Tất cả {n} decision đều ở trạng thái auto — sẽ materialize ngay.` | `i18n.py:313` | `Không có mục nào cần xác nhận. Cả {n} mục đều tự động — bấm nút bên phải để tạo phiên bản BOM.` |
| `proposals.review.no_permission` = `Bạn không có quyền duyệt proposal cho khách hàng này. Liên hệ manager / admin.` | `i18n.py:485` | `Bạn không có quyền duyệt đề xuất cho khách hàng này. Nhờ quản lý hoặc quản trị viên duyệt.` |

---

## 4. Unaccented or mixed-language text on screen

### 4.1 Unaccented Vietnamese — none found

Checked by running a Vietnamese-diacritic regex over every extracted visible string in both apps (CO 3,869 strings; DH 7,320 strings), then filtering pure-ASCII strings against a list of 40 unaccented Vietnamese forms (`cong ty`, `ho so`, `bang ke`, `to khai`, `dinh muc`, `ton kho`, `chot`, `duyet`, `de xuat`, `tai len`, `xoa`, `luu`, `cap nhat`, `tim kiem`, `xuat xu`, `so luong`, `don gia`, `tri gia`, …). **Zero matches in either app, including `app/i18n.py`.** The five apparent hits were the English word "them" inside `{# #}` developer comments, which do not render.

### 4.2 Fully English screens and labels in CO

Identifiers are excluded per the carve-out: `status`, `E31`, `LVC`, `RVC`, `CTC`, `CTH`, `CTSH`, `HS`, `FOB`, `VNM`, `KXX`, `MST`, `STT`, `ĐVT`, `TKN`, `TKX`, `BCCT`, `BOM`, `NVL`, `TP`, `BTP`, `NCC`, config enum values (`same_as_customs_code`, `manual_review`, `requires_review`, `full_catalog`, `partial_update`, `line_level`, `append_or_review_by_transaction_key`, `aggregate_by_declaration_and_allocation_code`, `description_regex`), DB column names shown as such (`co_stock`, `customs_code`, `declaration_no`, `line_no`, `remaining_qty`), env var names (`BARRY_DATABASE_URL`, `DATA_HUB_SERVICE_TOKEN`), and `data-*` attributes.

| File:line | English on screen | Proposed |
|---|---|---|
| `user.html:6` | `User` | `Tài khoản` |
| `user.html:7` | `Data Hub session and CO access context` | `Phiên đăng nhập Data Hub và quyền truy cập Barry CO` |
| `user.html:9` | `Settings` | `Cài đặt` |
| `user.html:23` | `Session` | `Phiên đăng nhập` |
| `user.html:27` | `Logged in` | `Đã đăng nhập` |
| `user.html:29` | `Local / anonymous` | `Cục bộ / ẩn danh` |
| `user.html:40` | `Role` | `Vai trò` |
| `user.html:50` | `Logout` | `Đăng xuất` |
| `user.html:55` | `No Data Hub user` | `Chưa đăng nhập Data Hub` |
| `user.html:61` | `Login with Data Hub` | `Đăng nhập bằng Data Hub` |
| `sso_logout.html:6` | `Logout` | `Đăng xuất` |
| `sso_logout.html:18` | `Tiếp tục logout` | `Tiếp tục đăng xuất` |
| `sso_logout.html:14` | `CO đã xóa session local. Trình duyệt sẽ tiếp tục xóa session Data Hub.` | `Barry CO đã xoá phiên đăng nhập trên máy này. Trình duyệt sẽ xoá tiếp phiên Data Hub.` |
| `portfolio.html:6` | `Source Portfolio` | `Dữ liệu nguồn` |
| `portfolio.html:16` | `Company Evidence` | `Chứng từ khách hàng` |
| `portfolio.html:41` | `Contracts` | `Hợp đồng` |
| `portfolio.html:46` | `Clients` | `Khách hàng` |
| `portfolio.html:47` | `Source summary` | `Tổng quan dữ liệu nguồn` |
| `portfolio.html:47` | `Version/count metadata cho snapshot.` | `Số phiên bản và số dòng của mỗi lần cập nhật.` |
| `portfolio.html:48` | `Source workspace` | `Không gian dữ liệu nguồn` |
| `portfolio.html:49,76` | `Client config` | `Cấu hình khách hàng` |
| `data_hub_settings.html:6` | `Technical Settings` | `Cài đặt kỹ thuật` |
| `data_hub_settings.html:33` | `Connection Check` | `Kiểm tra kết nối` |
| `data_hub_settings.html:57` | `Runtime Settings` | `Cài đặt đang chạy` |
| `data_hub_settings.html:82` | `Service Token` | `Mã truy cập dịch vụ` |
| `data_hub_settings.html:101,113` | `Test connection` | `Kiểm tra kết nối` |
| `co_form_settings.html:7` | `C/O Form Index` | `Danh mục form C/O` |
| `co_form_settings.html:8` | `Market aliases · form priority · HS criteria` | `Tên gọi khác của thị trường · thứ tự ưu tiên form · tiêu chí theo mã HS` |
| `co_form_settings.html:11` | `Settings` | `Cài đặt` |
| `co_form_settings.html:31` | `C/O form settings` | `Cài đặt form C/O` |
| `co_form_settings.html:37` | `Form index summary` | `Tổng quan danh mục form` |
| `co_form_settings.html:39,43,47,51,60,69` | `Forms` / `Markets` / `Picker` / `HS rules` / `Overview` / `Form priority` | `Form` / `Thị trường` / `Bộ chọn form` / `Quy tắc theo HS` / `Tổng quan` / `Thứ tự ưu tiên form` |
| `co_form_settings.html:74` | `Source note` | `Ghi chú nguồn` |
| `co_form_settings.html:79,156,233,359` | `Lưu overview` / `Lưu forms` / `Lưu markets` / `Lưu HS Criteria` | `Lưu tổng quan` / `Lưu danh sách form` / `Lưu thị trường` / `Lưu tiêu chí HS` |
| `co_form_settings.html:80` | `Reset seed mặc định` | `Khôi phục danh sách gốc` |
| `co_form_settings.html:180,181,183,213,243,268,294` | `Market` / `Label` / `Aliases` / `New market` / `HS Criteria` / `Status` / `HS scope` | `Thị trường` / `Nhãn` / `Tên gọi khác` / `Thêm thị trường` / `Tiêu chí HS` / `Trạng thái` / `Phạm vi HS` |
| `bom.html:258,262,263,264,324,353,355,378` | `Composition` / `Diff` / `Hash` / `Publish` / `Upload` / `File` / `Parse` / `Audit trail` | `BOM tổng hợp` / `Khác biệt` / `Mã băm` / `Publish` (keep — DH's own state name) / `Tải lên` / `File` (keep) / `Đọc file` / `Lịch sử thay đổi` |
| `bom.html:260` | `TP artifact` | `Bản BOM của thành phẩm` |
| `bom.html:33,74` | `Upload, flatten và cấu hình BOM canonical…` | `Việc tải lên, khai triển và cấu hình BOM gốc làm ở Data Hub. Barry CO chỉ đọc BOM đã publish.` |
| `bcct.html:56,64,69` | `Upload BCCT` | `Tải BCCT lên` |
| `bcct.html:57` | `Mode` | `Kiểu tải lên` |
| `bcct.html:89,90` | `Correction candidates` / `Các dòng này chưa được dùng cho C/O case cho tới khi review.` | `Dòng cần đối soát` / `Các dòng này chưa dùng được cho hồ sơ C/O cho tới khi đối soát xong.` |
| `catalog.html:20,44,65,82` | `Upload` / `Upload danh mục` | `Tải lên` / `Tải danh mục lên` |
| `catalog.html:71,72,93,94` | `DS NVL DK HQ` / `DS SP DK HQ` | `Danh mục NVL đã đăng ký HQ` / `Danh mục TP đã đăng ký HQ` |
| `catalog.html:75` | `Scope upload` | `Phạm vi tải lên` |
| `catalog.html:88` | `Catalog hiện tại được publish theo version tổng hợp mỗi công ty.` | `Danh mục hiện tại được publish theo phiên bản tổng hợp của từng khách hàng.` |
| `catalog_table.html:19` | `Upload` | `Tải lên` |
| `co_stock.html:120` | `Actor` | `Người thực hiện` |
| `co_stock.html:27` | `Refresh từ Data Hub` | `Cập nhật tồn từ Data Hub` |
| `co_stock.html:78` | `Upload & nạp snapshot` | `Tải file lên và cập nhật tồn CO` |
| `co_stock_workbook_tool.html:23,37` | `convert sang` / `Convert + xem trước` | `chuyển sang` / `Đọc workbook và xem trước` |
| `cost_allocation.html:21` | `Mặc định cả doanh nghiệp (Mode B)` | `Mặc định cho cả khách hàng` — `Mode A` / `Mode B` are internal names; label them `theo mã SP` / `mặc định` |
| `cost_allocation.html:68,90` | `Upload & thay thế` | `Tải lên và thay toàn bộ` |
| `cost_allocation.html:119` | `Upload file Excel hoặc nhập tay qua API.` | `Tải mẫu Excel về, điền, rồi tải lên.` |
| `co_case.html:1341` | `Load BOM` | `Nạp công thức NVL` |
| `co_case.html:1101` | `‹ Review` | `‹ Tổng hợp` |
| `co_case.html:1353` | `Đã propose ✓` | `Đã gửi đề xuất` |
| `co_case.html:1352,1401,1403` | `Đã propose artifact {{ id }} sang Data Hub` / `Bấm "Lưu BOM artifact mới" để gửi đề xuất` | `Đã gửi đề xuất {{ id }} sang Data Hub` / `Bấm "Gửi đề xuất BOM" để gửi sang Data Hub` |
| `co_case.html:625` | `Upload` | `Tải lên` |
| `co_case.html:883` | `Demo` | Remove or label the actual state |
| `co_case.html:19,20,22` | `BCCT reviewed rows: …. Config snapshot: …. Correction candidates không được dùng cho hồ sơ C/O.` | `Số dòng BCCT đã đối soát: … · Cấu hình tại thời điểm chụp: … · Dòng cần đối soát không được dùng cho hồ sơ C/O.` |
| `co_case.html:2306` | `BOM ghi` / `Cần refresh` (`:1261,1267,1268`) | `BOM ghi nhận` / `Cần cập nhật` |
| `co_case.html:1267` | `Thiếu input` | `Thiếu dữ liệu` |
| `workspace.html:17,49` | `Workspace này phục vụ việc làm C/O.` / `Hồ sơ C/O là trung tâm của workspace này.` | `Không gian làm việc này phục vụ việc làm C/O.` / `Hồ sơ C/O là trung tâm của không gian làm việc này.` |
| `workspace.html:29,49` | `xuất dossier` / `xuất bộ dossier nộp` | `xuất bộ hồ sơ` / `xuất bộ hồ sơ để nộp` |
| `_client_nav.html:35` | `Khu làm việc công ty` | `Không gian làm việc của khách hàng` |
| `settings.html:8,31` | `dùng chung toàn app` | `dùng chung toàn hệ thống` |
| `suppliers.html:23` | `Chưa có database — không ghi được cờ NCC` | See §3.2 |
| `co_stock.html:200`, `co_stock_workbook_tool.html:22`, `client_config.html:78` | `client` in Vietnamese prose | `khách hàng` |

### 4.3 Fully English or mixed labels in Data Hub

| File:line | English on screen | Proposed |
|---|---|---|
| `i18n.py:138` | `navgrp.config.parser_rules` = `Parser rules` | `Quy tắc đọc file` |
| `i18n.py:152` | `navgrp.admin.client_type_presets` = `Preset DNCX` | `Mẫu cấu hình DNCX` |
| `i18n.py:154,155,156` | `Adapter` / `Adapter BOM` / `Adapter Quyết toán` | `Bộ đọc file` / `Bộ đọc BOM` / `Bộ đọc quyết toán` |
| `i18n.py:158` | `navgrp.admin.service_accounts` = `Service tokens` | `Mã truy cập dịch vụ` |
| `i18n.py:160` | `navgrp.admin.settings_embedding` = `Embedding` | `Tìm kiếm theo ngữ nghĩa` |
| `i18n.py:272,284,290,291,292` | `Manual flat` / `Technical raw` / `flattened` / `non_flattened` / `manual_flat` | Status enum values shown raw. → `Bảng phẳng có sẵn` / `BOM kỹ thuật thô` / `đã khai triển` / `chưa khai triển` / `phẳng sẵn` |
| `i18n.py:276,278,280,282` | `SAP exploded (Level)` / `SAP indented walk (single root)` / `Multi-sheet per root` / `Technical flatten (auto)` | Adapter names — keep the SAP ones as product names, but translate the descriptions and rename `Multi-sheet per root` → `Mỗi sheet một thành phẩm`, `Technical flatten (auto)` → `Tự khai triển (tự nhận dạng)` |
| `i18n.py:299` | `flatten.preview.pending` = `Pending` | `Chờ xử lý` |
| `i18n.py:308,346,349` | `Unresolved nodes` / `unresolved` | `Mắt xích chưa giải được` / `chưa giải được` |
| `i18n.py:312` | `Mỗi card là một business decision. Tick "Confirm" để materialize variant tương ứng. Decision không tick = block.` | Six English words in one sentence. → `Mỗi thẻ là một lựa chọn cần xác nhận. Tick vào thẻ để tạo phiên bản tương ứng; thẻ không tick sẽ không được tạo.` |
| `i18n.py:316` | `flatten.decisions.target` = `Target` | `Áp cho` |
| `i18n.py:322,323` | `BCCT import vs. BOM con` / `…Cần xác nhận strategy nào ưu tiên.` | `BCCT nhập khẩu hay BOM con` / `…Cần chọn cái nào ưu tiên.` |
| `i18n.py:325` | `Bản này còn unresolved nodes — KHÔNG nên dùng để tính toán.` | `Bản này còn mắt xích chưa giải được — KHÔNG nên dùng để tính bảng kê.` |
| `i18n.py:329,331,333` | `Không có client-specific override — đang dùng global canonical factor…` / `…đang dùng UOM của row làm fallback…` / `…flatten engine lấy version mới nhất trong DB.` | Rewrite in Vietnamese; `override`, `global canonical factor`, `row`, `fallback`, `version`, `DB` all have Vietnamese equivalents already used elsewhere in this file. |
| `i18n.py:358,359,360,362` | `Materialize {n} bản lưu` / `Reject` / `Reject pending? Tất cả decisions sẽ bị xóa.` / `Decision không tick = không materialize bản đó. Default an toàn = block.` | See §2 |
| `i18n.py:377` | `uom_drift.sev_alias` = `synonym` | `tên gọi khác` |
| `i18n.py:384` | `bom.stale.refresh` = `Refresh ngay` | `Cập nhật ngay` |
| `i18n.py:382` | `Phụ thuộc external (catalog / UoM / sourcing / BTP BOM mới) đã thay đổi từ khi materialize. Click 'Refresh' để re-derive.` | `Dữ liệu liên quan (danh mục / hệ số quy đổi / nguồn cung / BOM bán thành phẩm) đã đổi từ lần tạo gần nhất. Bấm "Cập nhật" để dựng lại.` |
| `i18n.py:435,436,437,438,439,440` | `Actor` / `Intent` / `Parent` / `Rows` / `Hash` / `Published` | `Người thực hiện` / `Mục đích` / `Bản gốc` / `Số dòng` / `Mã băm` / `Đã publish` |
| `i18n.py:446` | `bom.upload_profile` = `Profile parser` | `Kiểu cấu trúc file` |
| `i18n.py:269` | `…(intent: asserted_technical), gồm raw_graph + shallow + full_flat bản lưu.` | Internal artefact names in operator-facing help. → `…tạo ba bản: BOM gốc, BOM rút gọn và BOM khai triển đầy đủ.` |
| `i18n.py:270` | `Chọn cấu trúc workbook hoặc 'technical_flatten' để chạy flatten engine…` | `Chọn cấu trúc file, hoặc "Tự khai triển" nếu không chắc.` |
| `i18n.py:484,485` | `Rút lại proposal này? Người gửi sẽ phải submit lại…` / `…quyền duyệt proposal…` | `Rút lại đề xuất này? Người gửi sẽ phải gửi lại…` / `…quyền duyệt đề xuất…` |
| `i18n.py:501,592` | `Xoá upload lỗi này?` / `Lần upload gần nhất` | `Xoá lần tải lên bị lỗi này?` / `Lần tải lên gần nhất` |
| `i18n.py:558,559,560,561,579,589` | `Dev` / `Admin` / `Manager` / `Staff` | Role names. Keep `Admin`/`Dev` as system roles; translate `Manager` → `Quản lý`, `Staff` → `Nhân viên` (DH already uses `Quản lý` at `i18n.py:98`, so it is inconsistent with itself) |
| `i18n.py:1299–1318` (`en` block, `flow.*` keys) | `Choose file`, `Review`, `Commit`, `Pending ID`, `Source file`, `Nothing is written to the Hub until you press the button on the right.`, `Legend`, `new`, `updated`, `not committed`, `duplicate`, `mismatch`, `Reason`, `Column in file`, `Target field`, `unmapped`, `mapped` | **21 `flow.*` keys exist only in `en` and have no `vi` entry** (`vi` block: 0 matches; `en` block: 21). `clients/_upload_mapping.html:8,64,70,99` calls `t('flow.map.*')` directly. `t()` falls back to the default language, then to the key — so a Vietnamese operator on the upload flow sees these in English. Add the 21 `vi` entries. |
| `clients/parser_rules.html:11` | `+ extract material_identity candidates` | `+ Tách mã NVL từ tên hàng` |
| `clients/declarations.html:135` | `…ingest BCCT trước` | `…tải BCCT lên trước` |
| `clients/declaration_zip_preview.html:102` | `Không có file hợp lệ để ingest.` | See §3.4 |
| `clients/bom.html:53`, `clients/bqd.html:24` | `File đã bị reject.` | `File đã bị từ chối.` |
| `clients/bom_preview.html:46` | `…hãy reject.` | `…bấm "Từ chối".` |
| `clients/catalog_candidates.html:190` | `Không có candidate nào đang chờ duyệt.` | `Không có ứng viên nào chờ duyệt.` |
| `clients/catalog_conflicts.html:169` | `Không có conflict khớp với bộ lọc hiện tại.` | `Không có mâu thuẫn nào khớp bộ lọc.` |
| `clients/catalog_detail.html:788,814` | `Không có BCCT row nào reference mã này.` / `Không có BOM artifact nào reference mã này.` | `Không dòng BCCT nào dùng mã này.` / `Không BOM nào dùng mã này.` |
| `clients/bcct_history.html:114` | `Không có thay đổi nào được log cho dòng này.` | `Chưa ghi nhận thay đổi nào cho dòng này.` |
| `clients/uom_factors.html:123` | `…hoặc import file bên dưới.` | `…hoặc tải file lên ở dưới.` |
| `admin/settings_technical.html:31` | `Khi parser cứng từ chối file Excel mới, hub gọi LLM để đề xuất…` | `Khi bộ đọc cố định không xử lý được file Excel mới, hệ thống dùng AI để đề xuất…` |
| `admin/settings_embedding.html` | `Chạy lại backfill cho client này`, `Budget cứng per-client. Vượt → upload bị reject với thông báo.` | `Tính lại vector tìm kiếm cho khách hàng này`, `Hạn mức cố định cho từng khách hàng. Vượt hạn mức thì file tải lên bị từ chối kèm thông báo.` |
| `admin/client_material_group_map.html:60` | `Chưa có bản đồ riêng cho client này.` | `Chưa có bảng ánh xạ riêng cho khách hàng này.` |
| `admin/service_accounts.html:125,134` | `Xoá service account '…'?` / `Chưa có service account nào.` | `Xoá tài khoản dịch vụ "…"?` / `Chưa có tài khoản dịch vụ nào.` |
| `admin/uom.html:157,173` | `Chưa có alias riêng (ngoài self).` / `Không có canonical nào khớp.` | `Chưa có tên gọi khác nào.` / `Không có đơn vị chuẩn nào khớp.` |
| `clients/nxt_preview.html`, `clients/_upload_preview.html`, `clients/bcct_upload_preview.html` | `Read-only — bạn không có quyền edit client này.` | `Chỉ xem — bạn không có quyền sửa khách hàng này.` |
| `jobs/detail.html`, `jobs/list.html` | `Job chạy nền với trang theo dõi tiến độ riêng.` | `Việc nền có trang theo dõi tiến độ riêng.` |

---

## 5. The 15 highest-payoff copy changes, ranked

Ranked by (how often an operator hits the string) × (how much confusion it causes when hit). Items 1–5 are the ones that cost time on every dossier.

| # | Change | File:line | Current | Proposed | Why |
|---|---|---|---|---|---|
| 1 | Unify the entity name | CO: 49 strings in 11 files (`_client_nav.html:4,35,53`, `base.html:182,192,266,267,273,295,296,302`, `clients.html:2,13,14,20,28`, `client_config.html:2,10,11,144,162`, `error.html:10`, `_picker_clients.html:15`, `_picker_cases.html:18`, `bom.html:74,113,398`, `catalog.html:88`, `settings.html:8,31`, `co_case.html:441,804,898,902,2295,2325`) | `Công ty` | `Khách hàng` | The same person switches between both apps on one dossier. Every switch costs a re-mapping of the top-level noun, and CO's own `Cấu hình khách` (`co_case.html:6822`) already points at a page titled `Cấu hình công ty` — the app contradicts itself on the most-used word on screen. |
| 2 | Fix the propose-BOM quartet | `co_case.html:1352,1353,1401,1403` | Button `Lưu BOM mới`; tooltip `Lưu BOM artifact mới về Data Hub`; helper `Bấm "Lưu BOM artifact mới" để gửi đề xuất sang Data Hub`; state `Đã propose ✓` | Button `Gửi đề xuất BOM`; tooltip `Gửi thay đổi BOM sang Data Hub để duyệt`; helper `Bấm "Gửi đề xuất BOM" để gửi sang Data Hub duyệt`; state `Đã gửi đề xuất` | Four names for one action inside one panel, and the helper text quotes a button label that does not exist on screen. `Lưu` says the change is saved locally when in fact it is queued for another person's approval in another app — the operator can leave believing the BOM is updated. |
| 3 | Rewrite the two generic error toasts | `base.html:127`, `base.html:139` | `Lỗi máy chủ (HTTP ${status}).` / `Lỗi máy chủ (HTTP 401).` | `Máy chủ không xử lý được yêu cầu (mã ${status}). Thử lại; nếu vẫn lỗi, chụp màn hình và báo kỹ thuật.` / `Phiên đăng nhập đã hết hạn. Đăng nhập lại ở tab mới rồi quay lại — thao tác đang làm vẫn được giữ.` | These two strings are the fallback for **every** failed `fetch` in CO. One edit improves every failure path in the app; today the operator gets a number and no instruction. |
| 4 | Replace `Upload` with `Tải lên` everywhere in CO | `bcct.html:56,64,69`, `bom.html:33,139,163,324,348`, `catalog.html:20,44,65,82`, `catalog_table.html:19`, `co_case.html:625`, `co_stock.html:78`, `co_stock_workbook_tool.html:22`, `cost_allocation.html:68,119` | `Upload` | `Tải lên` | 18 buttons and headings. DH already says `Tải lên` in its nav. Two apps, two words, one action, on screens the same person uses back to back. |
| 5 | One word for settings | CO `base.html:210,212,235,237,275`, `settings.html:8`, `data_hub_settings.html:6,12,57`, `co_form_settings.html:11,31`, `user.html:9`; DH `i18n.py:5` | `Cài đặt` / `Cài đặt hệ thống` / `Cài đặt kỹ thuật` / `Thiết lập` / `Settings` / `Technical Settings` / `Runtime Settings` | `Cài đặt` (app-wide) and `Cấu hình` (per-khách-hàng) — nothing else | 8 labels for 2 concepts. The operator cannot predict which menu holds which knob, so they open all of them. |
| 6 | Translate the `flatten.*` decision UI | `i18n.py:312,325,329,331,333,358,359,360,362` | `Mỗi card là một business decision. Tick "Confirm" để materialize variant tương ứng. Decision không tick = block.` and 8 siblings | Full Vietnamese (see §4.3) | Nine one-line edits in a single dict, all on the BOM upload path that every new product goes through. `materialize`, `variant`, `block`, `decision`, `Reject` are engineering words presented as instructions. |
| 7 | Rename DH `Chốt tồn kho` | `i18n.py:133,141`, `clients/inventory_snapshot*.html` (13 strings) | `Chốt tồn kho` | `Tồn kho quyết toán` | `Chốt` in CO means "lock this bảng kê and draw stock down the ledger" — irreversible. `Chốt tồn kho` in DH is a period-end settlement snapshot. Same verb, two operations, one operator. It already sits under DH's `Quyết toán` group, so the new name matches its own section. |
| 8 | Add the 21 missing `vi` keys for the upload flow | `i18n.py:1299–1318` | `Choose file`, `Review`, `Commit`, `Nothing is written to the Hub until you press the button on the right.`, `Legend`, `new`, `updated`, `not committed`, `duplicate`, `mismatch`, `Reason`, `Column in file`, `Target field`, `unmapped`, `mapped`, … | Vietnamese equivalents | These keys exist only under `en`. `t()` falls back to the default language and renders English to a Vietnamese operator on the column-mapping screen — the step where a wrong choice silently corrupts an import. |
| 9 | Give the four blocking messages an action | `co_case.html:7290,7291`, `co_case.html:965`, `co_case.html:2333` | `Còn NVL không xuất xứ thiếu đơn giá — bổ sung đơn giá rồi tính lại.` / `Chưa có BOM/NVL đầy đủ — nạp BOM rồi tính lại.` / `{{ n }} bảng kê chưa chọn tiêu chí — không chốt được` / `Chưa có hệ số thì dòng vẫn trừ tồn 1:1 và bảng kê không chốt được.` | See §3.3 — each names the count, the location and the button to press | These are the four hard blocks on the Chốt path. Today they say *what* is wrong but not *which row* or *which button*, so the operator hunts through a 1,000-row sheet. |
| 10 | Rename the two lock buttons to include their side effect | `co_case.html:1357`, `co_case.html:1345` | `Chốt` / `Mở chốt` | `Chốt & trừ tồn` / `Mở chốt & nhả tồn` | `Chốt` writes to `co_stock_claims` and draws stock down. Nothing on the button says stock moves. The undo is equally invisible. This is the highest-consequence button in the app. |
| 11 | Translate the fully English account and settings pages | `user.html:6,7,9,23,27,29,40,50,55,61`, `sso_logout.html:6,14,18`, `data_hub_settings.html:6,33,57,82,101,113` | 19 English strings | See §4.2 | Two whole pages render in English inside a Vietnamese app. `Logout`, `Session`, `Role`, `Service Token`, `Test connection` are read by the same staff who read `Tờ khai` and `Bảng kê` two clicks earlier. |
| 12 | `Load BOM` → `Nạp công thức NVL` | `co_case.html:1341` | `Load BOM` | `Nạp công thức NVL` | The only English button in the per-sheet action row, and the first button pressed on every new bảng kê. Its own tooltip is already Vietnamese and already says exactly this. |
| 13 | Empty states that name the button to press | `co_stock.html:22,44`, `bom.html:279,306,340`, `co_case.html:408,55`, `cost_allocation.html:119`, `suppliers.html:33` | `Chưa có snapshot`, `Chưa có artifact BOM.`, `Chưa có bảng kê`, `Chưa có hệ số nào. Upload file Excel hoặc nhập tay qua API.` | See §3.2 | 9 first-run screens. `snapshot` and `artifact` are storage words the operator has no reason to know, and `nhập tay qua API` instructs a non-developer to call an API. |
| 14 | One term for the catalog across both apps | CO `_client_nav.html:1,43`, `catalog.html:71,72,91,92,93,94`; DH `i18n.py:129` | `Danh mục mã hàng` (CO) / `Danh mục vật tư` (DH) / `DS NVL`, `DS SP` | `Danh mục NVL` and `Danh mục TP` in both | Same underlying table, reached from both apps, under three names plus two undefined abbreviations. `vật tư` also collides with CO's `phi vật tư`, which means something else. |
| 15 | Drop `snapshot` from operator-facing strings | `co_stock.html:22,44,53,55,61,63,66,73,78,194,198`, `co_stock_workbook_tool.html:10,20,23,53`, `client_config.html:61`, `co_case.html:20` | `snapshot`, `Nạp snapshot`, `snapshot rỗng`, `Config snapshot` | `tồn CO`, `Ghi vào tồn CO`, `chưa có dữ liệu tồn`, `Cấu hình tại thời điểm chụp` | 17 occurrences of a storage-layer word on the Tồn CO pages. The operator's mental model is "tồn"; `snapshot` adds a second object that does not exist for them, and `Upload & nạp snapshot` exposes two internal steps for one outcome. |

---

## Appendix — what was checked and found clean

- **Unaccented Vietnamese**: 0 instances in 11,189 extracted visible strings across both apps.
- **`bảng kê`**: 126 CO strings, 6 DH strings, no competing synonym.
- **`tờ khai`**: 111 strings across both apps, no competing synonym; `TKN`/`TKX` used consistently as abbreviations.
- **`vụ việc`**: not in use as a domain term in either app. The single grep hit is a word-boundary artefact.
- **`ghi nhận`**: 3 strings, all correct in context, not competing with `tải lên`.
- **`Nhập-Xuất-Tồn`** (DH `i18n.py:132`): a distinct settlement concept, correctly named, no change needed.
- **DH error page copy** (`i18n.py:20–34`): the 400/401/403/404 bodies already state cause and action correctly. Only 500 and generic need the additional action line.
