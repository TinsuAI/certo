# 2026-05-09 — Catalog multi-source (Phase 1) + BCCT view format

Long session covering two streams of work:
- **Stream A (early)**: BCCT view format/picker shipped (3 user asks).
- **Stream B (long)**: Catalog multi-source schema redesign — 4 migrations, app
  refactor across ~50 files, new derive tool, catalog list redesign, detail
  page, audit trigger, dual-source roles. Multiple user-pivots forced
  significant rework throughout.

## What Was Done

### Stream A — BCCT view format (early in session)

**User asks** (3): format số locale-aware, currency-correct labels (12B-VND
was sitting next to USD label = bug), configurable column show/hide.

Shipped:
- `app/templates/_format.html` — macros `format_number`, `format_money`,
  `format_date`, `format_int`. Locale via `lang` arg (vi: `1.234.567,89`).
- `app/templates/_sort.html` — extracted shared `sort_th(col, label, sort,
  sort_link, attrs)` macro from inline duplicates in bcct/bqd/catalog/bom
  templates.
- `app/static/js/col-picker.js` — vanilla JS, ~80 lines, localStorage-backed
  via `data-col` attributes + `<details class="col-picker" data-view-key>`
  pattern.
- `app/templates/clients/bcct.html` — applied above. Replaced single
  "Giá trị" column with two cells: `Giá trị NT` (FX domain:
  `total_value_nt + currency_nt`) + `Giá trị VND` (always VND label).
- `tests/test_format_macros.py` — 12 tests covering vi/en locale,
  None/empty handling, money + currency rendering.
- `.ai/features/2026-05-08-bcct-view-format/` — brief + ui_smoke.py +
  4 screenshots.

**Tests**: 638 baseline → 638+12 = passing.

### Stream B — Catalog multi-source

**Drove most of the session.** Started as a brief design discussion,
expanded through 4+ user-pivots into a full Phase 1 implementation.

#### Migrations applied (in order):

1. **Mig 042** `catalog_material_code_rename_and_provenance.sql`:
   - RENAME `materials.customs_code → material_code` (PK; mode-agnostic;
     ~620 touch sites estimated, ~50 actual SQL refs in this repo).
   - DROP `materials.internal_code` (vestigial — 100% = customs_code in
     all 11,580 existing rows).
   - ADD 5 cols: `source` enum (client_declared/bcct_observed/bom_observed/system),
     `status` enum (active/under_review/deprecated/tombstoned/inactive),
     `hq_registered` bool, `promoted_to_declared_at` ts, `promoted_by` text.
   - BACKFILL `source='bcct_observed'` from rows with old
     `provenance->'seen_in_bcct'` jsonb key (9001 rows). DROP that key.
   - BACKFILL `hq_registered=true` from `provenance->'registered_with_hq'` (4 rows).
   - DROP+RECREATE `v_material_roles` view with `material_code` rename +
     observation stats (`observed_count` from `count(distinct declaration_no)`,
     `observed_first_at`, `observed_last_at`, `observed_directions[]`).
2. **Mig 043** `catalog_derive_configs.sql` — single table for derive
   tool wizard form. Will likely be DROPPED in mig 047 (next session) per
   user pivot.
3. **Mig 045** `materials_audit_trigger.sql` — trigger on materials
   UPDATE/DELETE writes to `material_audit_events`. Mirrors mig 013 BCCT
   pattern. Audit history now self-populates.
4. **Mig 046** `v_material_roles_dual_source_btp.sql` — added 4th role
   `btp_nm` to observed_roles when has_imports + is_consumed_in_bom +
   has_own_bom. Dual-source emerges as `[btp_sx, btp_nm]` →
   is_multi_role=true. Mig 044 reserved for next session.

#### Resolver / app refactor:

- `material_identity` struct cleaned:
  - DROP `display_code` (consumer composes 3-tier
    `resolved_code or internal_code or customs_code`).
  - RENAME `declared_customs_code → customs_code`,
    `declared_internal_code → internal_code` (drop misleading "declared_"
    prefix; per user "internal_code không declared với ai cả").
  - KEEP `bom_product_code` and `selected_candidate_code` (clear semantic).
  - ADD `resolution_status='resolved_pending_review'` when resolver hits
    `bcct_observed/under_review` material.
- `materials.customs_code → material_code` SQL rename across:
  app/{routes/{api,catalog,bom},stores/{bom,provenance},resolvers/bcct_material_identity,agent/tools}.py
  scripts/{bootstrap_btp_roster,bootstrap_catalog_from_bcct,detect_dual_source_btps,
           derive_btp_shallows,feed_demo_company,materialize_shallow_and_full_flat,
           screenshot_flatten}.py
  app/templates/clients/{bcct,catalog}.html
  tests/test_*.py (15 files)
- App-side derived sourcing-confirmation conflict in catalog.py route:
  `r["is_dual_source"] = "btp_nm" in roles`,
  `r["suggested_sourcing"] = "dual_source" if dual else "self_produced_only" if just btp_sx else None`,
  `r["sourcing_conflict"] = bool(suggested and src != suggested)`.

#### UI:

- **Catalog list** (`/clients/<id>/catalog`) — full redesign:
  - Drop dead "Mã NB" column (internal_code gone).
  - Rename label "Mã HQ" → "Mã vật tư" (mode-agnostic).
  - Apply column-picker pattern from BCCT (data-col attributes +
    col-picker.js + localStorage).
  - New columns: source pill, status pill, ĐK HQ, observation stats
    (count + dates + directions live from view), Chi tiết link,
    inline Promote button.
  - Status filter chip row (active/under_review/deprecated).
  - Vai trò quan sát column shows observed_roles[] badges; "⇄ Đa nguồn"
    badge surfaces when both `btp_sx + btp_nm` in observed_roles
    (= dual-source pattern).
  - Sourcing-confirmation column ("Xác nhận nguồn cung" — renamed from
    "Nguồn cung BTP"): inline edit dropdown + Conflict warning if staff
    confirm differs from observed.
- **Catalog detail** (`/clients/<id>/catalog/<material_code>/detail`) — NEW:
  - Trạng thái hiện tại (full state including provenance jsonb)
  - Vai trò quan sát ƒ (live from v_material_roles)
  - Lịch sử thay đổi (audit events)
  - BCCT references (recent 20)
  - BOM references (recent 20)
- **Catalog-derive wizard** (`/clients/<id>/catalog/derive`) — shipped
  but **deferred** per user pivot (will be replaced by passive
  candidate feed next session).

#### Adoption guide:

`.ai/sister-app-notes/2026-05-09-catalog-multi-source-and-vocab.md` —
~250 lines. CO + BCQT migration map, behavior change disclosures, grep
commands, test plan. Strategy: hard cut, sister-apps adopt at their own
pace (CO is paused).

#### Tests:

- 6 new (`test_catalog_derive.py`)
- 12 new (`test_format_macros.py`)
- 15 test files refactored for vocab rename + struct field changes.
- Final: **644 pass / 15 skip / 0 fail**. From 638 baseline.

## Decisions Made

### 1. Vocab rename `customs_code → material_code` despite 620 sites

Critic round 2 flagged 620 touch sites as overscoped vs the actual
ambiguity. User explicitly overruled: "sai semantic, sai mental model
sao được? Nếu có nhiều nơi gọi thì refactor hết, chạy lại từ đầu cũng
được." Memory `feedback_naming_discipline.md` saved.

### 2. Drop `display_code` from material_identity struct

User decision: "không thể thêm 1 thứ confusing thế vào data nguồn".
Critic argued display_code load-bearing for CO 6 sites; user insisted
consumer compose 3-tier fallback locally. Drop scoped + behavior-change
disclosed in adoption guide. Memory `feedback_no_derived_in_source.md`
saved as principle.

### 3. Observation stats via VIEW, not stored columns

User catch: "nhiều khi upload file mới mới thấy, trong khi hôm qua
không thấy → stale". `observed_count`, `observed_first_at`,
`observed_last_at`, `observed_directions[]` derived live in
`v_material_roles` view, never cached on materials.

### 4. Multi-role vs dual-source — separate concepts

User feedback iteration:
- Round 1: I added `btp_nm` to observed_roles → user said dual-source
  + multi-role bị conflate.
- Round 2: I separated — observed_roles 3 roles only; is_dual_source
  as flag. Got tests green.
- Round 3 (final): User clarified: dual-source SHOULD be `btp_sx +
  btp_nm` both in observed_roles → is_multi_role=true → derived
  conclusion. is_dual_source flag = redundant. Btp_sourcing is staff
  CONFIRMATION (renamed "Xác nhận nguồn cung"); conflict warning when
  staff confirm contradicts observed.

Final logic:
- 4 roles: tp / btp_sx / btp_nm / nvl
- btp_nm rule: `has_imports AND has_own_bom AND is_consumed_in_bom`
  (only fires alongside btp_sx for dual-source case)
- declared_observed_conflict in_list excludes btp_nm (D8 last-row
  preserved: btp_nm declared never triggers conflict — data graph can't
  distinguish nvl-leaf from external-btp_nm without staff input)
- Python-side suggested_sourcing + sourcing_conflict in catalog route

### 5. Pivot from catalog-derive wizard → passive candidate feed

User mid-session: "thực ra rule thì có sẵn trong config của từng khách
hàng rồi, đâu cần enter thêm rule ở catalog?". Designed Mã chờ duyệt
replacement (passive feed surfacing codes from BCCT + BOM that aren't
in catalog yet, using existing client_parser_rules). Captured in
BACKLOG.md for next session. Wizard shipped this session but will be
replaced.

### 6. Phase 1 / Phase 2 split for catalog redesign

Phase 1 (this session): provenance/state/manual columns, vocab rename,
audit trigger, dual-source roles. Phase 2 (next session): multi-role
`roles[]` array + drop `category` + manual fields. Critic round 2
flagged dual-source-of-truth trap if `category` + `roles[]` coexist —
must commit to drop `category` same release.

## What Didn't Work

- **Initial sed-style mass refactor for `m.customs_code → m.material_code`**
  swept too broadly: replaced `m.internal_code` with `m.material_code`
  too (creating duplicate column names in SELECT). Required manual
  cleanup in 2 files.
- **Sed regex on test bind tuples**: dropping `internal_code` from
  INSERT column list didn't auto-drop the corresponding placeholder/value
  in bind tuples → 75 test failures from mismatched param counts. Took
  ~1 hour to fix file-by-file.
- **First mig 046 attempt** added `btp_nm` role + tried to cover pure-
  imported-BTP case (without own_bom). User flagged as conflating
  multi-role with dual-source. Reverted.
- **Critic round 2 on catalog brief** rejected: vocab rename overscoped,
  display_code drop is behavior change smuggled as rename, multi-role
  half-ship trap, filter rule split into 2 tables = false convenience,
  effort 30-40% light. User accepted critic on filter-rule single
  table + dual-source-of-truth concern, REJECTED critic on vocab rename
  + display_code drop. Brief revised rev 4.
- **Mass test-helper refactor for `_read_provenance`**: provenance jsonb
  `seen_in_bcct` key dropped (data moved to source enum + view), but
  tests still asserted on jsonb. Wrote a synthetic `_read_provenance`
  helper that re-derives `seen_in_bcct` shape from new schema for
  backward-compatible test assertions.

## Open Items

(See `BACKLOG.md` for each in detail.)

1. **Mã chờ duyệt** (~1-1.5 days) — passive candidate feed, replaces
   catalog_derive wizard. Drop `catalog_derive_configs` (mig 047). Add
   `catalog_candidate_rejections` table.
2. **Catalog conflicts page** (~0.5-1 day) — review queue for
   `declared_observed_conflict` + sourcing-conflict.
3. **Phase 2 catalog** (~2-3 days) — multi-role `roles[]`, drop
   `category`, manual fields (production_source, hq_registration_*,
   supplier_hint, name_source, uom).
4. **Wipe + ingest fresh** (Growatt + Johnson) — pre-MVP one-shot
   reset. Triple unblocked.
5. **CO + BCQT consumer migration** — adoption guide ready; coordinate
   when CO unpause.

## Files referenced

- Brief (rev 4): `.ai/features/2026-05-08-catalog-multi-source/brief.md`
- Adoption guide: `.ai/sister-app-notes/2026-05-09-catalog-multi-source-and-vocab.md`
- BCCT view brief: `.ai/features/2026-05-08-bcct-view-format/brief.md`
- BACKLOG entries: "Mã chờ duyệt", "Phase 2 catalog", "Catalog conflicts page"
- Memory entries created/updated:
  - `feedback_macros_over_view_engine.md`
  - `reference_terminology_client.md`
  - `feedback_naming_discipline.md`
  - `feedback_no_derived_in_source.md`

## Test status (final)

```
644 passed, 15 skipped, 23 warnings in 28-38s
```

Up from 638 baseline. +12 format macro tests, +6 catalog derive tests,
~6 obsolete test patterns refactored.
