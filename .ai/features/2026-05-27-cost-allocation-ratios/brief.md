# Feature: Cost Allocation Ratios — auto-fill cost-buildup from per-client config

Source request: phân bổ tỷ lệ chi phí (hệ số × FOB) cho cost-buildup LVC/RVC,
hai chế độ — A theo Mã TP, B cố định cả DN — quản lý qua admin UI + import Excel.
Sample: `.ai/samples/BANG-PHAN-BO-TY-LE-CHI-PHI.xlsx` (GROWATT, 24 mã SP, 7 cột hệ số).

## Scope

In:
- New table `co.cost_allocation_ratio` (Postgres, CO schema). Migration 012.
- Mode A (per `client_id × mã_sp`) primary; Mode B (per `client_id`, `mã_sp IS NULL`) fallback.
- Per-product schema expansion `cost_buildup`: 4 rollup keys → 6 detail keys
  (`wages, welfare, rent, depreciation, other_mfg, transport_storage`).
  `profit` stays derived (FOB − material − I+II+III − VII), no input field for profit.
- Read-side adapter: engine still consumes `labor/overhead/profit/other` rollups
  (XML config unchanged); rollups computed from 6 details. Legacy 4-key rows still
  read OK (treated as already-rolled).
- UI in origin product panel: cost-buildup grid grows to 6 inputs + "Áp hệ số" button
  next to FOB. Button visible only when criterion contains LVC/RVC.
- Admin page `/clients/{client_id}/cost-allocation`: table view of current ratios,
  Excel upload, Excel template download, "Save as default (Mode B)" toggle on a row.
- Excel importer accepts the GROWATT shape (7 cost columns + Mã SP + Ghi chú); maps
  the file's column groups to the 6 details using a fixed mapping documented in the
  importer.

Out:
- Versioning ratios over time (valid_from / valid_until). v1 = "current" only;
  reapply if rates change. Historical reproducibility is the user's job for now.
- Auto-recompute when FOB changes. "Áp hệ số" is explicit, idempotent, overwrites.
- Showing 6-row breakdown on the bảng kê itself. Engine still prints I-VIII; the
  6 details are CO-internal. (Future XML expansion possible without DB change.)
- Pushing ratios to Data Hub. Cost-buildup policy is CO-domain only.
- Multi-currency. Ratios are unit-less multipliers on FOB; FOB currency rules unchanged.
- Coefficient sum > 1 sanity check at admin time. Validate at apply time only
  (when result > FOB the existing orange hint already fires).

## Decisions

- **Storage**: CO Postgres, not Data Hub. Cost-buildup is C/O-form-specific
  accounting (TT 05/2018), no other consumer; Data Hub guardrail does not apply.
- **Schema** (column names final):
  ```
  create table co.cost_allocation_ratio (
    client_id          text not null,
    product_code       text not null default '',  -- '' = Mode B default row
    coef_wages              numeric(12,8) not null default 0,
    coef_welfare            numeric(12,8) not null default 0,
    coef_rent               numeric(12,8) not null default 0,
    coef_depreciation       numeric(12,8) not null default 0,
    coef_other_mfg          numeric(12,8) not null default 0,
    coef_transport_storage  numeric(12,8) not null default 0,
    note               text not null default '',
    updated_at         timestamptz not null default now(),
    primary key (client_id, product_code)
  );
  ```
  Empty `product_code` is the Mode B sentinel. Composite PK already enforces
  uniqueness; no separate index needed for the lookup pattern.
- **Mapping Excel → 6 details** (GROWATT column → CO detail key):
  - "Lương, thưởng" → `wages`
  - "Phúc lợi y tế" → `welfare`
  - "Phí thuê nhà xưởng" → `rent`
  - "Phí khấu hao… bảo hiểm, bảo dưỡng" → `depreciation`
  - "Chi phí khác (sản xuất chung, điện nước…)" → `other_mfg`
  - "Các chi phí khác (vận chuyển, lưu kho, dịch vụ…)" → `transport_storage`
  - "Lợi nhuận" column (`=GIÁ XUẤT XƯỞNG - CHI PHÍ XUẤT XƯỞNG`) is **ignored on
    import** — profit is derived per-case at apply time, not stored as a ratio.
- **Rollup contract** (engine adapter):
  - `labor` (II) = `wages + welfare`
  - `overhead` (III) = `rent + depreciation + other_mfg`
  - `other` (VII) = `transport_storage`
  - `profit` (V) = max(0, FOB − material_total − I+II+III − VII), already how
    "Lợi nhuận" is defined in the GROWATT file.
- **Apply timing**: explicit button. Click → compute coef × FOB → fill 6 inputs
  (overwrite any existing values, surface a confirm if non-empty), set autosave
  dirty flag. Profit field stays empty (derived).
- **Code matching**: `product.bom_product_code or product.code` — same key the
  bảng kê renderer already uses for Mã SP. Case-sensitive exact match. No fallback
  to fuzzy.
- **Admin UI**: dedicated route, not folded into `/clients/{client_id}/config`.
  Table is per-row editable inline (HTMX-style POST per row, consistent with
  existing client_config pattern), Excel upload at the top, template download next to it.
- **Schema migration**: forward-only. New writes always emit 6-key shape.
  `_sanitize_cost_buildup` extended to recognise both shapes — if input has any
  of the 6 detail keys, persist as 6-key; if only legacy 4-key, persist as-is.
  Engine reader at `bang_ke_xml_generator._coerce_cost_buildup` does the rollup,
  reading 6-key first, falling back to legacy 4-key.
- **`product.cost_buildup` migration of existing rows**: none. Recent (post 2026-05-26),
  expected to be near-empty in real cases. Legacy shape still renders correctly.
- **Multi-tenant scoping**: route enforces `client_id` from URL; SQL filters
  `where client_id = %s`. Same auth check as `/clients/{client_id}/bom/upload`.

## Risks

- **Schema drift on existing cost_buildup form fields**. UI currently posts
  `product_{i}_cost_buildup_labor / _overhead / _profit / _other`. Adding 6
  new field names while keeping the legacy 4 around → form-merge logic in
  `app/main.py:260-262` whitelists 4 keys; must extend whitelist to the 6 new
  keys and decide which wins when both are present (recommend: new keys win,
  legacy keys ignored on write). `app/demo_data.py:636-640` (form-to-product
  parser) similarly extends. Two-write-path drift is the main implementation
  risk — must update both code-paths or one will silently drop the data.
- **`_sanitize_cost_buildup` audit invariant**. Today it always returns the
  4 fixed keys. If we change it to "return 6 detail keys + 4 rollup keys
  computed", we double-store and risk diverging copies if anyone edits one
  side. Cleaner: persist only 6 details; compute rollups on read at the engine
  boundary. Means the bảng kê engine becomes the only place that knows about
  the rollup; safer than baking it into storage.
- **Profit derivation correctness**. Today `profit` is a user input; engine
  uses it as-is. If we stop persisting profit, all cases with criterion = LVC/RVC
  that previously had a user-supplied profit need a path to keep it editable.
  Option: keep profit as a separate field on `product.cost_buildup` (not derived
  from ratio, no coef applies to it). UI: profit field stays as a manual input
  (or auto-fills to "FOB − rest" when "Áp hệ số" is clicked).
- **Excel header drift**. GROWATT file has merged-cell headers across rows 2-3
  with bilingual Chinese annotations. Importer must match by *column index*
  not header text, OR normalise headers (strip Chinese, normalise diacritics)
  before matching. Recommend column-index match with a fixed template the
  agency downloads — same pattern as catalog upload.
- **Mã SP key uncertainty**. GROWATT file mixes formats: `PV00.0048400` (dotted),
  `BIENTAN.16` (textual). Need to confirm these match `product.bom_product_code`
  on Growatt cases in the DB before claiming Mode A works. Spot check during
  implementation.
- **Apply overwrite**. If user has typed values, clicking "Áp hệ số" overwrites.
  v1: confirm dialog when any of the 6 fields is non-empty. Cheaper than a
  full undo stack.
- **Bảng kê regression**. Existing samples at `.ai/samples/bang-ke-xml/` were
  generated from 4-key cost_buildup. After the engine reader change (sum 6
  details to rollups), regenerate samples and PDF-diff to confirm no numeric
  drift on the 4-key legacy path. Tests should cover both shapes.

## Resolved Open Questions

1. **Local JSON fallback for dev (no DB)**: yes, mirror `client_config_store.py`.
   File at `config/cost-allocation/<client>.json`. DB is authoritative; JSON used
   only when `DatabaseUnavailable`. Read-through both, write-through both when
   both available so they stay in sync during local dev.
2. **Excel upload = replace, not upsert**. UI shows a confirm dialog with the
   delta (added X / removed Y / changed Z) before committing. Wipes zombie
   ratios for codes the agency dropped from the new sheet.
3. **Mode B default in a separate panel above the table**, not as a phantom
   `product_code=''` row. Affordance is clearer: "default cho cả DN" is a
   conceptually different scope from "per-mã-SP override". Storage stays
   single-table (`product_code=''` sentinel) — UI splits the view.
4. **Profit field stays editable**. "Áp hệ số" leaves it blank by default
   (engine will derive). User can still type a manual profit to fix it,
   forcing the other costs to absorb the difference. Covers both cases.
5. **Bảng kê layout stays at I-VIII**. 6-detail breakdown is CO-internal;
   not surfaced on the form. TT 05/2018 form B expects 8 La Mã rows; agency
   reviewers are habituated to that layout; the 2026-05-26 settled style stands.
6. **Apply button is per-product**, placed next to the FOB display inside the
   origin product panel (same `<details class="cost-buildup-block">` already
   open for LVC/RVC). Per-product matches the per-mã-SP key structure of the
   ratio table.
