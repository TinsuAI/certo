# Feature: NXT (Nhập-Xuất-Tồn) + Year-end Inventory tier

**Slug:** `2026-06-14-nxt-inventory-tier`
**Status:** branch `feat/nxt-inventory-tier`.
- **Slice 1 SHIPPED** (commit `aeb9df0`): schema, 2 adapter registries +
  system_template, system templates, stores, data_promotion wiring,
  upload→preview→confirm UI both modules, "Quyết toán" nav group.
- **Slice 2 in progress**: `ezsoft_3tsoft` adapter (real Growatt EZSOFT/3TSoft —
  bilingual, group-row roles, lumped Xuất → new `outbound_total` col, mig 084);
  per-client adapter binding (mig 085 + `settlement_adapter_binding` store + upload
  selector + "set default"); admin registry view `/admin/settlement-adapters`.
  Validated on the real Growatt file (2936 lines, btp 150/tp 68/nvl 2718, 0 closing
  mismatch).
- **Slice 2c**: `manual_generic` adapter — last-resort fallback that alias-auto-matches
  any reasonably-headed NXT file (zero interaction) and honours a `mapping_override`
  (header→field) for headers outside the alias list. New `outbound_total` alias for a
  lumped Xuất column.
- **Slice 2d (closes slice 2)**: interactive column-mapping page (mig 086 widens
  parser_mappings.module). Unknown headers → `/nxt/upload/mapping/{id}`: rigid
  pre-fill + "Gợi ý bằng LLM" + per-column dropdowns + sample-row preview. Confirm
  → caches mapping in `parser_mappings` (keyed by file_signature) → re-upload of the
  same shape skips the page (cache hit). "Format lạ = 0 code, confirm qua UI." The
  mapping_override travels into preview/confirm so the immutable artifact re-parses
  identically.
**Slice 2 COMPLETE.** Tests: 23 in this feature + full suite 1517 passed.
UI proof in `screenshots/` (08 = mapping page). Slices 3-4 pending.
**Owner:** Data Hub

## Goal

Add a new shared data tier to Data Hub for two year-end settlement *inputs*
that today live scattered across the per-agency BCQT projects, not in Data Hub:

1. **NXT movement** — period-flow aggregate per material/product:
   `Tồn đầu kỳ + Nhập − Xuất = Tồn cuối kỳ`.
2. **Year-end inventory snapshot** (chốt tồn kho cuối năm) — point-in-time
   stock count, typically `số lượng sổ sách` vs `số lượng thực đếm` + chênh lệch,
   per warehouse, with lot/batch.

Data Hub owns *parse + store + read API* for both. It does **not** compute
settlement (Mẫu 15/15a/16) — BCQT-System stays the settlement engine and
becomes a read-only consumer of this tier. (Decision Q1.)

## Why / evidence (where the real files are)

Neither shape exists in Data Hub today. The `BaoCaoHangChiTiet NK/XK` files
already in `data/source_inventory/` are *detailed transaction reports*, not
NXT summaries. Real source files surveyed across sister repos:

### NXT movement (period flow)
| Client | File | ERP / shape |
|---|---|---|
| Growatt | `bcqt-growatt/data/archive/TongHopNXT.xls`; `.../23.03.2026/Tổng hợp Nhập - Xuất - Tồn ... 2026.xlsx` | EZSOFT/3TSoft, song ngữ VN/中文, header rows 5–8 (merged), ~2900 rows |
| DKE | `BCQT-DKE/.../2. Dữ liệu ERP/1.1, 1.2 物料收发汇总表 ...xlsx` | 收发汇总 in/out summary, ZH/VN |
| Hồng Phúc / Hồng An | `audit-hq/data/raw/HONG_*/*/NXT_TON/*.xls(x)` | MISA "CÂN ĐỐI TỒN KHO", header rows 1–9, "Kho hàng:" section breaks mid-table |
| Johnson | `Johnson/output/CLEAN_MB5B_SUMMARY.xlsx` | SAP MB5B: opening/receipt/issue/closing qty+value, grouped by GL account, 中文 descriptions |
| BCQT-System (fixtures) | `data/{202,11,test_company}/.../NXT_2025.xlsx`, `demo_nxt.xlsx` | 3 sheets NVL/TP/BTP — input of `EzsoftNxtParser` |

### Year-end inventory snapshot (chốt tồn)
| Client | File | Quirks |
|---|---|---|
| DKE | `BCQT-DKE/input/Archived/3. Kiểm kê tồn kho của kho/2. Bảng kiểm kê kho VN cuối tháng 12.2025.xlsx` | physical count, **6 sheets per warehouse**, `số lượng hệ thống` vs `实盘数量`, batch/lot, ZH/VN |
| Đô Thành | `bcqt-dothanh/data/extracted/BCQT SXXK 2025/BCQT TON KHO 2025 KHACH CUNG CAP.xlsx` | free-form + rollup, weight→base-NPL conversion |
| Hồng Phúc/An | `audit-hq/.../NXT_TON/TỒN KHO ...`, `Chênh lệch NXT NVL giữa Kế toán và XNK ...xlsx` | snapshot + KT↔XNK reconciliation |
| Johnson | MB5B `closing_stock_qty` doubles as the period-end snapshot | |

**Reference parser to learn from (and replace):**
`BCQT-System/app/parsers/ezsoft_nxt.py` — `EzsoftNxtParser`, hardcoded
3-sheet NVL/TP/BTP + `header_rows=3`. Rigid; the new parser must autodetect.

## Layout variance the parser must absorb
- Header at variable row (3 → 9); multi-row merged headers.
- Bilingual headers VN + 中文 (Growatt, DKE, Johnson).
- Field-name variance for the same semantic role, e.g. opening = `Tồn đầu kỳ`
  / `Đầu Kỳ` / `期初庫存` / `Lượng NL, VT tồn kho đầu kỳ` / `opening_stock_qty`.
- Outbound either a single `Xuất` or split into `Tái xuất` / `Chuyển MĐSD,
  TTNĐ, tiêu hủy` / `Xuất kho SX` / `Xuất kho khác`.
- Warehouse/section breaks chen giữa data rows (MISA).
- Extra variance/reconciliation columns (KT vs XNK).
- Formula cells for closing (`=E+F−ΣG:J`) — read values, validate, don't trust blindly.
- UoM drift across sources — reuse the existing convertibility classifier + drift gate.
- ERP families: EZSOFT/3TSoft, MISA, SAP (MB5B), hand-made.

## Decisions locked (from user)
- **Q1 — scope:** data tier only (parse + store + read API). No settlement compute.
- **Q2 — model:** two linked entities (movement vs snapshot), not one + discriminator.
- **Q3 — coverage:** cover *all* clients. Priority is a **modular, Web-UI-manageable
  adapter system** so new adapters/variants are cheap to add later.
- **Q4 (added) — templates:** ship a **system-standard template** for each of
  the two data types.

## Reuse existing infra (do NOT rebuild)
- `app/parsers/_excel.py::header_row(aliases=...)` — alias-scored header
  autodetect; `index_headers`, `cell_str/cell_num`, `compute_file_signature`.
- Adapter registry pattern `app/parsers/bom_adapters/__init__.py` —
  `Protocol + register() + detect()-ranked parse_with_fallback + post_ingest_hooks`.
  Clone the *shape* into `app/parsers/nxt_adapters/`.
- `client_column_aliases` (mig 075) + `parser_mappings` (LLM-proposed mapping
  cache keyed by `compute_file_signature`) + `adapter_binding` (per-client
  default adapter) — "new format from existing client = 0 code".
- Template-download pattern: `app/routes/client_uom_factors.py:209`
  (`GET .../template.xlsx` → `render_template_xlsx()`).
- Admin registry view pattern: `GET /admin/bom-adapters` (`admin.py:293`),
  `registry_info()`, `adapter_binding.list_bindings()`, `_admin_nav.html`.
- UoM convertibility classifier + ingest drift gate (A.4.4) — for NXT/snapshot UoM warnings.
- `bom_audit_events` (mig 006) — reuse for new event types (closing-mismatch,
  variance-flag) per the "reuse audit events" rule; no new audit table.

## Data model (forward-only migration)

Two entity pairs (artifact + lines), both immutable (edit = new artifact;
tombstone allowed) per the BOM immutable principle.

### `hub.nxt_artifacts` / `hub.nxt_lines`
- `nxt_artifacts`: `id` (`nxt_*` prefix), `client_id`, `period_from`,
  `period_to`, `source_kind`
  (system_template|ezsoft_3tsoft|misa|sap_mb5b|manual), `adapter_name`,
  `file_sha256`, `file_path`, `created_at`, `superseded_by`.
  - NOTE: no `material_class` here. One upload can carry NVL+TP+BTP (EZSOFT =
    3 sheets in one workbook); role belongs on the line, not the artifact.
- `nxt_lines`: `artifact_id`, `internal_code`, `customs_code`, `name`, `uom`,
  `opening`, `inbound_total`, `outbound` (JSONB sub-columns: `tai_xuat`,
  `chuyen_mdsd`, `xuat_sx`, `xuat_khac`), `closing_reported`, `reported_role`
  (nvl|tp|btp|null — **provenance**, not authority), `note`.
  - `closing_implied = opening + inbound_total − Σ outbound` is **derived at
    runtime**, not stored (no-derived-in-source rule). Mismatch vs
    `closing_reported` → `bom_audit_events` row, surfaced in preview gate.

#### Classification: provenance, not duplication (design note)
The authoritative NVL/TP/BTP classification of a code lives in the catalog
(Danh Mục) — do **not** duplicate it onto NXT lines as authority (no-derived-in-
source). Display/API/form-routing resolve class from the catalog at runtime via
`bcct_material_identity`.

`reported_role` is kept anyway, but only as **provenance** — "the role the
source file declared this line under" (which sheet/section it came from). It is
*not* derivable from the catalog and earns its place because:
1. **Multi-role codes (cải chế/rework):** a code can be NVL *and* BTP *and* TP at
   once; the catalog's single category is impoverished. The same code can appear
   on both the NVL and BTP sheet of one NXT with different balances — without a
   per-line role, the two lines collapse to one (wrong) class.
2. **Form routing:** Mẫu 15 (NVL) vs 15a (TP) needs to know each line's role;
   `reported_role` carries it directly to the BCQT consumer.
3. **Reconciliation:** source role ≠ catalog category → `bom_audit_events`
   drift signal.
For single-role codes `reported_role` simply agrees with the catalog — harmless.

### `hub.inventory_snapshots` / `hub.inventory_snapshot_lines`
- `inventory_snapshots`: `id` (`inv_*`), `client_id`, `snapshot_date`,
  `source_kind`, `adapter_name`, `file_sha256`, `file_path`, `created_at`,
  `superseded_by`.
- `inventory_snapshot_lines`: `snapshot_id`, `code`, `name`, `uom`,
  `warehouse`, `batch`, `qty_book`, `qty_physical`, `note`.
  - `variance = qty_physical − qty_book` derived at runtime.

**Link:** snapshot at `snapshot_date` ↔ NXT `closing` where `period_to ==
snapshot_date` (and ↔ next-year `opening`). Exposed by a read helper, not a
stored FK chain — `period_to`/`snapshot_date` + `client_id` is the join key.

## Parser / adapter architecture (modular + Web-UI-manageable)

Mirror the BOM registry. Adapter `Protocol` per module (`nxt` and
`inventory`): `name`, `label_key`, `description_key`,
`supports_mapping_override`, `detect(blob) -> float|None`, `parse(blob, *,
mapping_override=None) -> canonical_lines`. Every adapter maps INTO the
canonical line shape above.

Day-1 adapters:
- `system_template` (both modules) — parses the canonical template; highest
  `detect()` precedence. The deterministic happy path.
- `ezsoft_3tsoft` — Growatt NXT (3-sheet, bilingual, merged header band).
- `misa_can_doi_ton` — Hồng Phúc/An NXT (section breaks, header rows 1–9).
- `sap_mb5b` — Johnson NXT/closing (qty+value, GL grouping, 中文).
- `manual_generic` — alias + **LLM-mapping fallback** (parser_mappings cache);
  absorbs unknown layouts with zero new code.
- `kiem_ke_multi_kho` (inventory) — DKE multi-warehouse physical count.

**Three tiers of "add a new format", by cost (respects B.0 decision):**
1. **New column-naming variant of a known shape** → pure DATA via Web UI:
   `client_column_aliases` + per-client `adapter_binding`. Zero code.
2. **Unknown layout** → `manual_generic` proposes a mapping (LLM), admin
   **confirms it in Web UI**, cached in `parser_mappings`. Zero code.
3. **Genuinely new structural shape** → 1 adapter file + tests + CI deploy
   (git-governed). **No runtime `.py` upload** (RCE-by-design — rejected in
   B.0 item 4).

### Web-UI management (the Q3 emphasis)
- `GET /admin/nxt-adapters` + `GET /admin/inventory-adapters` (or one combined
  `/admin/data-adapters` with module tabs) — registry view + per-client binding
  matrix, mirroring `/admin/bom-adapters`. Add to `_admin_nav.html`.
- Per-client default-adapter binding: `POST /clients/{id}/nxt/default-adapter`
  (mirror `bom.py:210`).
- Column-alias + mapping-confirmation UI: reuse the group-map / mapping-confirm
  surfaces already built for BOM (B.0 item 2).
- Upload + preview + confirm flow mirrors BCCT/BOM (drift gate before commit).

## System-standard templates (Q4)
Two downloadable canonical `.xlsx`, built in-memory via a `render_template_xlsx()`
helper (mirror `client_uom_factors`), served at:
- `GET /templates/nxt.xlsx`
- `GET /templates/inventory-snapshot.xlsx`

**NXT template** — 3 sheets (NVL / TP / BTP, matching the dominant convention
and EzsoftNxtParser muscle memory), header block (client, kỳ từ/đến), columns:
`STT | Mã nội bộ | Mã hải quan | Tên | ĐVT | Tồn đầu kỳ | Nhập trong kỳ |
Tái xuất | Chuyển MĐSD/TTNĐ/tiêu hủy | Xuất kho SX | Xuất kho khác |
Tồn cuối kỳ | Ghi chú`.

**Inventory-snapshot template** — 1 sheet, header block (client, ngày chốt),
columns: `STT | Mã | Tên | ĐVT | Kho | Lô/Batch | SL sổ sách | SL thực đếm |
Chênh lệch (auto) | Ghi chú`. (Chênh lệch is derived — shown for human
convenience, ignored on parse.)

The template is also the canonical schema all adapters map into, and the
`system_template` adapter's target.

## Read API (for BCQT-System consumer)
Mirror the dual-routing convention (`[[api_routing_convention]]`):
- `/v1/hub/clients/{id}/nxt?class=&period=` and `.../inventory-snapshots?date=`
  (Bearer, sister-app).
- `/api/v1/...` cookie-UI mirrors as needed.
Returns canonical lines + provenance (source_kind, adapter, period). Document
in `docs/API_CONTRACT.md`; bump `API_CHANGELOG.md`.

## Phased plan (stop + review each slice)
1. **Schema + registry skeleton + `system_template` adapter + templates** —
   migration, `nxt_adapters/` + `inventory_adapters/` registries, two template
   downloads, upload→preview→commit for the template happy path. Proves the pipe.
2. **`ezsoft_3tsoft` + `manual_generic` + LLM-mapping fallback + per-client
   binding UI** — Growatt end-to-end (files already in repo), Web-UI adapter
   admin + binding + mapping-confirm.
3. **`misa_can_doi_ton` + `sap_mb5b`** — broaden ERP coverage (Hồng Phúc/An, Johnson).
4. **Inventory snapshot: `kiem_ke_multi_kho`** + closing↔opening↔snapshot link
   + UoM drift gate + read API for BCQT consumer.

## Manual test plan
- Upload each surveyed real file (Growatt EZSOFT, MISA, SAP MB5B, DKE kiểm kê)
  → adapter auto-selected via `detect()`, preview matches eyeballed totals.
- Fill + upload the system template → `system_template` adapter, exact parse.
- Unknown layout → `manual_generic` proposes mapping → confirm in UI → cached;
  re-upload same shape → no re-prompt.
- Closing mismatch (`opening+in−out ≠ reported`) → audit event + gate warning.
- Snapshot with book≠physical → variance surfaced; cross-family UoM → drift ack.
- Per-client binding overrides detect() order; admin registry view lists all
  adapters + bindings.
- `/v1/hub` read returns canonical lines + provenance for BCQT consumer.

## Done criteria
- All surveyed real files ingest correctly via auto-detected adapters.
- Both system templates downloadable + round-trip ingest cleanly.
- Adding a new column-variant or confirming an unknown mapping needs **zero code**,
  done entirely in Web UI; a new structural shape = 1 adapter file + tests.
- Two-entity schema, immutable, with runtime-derived closing_implied/variance.
- Read API live + documented; BCQT-System can consume.
- UI proof screenshots committed under this folder.

## Open / risks
- Canonical NXT template: 3-sheet (NVL/TP/BTP) vs single sheet + `loại` column —
  recommend 3-sheet (least surprise). The sheet only sets `reported_role`
  (provenance); authoritative class still resolves from catalog at runtime, so
  this is purely an input-ergonomics choice. Confirm.
- SAP MB5B is GL-account-grouped, not material-line-grouped — `sap_mb5b` adapter
  must explode GL groups to material lines or store at GL granularity; needs a
  closer look at the real file before slice 3.
- Đô Thành snapshot is free-form (narrative + rollup) — may not fit
  `kiem_ke_multi_kho`; could need its own adapter or be declared out-of-scope
  for v1 (manual entry).
- Material identity: NXT `internal_code`/`customs_code` must resolve against the
  existing catalog (reuse `bcct_material_identity` resolver) for cross-linking.
