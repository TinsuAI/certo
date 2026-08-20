# Flow + IA proposal — Data Hub, 2026-08-20

Companion to `DESIGN.md` (the visual contract). `DESIGN.md` owns the shell,
tokens and components; this file owns what goes *in* the shell, in what order,
and what disappears. Nothing here is built by this document; the parallel
reskin agent landed some of the nav items mid-session — see Baseline and drift.

Evidence base: `app/routes/*.py` (254 route decorators), `app/templates/` (58
client templates), and a live pass against `http://127.0.0.1:8754` logged in as
`admin@data-hub.local`, client `growatt-vn` (3,445 materials · 2,913 code
mappings · 39,203 BCCT rows · 822 BOM artifacts · 0 proposals).

### Baseline and drift

Everything in §2 and §4 was measured against the tree as it stood at the start
of this session — the `<details>`-dropdown `_client_nav.html`. **Mid-session the
parallel reskin agent landed `app/templates/_sidebar.html`**, a persistent
grouped sidebar rendered once from `base.html`, and slimmed `_client_nav.html`
to a page-title bar. That closes problem **P1** and part of **P6** in code
before this document was finished.

The measured baseline is kept below because it is the "before" that justifies
the rest, and because the new sidebar reproduces the old group structure
one-for-one. What the sidebar did **not** change, verified against the current
`_sidebar.html`:

- `/clients/{id}/jobs` and `/clients/{id}/declaration-config` are still in no
  nav (**P2**).
- `/bom/needs-action` is in the sidebar at `_sidebar.html:46` with a bare
  `class="side-a"` and no `active_tab` test, so it still never highlights;
  `/bom/audit-log` is still absent entirely (**P3**).
- The client switcher is still not in the header — `base.html`'s `<header
  class="topnav">` has no `<select>` (**P4**).
- No queue group exists: catalog candidates (318 pending) and catalog
  conflicts are still body links only.
- `Đề xuất` / `Duyệt BOM` still name the same object twice (**P10**).

§5 and §6 are written as a delta against the sidebar that now exists, not
against the retired `<details>` nav.

---

## 1. The operator's real job

An agency staffer onboarding a DNCX first creates the client record and sets
`code_resolution_mode` (`identity` | `simple_mapping` | `batch_aggregate_resolution`),
`bom_proposal_mode` and `bom_proposal_qty_tolerance_pct` — `app/routes/clients.py:145`
— because that mode decides how every later internal-code↔customs-code join
resolves and cannot be changed casually afterwards. They then load **Danh mục**
(the material catalog) from the client's ERP export, because `hub.materials` is
the table every later module joins against (`catalog.py:324`). If the mode is
not `identity` they load **Mã Quy Đổi** next (`bqd.py:154`), since
`hub.code_mappings` is what turns an internal code into a customs code for BCCT
and BOM lookups. With codes resolvable they load **BCCT**, the year's customs
declaration registry (`bcct.py:202` → 39,203 rows for growatt-vn), then attach
the per-declaration **tờ khai** XLS/PDF files, singly or as one ZIP
(`declarations.py:307` and `:400`). **BOM** comes last of the ingest steps
(`bom.py:247`), because flattening a product structure needs both the catalog
rows and the resolved codes to already exist. The app states this order itself:
`workspace.module_meta` renders as *"Danh mục → Bảng quy đổi → BCCT → BOM →
Duyệt BOM"* (`app/i18n.py:152`).

Ingest is not the end of the job. Each upload leaves queues behind — unknown
codes seen in BCCT/BOM land in **catalog candidates** (`catalog_discovery.py:143`,
318 pending on this instance per `.ai/STATUS.md`), catalog rows that disagree
with BCCT land in **conflicts** (`catalog.py:249`), BOM artifacts that went stale
or lost a UoM factor land in **needs-action** (`bom.py:973`), and the CO app
posts **BOM proposals** back that a human must approve or reject
(`proposals.py:70`/`:92`). At settlement time the operator adds the year's
**NXT** movement summary and an **inventory snapshot**
(`nxt.py:158`, `inventory_snapshots.py:115`). Steady state is therefore a loop:
re-upload a changed file, re-confirm the column mapping, clear whatever the new
rows pushed into the four queues, and keep the config in sync — not a one-time
wizard.

---

## 2. Current screen inventory

**Click convention.** Counts are mouse clicks starting from the client
workspace overview `/clients/{id}`, using the **session-start** `<details>` nav:
opening a group in `_client_nav.html` costs 1 click, the link inside costs a
second. The overview page also carries a 6-tile `module-grid` giving a 1-click
path to catalog / bqd / bcct / bom / proposals / uploads, but that grid exists
**only** on the overview, so the nav cost below is what applies from every
other screen. Rows marked **>3** exceed the task's threshold.

With `_sidebar.html` now in place, subtract 1 from every count of 2 or more
whose first click was opening a group — the 15 grouped destinations are now
1 click. The 6 screens at 4+ clicks drop by 1 too but stay the deepest in the
app, and the 2 orphans stay at their body-link cost — the sidebar did not add
either group.

### Client workspace

| Route | Template | Purpose | Job step | Reached from | Clicks |
|---|---|---|---|---|---|
| `/clients/{id}` | `workspace.html` | Overview: 5 stats, 6 module tiles, config summary | all | header → Khách hàng → row | 0 |
| `/clients/{id}/catalog` | `catalog.html` (443 ln) | Material list + AI panel + 3 chip filter rows + column picker | 2 | Danh mục ▸ Danh mục vật tư | 2 |
| `/clients/{id}/catalog/upload` | `catalog_upload.html` | Pick file + `is_hq_registered` flag | 2 | catalog → Tải lên Danh mục | 3 |
| `/clients/{id}/catalog/upload/mapping/{uid}` | `_upload_mapping.html` | Confirm column→field map, pick header row | 2 | POST upload (cache miss) | flow |
| `/clients/{id}/catalog/preview/{pid}` | `catalog_preview.html` | Sample rows, skipped-row repair, save/reject | 2 | POST parse | flow |
| `/clients/{id}/catalog/candidates` | `catalog_candidates.html` (21k) | Queue of codes seen in BCCT/BOM with no catalog row | queue | catalog → Mã chờ duyệt | 3 |
| `/clients/{id}/catalog/candidates/detail` | `catalog_candidate_detail.html` | One candidate's evidence + accept form | queue | candidates → row | **4** |
| `/clients/{id}/catalog/conflicts` | `catalog_conflicts.html` | Catalog-vs-BCCT disagreements, 2 types | queue | catalog body link | 3 |
| `/clients/{id}/catalog/{code}/detail` | `catalog_detail.html` (818 ln, 12 `<details>`) | Everything about one material | 2 / queue | catalog → row | 3 |
| `/clients/{id}/catalog/{code}/edit` | `catalog_material_edit.html` | Edit 7 fields — **duplicate** of the inline panel at `catalog_detail.html:469` | 2 | conflicts row, or detail header | **4** |
| `/clients/{id}/bqd` | `bqd.html` | Code-mapping list NB↔HQ | 3 | Danh mục ▸ Mã Quy Đổi | 2 |
| `/clients/{id}/bqd/upload` | `bqd_upload.html` | Pick file | 3 | bqd → Tải lên | 3 |
| `/clients/{id}/bqd/upload/mapping/{uid}` | `_upload_mapping.html` | Column map | 3 | POST upload | flow |
| `/clients/{id}/bqd/preview/{pid}` | `bqd_preview.html` | Preview + save/reject | 3 | POST parse | flow |
| `/clients/{id}/bcct` | `bcct.html` | Declaration-row registry, year + direction filters | 4 | Hải quan ▸ BCCT | 2 |
| `/clients/{id}/bcct/upload` | `bcct_upload.html` | Pick file | 4 | bcct → Tải lên | 3 |
| `/clients/{id}/bcct/upload/mapping/{uid}` | `_upload_mapping.html` | Column map | 4 | POST upload | flow |
| `/clients/{id}/bcct/upload/preview/{pid}` | `bcct_upload_preview.html` (195 ln) | Preview + confirm-on-update diff + UoM-drift ack gate | 4 | POST parse | flow |
| `/clients/{id}/bcct/history/{key}/{line}` | `bcct_history.html` | Per-line change history | 4 | bcct → row | 3 |
| `/clients/{id}/declarations` | `declarations.html` | Declaration list, direction / has_files / q filters | 5 | Hải quan ▸ Tờ khai | 2 |
| `/clients/{id}/declarations/upload` | `declaration_upload.html` (179 ln) | Two JS-toggled panels: single file, ZIP | 5 | declarations → Tải lên | 3 |
| *(POST)* `/declarations/upload-zip` | `declaration_zip_preview.html` | ZIP staging preview, ok/duplicate/mismatch counts | 5 | ZIP submit | flow |
| `/clients/{id}/declarations/{no}` | `declaration_detail.html` | Files attached to one declaration | 5 | declarations → row | 3 |
| `/clients/{id}/bom` | `bom.html` | Product list with artifact counts, tp/btp filter | 6 | BOM ▸ Định mức (BOM) | 2 |
| `/clients/{id}/bom/upload` | `bom_upload.html` | Pick file + parser profile + a second form to set the client default | 6 | bom → Tải lên | 3 |
| `/clients/{id}/bom/upload/mapping/{uid}` | `_upload_mapping.html` | Column map (manual_flat only) | 6 | POST upload | flow |
| `/clients/{id}/bom/preview/{pid}` | `bom_preview.html` | Preview + save/reject | 6 | POST parse | flow |
| `/clients/{id}/bom/flatten-preview/{pid}` | `bom_flatten_preview.html` (242 ln, 4 `<details>`) | BTP sourcing decisions before flatten | 6 | preview confirm | flow |
| `/clients/{id}/bom/needs-action` | `bom_needs_action.html` | Stale / missing-factor / unresolved clusters | queue | BOM ▸ Cần xử lý | 2 |
| `/clients/{id}/bom/audit-log` | `bom_audit_log.html` | Forensic BOM event log | queue | needs-action body link only | 3 |
| `/clients/{id}/bom/{code}/artifacts` | `bom_artifacts.html` | Artifact list for one product | 6 | bom → row | 3 |
| `/clients/{id}/bom/artifact/{aid}` | `bom_artifact_detail.html` (15k) | One artifact's rows + lineage | 6 | artifacts → row | **4** |
| `/clients/{id}/bom/artifact/{aid}/refresh/preview` | `bom_refresh_preview.html` | Diff before re-flatten | 6 | artifact detail | **5** |
| `/clients/{id}/bom/{code}/presets` | `bom_presets.html` | Saved interpretations pinning an artifact | 6 | artifacts → Preset | **4** |
| `/clients/{id}/bom/stale` | — | 308 → `/bom/needs-action` (legacy bookmark, `bom.py:1250`) | — | deeplink only | n/a |
| `/clients/{id}/nxt` | `nxt.html` | Settlement movement artifacts | 8 | Quyết toán ▸ Nhập-Xuất-Tồn | 2 |
| `/clients/{id}/nxt/upload` | `nxt_upload.html` | File + required `period_year` + adapter + a second default-adapter form | 8 | nxt → Tải lên | 3 |
| `/clients/{id}/nxt/upload/mapping/{uid}` | `nxt_mapping.html` (64 ln) | Column map — **private copy**, not `_upload_mapping.html` | 8 | POST upload | flow |
| `/clients/{id}/nxt/preview/{uid}` | `nxt_preview.html` | Preview 200 lines + save/reject | 8 | POST parse | flow |
| `/clients/{id}/nxt/{aid}` | `nxt_detail.html` | Browse ingested lines | 8 | nxt → row | 3 |
| `/clients/{id}/inventory-snapshots` | `inventory_snapshots.html` | Stocktake snapshot list | 8 | Quyết toán ▸ Chốt tồn kho | 2 |
| `/clients/{id}/inventory-snapshots/upload` | `inventory_snapshot_upload.html` | File + required `snapshot_date` + adapter + default-adapter form | 8 | list → Tải lên | 3 |
| `/clients/{id}/inventory-snapshots/preview/{uid}` | `inventory_snapshot_preview.html` | Preview + save/reject | 8 | POST upload | flow |
| `/clients/{id}/inventory-snapshots/{sid}` | `inventory_snapshot_detail.html` | Browse snapshot lines | 8 | list → row | 3 |
| `/clients/{id}/proposals` | `proposals.html` | BOM change requests from CO, status filter | queue | BOM ▸ Đề xuất | 2 |
| `/clients/{id}/proposals/{pid}` | `proposal_detail.html` | Approve / reject / withdraw one proposal | queue | proposals → row | 3 |
| `/clients/{id}/uom-factors` | `uom_factors.html` (18k) | Per-client UoM conversion factors + xlsx import | 6 | BOM ▸ Hệ số quy đổi | 2 |
| `/clients/{id}/uploads` | `uploads.html` | All upload events, module filter | audit | Tải lên (top level) | 1 |
| `/clients/{id}/uploads/{uid}` | `upload_detail.html` | One upload's status + stored file | audit | uploads → row | 2 |
| `/clients/{id}/jobs` | `jobs/list.html` | Background job history | audit | **catalog body only — not in nav** | 3 |
| `/jobs/{job_id}` | `jobs/detail.html` | One job's progress | audit | jobs list, or catalog AI panel | **4** |
| `/clients/{id}/edit` | `edit.html` | Client config: mode, proposal mode, tolerance, status, notes | 1 | Cấu hình ▸ Thông tin chung | 2 |
| `/clients/{id}/declaration-config` | `declaration_config.html` | Eligible import / relevant export declaration types + preset | 1 | **`edit.html:19` button only — not in nav** | 3 |
| `/clients/{id}/parser-rules` | `parser_rules.html` | Client parser rules + test harness | 1 | Cấu hình ▸ Parser rules | 2 |
| `/clients/{id}/parser-rules/{rid}/edit` | `parser_rule_edit.html` | Edit one rule | 1 | parser-rules → row | 3 |
| `/clients/{id}/column-aliases` | `admin/client_column_aliases.html` | Column-header aliases per module | 1 | Cấu hình ▸ Cấu hình cột | 2 |
| `/clients/{id}/material-group-map` | `admin/client_material_group_map.html` | ERP material-group → category map | 1 | Cấu hình ▸ Bản đồ Material Group | 2 |
| `/clients/{id}/staff` | `admin/client_staff.html` | Who may see/edit this client | 1 | Cấu hình ▸ Staff | 2 |
| `/clients/{id}/agent` | `agent_threads.html` | LLM assistant thread list | — | Trợ lý (top level) | 1 |
| `/clients/{id}/agent/{tid}` | `agent_thread.html` | One thread | — | agent → row | 2 |

### Global / admin

| Route | Template | Purpose | Reached from | Clicks |
|---|---|---|---|---|
| `/clients` | `clients/list.html` (91 ln) | Client picker — the only client switcher | header → Khách hàng | 1 |
| `/clients/new` | `edit.html` | Create client | clients list → Tạo mới | 2 |
| `/whats-new` | `whats-new.html` | Changelog | footer | 1 |
| `/admin/users` | `admin/users.html` | Accounts + roles | header → Quản trị | 1 |
| `/admin/users/{uid}/clients` | `admin/user_clients.html` | Per-user client grants | users → row | 2 |
| `/admin/bom-adapters` | `admin/bom_adapters.html` | Registered BOM parsers | admin nav | 1 |
| `/admin/settlement-adapters` | `admin/settlement_adapters.html` | Registered NXT/stock adapters | admin nav | 1 |
| `/admin/declaration-types` | `admin/declaration_types.html` | Mã loại hình master data | Dữ liệu tham chiếu ▸ | 2 |
| `/admin/client-type-presets` | `admin/client_type_presets.html` | DNCX config presets | Dữ liệu tham chiếu ▸ | 2 |
| `/admin/uom` | `admin/uom.html` | Canonical UoM + aliases | Dữ liệu tham chiếu ▸ | 2 |
| `/admin/service-accounts` | `admin/service_accounts.html` | API tokens (dev only) | Hệ thống ▸ | 2 |
| `/admin/settings/technical` | `admin/settings_technical.html` | Feature flags, auth strictness (dev only) | Hệ thống ▸ | 2 |
| `/admin/settings/embedding` | `admin/settings_embedding.html` | Embedding provider (dev only) | Hệ thống ▸ | 2 |

**Count:** 20 nav destinations exist in `_client_nav.html`; 5 are top-level
(0–1 click) and 15 sit behind a `<details>` group (2 clicks). Six screens cost
4+ clicks. Two screens (`/jobs`, `/declaration-config`) are in no nav at all.

---

## 3. The upload family, measured

Seven ingest flows exist. Four already share `app/routes/_mapping_flow.py`
(catalog, bqd, bcct, bom); three do not (nxt, inventory-snapshots,
declarations).

### What each flow actually does

| Flow | Column mapping page | Adapter/profile picker | Extra required form fields | Preview | Reject route | Sink |
|---|---|---|---|---|---|---|
| catalog | `_upload_mapping.html` (shared) | no | `is_hq_registered` checkbox | shared | `catalog.py:567` | `hub.materials` |
| bqd | shared | no | — | shared | `bqd.py:357` | `hub.code_mappings` |
| bcct | shared | no | — | **own 195-line template** | **none** | `hub.bcct_rows` |
| bom | shared | `profile` + set-default form | — | shared, then `bom_flatten_preview` | `bom.py:1282` | `hub.bom_artifacts` |
| nxt | **own `nxt_mapping.html`** | `adapter` + set-default form | `period_year` (required), `period_from`, `period_to` | own 72-line template | `nxt.py:444` | `hub.nxt_artifacts` |
| inventory | **none** | `adapter` + set-default form | `snapshot_date` (required) | own 61-line template | `inventory_snapshots.py:250` | `hub.inventory_snapshots` |
| declarations | **none** (files, not rows) | no | `direction` (required), optional `declaration_no` | ZIP path only | cancel route | `hub.declaration_files` |

### What genuinely differs

Four things, and only four:

1. **Extra form fields collected at upload time** — `is_hq_registered` (catalog),
   `period_year`/`from`/`to` (nxt), `snapshot_date` (inventory), `direction`
   (declarations). `ModuleConfig.extra_pending_kwargs_fn` (`_mapping_flow.py:87`)
   already exists for exactly this and catalog already uses it.
2. **Whether an adapter/profile is chosen before parse** — bom, nxt, inventory
   yes; catalog, bqd, bcct no.
3. **The domain summary panel and sample table** in the preview —
   already a solved problem: `_upload_preview.html` exposes
   `{% block module_summary %}`, `{% block module_sample %}`,
   `{% block diff_view %}`.
4. **The write target** — one `create_*` / `_ingest_*` call.
   `ModuleConfig.ingest_fn` already covers it.

### What is copy-paste

`app/routes/nxt.py` (480 lines) and `app/routes/inventory_snapshots.py`
(286 lines) declare the same handler sequence in the same order —
`list_view`, `upload_view`, `set_default_adapter`, `upload_submit`,
`_load_lines`, `_summarize`, `preview_view`, `preview_confirm`,
`preview_reject`, `detail_view` — with identical auth guards
(`require_user` → `require_can_edit_client` → `get_client` 404 →
`get_upload` module check), identical `parse_status` guards, and identical
redirect-with-flash idiom. After normalising the module name out of both
files, `diff` reports 389 differing lines out of 480/286 — and most of that
delta is nxt's extra mapping-page block, which inventory simply lacks.

`nxt_mapping.html` (64 lines) is a private reimplementation of
`_upload_mapping.html` (192 lines) with its own `_mapping_context` builder
(`nxt.py:253`) and its own LLM-suggest endpoint at `…/mapping/{uid}/llm`
instead of the shared `…/mapping/{uid}/llm_suggest`.

The six upload landing pages (`catalog_upload.html` 35, `bqd_upload.html` 22,
`bcct_upload.html` 23, `bom_upload.html` 50, `nxt_upload.html` 60,
`inventory_snapshot_upload.html` 55 — **245 lines total**) are the same
`<section class="zone">` + `zone-head` + `<form enctype="multipart/form-data">`
+ `<div class="upload-zone">` + submit button, differing only in the four
knobs listed above.

The codebase already states this direction. `_mapping_flow.py:1` — *"Shared
upload-mapping-preview-confirm flow used by all 4 modules. Replaces the older
per-module copy-paste"* — and `:18` — *"Slice 5 will retire `_llm_fallback.py`
once all 4 modules have migrated."* `ModuleConfig`'s own docstring (`:57`)
says *"adding a 5th module later must not require new dataclass fields, only
filling these in."* The work is half-done, not undecided.

### Collapse count

**6 of the 7 flows collapse into one parameterised flow. Declarations does not.**

Declarations is genuinely different: the unit of upload is a whole document
(XLS or PDF), not a row grid, so there is no column map, no `upload_pending`
row, no skipped-row repair. Single-file upload commits directly with no
preview at all (`declarations.py:307`); only the ZIP path has a preview, and it
stages to a filesystem `staging_id` rather than a pending record
(`declarations.py:400`). Forcing it into `ModuleConfig` would add fields the
dataclass docstring explicitly forbids.

Templates that collapse — **9 files, 442 lines, into 1 parameterised
`clients/_upload_form.html` plus 6 small `{% block %}` overrides**:

```
app/templates/clients/catalog_upload.html              35
app/templates/clients/bqd_upload.html                  22
app/templates/clients/bcct_upload.html                 23
app/templates/clients/bom_upload.html                  50
app/templates/clients/nxt_upload.html                  60
app/templates/clients/inventory_snapshot_upload.html   55
app/templates/clients/nxt_mapping.html                 64  → delete, use _upload_mapping.html
app/templates/clients/nxt_preview.html                 72  → reduce to blocks on _upload_preview.html
app/templates/clients/inventory_snapshot_preview.html  61  → reduce to blocks on _upload_preview.html
```

Plus `bcct_upload_preview.html` (195 lines) which extends `base.html` today
and should extend `clients/_upload_preview.html`, keeping only its
`{% block diff_view %}` and the UoM-ack banner. That is the BCCT
half-migration: its *routes* are on `_mapping_flow`, its *preview template*
is not.

Routes that collapse — **47 handlers into 9**:

```
app/routes/catalog.py            306,324,360,381,402,458,484,567   (8)
app/routes/bqd.py                136,154,181,202,223,268,290,357   (8)
app/routes/bcct.py               188,202,325,346,367,802,959       (7, no reject)
app/routes/bom.py                193,210,247,1346,1367,1388,526,611,1282 (9)
app/routes/nxt.py                117,135,158,275,288,310,386,414,444 (9)
app/routes/inventory_snapshots.py 82,100,115,197,222,250           (6)
```

Sum: 8 + 8 + 7 + 9 + 9 + 6 = **47**.

Target: `GET|POST /clients/{id}/ingest/{module}/upload`,
`GET /…/{module}/mapping/{upload_id}`, `POST /…/mapping/{uid}/llm_suggest`,
`POST /…/mapping/{uid}/parse`, `GET /…/preview/{pid}`,
`POST /…/preview/{pid}/confirm`, `POST /…/preview/{pid}/reject`, plus one
`POST /…/{module}/default-adapter` — 9 handlers total. Existing URLs stay as 308 redirects so
bookmarks and `uploads.html` links keep working.

---

## 4. Named problems

Ordered by cost to the operator. **`_client_nav.html` line numbers in this
section refer to the session-start file** (the `<details>` nav), which the
reskin agent has since rewritten; they are kept because they are the evidence
for the measurement, not as an edit target. Every other citation is current.

**P1 — LANDED. Every workspace destination except 5 costs 2 clicks, and the
first click shows nothing.**
`_client_nav.html` puts 15 of 20 destinations inside 5 `<details>` groups
(`navgrp.catalog`, `navgrp.customs`, `navgrp.settlement`, `tabs.bom`,
`tabs.config`). A `<details>` closes when the page navigates, so the state is
never persistent: moving from `/catalog` to `/bqd` is open-group + click, then
the group closes again. Cost: **+1 click on every navigation between the 15
grouped screens**, and the operator can never see the full set of available
screens at once. This is the single largest contributor to "rối rắm".

**P2 — Two screens are in no navigation at all.**
`/clients/{id}/declaration-config` (which sets
`eligible_import_declaration_types` — the list CO uses to filter BCCT imports,
see `docs/API_CONTRACT.md` §Source Summary) is reachable only from a
`btn-secondary` at `edit.html:19`. `/clients/{id}/jobs` is reachable only from
a `btn-ghost` at `catalog.html:25`. Neither appears in `_client_nav.html`.
Cost: an operator who does not already know they exist cannot find them.

**P3 — `/clients/{id}/bom/needs-action` and `/bom/audit-log` never highlight.**
`_client_nav.html:73` renders the needs-action link with no `class` attribute
at all, and neither route sets an `active_tab` — `bom.py:973` and `bom.py:1140`
omit the key (compare the 17 distinct `active_tab` values in use elsewhere).
`bom_tabs` at `_client_nav.html:22` lists only `['bom','proposals','uom-factors']`,
so the parent group does not highlight either. Cost: on two of the four queue
screens, the nav shows the operator as being nowhere.

**P4 — The client switcher requires a full page round-trip, and there are two
of them.**
Switching client means clicking "← Danh sách khách hàng" in the page-bar
(`_client_nav.html:19`), landing on `/clients`, scanning a 9-row table, and
clicking through — 2 clicks plus a scan, and it dumps whatever screen you were
on. Meanwhile `_chat_widget.html:36` already renders a `<select>` of the same
clients. The data for a header switcher is already in every template context:
`chat_widget_clients` is injected globally at `app/main.py:85`.

**P5 — BCCT is the only ingest flow with no reject route.**
`catalog.py:567`, `bqd.py:357`, `bom.py:1282`, `nxt.py:444` and
`inventory_snapshots.py:250` all expose `…/preview/{id}/reject`.
`app/routes/bcct.py` has none — grep for `reject` in that file returns one
comment at `:558`. `bcct_upload_preview.html:163` therefore offers "Hủy", a
plain `<a>` back to `/bcct`. Cost: a wrong BCCT file cannot be dismissed; the
pending record survives until it expires, and the operator gets no confirmation
that nothing was written.

**P6 — The overview renders each count three times and the client name three
times.**
Live on `/clients/growatt-vn`: `3445` appears in the page-bar tagline
(`_client_nav.html:8`), in a hero stat (`workspace.html:14`), and in a module
tile subtitle (`workspace.html:47`). Same for `2913`, `39203`, `822`. The name
"Growatt VN" appears in `<title>`, in `page-bar h1`, and in `hero-headline`.
The 6 module tiles duplicate 6 nav links. Cost: the overview's 13,188 bytes
carry roughly 5 distinct facts.

**P7 — `catalog_detail.html` puts 12 `<details>` blocks on one 818-line page.**
Sections: Chi tiết, Đơn vị tính, Vai trò quan sát, Liên kết NB ↔ HQ, Lịch sử
thay đổi, Chi tiết kỹ thuật, Phân tích từ BCCT, BCCT references, BOM
references, plus per-event diff expanders and an inline edit panel. It is the
most complex screen in the app and it has no internal navigation. Cost:
scrolling replaces navigation.

**P8 — Two full edit surfaces for the same 7 material fields.**
`catalog_material_edit.html` (95 lines, a full page) and the
`<details class="inline-edit">` panel at `catalog_detail.html:469-528` expose
byte-identical field sets — `name`, `category`, `status`, `uom`,
`production_source`, `supplier_hint`, `hq_registered` — and post to the same
handler `catalog.py:1011`. The standalone page costs 4 clicks; the inline panel
costs 3 plus a disclosure toggle. Cost: two maintenance sites, and an operator
who reaches one has no way to know the other is the same thing.

**P9 — One dead link.**
`uploads.html:51` links to `/clients/{id}/bcct/parse-mapping/{upload_id}` under
the label `uploads.review_mapping`. No such route exists — the real one is
`/clients/{id}/bcct/upload/mapping/{upload_id}` (`bcct.py:325`). Verified live:
`GET /clients/growatt-vn/bcct/parse-mapping/abc` → **404**. It renders whenever
a BCCT upload sits at `parse_status = 'proposed_mapping'`, which is exactly
when the operator most needs it.

**P10 — "Đề xuất" and "Duyệt BOM" name the same object; "Đề xuất" carries four
meanings.**
`tabs.proposals` = "Đề xuất" (`i18n.py:132`) and `workspace.stat.proposals` =
"Duyệt BOM" (`i18n.py:159`) both count `hub.bom_change_requests`. On top of
that, `.ai/STATUS.md` Next Steps item 5 records from the #54/#55 review that
the "Đề xuất" column carries four unrelated meanings in one cell and "Duyệt"
names two different operations side by side. Cost: the operator cannot tell
from the label which queue a number belongs to.

**P11 — Six upload landing pages, three preview shapes, two mapping-page
implementations.** Quantified in §3. Cost per operator: the same task looks
different in every module, so nothing transfers between them.

**P12 — Every upload page carries a second, unrelated form.**
`bom_upload.html:38`, `nxt_upload.html:46` and
`inventory_snapshot_upload.html:41` each append a "Lưu mặc định" form that
writes a **client-level** setting from inside a per-file upload screen. Cost:
a config write is one mis-click away from a file upload.

---

## 5. Proposed IA

Slots into the `DESIGN.md` shell: 52px navy header, 228px grouped sidebar,
`rail` under the header on pipeline screens. Group labels are uppercase
10.5px; item labels are the literal text below. `[key]` is the existing
`app/i18n.py` key, `[NEW: key]` needs adding.

**This is a delta against `app/templates/_sidebar.html` as it now stands**, not
a from-scratch spec. That file already has the shell, the `.side-grp` /
`.side-a` / `.ct` classes, the permission gates and the admin group set. What
changes below is grouping and membership: 3 groups are re-cut, 5 items are
added, 2 labels change.

### Header

```
[DH]  Data Hub        ▾ Growatt VN            [A] Admin ▾
```

- Company switcher is a `<select>` over `chat_widget_clients`
  (`app/main.py:85`), posting to the same path under the new `client_id`.
  Replaces the page-bar "← Danh sách khách hàng" link. **Not built yet** —
  `base.html`'s `<header class="topnav">` currently has no switcher, so
  changing client is still a round-trip through `/clients`.
- User menu holds theme toggle, language toggle, logout, and a
  "Quản trị" entry when `user.role in ('dev','admin')`.

### Client workspace sidebar

```
TỔNG QUAN
  Tổng quan                     /clients/{id}                     [tabs.overview]

DỮ LIỆU NỀN
  Danh mục vật tư               /catalog                 3.445    [navgrp.catalog.item]
  Mã Quy Đổi                    /bqd                     2.913    [tabs.bqd]
  Định mức (BOM)                /bom                       822    [navgrp.bom.list]
  Hệ số quy đổi                 /uom-factors                      [navgrp.bom.uom]

HẢI QUAN
  BCCT                          /bcct                   39.203    [tabs.bcct]
  Tờ khai                       /declarations                     [tabs.declarations]

QUYẾT TOÁN
  Nhập-Xuất-Tồn                 /nxt                              [navgrp.settlement.nxt]
  Chốt tồn kho                  /inventory-snapshots              [navgrp.settlement.inventory]

CẦN XỬ LÝ
  Mã chờ duyệt                  /catalog/candidates        318    [NEW: navgrp.queue.candidates]
  Mã xung đột                   /catalog/conflicts                [NEW: navgrp.queue.conflicts]
  BOM cần xử lý                 /bom/needs-action                 [navgrp.bom.needs_action]
  Đề xuất từ CO                 /proposals                   0    [NEW: navgrp.queue.proposals]

NHẬT KÝ
  Lịch sử tải lên               /uploads                          [tabs.uploads]
  Lịch sử chạy tác vụ           /jobs                             [NEW: navgrp.log.jobs]
  Nhật ký BOM                   /bom/audit-log                    [NEW: navgrp.log.bom_audit]

CẤU HÌNH
  Thông tin chung               /edit                             [navgrp.config.general]
  Loại hình tờ khai             /declaration-config               [NEW: navgrp.config.declaration_types]
  Cấu hình cột                  /column-aliases                   [navgrp.config.column_aliases]
  Bản đồ Material Group         /material-group-map               [navgrp.config.material_group_map]
  Parser rules                  /parser-rules                     [navgrp.config.parser_rules]
  Nhân sự phụ trách             /staff                            [NEW: navgrp.config.staff]

TRỢ LÝ
  Trợ lý dữ liệu                /agent                            [tabs.agent]
```

Notes on this structure:

- **Group-label keys that already exist**, so the implementer reuses rather
  than duplicates: `nav.group.workspace` = "Không gian làm việc" (currently on
  the TỔNG QUAN group — either label works, pick one), `navgrp.catalog` =
  "Danh mục", `navgrp.customs` = "Hải quan", `navgrp.settlement` = "Quyết
  toán", `tabs.bom` = "BOM", `tabs.config` = "Cấu hình", `nav.group.global` =
  "Toàn hệ thống". `nav.group.data_in` = "Dữ liệu vào" is today's group for
  uploads + agent; this proposal splits it into NHẬT KÝ and TRỢ LÝ, so that
  key is either retired or relabelled — do not leave it pointing at a group
  that no longer means "data coming in".
- **Delta against `_sidebar.html` in one line:** re-cut DỮ LIỆU NỀN (fold
  BOM + UoM factors in with catalog + BQD), add CẦN XỬ LÝ and NHẬT KÝ, add the
  5 missing items (`/catalog/candidates`, `/catalog/conflicts`,
  `/bom/audit-log`, `/jobs`, `/declaration-config`), give
  `/bom/needs-action` an `active_tab` test, relabel 2 items.
- **Group labels name the job step, not the data type.** "DỮ LIỆU NỀN" is the
  ingest set; "CẦN XỬ LÝ" is the four queues that were previously scattered
  across three groups and two body links.
- **`Đề xuất` → `Đề xuất từ CO`** (P10). `workspace.stat.proposals` changes
  from "Duyệt BOM" to the same string so one object has one name.
- **`Staff` → `Nhân sự phụ trách`.** `tabs.staff` is the only untranslated
  Vietnamese-side label in the nav (`i18n.py:560`).
- **Counts render as mono pills** per `DESIGN.md` §3. The four counts already
  come free from `stats_for_client` (`clients.py:58`); `catalog.candidates`
  and `catalog.conflicts` counts would need adding to that one query, not a
  new round-trip.
- Sidebar items honour the existing permission gates: the last three CẤU HÌNH
  items stay behind `can_edit_technical(client_id)` / `can_manage_staff(client_id)`,
  exactly as `_sidebar.html:60` (`can_edit_technical`) and `:69`
  (`can_manage_staff`) do today.

### Rail (pipeline strip, under the header)

On the 6 ingest screens plus the upload/mapping/preview steps:

```
Danh mục  ›  Mã Quy Đổi  ›  BCCT  ›  Tờ khai  ›  BOM  ›  Đề xuất từ CO
```

This is `workspace.module_meta` (`i18n.py:152`) promoted from a subtitle on one
page into persistent chrome. Inside an upload flow the rail switches to the
step strip:

```
1 Chọn file  ›  2 Khớp cột  ›  3 Xem trước  ›  4 Lưu
```

### Admin sidebar

```
NGƯỜI DÙNG
  Tài khoản                     /admin/users                      [NEW: admin.nav.users]

DỮ LIỆU THAM CHIẾU
  Mã loại hình                  /admin/declaration-types
  Preset DNCX                   /admin/client-type-presets
  Chuẩn ĐVT                     /admin/uom

ADAPTER
  Adapter BOM                   /admin/bom-adapters
  Adapter Quyết toán            /admin/settlement-adapters

HỆ THỐNG            (role == 'dev' only)
  Service tokens                /admin/service-accounts
  Cài đặt kỹ thuật              /admin/settings/technical
  Embedding                     /admin/settings/embedding
```

**Already landed.** The reskin agent moved the admin nav into
`_sidebar.html:75-100` with this exact group structure and added the keys
`navgrp.admin.users`, `navgrp.admin.reference`, `navgrp.admin.adapters`,
`navgrp.admin.system` (+ 9 item keys) at `app/i18n.py:157-168`. `nav.group.workspace`,
`nav.group.data_in` and `nav.group.global` were added at `:151-153`. The only
open item is the label: `navgrp.admin.users` is "Người dùng" today; "Tài khoản"
under a "NGƯỜI DÙNG" group label reads better but is optional.

### Merge / panel / disappear

| Screen | Fate | Why |
|---|---|---|
| `workspace.html` module-grid (6 tiles) | **disappears** | duplicates 6 sidebar items (P6) |
| `_client_nav.html` page-bar stat tagline | **gone (landed)** | duplicated the hero stats (P6) |
| `_client_nav.html` "← Danh sách khách hàng" | **gone (landed)** — header switcher still owed | P4 |
| `catalog_material_edit.html` | **merges** into `catalog_detail.html`'s existing inline panel | identical 7 fields, identical handler (P8) |
| `bom_audit_log.html` | **becomes a tab** on `/bom/needs-action` | one BOM history surface, still its own route |
| `catalog_conflicts.html` | **stays a screen**, gains a sidebar slot | it is a queue with its own filters |
| `bom_upload.html` / `nxt_upload.html` / `inventory_snapshot_upload.html` set-default forms | **become a panel** on the module's config screen | a client setting does not belong on a file form (P12) |
| `nxt_mapping.html` | **disappears** | `_upload_mapping.html` does the same job (P11) |
| 6 `*_upload.html` | **merge** into one `_upload_form.html` + 6 blocks | §3 |
| `catalog_detail.html`'s 12 `<details>` | **become 4 in-page tabs**: Chi tiết · Liên kết · BCCT/BOM · Lịch sử | P7 |
| `/bom/stale` | **stays** as the 308 redirect | sister-app deeplinks (`bom.py:1250`) |

---

## 6. Proposed flow changes

### 6a. Safe — navigation and template only

Status column: **LANDED** = already in the working tree from the parallel
reskin agent; **OPEN** = still to do.

**S1 — LANDED. Flatten the 5 `<details>` groups into the always-visible
sidebar.**
Was: any of 15 screens = open group + click = 2 clicks, repeated on every
navigation. Now: 1 click, all 20 destinations visible.
Landed in `app/templates/_sidebar.html` (new), `base.html`, `_client_nav.html`
(reduced to a page-title bar), `_admin_nav.html`, `app/static/css/app.css`.
Every `href` is unchanged and highlighting still reads `active_tab` /
`request.url.path`, so no route changed — as the file's own header comment
states. Nothing further needed.

**S2 — OPEN. Add the two orphans to the sidebar.**
Today: `/declaration-config` = 3 clicks via a button on `/edit`; `/jobs` =
3 clicks via a button on `/catalog`. Proposed: 1 click each.
Changes: `_sidebar.html` only. The body buttons at `edit.html:19` and
`catalog.html:25` stay as contextual shortcuts.
Risk: none — `GET /clients/growatt-vn/declaration-config` and `/jobs` both
return 200 today.

**S3 — OPEN. Fix the dead BCCT mapping link.**
Today: `uploads.html:51` → 404 (verified live).
Proposed: point it at `/clients/{id}/bcct/upload/mapping/{upload_id}`.
Changes: `app/templates/clients/uploads.html:51`, one string.
Risk: none. Worth a `tests/` assertion that every `href` in `uploads.html`
resolves, since this one shipped unnoticed.

**S4 — PARTLY LANDED. Remove the duplicate counts and the module-grid.**
Was: 3 renderings of each of 4 counts on `/clients/{id}` (page-bar tagline +
hero stat + module tile). The tagline copy is gone and the counts now render
as `.ct` pills in the sidebar. Remaining: the 6-tile `module-grid` still
duplicates 6 sidebar items. Target = sidebar pill (persistent) + hero stat
(overview only).
Changes: `workspace.html:34-73` (module-grid). The stat tagline is already
gone — the reskin agent's `_client_nav.html` rewrite dropped it.
Risk: none. Keep the config-summary section — it is the only place
`bom_proposal_qty_tolerance_pct` is visible without opening `/edit`.

**S5 — OPEN. Move the client switcher into the header.**
Today: the page-bar link is gone but no replacement exists, so switching
client now means the sidebar's "Khách hàng" → `/clients` → scan → row click,
and the current screen is lost.
Proposed: header `<select>`, stays on the same relative path.
Changes: `base.html` (header markup) only. No new query:
`chat_widget_clients` is already injected on every render at `app/main.py:85`.
Risk: low. The `<select>` must post to a route that resolves "same page,
other client"; if that mapping is not obvious for a detail URL
(`/catalog/{code}/detail`), fall back to the new client's overview. Decide
that rule before building — silently landing on a 404 for the other client
would be worse than today.

**S6 — OPEN. One name per object.**
Today: "Đề xuất" (nav) and "Duyệt BOM" (stat) for `hub.bom_change_requests`.
Proposed: "Đề xuất từ CO" in both; `tabs.staff` "Staff" → "Nhân sự phụ trách".
Changes: `app/i18n.py:132`, `:159`, `:560` (+ the `en` block at `:737`, `:761`,
`:1143`).
Risk: none in the app. `.ai/STATUS.md` item 5 records two further label
defects on the candidates *detail* page that this does not fix.

**S7 — OPEN. `active_tab` for the two unmarked queue screens.**
Today: `/bom/needs-action` and `/bom/audit-log` highlight nothing (P3). The
sidebar carried the defect forward — `_sidebar.html:46` renders the
needs-action link with a bare `class="side-a"` and no `active_tab` test, and
audit-log is absent.
Proposed: add `"active_tab": "bom_needs_action"` / `"bom_audit_log"` and give
the sidebar items the matching test.
Changes: `app/routes/bom.py:973` and `:1140` — one key added to each
`TemplateResponse` context dict — plus `_sidebar.html`. This touches Python
but changes no routing, no query, no gate; an unread context key is inert.
Risk: none.

### 6b. Needs a route or logic change

**R1. Collapse the ingest flows into one parameterised family.**
Today: 6 upload landing pages, 3 preview shapes, 2 mapping implementations,
47 handlers across 6 route files (§3).
Proposed: `/clients/{id}/ingest/{module}/…` with 9 handlers driven by
`ModuleConfig`; today's URLs kept as 308 redirects.
Changes: `app/routes/_mapping_flow.py` (extend `ModuleConfig` with the
adapter/profile knob), new `app/routes/ingest.py`, delete the per-module
upload/mapping/preview handlers listed in §3, `_upload_form.html` +
6 block-only wrappers, delete `nxt_mapping.html`, re-parent
`nxt_preview.html`, `inventory_snapshot_preview.html` and
`bcct_upload_preview.html` onto `_upload_preview.html`.
Risk: **high, and the highest-value item here.** `ModuleConfig` currently
lies for two modules — `bcct` and `bom` pass `summarize_fn=lambda _: {}` and
`ingest_fn=lambda *a, **kw: 0` with the comment "not called via this cfg"
(`bcct.py:316-317`, `bom.py:1336-1337`), meaning their confirm paths still run bespoke
code. Unifying means making those two honest first. Do this as its own slice
with the full suite (baseline 1686 passed / 16 skipped per `.ai/STATUS.md`)
green between each module.

**R2. Give BCCT a reject route.**
Today: no way to dismiss a wrong BCCT file (P5).
Proposed: `POST /clients/{id}/bcct/upload/preview/{pid}/reject` mirroring
`catalog.py:567`; swap `bcct_upload_preview.html:163`'s "Hủy" link for the
reject button the shared template already renders.
Changes: `app/routes/bcct.py`, `app/templates/clients/bcct_upload_preview.html`.
Risk: low, but it must not weaken the UoM-drift ack gate. Note that
`.ai/STATUS.md` next-step 2 records **#57** — `upload_preview_confirm`
(`bcct.py:975`) never reads `ack_uom_drift`, so that gate is client-JS only
today. Do not let a template rewrite quietly drop the JS while the server side
still does not check.

**R3. Migrate nxt and inventory-snapshots onto `_mapping_flow`.**
The narrower half of R1, shippable alone. `inventory_snapshots.py` has no
mapping page at all today, so migrating it *adds* a step for files the adapter
cannot read — currently those just fail.
Changes: `app/routes/nxt.py`, `app/routes/inventory_snapshots.py`,
`_mapping_flow.py` (adapter knob).
Risk: medium. The required period fields (`period_year`, `snapshot_date`) must
survive the mapping detour; today they are read straight off the upload POST
(`nxt.py:159`, `inventory_snapshots.py:116`) and would have to ride in
`extra_pending_kwargs_fn`.

**R4. Merge `catalog_material_edit.html` into `catalog_detail.html`.**
Today: 2 surfaces, 7 identical fields, 1 handler (P8).
Proposed: delete the standalone page, keep `GET /catalog/{code}/edit` as a 303
to `/catalog/{code}/detail#edit`, repoint `catalog_conflicts.html:155`.
Changes: `app/routes/catalog.py:975` (GET handler → redirect), delete
`catalog_material_edit.html`, `catalog_conflicts.html:155`.
Risk: low. The POST handler `catalog.py:1011` is untouched.

**R5. Move the set-default-adapter forms off the upload pages.**
Today: three upload screens each carry a client-level config write (P12).
Proposed: one "Adapter mặc định" panel per module on the module's own list
page or under CẤU HÌNH.
Changes: `bom_upload.html`, `nxt_upload.html`,
`inventory_snapshot_upload.html`; the three `POST …/default-adapter` routes
keep their paths.
Risk: low. Folds naturally into R1.

**R6. `bom/audit-log` becomes a tab on `bom/needs-action`.**
Today: 3 clicks, reachable only from a body link (P3).
Proposed: `?view=log` on the needs-action route, one sidebar item.
Changes: `app/routes/bom.py:973`/`:1140`, the two templates.
Risk: low. Keep `/bom/audit-log` as a 308 for existing links.

---

## 7. What I would not change

**The `/v1/hub` API contract.** `docs/API_CONTRACT.md` is the binding
interface for two consumers — `barry-CO-main` and `BCQT-System` — and it is
served by `app/routes/api.py`, which shares **no** route, template, or handler
with the HTML screens discussed above. Every merge, redirect and template
deletion proposed in §6 touches only `/clients/…` and `/admin/…` HTML routes.
The API is deliberately a separate surface and this proposal keeps it that
way. Specifically untouched: `GET /v1/hub/dncxs/{id}/source-summary` and its
`bom` block (`exported_with_bom` / `exported_without_bom` / `stale_count`),
`GET /v1/hub/dncxs/{id}/client-config` and its `config_version` /
`config_hash`, and `GET /v1/hub/clients/{id}/bcct/by-codes`. Note the one
crossing point: **S2 puts `/declaration-config` into the sidebar, and that
screen writes `eligible_import_declaration_types`** — the exact field CO reads
to filter BCCT imports. Making it easier to find must not make it easier to
change by accident; the screen keeps whatever confirmation it has today.

**The promotion and approval gates.** `proposals.py:70`/`:92`/`:114`
(approve / reject / withdraw), `bom_approver_tier` on the client record, and
the `require_can_edit_client` / `can_edit_client_technical` /
`can_manage_staff` checks that gate the three technical config screens are
correctness boundaries, not navigation. The sidebar in §5 renders exactly the
same permission conditionals `_sidebar.html:60` and `:69` use today. No
gate moves, weakens, or gets a shortcut.

**The UoM cross-family drift gate.** `_uom_drift_banner.html` plus the #56
locked-state hint on `bcct_upload_preview.html` exist because operators read a
disabled Apply button as broken (`.ai/STATUS.md`, `v0.22.0`). R2 re-parents
that template; it must carry the banner, the ack checkbox and the hint across
unchanged. And #57 is still open — the gate is JS-only — so a rewrite that
loses the JS loses the gate entirely.

**Parser rule resolution.** `app/routes/clients.py:255-464` (client parser
rules + the test harness) and `_module_aliases` / `_rigid_match_header` /
`try_auto_map` in `_mapping_flow.py:596-681` (plus `resolved_aliases`, imported
from `app.stores.column_aliases`) decide how a column header becomes a logical
field. §6 changes where the *screens* live, never the
resolution order (client rule → column alias → rigid match → LLM proposal →
cached mapping). `.ai/STATUS.md` next-step 3 lists **S3, stored SQLi in parser
rules**, as an open finding — that is a security fix, not an IA change, and it
should not be bundled into a nav round.

**The `upload_pending` / cache-hit fast path.** `upload_initial_dispatch`
(`_mapping_flow.py:99`) skips the mapping page when a confirmed mapping matches
the file signature, and falls back to the mapping page when the cached mapping
fails to re-parse. That is the mechanism that makes repeat uploads cheap. R1
must preserve both branches; a "consistent 4-step wizard" that always shows the
mapping page would add a step to the most common operation in the app.

**The three-group domain vocabulary** (Danh mục / Hải quan / Quyết toán),
carried from `_client_nav.html` into `_sidebar.html`, is correct and stays.
§5 keeps those groups and adds "CẦN XỬ LÝ" and "NHẬT KÝ"; it does not re-cut
the domain.
